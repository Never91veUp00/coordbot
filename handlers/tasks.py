from aiogram import Bot, types
from keyboards import ready_squads_keyboard, task_keyboard
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils import notify_admins, now_hm, update_user_status
from asyncpg.exceptions import UniqueViolationError
from db import is_admin
from datetime import datetime, timedelta
from enums import TaskStatus
import db


# ---------------- Назначение задачи ----------------
async def task_cmd(message: types.Message):
    """Команда /task — выбор отряда для назначения задачи"""
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    kb = await ready_squads_keyboard()
    if not kb.inline_keyboard:
        await message.answer("⚠ Нет готовых отрядов.")
    else:
        await message.answer("Выбери отряд для назначения задачи:", reply_markup=kb)


async def choose_target(callback: CallbackQuery):
    """Админ выбрал отряд → создаём pending"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    target_uid = int(callback.data.split(":")[1])
    row = await db.DB.fetchrow("SELECT u.squad FROM users u WHERE u.tg_id=$1", target_uid)
    squad = row["squad"] if row else None

    try:
        await db.DB.execute(
            "INSERT INTO pending (admin_id, target_uid, squad, created_at) VALUES ($1, $2, $3, $4)",
            callback.from_user.id, target_uid, squad, datetime.now().isoformat(timespec="seconds")
        )
    except UniqueViolationError:
        await callback.message.answer(
            f"⚠️ Отряду {squad} уже назначается задача другим админом. Подождите."
        )
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить назначение", callback_data="cancel_task")]
    ])

    await callback.message.edit_text(
        "✏ Введи цель в формате:\n`<цифра> <цвет>`.\n\n"
        "Или нажми «Отменить назначение».",
        parse_mode="Markdown",
        reply_markup=kb
    )
    await callback.answer()


async def handle_admin_task_message(message: types.Message, bot: Bot):
    """Обработка ввода цели админом"""
    text = (message.text or "").strip()
    if not text:
        return

    row = await db.DB.fetchrow(
        "SELECT id, target_uid, squad, point, color, is_edit, created_at "
        "FROM pending WHERE admin_id=$1 ORDER BY created_at DESC LIMIT 1",
        message.from_user.id
    )
    if not row:
        return

    pending_id, target_uid, squad = row["id"], row["target_uid"], row["squad"]
    old_point, old_color, is_edit, created_at = row["point"], row["color"], row["is_edit"], row["created_at"]

    # ⏰ Проверка таймаута
    try:
        created_at_dt = datetime.fromisoformat(created_at)
    except Exception:
        created_at_dt = datetime.now()

    if datetime.now() - created_at_dt > timedelta(minutes=5):
        await db.DB.execute("DELETE FROM pending WHERE id=$1", pending_id)
        await message.answer("⚠️ Время для назначения задачи истекло (5 минут). Начни заново.")
        return

    # Проверяем формат
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠ Формат: <точка> <цвет>")
        return

    new_point, new_color = parts[0], parts[1]

    rec = await db.DB.fetchrow(
        "INSERT INTO tasks(squad, point, color, status) VALUES ($1, $2, $3, $4) RETURNING id",
        squad, new_point, new_color, TaskStatus.PENDING
    )
    task_id = rec["id"]

    # сообщение отряду
    if is_edit:
        sent = await bot.send_message(
            target_uid,
            f"✏ Задача отредактирована!\n"
            f"Старая цель: {old_point} ({old_color})\n"
            f"Новая цель: {new_point} ({new_color})",
            reply_markup=task_keyboard(task_id)
        )
    else:
        sent = await bot.send_message(
            target_uid,
            f"📋 Новая задача для {squad}\nЦель: {new_point} ({new_color})",
            reply_markup=task_keyboard(task_id)
        )

    await db.DB.execute("UPDATE tasks SET message_id=$1 WHERE id=$2", sent.message_id, task_id)
    await db.DB.execute("DELETE FROM pending WHERE id=$1", pending_id)

    # убираем кнопку «Отменить назначение»
    try:
        await message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await message.answer(
        f"✅ {'Задача отредактирована' if is_edit else 'Задача создана'} и отправлена {squad}."
    )

# ---------------- Редактирование задачи ----------------
async def edit_task_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    rows = await db.DB.fetch(
        "SELECT DISTINCT t.squad FROM tasks t WHERE t.status IN ($1, $2)",
        TaskStatus.PENDING, TaskStatus.ACCEPTED
    )
    squads = [r["squad"] for r in rows]

    if not squads:
        await message.answer("⚠ Активных задач нет.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=s, callback_data=f"edit_squad:{s}")] for s in squads]
    )
    await message.answer("Выбери отряд для корректировки задач:", reply_markup=kb)


async def edit_task_choose_squad(callback: CallbackQuery):
    squad = callback.data.split(":")[1]

    rows = await db.DB.fetch(
        "SELECT t.id, t.point, t.color FROM tasks t WHERE t.squad=$1 AND t.status IN ($2, $3)",
        squad, TaskStatus.PENDING, TaskStatus.ACCEPTED
    )

    if not rows:
        await callback.message.answer("⚠ У этого отряда нет активных задач.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{row['point']} ({row['color']})", callback_data=f"edit_task:{row['id']}")]
            for row in rows
        ]
    )
    await callback.message.edit_text(f"Выбери задачу отряда {squad} для редактирования:", reply_markup=kb)
    await callback.answer()


async def edit_task_select(callback: CallbackQuery, bot: Bot):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    task_id = int(callback.data.split(":")[1])

    row = await db.DB.fetchrow(
        "SELECT t.message_id, u.tg_id, t.point, t.color, t.squad "
        "FROM tasks t JOIN users u ON u.squad = t.squad WHERE t.id=$1",
        task_id
    )
    if not row:
        await callback.answer("⚠ Задача не найдена.")
        return

    msg_id, user_id = row["message_id"], row["tg_id"]
    old_point, old_color, squad = row["point"], row["color"], row["squad"]

    try:
        await bot.edit_message_reply_markup(chat_id=user_id, message_id=msg_id, reply_markup=None)
    except Exception:
        pass

    await db.DB.execute("UPDATE tasks SET status=$1 WHERE id=$2", TaskStatus.ARCHIVED, task_id)

    await db.DB.execute(
        "INSERT INTO pending (admin_id, target_uid, point, color, squad, created_at, is_edit) "
        "VALUES ($1, $2, $3, $4, $5, $6, TRUE)",
        callback.from_user.id, user_id, old_point, old_color, squad,
        datetime.now().isoformat(timespec="seconds")
    )

    await callback.message.edit_text(
        "✏ Введи новую цель в формате: `<точка> <цвет>`.",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------------- Принятие задачи ----------------
async def accept_task(callback: CallbackQuery, bot: Bot):
    task_id = int(callback.data.split(":")[1])
    start_time = now_hm()

    row = await db.DB.fetchrow(
        "SELECT t.squad, t.point, t.color, t.message_id, u.tg_id "
        "FROM tasks t JOIN users u ON u.squad = t.squad "
        "WHERE t.id=$1 AND t.status=$2",
        task_id, TaskStatus.PENDING
    )
    if not row or row["message_id"] != callback.message.message_id:
        await callback.answer("⚠ Эта задача больше не актуальна.", show_alert=True)
        return

    squad, point, color, user_id = row["squad"], row["point"], row["color"], row["tg_id"]

    await db.DB.execute(
        "UPDATE tasks SET start_time=$1, status=$2 WHERE id=$3",
        start_time, TaskStatus.ACCEPTED, task_id
    )

    await update_user_status(user_id)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.message.answer(
        f"✅ Задача принята\n"
        f"Отряд: {squad}\n"
        f"Цель: {point} ({color})\n"
        f"Время начала: {start_time}\n\n"
        f"После выполнения используй команду /report."
    )

    await notify_admins(bot, f"📌 Отряд {squad} принял задачу: {point} ({color}) в {start_time}")
    await callback.answer()


# ---------------- Готовность ----------------
async def set_ready(callback: CallbackQuery, bot: Bot):
    row = await db.DB.fetchrow(
        "SELECT u.squad, u.bow, u.arrow FROM users u WHERE u.tg_id=$1",
        callback.from_user.id
    )
    if not row:
        await callback.message.answer("Сначала введи код отряда.")
        return

    squad, bow, arrow = row["squad"], row["bow"], row["arrow"]

    # 👇 вручную ставим готовность
    await db.DB.execute(
        "UPDATE users SET ready=TRUE, status='idle' WHERE tg_id=$1",
        callback.from_user.id
    )

    await notify_admins(bot, f"✅ Отряд {squad} готов к работе\nПтица: {bow}\nСнаряд: {arrow}")

    await bot.send_message(
        callback.from_user.id,
        f"✅ Статус обновлён!\nОтряд: {squad}\nПтица: {bow}\nСнаряд: {arrow}\n\nЖди назначения задачи."
    )

    try:
        await callback.message.edit_text("Ты отметил готовность ✅")
    except Exception:
        pass


async def cancel_task(callback: CallbackQuery):
    """Отмена назначения задачи"""
    await db.DB.execute(
        "DELETE FROM pending WHERE admin_id=$1",
        callback.from_user.id
    )
    await callback.message.edit_text("❌ Назначение задачи отменено.")
    await callback.answer()
