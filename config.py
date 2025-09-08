import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DB_FILE = os.getenv("DB_FILE", "archery.db")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "845332383"))
