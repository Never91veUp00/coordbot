from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import db


# ---------------- Общие клавиатуры ----------------
def ready_kb():
    """Кнопка 'Готов к работе' для пользователя"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Готов к работе", callback_data="ready")]
    ])


def report_keyboard(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Попадание", callback_data=f"report:{task_id}:hit"),
            InlineKeyboardButton(text="❌ Промах", callback_data=f"report:{task_id}:miss"),
        ],
        [
            InlineKeyboardButton(text="🎯 Попал в другую точку", callback_data=f"report:{task_id}:other"),
        ],
        [
            InlineKeyboardButton(text="⏸ Не выполнил", callback_data=f"report:{task_id}:skip"),
        ]
    ])


# ---------------- Клавиатуры выбора вооружения ----------------
async def bows_keyboard():
    """Клавиатура для выбора 'птицы' (лука/самолёта)"""
    assert db.DB is not None
    rows = await db.DB.fetch("SELECT name FROM bows")
    kb = [[InlineKeyboardButton(text=row["name"], callback_data=f"bow:{row['name']}")] for row in rows]
    return InlineKeyboardMarkup(inline_keyboard=kb)


async def arrows_keyboard():
    """Клавиатура для выбора 'снаряда' (боеприпаса)"""
    assert db.DB is not None
    rows = await db.DB.fetch("SELECT name FROM arrows")
    kb = [[InlineKeyboardButton(text=row["name"], callback_data=f"arrow:{row['name']}")] for row in rows]
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ---------------- Клавиатуры задач ----------------
def task_keyboard(task_id: int):
    """Кнопка 'Принял задачу' (для конкретной задачи по её id)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Принял задачу", callback_data=f"accept:{task_id}")]
    ])


async def ready_squads_keyboard():
    """Клавиатура со списком готовых отрядов"""
    assert db.DB is not None
    rows = await db.DB.fetch("SELECT tg_id, squad FROM users WHERE ready=TRUE")
    kb = [[InlineKeyboardButton(text=row["squad"], callback_data=f"task_squad:{row['tg_id']}")] for row in rows]
    return InlineKeyboardMarkup(inline_keyboard=kb)
