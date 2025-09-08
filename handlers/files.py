from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from utils import update_user_status
from db import is_admin
import db


# ------------------- Отправка LDK -------------------
async def send_ldk_cmd(message: types.Message):
    uid = message.from_user.id
    print(f"📌 /sendldk вызвал {uid}")

    try:
        if not await is_admin(uid):
            await message.answer("❌ У тебя нет прав администратора.")
            return

        assert db.DB is not None
        async with db.DB.execute("SELECT tg_id, squad FROM users") as cur:
            rows = await cur.fetchall()

        if not rows:
            await message.answer("⚠ Нет зарегистрированных отрядов.")
            return

        # Попробуем через row[...] и row["..."], но в отладке выведем всё содержимое
        print("📋 users:", rows)

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=row[1], callback_data=f"ldk_target:{row[0]}")]
                for row in rows
            ]
        )

        await message.answer("📎 Выбери отряд для отправки LDK файла:", reply_markup=kb)

    except Exception as e:
        print(f"⚠ Ошибка в send_ldk_cmd: {e}")
        try:
            await message.answer(f"⚠ Ошибка при выполнении: {e}")
        except:
            pass


async def choose_ldk_target(callback: CallbackQuery):
    if not await is_admin(callback.from_user.id):
        await callback.answer("Нет прав.")
        return

    target_uid = int(callback.data.split(":")[1])
    await db.DB.execute(
        "INSERT INTO pending (admin_id, target_uid, created_at, await_ldk) VALUES (?, ?, datetime('now'), 1)",
        (callback.from_user.id, target_uid)
    )
    await db.DB.commit()

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Не отправлять", callback_data="ldk_cancel")]
        ]
    )
    await callback.message.edit_text("📎 Пришли .ldk файл одним сообщением:", reply_markup=kb)
    await callback.answer()


async def cancel_ldk(callback: CallbackQuery):
    await db.DB.execute(
        "DELETE FROM pending WHERE admin_id=? AND await_ldk=1",
        (callback.from_user.id,)
    )
    await db.DB.commit()
    await callback.message.edit_text("❌ Отправка LDK отменена.")
    await callback.answer()


async def handle_ldk(message: types.Message, bot: Bot):
    if not message.document or not message.document.file_name.endswith(".ldk"):
        return

    if not await is_admin(message.from_user.id):
        await message.answer("⚠ Файл не ожидается.")
        return

    async with db.DB.execute(
        "SELECT id, target_uid FROM pending WHERE admin_id=? AND await_ldk=1 ORDER BY created_at DESC LIMIT 1",
        (message.from_user.id,)
    ) as cur:
        row = await cur.fetchone()

    if not row:
        await message.answer("⚠ Файл не ожидается.")
        return

    pending_id, target_uid = row

    await bot.send_document(
        target_uid,
        message.document.file_id,
        caption="📎 Админ отправил LDK файл."
    )

    await message.answer("✅ LDK файл отправлен выбранному отряду.")

    await db.DB.execute("DELETE FROM pending WHERE id=?", (pending_id,))
    await db.DB.commit()


# ------------------- Видео отчёты -------------------
async def handle_video(message: types.Message, bot: Bot):
    """Приём видео от пользователя для отчёта"""
    uid = message.from_user.id
    assert db.DB is not None

    async with db.DB.execute(
        """
        SELECT u.squad, u.bow, u.arrow, t.id, t.point, t.color, t.start_time,
               COALESCE(t.result, 'без указания')
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE u.tg_id=? AND t.await_video=1
        ORDER BY t.id DESC LIMIT 1
        """,
        (uid,)
    ) as cur:
        task = await cur.fetchone()

    if not task:
        await message.answer("⚠ Активная задача не найдена или видео не ожидалось.")
        return

    from utils import make_report, now_hm, notify_admins, update_user_status
    from enums import TaskStatus
    from keyboards import ready_kb

    squad, bow, arrow, task_id, point, color, start_time, result = task
    end_time = now_hm()

    final_report = make_report(
        squad, bow, arrow, point, color, start_time, end_time,
        result, video_attached=True
    )

    # закрываем задачу
    await db.DB.execute(
        "UPDATE tasks SET status=?, report=?, end_time=?, video_attached=1, await_video=0 WHERE id=?",
        (TaskStatus.FINISHED, final_report, end_time, task_id)
    )
    await db.DB.commit()

    # пересчитываем статус отряда по задачам
    await update_user_status(uid)
    await db.DB.commit()

    # уведомляем админов
    await notify_admins(bot, final_report, video=message.video.file_id)

    # отправляем пользователю
    await message.answer_video(
        message.video.file_id,
        caption=final_report + "\n\nКогда будешь готов — нажми кнопку:",
        reply_markup=ready_kb()
    )
