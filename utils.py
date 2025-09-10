from datetime import datetime
import random
import string
import phonenumbers
from phonenumbers.phonenumberutil import NumberParseException
from aiogram import types, Bot
from aiogram.types import BotCommand
import db
from enums import TaskStatus


# ---------------- Время и коды ----------------
def now_hm() -> str:
    """Текущее время в формате HH:MM"""
    return datetime.now().strftime("%H:%M")


def generate_code(squad: str) -> str:
    """Генерация уникального кода отряда: SQUAD-XXXX"""
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{squad.upper()}-{suffix}"


# ---------------- Управление командами ----------------
async def reset_user_commands(bot: Bot, user_id: int):
    """Сброс меню пользователя до стандартного"""
    user_cmds = [
        types.BotCommand(command="start", description="Войти по коду"),
        types.BotCommand(command="report", description="Отправить отчет"),
        types.BotCommand(command="mytasks", description="Список моих задач"),
        types.BotCommand(command="config", description="Изменить конфигурацию"),
        types.BotCommand(command="myid", description="Показать мой Telegram ID"),
        types.BotCommand(command="support", description="Связаться с Главным администратором"),
        types.BotCommand(command="finish", description="Завершить работу")
    ]
    await bot.set_my_commands(user_cmds, scope=types.BotCommandScopeChat(chat_id=user_id))


async def update_admin_commands(bot: Bot, admin_id: int, is_main: bool = False):
    """Обновление меню администратора"""
    if is_main:
        admin_cmds = [
            BotCommand(command="task", description="Назначить задачу"),
            BotCommand(command="edittask", description="Редактировать активную задачу"),
            BotCommand(command="sendldk", description="Отправить .ldk отряду"),
            BotCommand(command="status", description="Список готовых отрядов"),
            BotCommand(command="active", description="Список активных задач"),
            BotCommand(command="addadmin", description="Добавить администратора"),
            BotCommand(command="deladmin", description="Удалить администратора"),
            BotCommand(command="adduser", description="Добавить отряд"),
            BotCommand(command="admins", description="Список админов"),
            BotCommand(command="myid", description="Показать мой Telegram ID"),
            BotCommand(command="support", description="Связаться с Главным администратором"),
        ]
    else:
        admin_cmds = [
            BotCommand(command="task", description="Назначить задачу"),
            BotCommand(command="edittask", description="Редактировать активную задачу"),
            BotCommand(command="sendldk", description="Отправить .ldk отряду"),
            BotCommand(command="status", description="Список готовых отрядов"),
            BotCommand(command="active", description="Список активных задач"),
            BotCommand(command="adduser", description="Добавить отряд"),
            BotCommand(command="admins", description="Список админов"),
            BotCommand(command="myid", description="Показать мой Telegram ID"),
            BotCommand(command="support", description="Связаться с Главным администратором"),
        ]

    await bot.set_my_commands(admin_cmds, scope=types.BotCommandScopeChat(chat_id=admin_id))


async def update_user_status(user_id: int):
    """Пересчитать статус отряда по его задачам"""
    assert db.DB is not None

    rows = await db.DB.fetch(
        """
        SELECT t.status
        FROM tasks t
        JOIN users u ON u.squad = t.squad
        WHERE u.tg_id=$1
        """,
        user_id
    )
    tasks = [r["status"] for r in rows]

    if not tasks:
        await db.DB.execute("UPDATE users SET ready=FALSE, status='idle' WHERE tg_id=$1", user_id)
        return

    if any(st == TaskStatus.ACCEPTED for st in tasks):
        await db.DB.execute("UPDATE users SET ready=TRUE, status='busy' WHERE tg_id=$1", user_id)
    else:
        await db.DB.execute("UPDATE users SET ready=TRUE, status='idle' WHERE tg_id=$1", user_id)


async def set_commands(bot: Bot):
    """Установка глобальных и индивидуальных команд"""
    user_cmds = [
        BotCommand(command="start", description="Войти"),
        BotCommand(command="report", description="Отправить отчет"),
        BotCommand(command="mytasks", description="Список моих задач"),
        BotCommand(command="config", description="Изменить конфигурацию"),
        BotCommand(command="myid", description="Показать мой Telegram ID"),
        BotCommand(command="support", description="Связаться с Главным администратором"),
        BotCommand(command="finish", description="Завершить работу")
    ]

    # глобальные команды для всех
    await bot.set_my_commands(user_cmds)

    rows = await db.DB.fetch("SELECT tg_id, is_main FROM admins")
    admin_ids = {r["tg_id"] for r in rows}

    for r in rows:
        try:
            await update_admin_commands(bot, r["tg_id"], is_main=bool(r["is_main"]))
        except Exception as e:
            print(f"⚠ Не удалось обновить меню для админа {r['tg_id']}: {e}")

    rows = await db.DB.fetch("SELECT tg_id FROM users WHERE tg_id IS NOT NULL")
    user_ids = {r["tg_id"] for r in rows}

    for uid in user_ids - admin_ids:
        try:
            await bot.set_my_commands(user_cmds, scope=types.BotCommandScopeChat(chat_id=uid))
        except Exception as e:
            print(f"⚠ Не удалось сбросить меню для пользователя {uid}: {e}")


# ---------------- Отчёты и уведомления ----------------
def make_report(
    squad: str,
    bow: str,
    arrow: str,
    point: str,
    color: str,
    start_time: str,
    end_time: str,
    result: str | None,
    video_attached: bool,
    true_point: str | None = None,
    true_color: str | None = None,
) -> str:
    """Формирование текста отчёта"""
    res_line = f"Результат: {result}" if result else "Результат: —"
    vid_line = "Видео: приложено" if video_attached else "Видео: не приложили"

    true_line = (
        f"Реальная цель: {true_point} ({true_color.lower()})\n" if true_point and true_color else "Реальная цель: не заполняется"
    )

    return (
        f"📋 Отчет от {squad}\n"
        f"Птица: {bow}\nСнаряд: {arrow}\n"
        f"Цель: {point} ({color.lower()})\n"
        f"{true_line}\n"
        f"Вылет: {start_time}\n"
        f"Окончание: {end_time}\n"
        f"{res_line}\n{vid_line}"
    )


async def notify_admins(bot: Bot, text: str, video: str | None = None, reply_markup=None, exclude: list[int] = None):
    exclude = exclude or []
    rows = await db.DB.fetch("SELECT tg_id FROM admins")
    for r in rows:
        admin_id = r["tg_id"]
        if admin_id in exclude:
            continue
        try:
            if video:
                await bot.send_video(admin_id, video, caption=text, parse_mode="HTML", reply_markup=reply_markup)
            else:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=reply_markup)
        except Exception as e:
            print(f"⚠ Не удалось уведомить админа {admin_id}: {e}")


# ---------------- Регион и телефоны ----------------
def detect_region(message: types.Message) -> str:
    """Определяет регион по language_code (RU по умолчанию)"""
    lang = (message.from_user.language_code or "").lower()
    mapping = {
        "ru": "RU",
        "uk": "UA",
        "be": "BY",
        "kk": "KZ",
        "uz": "UZ",
        "en": "US",
    }
    return mapping.get(lang, "RU")


def validate_phone(raw: str, region: str = "RU") -> str | None:
    """Проверка и нормализация телефона (E.164)"""
    try:
        if raw.strip().startswith("+"):
            num = phonenumbers.parse(raw, None)
        else:
            num = phonenumbers.parse(raw, region)

        if phonenumbers.is_valid_number(num):
            return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        return None
    except NumberParseException:
        return None
