"""Central configuration — loads .env and exposes typed constants."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv(Path(__file__).parent / ".env")

# ── Telegram ─────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

# ── LM Studio ────────────────────────────────────────────────────────
LM_STUDIO_URL: str = os.getenv("LM_STUDIO_URL", "http://127.0.0.1:1234")
LM_STUDIO_MODEL: str = os.getenv("LM_STUDIO_MODEL", "qwen/qwen3-vl-8b")

# ── OCR ──────────────────────────────────────────────────────────────
TESSERACT_PATH: str = os.getenv("TESSERACT_PATH", "")

# ── Paths ────────────────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).parent
RECEIPTS_DIR: Path = PROJECT_ROOT / os.getenv("RECEIPTS_DIR", "receipts")
EXCEL_PATH: Path = PROJECT_ROOT / os.getenv("EXCEL_PATH", "Transactions.xlsx")

# ── Allowed values ───────────────────────────────────────────────────
ALLOWED_CURRENCIES = {"ZAR", "USD", "EUR", "GBP"}

ALLOWED_CATEGORIES = {
    "Rent",
    "Groceries",
    "Transport",
    "Airtime/Data",
    "Fuel",
    "Health/Pharmacy",
    "Utilities",
    "Insurance",
    "Office Supplies",
    "Software/Subscriptions",
    "Entertainment",
    "Food/Dining",
    "Unknown",
}

CATEGORY_SHEET_MAP = {
    "Rent": "Rent",
    "Groceries": "Groceries",
    "Transport": "Transport",
    "Airtime/Data": "Airtime_Data",
    "Fuel": "Fuel",
    "Health/Pharmacy": "Health_Pharmacy",
    "Utilities": "Utilities",
    "Insurance": "Insurance",
    "Office Supplies": "Office_Supplies",
    "Software/Subscriptions": "Software_Subs",
    "Entertainment": "Entertainment",
    "Food/Dining": "Food_Dining",
    "Unknown": "Unknown",
}
