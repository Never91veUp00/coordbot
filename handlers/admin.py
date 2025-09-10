from aiogram import Bot, types
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from utils import notify_admins, generate_code, update_admin_commands, reset_user_commands
from db import is_admin
from enums import TaskStatus
import db
import random, string


async def add_admin(message: types.Message, bot: Bot):
    assert db.DB is not None

    # Проверяем, что команду вызвал именно главный админ
    row = await db.DB.fetchrow("SELECT is_main FROM admins WHERE tg_id=$1", message.from_user.id)
    if not row or not row["is_main"]:
        await message.answer("❌ Только главный админ может назначать новых админов.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используй: /addadmin <tg_id>")
        return

    new_admin_id = int(args[1])

    if new_admin_id == message.from_user.id:
        await message.answer("❌ Ты уже главный админ, нельзя назначить самого себя.")
        return

    # 🚫 Запрет: нельзя назначить отряд админом
    row = await db.DB.fetchrow("SELECT 1 FROM users WHERE tg_id=$1", new_admin_id)
    if row:
        await message.answer("❌ Отряд не может быть назначен админом.")
        return

    # пробуем получить username
    try:
        chat = await bot.get_chat(new_admin_id)
        username = chat.username or None
    except Exception:
        username = None

    name = username or random.choice(["Орел", "Ястреб", "Сокол", "Волк", "Тигр"]) + "-" + ''.join(random.choices(string.ascii_uppercase, k=3))

    await db.DB.execute(
        "INSERT INTO admins (tg_id, name, is_main) VALUES ($1, $2, FALSE) "
        "ON CONFLICT (tg_id) DO UPDATE SET name=EXCLUDED.name",
        new_admin_id, name
    )

    try:
        await update_admin_commands(bot, new_admin_id)
    except Exception as e:
        print(f"⚠ Не удалось обновить меню для нового админа {new_admin_id}: {e}")

    await bot.send_message(new_admin_id, "👑 Поздравляем! Тебя назначили администратором.")
    await message.answer(f"✅ Пользователь {new_admin_id} добавлен как админ под именем {name}")


async def del_admin_cmd(message: types.Message):
    assert db.DB is not None

    row = await db.DB.fetchrow("SELECT is_main FROM admins WHERE tg_id=$1", message.from_user.id)
    if not row or not row["is_main"]:
        await message.answer("❌ Только главный админ может удалять администраторов.")
        return

    admins = await db.DB.fetch("SELECT tg_id, name FROM admins WHERE is_main=FALSE")
    if not admins:
        await message.answer("⚠ Других админов нет.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{adm['name'] or 'Безымянный'} ({adm['tg_id']})", callback_data=f"deladm:{adm['tg_id']}")]
            for adm in admins
        ]
    )
    await message.answer("Выбери админа для удаления:", reply_markup=kb)


async def del_admin_cb(callback: CallbackQuery, bot: Bot):
    removed_id = int(callback.data.split(":")[1])

    await db.DB.execute("DELETE FROM admins WHERE tg_id=$1", removed_id)

    try:
        await reset_user_commands(bot, removed_id)
    except Exception:
        pass

    await callback.message.edit_text(f"✅ Админ {removed_id} удалён.")
    try:
        await bot.send_message(removed_id, "⚠ У тебя больше нет прав администратора.")
    except Exception:
        pass


async def list_admins(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    rows = await db.DB.fetch("SELECT tg_id, name FROM admins")

    if not rows:
        await message.answer("Админов пока нет.")
    else:
        text = "👑 Список админов:\n\n" + "\n".join(
            f"{r['tg_id']}{(' — ' + r['name']) if r['name'] else ''}" for r in rows
        )
        await message.answer(text)


async def show_ready_squads(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    rows = await db.DB.fetch("""
        SELECT u.squad, u.bow, u.arrow
        FROM users u
        WHERE u.ready=TRUE
    """)

    if not rows:
        await message.answer("Нет готовых отрядов.")
        return

    text = "📋 Готовые отряды:\n\n"
    text += "\n".join(
        f"{row['squad']} | Птица: {row['bow'] or '—'} | Снаряд: {row['arrow'] or '—'}"
        for row in rows
    )

    await message.answer(text)


async def show_active_tasks(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    rows = await db.DB.fetch(
        "SELECT squad, point, color, start_time, status "
        "FROM tasks WHERE status = $1",
        TaskStatus.ACCEPTED
    )

    if not rows:
        await message.answer("Активных задач нет.")
    else:
        lines = []
        for row in rows:
            status_emoji = "⏳" if row["status"] == TaskStatus.PENDING else "✅"
            lines.append(
                f"{status_emoji} {row['squad']} → {row['point']} ({row['color']}) | старт: {row['start_time'] or '—'}"
            )
        text = "🔥 Активные задачи:\n\n" + "\n".join(lines)
        await message.answer(text)


async def add_user(message: types.Message, bot: Bot):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Используй: /adduser <tg_id> <название_отряда>")
        return

    try:
        new_tg_id = int(args[1])
    except ValueError:
        await message.answer("⚠ tg_id должен быть числом.")
        return

    if new_tg_id == message.from_user.id:
        await message.answer("❌ Ты не можешь назначить себя отрядом.")
        return

    row = await db.DB.fetchrow("SELECT is_main FROM admins WHERE tg_id=$1", new_tg_id)
    if row and row["is_main"]:
        await message.answer("❌ Главный админ не может быть назначен отрядом.")
        return

    squad_name = args[2]
    code = generate_code(squad_name)

    await db.DB.execute(
        "INSERT INTO users (tg_id, squad, code, bow, arrow, ready, status) "
        "VALUES ($1, $2, $3, NULL, NULL, FALSE, 'idle') "
        "ON CONFLICT (tg_id) DO UPDATE SET squad=EXCLUDED.squad, code=EXCLUDED.code",
        new_tg_id, squad_name, code
    )

    await notify_admins(bot, f"👤 Новый отряд добавлен: {squad_name} (ID {new_tg_id})")

    try:
        await bot.send_message(
            new_tg_id,
            f"🔹 Тебя добавили в систему как отряд {squad_name}.\n"
            f"Нажми /start, чтобы продолжить настройку."
        )
    except Exception as e:
        await message.answer(f"⚠ Не удалось уведомить {new_tg_id}: {e}")

    await message.answer(f"✅ Отряд {squad_name} добавлен (ID {new_tg_id})")
