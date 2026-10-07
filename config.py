import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(admin_id.strip()) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id.strip()]
DATABASE_URL = os.getenv("DATABASE_URL")
REFERRAL_REWARD = float(os.getenv("REFERRAL_REWARD", "1.0"))
