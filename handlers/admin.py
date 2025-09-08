from aiogram import Bot, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from utils import notify_admins, generate_code, update_admin_commands, reset_user_commands
from db import is_admin
from enums import TaskStatus
import db
import random, string


async def add_admin(message: types.Message, bot: Bot):
    assert db.DB is not None

    # Проверяем, что команду вызвал именно главный админ
    async with db.DB.execute("SELECT is_main FROM admins WHERE tg_id=?", (message.from_user.id,)) as cur:
        row = await cur.fetchone()
    if not row or row[0] != 1:
        await message.answer("❌ Только главный админ может назначать новых админов.")
        return

    args = message.text.split()
    if len(args) < 2:
        await message.answer("Используй: /addadmin <tg_id>")
        return

    new_admin_id = int(args[1])

    # 🚫 Запрет: главный админ не может назначить сам себя
    if new_admin_id == message.from_user.id:
        await message.answer("❌ Ты уже главный админ, нельзя назначить самого себя.")
        return

    # 🚫 Запрет: нельзя назначить отряд админом
    async with db.DB.execute("SELECT 1 FROM users WHERE tg_id=?", (new_admin_id,)) as cur:
        if await cur.fetchone():
            await message.answer("❌ Отряд не может быть назначен админом.")
            return

    # пробуем получить username
    try:
        chat = await bot.get_chat(new_admin_id)
        username = chat.username or None
    except Exception:
        username = None

    import random, string
    name = username or random.choice(["Орел", "Ястреб", "Сокол", "Волк", "Тигр"]) + "-" + ''.join(random.choices(string.ascii_uppercase, k=3))

    await db.DB.execute(
        "INSERT OR REPLACE INTO admins (tg_id, name, is_main) VALUES (?, ?, 0)",
        (new_admin_id, name)
    )
    await db.DB.commit()

    # 👇 Теперь корректный вызов
    try:
        await update_admin_commands(bot, new_admin_id)
    except Exception as e:
        print(f"⚠ Не удалось обновить меню для нового админа {new_admin_id}: {e}")

    await bot.send_message(new_admin_id, "👑 Поздравляем! Тебя назначили администратором.")
    await message.answer(f"✅ Пользователь {new_admin_id} добавлен как админ под именем {name}")


async def del_admin_cmd(message: types.Message):
    assert db.DB is not None

    # Только главный админ
    async with db.DB.execute("SELECT is_main FROM admins WHERE tg_id=?", (message.from_user.id,)) as cur:
        row = await cur.fetchone()
    if not row or row[0] != 1:
        await message.answer("❌ Только главный админ может удалять администраторов.")
        return

    # список всех админов, кроме главного
    async with db.DB.execute("SELECT tg_id, name FROM admins WHERE is_main=0") as cur:
        admins = await cur.fetchall()

    if not admins:
        await message.answer("⚠ Других админов нет.")
        return

    # клавиатура
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{name or 'Безымянный'} ({uid})", callback_data=f"deladm:{uid}")]
            for uid, name in admins
        ]
    )
    await message.answer("Выбери админа для удаления:", reply_markup=kb)


async def del_admin_cb(callback: CallbackQuery, bot: Bot):
    removed_id = int(callback.data.split(":")[1])

    await db.DB.execute("DELETE FROM admins WHERE tg_id=?", (removed_id,))
    await db.DB.commit()

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

    assert db.DB is not None
    async with db.DB.execute("SELECT tg_id, name FROM admins") as cur:
        rows = await cur.fetchall()

    if not rows:
        await message.answer("Админов пока нет.")
    else:
        text = "👑 Список админов:\n\n" + "\n".join(
            f"{r[0]}{(' — ' + r[1]) if r[1] else ''}" for r in rows
        )
        await message.answer(text)


async def show_ready_squads(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    assert db.DB is not None
    async with db.DB.execute("""
        SELECT u.squad, u.bow, u.arrow
        FROM users u
        WHERE u.ready=1
    """) as cur:
        rows = await cur.fetchall()

    if not rows:
        await message.answer("Нет готовых отрядов.")
        return

    text = "📋 Готовые отряды:\n\n" + "\n".join(
        f"{squad} | Птица: {bow or '—'} | Снаряд: {arrow or '—'}"
        for squad, bow, arrow in rows
    )
    await message.answer(text)



async def show_active_tasks(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.answer("Нет прав.")
        return

    assert db.DB is not None
    async with db.DB.execute(
        "SELECT squad, point, color, start_time, status "
        "FROM tasks WHERE status = ?",
        (TaskStatus.ACCEPTED,)
    ) as cur:
        rows = await cur.fetchall()

    if not rows:
        await message.answer("Активных задач нет.")
    else:
        lines = []
        for squad, point, color, start_time, status in rows:
            status_emoji = "⏳" if status == TaskStatus.PENDING else "✅"
            lines.append(
                f"{status_emoji} {squad} → {point} ({color}) | старт: {start_time or '—'}"
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

    async with db.DB.execute("SELECT is_main FROM admins WHERE tg_id=?", (new_tg_id,)) as cur:
        row = await cur.fetchone()
    if row and row[0] == 1:
        await message.answer("❌ Главный админ не может быть назначен отрядом.")
        return

    squad_name = args[2]
    code = generate_code(squad_name)

    await db.DB.execute(
        "INSERT OR REPLACE INTO users (tg_id, squad, code, bow, arrow, ready, status) "
        "VALUES (?, ?, ?, NULL, NULL, 0, 'idle')",
        (new_tg_id, squad_name, code)
    )
    await db.DB.commit()

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
