"""
集中設定模組
- 從 .env 載入所有設定
- 啟動時驗證必要設定
- 所有模組統一引用 config.XXX
"""
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# 載入 .env
load_dotenv()

# ── 路徑 ──
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── 資料庫 ──
DB_PATH = Path(os.getenv("DB_PATH", str(DATA_DIR / "leads.db")))

# ── Gmail SMTP ──
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
SENDER_NAME = os.getenv("SENDER_NAME", "業務部門")

# ── Gmail API ──
USE_GMAIL_API = os.getenv("USE_GMAIL_API", "false").lower() in ("true", "1", "yes")
GMAIL_CREDENTIALS_PATH = Path(os.getenv("GMAIL_CREDENTIALS_PATH", str(BASE_DIR / "credentials.json")))
GMAIL_TOKEN_PATH = Path(os.getenv("GMAIL_TOKEN_PATH", str(DATA_DIR / "token.json")))

# ── 每日信件限額 ──
DAILY_EMAIL_QUOTA = int(os.getenv("DAILY_EMAIL_QUOTA", "100"))

# ── 爬蟲 ──
CRAWLER_DELAY = float(os.getenv("CRAWLER_DELAY", "0.6"))
CRAWLER_MAX_RETRIES = int(os.getenv("CRAWLER_MAX_RETRIES", "3"))
CRAWLER_RETRY_BASE_DELAY = float(os.getenv("CRAWLER_RETRY_BASE_DELAY", "2.0"))

# ── ByCrawl API ──
BYCRAWL_API_KEY = os.getenv("BYCRAWL_API_KEY", "")

# ── 認證 ──
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "false").lower() in ("true", "1", "yes")
AUTH_COOKIE_KEY = os.getenv("AUTH_COOKIE_KEY", "leadflow_auth")
AUTH_COOKIE_EXPIRY_DAYS = int(os.getenv("AUTH_COOKIE_EXPIRY_DAYS", "30"))

# ── 日誌 ──
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_DIR = DATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)


def validate_config(require_gmail: bool = False, require_bycrawl: bool = False) -> list[str]:
    """
    驗證必要設定，回傳缺失項目清單（空 = 全部通過）
    """
    missing = []
    if require_gmail:
        if not GMAIL_USER:
            missing.append("GMAIL_USER")
        if not GMAIL_APP_PASSWORD and not USE_GMAIL_API:
            missing.append("GMAIL_APP_PASSWORD（或啟用 USE_GMAIL_API）")
    if require_bycrawl and not BYCRAWL_API_KEY:
        missing.append("BYCRAWL_API_KEY")
    return missing
