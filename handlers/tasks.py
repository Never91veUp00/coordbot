# tasks.py
from aiogram import Bot, types
from keyboards import ready_squads_keyboard, task_keyboard
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils import notify_admins, now_hm, update_user_status
from db import is_admin
from datetime import datetime
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
    """Админ выбрал отряд → вносим в pending"""
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    target_uid = int(callback.data.split(":")[1])
    assert db.DB is not None

    async with db.DB.execute("SELECT u.squad FROM users u WHERE u.tg_id=?", (target_uid,)) as cur:
        row = await cur.fetchone()
    squad = row[0] if row else None

    await db.DB.execute(
        "INSERT INTO pending (admin_id, target_uid, squad, created_at) "
        "VALUES (?, ?, ?, ?)",
        (callback.from_user.id, target_uid, squad, datetime.now().isoformat(timespec="seconds"))
    )
    await db.DB.commit()

    await callback.message.edit_text(
        "✏ Введи цель в формате: `<точка> <цвет>`.",
        parse_mode="Markdown"
    )
    await callback.answer()


async def handle_admin_task_message(message: types.Message, bot: Bot):
    """Обработка ввода цели админом"""
    text = (message.text or "").strip()
    if not text:
        return

    async with db.DB.execute(
        "SELECT p.id, p.target_uid, p.squad, p.point, p.color, p.is_edit "
        "FROM pending p WHERE p.admin_id=? ORDER BY p.created_at DESC LIMIT 1",
        (message.from_user.id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        return

    pending_id, target_uid, squad, old_point, old_color, is_edit = row
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠ Формат: <точка> <цвет>")
        return

    new_point, new_color = parts[0], parts[1]

    # создаём новую задачу
    cur = await db.DB.execute(
        "INSERT INTO tasks(squad, point, color, status) VALUES (?,?,?,?)",
        (squad, new_point, new_color, TaskStatus.PENDING)
    )
    task_id = cur.lastrowid
    await db.DB.commit()

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

    await db.DB.execute("UPDATE tasks SET message_id=? WHERE id=?", (sent.message_id, task_id))
    await db.DB.execute("DELETE FROM pending WHERE id=?", (pending_id,))
    await db.DB.commit()

    await message.answer(
        f"✅ {'Задача отредактирована' if is_edit else 'Задача создана'} и отправлена {squad}."
    )


# ---------------- Редактирование задачи ----------------
async def edit_task_cmd(message: types.Message):
    """Команда /edittask — выбор отряда с активными задачами"""
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    assert db.DB is not None
    async with db.DB.execute(
        "SELECT DISTINCT t.squad FROM tasks t WHERE t.status IN (?, ?)",
        (TaskStatus.PENDING, TaskStatus.ACCEPTED)
    ) as cur:
        squads = [row[0] async for row in cur]

    if not squads:
        await message.answer("⚠ Активных задач нет.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s, callback_data=f"edit_squad:{s}")] for s in squads
        ]
    )
    await message.answer("Выбери отряд для корректировки задач:", reply_markup=kb)


async def edit_task_choose_squad(callback: CallbackQuery):
    """Выбор отряда → список его задач"""
    squad = callback.data.split(":")[1]
    assert db.DB is not None

    async with db.DB.execute(
        "SELECT t.id, t.point, t.color FROM tasks t "
        "WHERE t.squad=? AND t.status IN (?, ?)",
        (squad, TaskStatus.PENDING, TaskStatus.ACCEPTED)
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        await callback.message.answer("⚠ У этого отряда нет активных задач.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{point} ({color})", callback_data=f"edit_task:{task_id}")]
            for task_id, point, color in rows
        ]
    )
    await callback.message.edit_text(f"Выбери задачу отряда {squad} для редактирования:", reply_markup=kb)
    await callback.answer()


async def edit_task_select(callback: CallbackQuery, bot: Bot):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    task_id = int(callback.data.split(":")[1])
    assert db.DB is not None

    # достаём данные старой задачи
    async with db.DB.execute(
        "SELECT t.message_id, u.tg_id, t.point, t.color, t.squad "
        "FROM tasks t JOIN users u ON u.squad = t.squad WHERE t.id=?",
        (task_id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        await callback.answer("⚠ Задача не найдена.")
        return

    msg_id, user_id, old_point, old_color, squad = row

    # убираем у юзера кнопки "Принять" для старой задачи
    try:
        await bot.edit_message_reply_markup(chat_id=user_id, message_id=msg_id, reply_markup=None)
    except Exception:
        pass

    # архивируем старую задачу
    await db.DB.execute("UPDATE tasks SET status=? WHERE id=?", (TaskStatus.ARCHIVED, task_id))

    # создаём новую запись в pending с отметкой, что это редактирование
    await db.DB.execute(
        """
        INSERT INTO pending (admin_id, target_uid, point, color, squad, created_at, is_edit)
        VALUES (?, ?, ?, ?, ?, ?, 1)
        """,
        (callback.from_user.id, user_id, old_point, old_color, squad,
         datetime.now().isoformat(timespec="seconds"))
    )
    await db.DB.commit()

    # сообщение администратору
    await callback.message.edit_text(
        "✏ Введи новую цель в формате: `<точка> <цвет>`.",
        parse_mode="Markdown"
    )
    await callback.answer()


# ---------------- Принятие задачи ----------------
async def accept_task(callback: CallbackQuery, bot: Bot):
    """Юзер принимает задачу"""
    task_id = int(callback.data.split(":")[1])
    start_time = now_hm()
    assert db.DB is not None

    async with db.DB.execute(
        "SELECT t.squad, t.point, t.color, t.message_id, u.tg_id "
        "FROM tasks t JOIN users u ON u.squad = t.squad "
        "WHERE t.id=? AND t.status=?",
        (task_id, TaskStatus.PENDING)
    ) as cur:
        task = await cur.fetchone()

    if not task or task[3] != callback.message.message_id:
        await callback.answer("⚠ Эта задача больше не актуальна.", show_alert=True)
        return

    squad, point, color, _, user_id = task

    # обновляем задачу → теперь она принята
    await db.DB.execute(
        "UPDATE tasks SET start_time=?, status=? WHERE id=?",
        (start_time, TaskStatus.ACCEPTED, task_id)
    )

    # пересчёт статуса отряда
    await update_user_status(user_id)
    await db.DB.commit()

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
    """Отметить отряд готовым"""
    assert db.DB is not None
    async with db.DB.execute(
        "SELECT u.squad, u.bow, u.arrow FROM users u WHERE u.tg_id=?",
        (callback.from_user.id,)
    ) as cur:
        row = await cur.fetchone()
    if not row:
        await callback.message.answer("Сначала введи код отряда.")
        return

    squad, bow, arrow = row

    # при ручной готовности — пересчёт статуса
    await update_user_status(callback.from_user.id)
    await db.DB.commit()

    await notify_admins(bot, f"✅ Отряд {squad} готов к работе\nПтица: {bow}\nСнаряд: {arrow}")

    await bot.send_message(
        callback.from_user.id,
        f"✅ Статус обновлён!\nОтряд: {squad}\nПтица: {bow}\nСнаряд: {arrow}\n\nЖди назначения задачи."
    )

    try:
        await callback.message.edit_text("Ты отметил готовность ✅")
    except Exception:
        pass