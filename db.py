import aiosqlite
from config import DB_FILE

# ---------------- Глобальная переменная ----------------
DB: aiosqlite.Connection | None = None


# ---------------- Инициализация и закрытие ----------------
async def init_db():
    """Создать соединение с БД"""
    global DB
    DB = await aiosqlite.connect(DB_FILE)
    DB.row_factory = aiosqlite.Row
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
    async with DB.execute("SELECT 1 FROM admins WHERE tg_id=?", (user_id,)) as cur:
        return bool(await cur.fetchone())


# ---------------- Миграции ----------------
async def migrate():
    """Создание и «мягкие» миграции схемы"""
    assert DB is not None

    # --- users ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS users (
        tg_id INTEGER PRIMARY KEY,
        squad TEXT,
        code TEXT UNIQUE,
        bow TEXT,
        arrow TEXT,
        ready INTEGER DEFAULT 0,
        status TEXT DEFAULT 'idle'
    )""")

    # --- tasks ---
    async with DB.execute("PRAGMA table_info(tasks)") as cur:
        cols = [row[1] async for row in cur]

    if not cols:
        # таблицы tasks ещё нет
        await DB.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id INTEGER,
            squad TEXT,
            point TEXT,
            color TEXT,
            start_time TEXT,
            end_time TEXT,
            status TEXT,
            report TEXT,
            video_attached INTEGER DEFAULT 0,
            result TEXT,
            await_video INTEGER DEFAULT 0,
            ldk_file TEXT
        )""")
    elif "id" not in cols:
        # таблица есть, но без id → пересоздаём
        await DB.execute("ALTER TABLE tasks RENAME TO tasks_old")

        await DB.execute("""
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            squad TEXT NOT NULL,
            point TEXT,
            color TEXT,
            status TEXT CHECK(status IN ('pending', 'accepted', 'finished', 'archived')),
            start_time TEXT,
            end_time TEXT,
            message_id INTEGER,
            result TEXT,
            report TEXT,
            video_attached INTEGER DEFAULT 0,
            await_video INTEGER DEFAULT 0,
            ldk_file TEXT
        );
        """)

        # переносим данные (без id)
        await DB.execute("""
        INSERT INTO tasks (squad, point, color, start_time, end_time, status, report,
                           video_attached, result)
        SELECT squad, point, color, start_time, end_time, status, report,
               COALESCE(video_attached, 0), result
        FROM tasks_old
        """)
        await DB.execute("DROP TABLE tasks_old")
    else:
        # таблица есть с id → добавляем недостающие колонки
        for col, ddl in [
            ("video_attached", "ALTER TABLE tasks ADD COLUMN video_attached INTEGER DEFAULT 0"),
            ("result", "ALTER TABLE tasks ADD COLUMN result TEXT"),
            ("await_video", "ALTER TABLE tasks ADD COLUMN await_video INTEGER DEFAULT 0"),
            ("ldk_file", "ALTER TABLE tasks ADD COLUMN ldk_file TEXT"),
        ]:
            if col not in cols:
                try:
                    await DB.execute(ddl)
                except Exception:
                    pass

    # --- admins ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        tg_id INTEGER PRIMARY KEY,
        name TEXT,
        is_main INTEGER DEFAULT 0
    )""")

    # --- bows ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS bows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )""")

    # --- arrows ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS arrows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )""")

    # --- pending ---
    await DB.execute("""
    CREATE TABLE IF NOT EXISTS pending (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        admin_id INTEGER,
        target_uid INTEGER,
        point TEXT,
        color TEXT,
        squad TEXT,
        phone TEXT,
        await_ldk INTEGER DEFAULT 0,
        created_at TEXT,
        is_edit INTEGER DEFAULT 0   -- 👈 добавляем
    )
    """)

    # главный админ
    await DB.execute(
        "INSERT OR IGNORE INTO admins (tg_id, name, is_main) VALUES (?, ?, ?)",
        (845332383, 'Главный админ', 1)
    )

    # тестовые данные
    for b in ["Утка", "Молния"]:
        await DB.execute("INSERT OR IGNORE INTO bows (name) VALUES (?)", (b,))
    for a in ["ОФСП", "ОФБЧ", "СВУ", "Зажигалка", "Кумулятив", "ТМ62"]:
        await DB.execute("INSERT OR IGNORE INTO arrows (name) VALUES (?)", (a,))

    await DB.commit()

