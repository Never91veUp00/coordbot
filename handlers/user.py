from aiogram import Bot, types
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from keyboards import bows_keyboard, arrows_keyboard, ready_kb
from utils import notify_admins
from enums import TaskStatus
import db


async def finish_cmd(message: types.Message):
    """Команда /finish — закончить работу"""
    await db.DB.execute(
        "UPDATE users SET ready=FALSE, status='idle' WHERE tg_id=$1",
        message.from_user.id
    )
    await message.answer("🛑 Ты завершил работу. Теперь отряд не числится готовым.")


async def start_cmd(message: types.Message):
    assert db.DB is not None
    row = await db.DB.fetchrow(
        "SELECT squad, bow, arrow FROM users WHERE tg_id=$1", message.from_user.id
    )

    if row:
        squad, bow, arrow = row["squad"], row["bow"], row["arrow"]
        if not bow:
            await message.answer(
                f"✅ Отряд {squad} найден.\nТеперь выбери птицу:",
                reply_markup=await bows_keyboard()
            )
        elif not arrow:
            await message.answer(
                f"✅ Отряд {squad} найден.\nПтица: {bow}\nТеперь выбери снаряд:",
                reply_markup=await arrows_keyboard()
            )
        else:
            await message.answer(
                f"🔹 Ты уже закреплён за отрядом {squad}.\n"
                f"Птица: {bow}, Снаряд: {arrow}",
                reply_markup=ready_kb()
            )
    else:
        # новый юзер → предлагаем указать название
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏ Указать название отряда", callback_data="register_request")]
        ])
        await message.answer(
            "⚠ Ты ещё не зарегистрирован.\n"
            "Для регистрации укажи название своего отряда:",
            reply_markup=kb
        )


async def reconfig(message: types.Message):
    assert db.DB is not None

    # Проверяем, зарегистрирован ли пользователь
    row = await db.DB.fetchrow("SELECT squad FROM users WHERE tg_id=$1", message.from_user.id)

    if not row:
        await message.answer("⚠ Ты ещё не зарегистрирован. Используй /start для регистрации.")
        return

    squad = row["squad"]

    # Сбрасываем настройки
    await db.DB.execute(
        "UPDATE users SET bow=NULL, arrow=NULL, ready=FALSE WHERE tg_id=$1",
        message.from_user.id
    )

    await message.answer(
        f"✅ Отряд {squad} найден.\nТеперь выбери птицу:",
        reply_markup=await bows_keyboard()
    )


async def my_id(message: types.Message):
    await message.answer(f"Твой Telegram ID: {message.from_user.id}")


async def support_cmd(message: types.Message):
    assert db.DB is not None

    row = await db.DB.fetchrow("SELECT tg_id, name FROM admins WHERE is_main=TRUE LIMIT 1")
    if not row:
        await message.answer("⚠ Главный админ ещё не назначен.")
        return

    tg_id, name = row["tg_id"], row["name"]

    # Получаем объект пользователя через get_chat
    try:
        chat = await message.bot.get_chat(tg_id)
        username = chat.username
    except Exception:
        username = None

    if username:
        link = f"https://t.me/{username}"
    else:
        link = f"tg://user?id={tg_id}"

    text = (
        f"👑 Для связи с главным админом:\n"
        f"{name or 'Главный админ'} — <a href=\"{link}\">написать</a>"
    )
    await message.answer(text, parse_mode="HTML")


async def set_bow(callback: CallbackQuery):
    bow = callback.data.split(":", 1)[1]
    assert db.DB is not None
    await db.DB.execute("UPDATE users SET bow=$1 WHERE tg_id=$2", bow, callback.from_user.id)
    await callback.message.edit_text(
        f"Птица выбрана: {bow}\nТеперь выбери снаряд:",
        reply_markup=await arrows_keyboard()
    )
    await callback.answer()


async def set_arrow(callback: CallbackQuery):
    arrow = callback.data.split(":", 1)[1]
    assert db.DB is not None
    await db.DB.execute("UPDATE users SET arrow=$1 WHERE tg_id=$2", arrow, callback.from_user.id)
    await callback.message.edit_text(
        f"Снаряд выбран: {arrow}\nКогда будешь готов — нажми кнопку.",
        reply_markup=ready_kb()
    )
    await callback.answer()


# ---------------- Список моих задач ----------------
async def my_tasks(message: types.Message):
    uid = message.from_user.id
    row = await db.DB.fetchrow("SELECT squad FROM users WHERE tg_id=$1", uid)
    if not row:
        await message.answer("⚠ Ты не зарегистрирован в системе.")
        return
    squad = row["squad"]

    tasks = await db.DB.fetch(
        "SELECT id, point, color, status FROM tasks "
        "WHERE squad=$1 AND status IN ($2, $3) ORDER BY id",
        squad, TaskStatus.PENDING, TaskStatus.ACCEPTED
    )

    if not tasks:
        await message.answer("У тебя нет задач.")
        return

    text = "📋 Твои задачи:\n\n"
    for t in tasks:
        text += f"{t['status']} — {t['point']} ({t['color']})\n"

    await message.answer(text)