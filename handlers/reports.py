from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from keyboards import report_keyboard, ready_kb
from utils import notify_admins, now_hm, make_report, update_user_status
from enums import TaskStatus
import db


# ---------------- Список моих задач ----------------
async def my_tasks(message: types.Message):
    uid = message.from_user.id
    assert db.DB is not None

    async with db.DB.execute("SELECT squad FROM users WHERE tg_id=?", (uid,)) as cur:
        row = await cur.fetchone()
    if not row:
        await message.answer("⚠ Ты не зарегистрирован в системе.")
        return
    squad = row[0]

    async with db.DB.execute(
        "SELECT id, point, color, status FROM tasks "
        "WHERE squad=? AND status IN (?, ?) ORDER BY id",
        (squad, TaskStatus.PENDING, TaskStatus.ACCEPTED)
    ) as cur:
        tasks = await cur.fetchall()

    if not tasks:
        await message.answer("У тебя нет задач.")
        return

    text = "📋 Твои задачи:\n\n"
    for t in tasks:
        text += f"{t['status']} — {t['point']} ({t['color']})\n"

    await message.answer(text)


# ---------------- Старт отчёта ----------------
async def report_start(message: types.Message):
    uid = message.from_user.id
    assert db.DB is not None

    async with db.DB.execute("SELECT squad FROM users WHERE tg_id=?", (uid,)) as cur:
        row = await cur.fetchone()
    if not row:
        await message.answer("⚠ Ты не зарегистрирован в системе.")
        return
    squad = row[0]

    async with db.DB.execute(
        "SELECT id, point, color, start_time FROM tasks "
        "WHERE squad=? AND status=?",
        (squad, TaskStatus.ACCEPTED)
    ) as cur:
        tasks = await cur.fetchall()

    if not tasks:
        await message.answer("⚠ У тебя нет активных задач для отчёта.")
        return

    if len(tasks) == 1:
        task = tasks[0]
        await message.answer(
            f"📋 Активная задача #{task[0]}:\n"
            f"Цель: {task[1]} ({task[2]})\nНачало: {task[3]}\n\nВыбери результат:",
            reply_markup=report_keyboard(task_id=task[0])
        )
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{t['point']} ({t['color']}) — {t['start_time']}",
                callback_data=f"choose_task:{t['id']}"
            )] for t in tasks
        ]
    )
    await message.answer("У тебя несколько активных задач. Выбери задачу для отчёта:", reply_markup=kb)


# ---------------- Выбор задачи ----------------
async def choose_task(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    assert db.DB is not None

    async with db.DB.execute(
        "SELECT point, color, start_time FROM tasks WHERE id=?",
        (task_id,)
    ) as cur:
        task = await cur.fetchone()

    if not task:
        await callback.message.answer("⚠ Задача не найдена.")
        return

    await callback.message.edit_text(
        f"📋 Задача #{task_id}:\n"
        f"Цель: {task[0]} ({task[1]})\nНачало: {task[2]}\n\nВыбери результат:",
        reply_markup=report_keyboard(task_id=task_id)
    )
    await callback.answer()


# ---------------- Приём результата ----------------
async def handle_report(callback: CallbackQuery):
    _, task_id, chosen = callback.data.split(":")
    task_id = int(task_id)

    result_map = {"hit": "✅ Попадание", "miss": "❌ Промах", "skip": "⏸ Не выполнил"}
    result = result_map.get(chosen)
    end_time = now_hm()

    assert db.DB is not None
    await db.DB.execute(
        "UPDATE tasks SET end_time=?, result=?, await_video=1 WHERE id=?",
        (end_time, result, task_id)
    )
    await db.DB.commit()

    await callback.message.edit_text(
        "Отчет принят.\nПришли видео (оно будет приложено с подписью).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Видео не будет", callback_data=f"novideo:{task_id}")]
        ])
    )
    await callback.answer()


# ---------------- Отказ от видео ----------------
async def no_video(callback: CallbackQuery):
    task_id = int(callback.data.split(":")[1])
    await callback.message.edit_text(
        "⚠ Вы уверены, что хотите отправить отчет без видео?\n"
        "Для полноты картины рекомендуется прикрепить видео.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, без видео", callback_data=f"confirm_novideo:{task_id}"),
                InlineKeyboardButton(text="❌ Нет, отправлю видео", callback_data=f"wait_video:{task_id}")
            ]
        ])
    )
    await callback.answer()


async def confirm_no_video(callback: CallbackQuery, bot: Bot):
    """Отчёт без видео"""
    task_id = int(callback.data.split(":")[1])
    uid = callback.from_user.id
    assert db.DB is not None

    async with db.DB.execute(
        """
        SELECT u.squad, u.bow, u.arrow, t.point, t.color, t.start_time,
               COALESCE(t.result, 'без указания')
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE t.id=? AND u.tg_id=? AND t.await_video=1
        """,
        (task_id, uid)
    ) as cur:
        task = await cur.fetchone()

    if not task:
        await callback.message.answer("⚠ Задача не найдена.")
        return

    squad, bow, arrow, point, color, start_time, result = task
    end_time = now_hm()

    final_report = make_report(
        squad, bow, arrow, point, color, start_time, end_time,
        result, video_attached=False
    )

    # закрываем задачу
    await db.DB.execute(
        "UPDATE tasks SET status=?, report=?, end_time=?, video_attached=0, await_video=0 WHERE id=?",
        (TaskStatus.FINISHED, final_report, end_time, task_id)
    )
    await db.DB.commit()

    # пересчитываем статус пользователя
    await update_user_status(uid)
    await db.DB.commit()

    await notify_admins(bot, final_report)

    await callback.message.edit_text("✅ Отчет зафиксирован без видео.")
    await callback.message.answer(
        final_report + "\n\nКогда будешь готов — нажми кнопку:",
        reply_markup=ready_kb()
    )
    await callback.answer()


async def wait_video(callback: CallbackQuery):
    await callback.message.edit_text("📎 Жду видео. Пришли его одним сообщением, оно пойдет как отчет.")
    await callback.answer()
