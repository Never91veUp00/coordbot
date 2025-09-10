from aiogram import Bot, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.filters import StateFilter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from keyboards import report_keyboard, ready_kb
from utils import notify_admins, now_hm, make_report, update_user_status
from enums import TaskStatus
import db

# --- Состояния отчёта ---
class ReportStates(StatesGroup):
    await_true_point = State()

# ---------------- Старт отчёта ----------------
async def report_start(message: types.Message):
    uid = message.from_user.id
    row = await db.DB.fetchrow("SELECT squad FROM users WHERE tg_id=$1", uid)
    if not row:
        await message.answer("⚠ Ты не зарегистрирован в системе.")
        return
    squad = row["squad"]

    tasks = await db.DB.fetch(
        "SELECT id, point, color, start_time FROM tasks "
        "WHERE squad=$1 AND status=$2",
        squad, TaskStatus.ACCEPTED
    )

    if not tasks:
        await message.answer("⚠ У тебя нет активных задач для отчёта.")
        return

    if len(tasks) == 1:
        task = tasks[0]
        await message.answer(
            f"📋 Активная задача #{task['id']}:\n"
            f"Цель: {task['point']} ({task['color']})\nНачало: {task['start_time']}\n\nВыбери результат:",
            reply_markup=report_keyboard(task_id=task["id"])
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

    task = await db.DB.fetchrow(
        "SELECT point, color, start_time FROM tasks WHERE id=$1",
        task_id
    )
    if not task:
        await callback.message.answer("⚠ Задача не найдена.")
        return

    await callback.message.edit_text(
        f"📋 Задача #{task_id}:\n"
        f"Цель: {task['point']} ({task['color']})\nНачало: {task['start_time']}\n\nВыбери результат:",
        reply_markup=report_keyboard(task_id=task_id)
    )
    await callback.answer()


# ---------------- Приём результата ----------------

async def handle_report(callback: CallbackQuery, state: FSMContext):
    _, task_id, chosen = callback.data.split(":")
    task_id = int(task_id)
    end_time = now_hm()

    if chosen == "other":
        # 👇 ставим заглушку, ждём уточнения
        await db.DB.execute(
            "UPDATE tasks SET await_video=FALSE, result=$1, end_time=$2 WHERE id=$3",
            "🎯 Попал в другую точку", end_time, task_id
        )
        await db.DB.execute(
            "UPDATE tasks SET report=$1 WHERE id=$2",
            "Ожидается ввод реального попадания...", task_id
        )
        
        # переводим пользователя в состояние ожидания реальной точки
        await state.set_state(ReportStates.await_true_point)

        await callback.message.edit_text(
            "✏ Укажи, в какую именно точку и цвет ты попал (например: 3 красный)."
        )
        await callback.answer()
        return

    # остальные варианты
    result_map = {
        "hit": "✅ Попадание",
        "miss": "❌ Промах",
        "skip": "⏸ Не выполнил"
    }
    result = result_map.get(chosen)

    await db.DB.execute(
        "UPDATE tasks SET end_time=$1, result=$2, await_video=TRUE WHERE id=$3",
        end_time, result, task_id
    )

    await callback.message.edit_text(
        "Отчет принят.\nПришли видео (оно будет приложено с подписью).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Видео не будет", callback_data=f"novideo:{task_id}")]
        ])
    )
    await callback.answer()


async def handle_true_point(message: types.Message, state: FSMContext):
    # если по какой-то причине не в нужном состоянии — выходим молча
    if await state.get_state() != ReportStates.await_true_point.state:
        return

    uid = message.from_user.id
    text = (message.text or "").strip()

    # Ищем задачу, которая ждёт уточнения
    row = await db.DB.fetchrow(
        """
        SELECT t.id
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE u.tg_id=$1
          AND t.result LIKE '🎯%'
          AND t.await_video=FALSE
        ORDER BY t.id DESC
        LIMIT 1
        """,
        uid
    )

    if not row:
        # сбросим состояние на всякий случай и выйдем
        await state.clear()
        return

    task_id = row["id"]

    # Разбор "A3 красный"
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("⚠ Формат: <точка> <цвет> (например: A3 красный)")
        return

    true_point, true_color = parts[0], parts[1]

    # Сохраняем уточнённую цель
    await db.DB.execute(
        "UPDATE tasks SET true_point=$1, true_color=$2, await_video=TRUE WHERE id=$3",
        true_point, true_color, task_id
    )

    # очищаем состояние
    await state.clear()

    # Сообщаем пользователю
    await message.answer(
        f"✅ Принято ({true_point} {true_color}). Теперь пришли видео (или выбери «Видео не будет»).",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Видео не будет", callback_data=f"novideo:{task_id}")]
        ])
    )


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

    row = await db.DB.fetchrow(
        """
        SELECT u.squad, u.bow, u.arrow, t.point, t.color, t.true_point, t.true_color, t.start_time, COALESCE(t.result, 'без указания') AS result
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE t.id=$1 AND u.tg_id=$2 AND t.await_video=TRUE
        """,
        task_id, uid
    )
    if not row:
        await callback.message.answer("⚠ Задача не найдена.")
        return

    squad, bow, arrow = row["squad"], row["bow"], row["arrow"]
    point, color, start_time, result = row["point"], row["color"], row["start_time"], row["result"]
    true_point, true_color = row["true_point"], row["true_color"]
    end_time = now_hm()

    final_report = make_report(
        squad, bow, arrow, point, color, start_time, end_time,
        result, video_attached=False,
        true_point=true_point, true_color=true_color
    )

    await db.DB.execute(
        "UPDATE tasks SET status=$1, report=$2, end_time=$3, video_attached=FALSE, await_video=FALSE WHERE id=$4",
        TaskStatus.FINISHED, final_report, end_time, task_id
    )

    await update_user_status(uid)
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
