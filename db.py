# db.py
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("DATABASE_URL")

# Глобальное подключение (pool)
DB: asyncpg.Pool | None = None


# ---------------- Инициализация и закрытие ----------------
async def init_db():
    """Создать пул соединений с PostgreSQL"""
    global DB
    DB = await asyncpg.create_pool(DB_URL)
    return DB


async def close_db():
    """Закрыть соединение с БД"""
    global DB
    if DB:
        await DB.close()
        DB = None


# ---------------- Проверки ----------------
async def is_admin(user_id: int) -> bool:
    """Проверка: является ли пользователь админом"""
    assert DB is not None
    row = await DB.fetchrow("SELECT 1 FROM admins WHERE tg_id=$1", user_id)
    return bool(row)


# ---------------- Миграции ----------------
async def migrate():
    """Создание таблиц (минимальные миграции)"""
    assert DB is not None

    # --- users ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id BIGINT PRIMARY KEY,
        squad TEXT,
        code TEXT UNIQUE,
        bow TEXT,
        arrow TEXT,
        ready BOOLEAN DEFAULT FALSE,
        status TEXT DEFAULT 'idle'
    )
    """)

    # --- tasks ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id SERIAL PRIMARY KEY,
        message_id BIGINT,
        squad TEXT NOT NULL,
        point TEXT,
        color TEXT,
        start_time TEXT,      -- сохраняем только часы и минуты для отчёта
        end_time TEXT,
        status TEXT,
        report TEXT,
        video_attached BOOLEAN DEFAULT FALSE,
        result TEXT,
        await_video BOOLEAN DEFAULT FALSE,
        ldk_file TEXT,
        true_point TEXT,
        true_color TEXT,
        created_at TIMESTAMP DEFAULT now()  -- 👈 дата и время создания
    )
    """)

    # --- admins ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        tg_id BIGINT PRIMARY KEY,
        name TEXT,
        is_main BOOLEAN DEFAULT FALSE
    )
    """)

    # --- bows ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS bows (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
    )
    """)

    # --- arrows ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS arrows (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
    )
    """)

    # --- pending ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS pending (
        id SERIAL PRIMARY KEY,
        admin_id BIGINT,
        target_uid BIGINT UNIQUE,
        point TEXT,
        color TEXT,
        squad TEXT,
        phone TEXT,
        await_ldk BOOLEAN DEFAULT FALSE,
        created_at TIMESTAMP DEFAULT now(),  -- 👈 дата заявки
        is_edit BOOLEAN DEFAULT FALSE
    )
    """)

    # главный админ
    await DB.execute("""
    INSERT INTO admins (tg_id, name, is_main)
    VALUES (845332383, 'Главный админ', TRUE)
    ON CONFLICT (tg_id) DO NOTHING
    """)

    # тестовые данные
    for b in ["Утка", "Молния"]:
        await DB.execute("INSERT INTO bows (name) VALUES ($1) ON CONFLICT DO NOTHING", b)
    for a in ["ОФСП", "ОФБЧ", "СВУ", "Зажигалка", "Кумулятив", "ТМ62"]:
        await DB.execute("INSERT INTO arrows (name) VALUES ($1) ON CONFLICT DO NOTHING", a)
