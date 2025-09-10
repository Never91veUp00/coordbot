from aiogram import Bot, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from datetime import datetime
from utils import detect_region, validate_phone, notify_admins, generate_code
import db


# --- Для пользователей, которые проходят регистрацию ---
async def handle_registration(message: types.Message, bot: Bot):
    text = (message.text or "").strip()
    if not text:
        return

    # Проверяем, зарегистрирован ли уже
    exists = await db.DB.fetchrow("SELECT 1 FROM users WHERE tg_id=$1", message.from_user.id)
    if exists:
        return

    # Проверяем, есть ли заявка в pending
    row = await db.DB.fetchrow(
        "SELECT id, squad, phone FROM pending WHERE target_uid=$1 ORDER BY created_at DESC LIMIT 1",
        message.from_user.id
    )

    if not row:
        # первая запись
        await db.DB.execute(
            "INSERT INTO pending (admin_id, target_uid, squad, created_at) VALUES ($1, $2, $3, $4)",
            0, message.from_user.id, text, datetime.now().isoformat(timespec="seconds")
        )
        await message.answer("📞 Теперь введи номер телефона для связи (например, +79998887766):")
        return

    pending_id, squad, phone = row["id"], row["squad"], row["phone"]

    if not squad:
        # 👈 сюда попадает после register_request
        await db.DB.execute("UPDATE pending SET squad=$1 WHERE id=$2", text, pending_id)
        await message.answer("📞 Теперь введи номер телефона для связи (например, +79998887766):")
        return

    if squad and not phone:
        # ждём телефон
        region = detect_region(message)
        phone_norm = validate_phone(text, region)
        if not phone_norm:
            await message.answer("⚠ Некорректный номер телефона. Укажи его в международном формате (например, +79998887766).")
            return

        await db.DB.execute("UPDATE pending SET phone=$1 WHERE id=$2", phone_norm, pending_id)

        # Отправляем заявку всем админам
        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Зарегистрировать", callback_data=f"approve:{pending_id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"reject:{pending_id}")
        ]])

        await notify_admins(
            bot,
            f"📋 Новая заявка на регистрацию\n"
            f"🕒 <i>{ts}</i>\n\n"
            f"👤 <a href=\"tg://user?id={message.from_user.id}\">Чат с пользователем</a>\n"
            f"Отряд: <b>{squad}</b>\n"
            f"☎ Телефон: <a href=\"tel:{phone_norm}\">{phone_norm}</a>\n"
            f"🌍 Язык/регион: {(message.from_user.language_code or 'неизвестно').upper()}",
            video=None,
            reply_markup=kb
        )

        await message.answer("📨 Заявка отправлена администратору. Жди решения.")
        return

    if squad and phone:
        await message.answer("📨 Твоя заявка уже отправлена администратору. Жди решения.")


async def register_request(callback: CallbackQuery):
    await callback.message.edit_text("✏ Введи название своего отряда одним сообщением.")
    await db.DB.execute(
        "INSERT INTO pending (admin_id, target_uid, created_at) VALUES ($1, $2, $3) "
        "ON CONFLICT (target_uid) DO UPDATE SET created_at=EXCLUDED.created_at",
        0, callback.from_user.id, datetime.now().isoformat(timespec="seconds")
    )
    await callback.answer()


async def approve_user(callback: CallbackQuery, bot: Bot):
    pending_id = int(callback.data.split(":")[1])

    row = await db.DB.fetchrow(
        "SELECT target_uid, squad, phone FROM pending WHERE id=$1",
        pending_id
    )

    if not row:
        await callback.answer("⚠ Заявка не найдена.")
        return

    uid, squad_name, phone = row["target_uid"], row["squad"], row["phone"]
    code = generate_code(squad_name)

    await db.DB.execute(
        "INSERT INTO users (tg_id, squad, code, bow, arrow, ready, status) "
        "VALUES ($1, $2, $3, NULL, NULL, FALSE, 'idle') "
        "ON CONFLICT (tg_id) DO UPDATE SET squad=EXCLUDED.squad, code=EXCLUDED.code",
        uid, squad_name, code
    )
    await db.DB.execute("DELETE FROM pending WHERE id=$1", pending_id)

    # уведомляем пользователя
    try:
        await bot.send_message(
            uid,
            f"✅ Ты зарегистрирован как отряд <b>{squad_name}</b>.\n"
            f"Нажми /start для продолжения.",
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠ Не удалось уведомить {uid}: {e}")

    # редактируем сообщение у того админа, кто нажал
    await callback.message.edit_text(
        f"✅ Пользователь зарегистрирован\n"
        f"Отряд: <b>{squad_name}</b>\n"
        f"ID: <a href=\"tg://user?id={uid}\">{uid}</a>\n"
        f"☎ Телефон: <a href=\"tel:{phone}\">{phone}</a>",
        parse_mode="HTML"
    )

    # уведомляем других админов
    await notify_admins(
        bot,
        f"👤 Новый пользователь зарегистрирован админом {callback.from_user.id}\n"
        f"Отряд: <b>{squad_name}</b>\n"
        f"ID: <a href=\"tg://user?id={uid}\">{uid}</a>\n"
        f"☎ Телефон: <a href=\"tel:{phone}\">{phone}</a>",
        exclude=[callback.from_user.id]
    )

    await callback.answer()


async def reject_user(callback: CallbackQuery, bot: Bot):
    pending_id = int(callback.data.split(":")[1])

    row = await db.DB.fetchrow("SELECT target_uid FROM pending WHERE id=$1", pending_id)

    if not row:
        await callback.answer("⚠ Заявка не найдена.")
        return

    uid = row["target_uid"]
    await db.DB.execute("DELETE FROM pending WHERE id=$1", pending_id)

    try:
        await bot.send_message(
            uid,
            "❌ Тебе отказано в доступе.\n"
            "Для уточнения свяжись с главным администратором, нажми /support."
        )
    except Exception as e:
        print(f"⚠ Не удалось уведомить пользователя {uid}: {e}")

    ts = datetime.now().strftime("%d.%m.%Y %H:%M")
    await callback.message.edit_text(
        f"❌ Заявка от <a href=\"tg://user?id={uid}\">{uid}</a> отклонена\n"
        f"🕒 <i>{ts}</i>",
        parse_mode="HTML"
    )

    # уведомляем других админов
    await notify_admins(
        bot,
        f"❌ Админ {callback.from_user.id} отклонил заявку пользователя <a href=\"tg://user?id={uid}\">{uid}</a>\n"
        f"🕒 <i>{ts}</i>",
        exclude=[callback.from_user.id]
    )

    await callback.answer()
