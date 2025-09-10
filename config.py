import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
MAIN_ADMIN_ID = int(os.getenv("MAIN_ADMIN_ID", "845332383"))
