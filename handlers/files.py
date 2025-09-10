from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils import update_user_status
from db import is_admin
import db


# ------------------- Отправка LDK -------------------
async def send_ldk_cmd(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    rows = await db.DB.fetch("SELECT tg_id, squad FROM users")

    if not rows:
        await message.answer("⚠ Нет отрядов.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=row["squad"], callback_data=f"ldk_target:{row['tg_id']}")]
            for row in rows
        ]
    )
    await message.answer("Выбери отряд для отправки LDK файла:", reply_markup=kb)


async def choose_ldk_target(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    target_uid = int(callback.data.split(":")[1])
    await db.DB.execute(
        "INSERT INTO pending (admin_id, target_uid, created_at, await_ldk) "
        "VALUES ($1, $2, NOW(), TRUE)",
        callback.from_user.id, target_uid
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ldk_cancel")]
        ]
    )
    await callback.message.edit_text("📎 Пришли .ldk файл одним сообщением:", reply_markup=kb)
    await callback.answer()


async def cancel_ldk(callback: CallbackQuery):
    await db.DB.execute(
        "DELETE FROM pending WHERE admin_id=$1 AND await_ldk=TRUE",
        callback.from_user.id
    )
    await callback.message.edit_text("❌ Отправка LDK отменена.")
    await callback.answer()


async def handle_ldk(message: types.Message, bot: Bot):
    if not message.document or not message.document.file_name.endswith(".ldk"):
        return

    if not await is_admin(message.from_user.id):
        await message.answer("⚠ Файл не ожидается.")
        return

    row = await db.DB.fetchrow(
        "SELECT id, target_uid FROM pending WHERE admin_id=$1 AND await_ldk=TRUE "
        "ORDER BY created_at DESC LIMIT 1",
        message.from_user.id
    )

    if not row:
        await message.answer("⚠ Файл не ожидается.")
        return

    pending_id, target_uid = row["id"], row["target_uid"]

    await bot.send_document(
        target_uid,
        message.document.file_id,
        caption="📎 Админ отправил LDK файл."
    )

    await message.answer("✅ LDK файл отправлен выбранному отряду.")

    await db.DB.execute("DELETE FROM pending WHERE id=$1", pending_id)


# ------------------- Видео отчёты -------------------
async def handle_video(message: types.Message, bot: Bot):
    """Приём видео от пользователя для отчёта"""
    uid = message.from_user.id

    row = await db.DB.fetchrow(
        """
        SELECT u.squad, u.bow, u.arrow, t.id, t.point, t.color, t.true_point, t.true_color, t.start_time, COALESCE(t.result, 'без указания') AS result
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE u.tg_id=$1 AND t.await_video=TRUE
        ORDER BY t.id DESC LIMIT 1
        """,
        uid
    )

    if not row:
        await message.answer("⚠ Активная задача не найдена или видео не ожидалось.")
        return

    from utils import make_report, now_hm, notify_admins
    from enums import TaskStatus
    from keyboards import ready_kb

    squad, bow, arrow = row["squad"], row["bow"], row["arrow"]
    task_id, point, color = row["id"], row["point"], row["color"]
    start_time, result = row["start_time"], row["result"]
    true_point, true_color = row["true_point"], row["true_color"]
    end_time = now_hm()

    final_report = make_report(
        squad, bow, arrow, point, color, start_time, end_time,
        result, video_attached=True, true_point=true_point, true_color=true_color
    )

    # закрываем задачу
    await db.DB.execute(
        "UPDATE tasks SET status=$1, report=$2, end_time=$3, video_attached=TRUE, await_video=FALSE WHERE id=$4",
        TaskStatus.FINISHED, final_report, end_time, task_id
    )

    # пересчитываем статус отряда
    await update_user_status(uid)

    # уведомляем админов
    await notify_admins(bot, final_report, video=message.video.file_id)

    # отправляем пользователю
    await message.answer_video(
        message.video.file_id,
        caption=final_report + "\n\nКогда будешь готов — нажми кнопку:",
        reply_markup=ready_kb()
    )
