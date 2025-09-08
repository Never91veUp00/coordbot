from aiogram import Bot, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from keyboards import bows_keyboard, arrows_keyboard, ready_kb
from utils import notify_admins
import db

async def start_cmd(message: types.Message):
    assert db.DB is not None
    async with db.DB.execute(
        "SELECT squad, bow, arrow FROM users WHERE tg_id=?", (message.from_user.id,)
    ) as cur:
        row = await cur.fetchone()

    if row:
        squad, bow, arrow = row
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
    async with db.DB.execute("SELECT squad FROM users WHERE tg_id=?", (message.from_user.id,)) as cur:
        row = await cur.fetchone()

    if not row:
        await message.answer("⚠ Ты ещё не зарегистрирован. Используй /start для регистрации.")
        return

    squad = row[0]

    # Сбрасываем настройки
    await db.DB.execute(
        "UPDATE users SET bow=NULL, arrow=NULL, ready=0 WHERE tg_id=?",
        (message.from_user.id,)
    )
    await db.DB.commit()

    await message.answer(
        f"✅ Отряд {squad} найден.\nТеперь выбери птицу:",
        reply_markup=await bows_keyboard()
    )

from utils import finish_work

async def finish_cmd(message: types.Message):
    await finish_work(message.from_user.id)
    await db.DB.commit()
    await message.answer("🛑 Работа окончена. Тебе больше не будут назначать задачи, пока снова не нажмёшь «Готов».")


async def my_id(message: types.Message):
    await message.answer(f"Твой Telegram ID: {message.from_user.id}")


async def support_cmd(message):
    assert db.DB is not None

    async with db.DB.execute("SELECT tg_id, name FROM admins WHERE is_main=1 LIMIT 1") as cur:
        row = await cur.fetchone()

    if not row:
        await message.answer("⚠ Главный админ ещё не назначен.")
        return

    tg_id, name = row

    # Получаем объект пользователя через get_chat
    try:
        chat = await message.bot.get_chat(tg_id)
        username = chat.username
    except Exception:
        username = None

    if username:
        link = f"https://t.me/{username}"
    else:
        # Фолбэк — хоть что-то, если username отсутствует
        link = f"tg://user?id={tg_id}"

    text = (
        f"👑 Для связи с главным админом:\n"
        f"{name or 'Главный админ'} — <a href=\"{link}\">написать</a>"
    )
    await message.answer(text, parse_mode="HTML")


async def set_bow(callback: CallbackQuery):
    bow = callback.data.split(":", 1)[1]
    assert db.DB is not None
    await db.DB.execute("UPDATE users SET bow=? WHERE tg_id=?", (bow, callback.from_user.id))
    await db.DB.commit()
    await callback.message.edit_text(
        f"Птица выбрана: {bow}\nТеперь выбери снаряд:",
        reply_markup=await arrows_keyboard()
    )
    await callback.answer()


async def set_arrow(callback: CallbackQuery):
    arrow = callback.data.split(":", 1)[1]
    assert db.DB is not None
    await db.DB.execute("UPDATE users SET arrow=? WHERE tg_id=?", (arrow, callback.from_user.id))
    await db.DB.commit()
    await callback.message.edit_text(
        f"Снаряд выбран: {arrow}\nКогда будешь готов — нажми кнопку.",
        reply_markup=ready_kb()
    )
    await callback.answer()