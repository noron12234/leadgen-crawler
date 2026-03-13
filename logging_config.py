"""
集中日誌設定
- RotatingFileHandler（5MB，保留 3 份）
- Console + File 雙輸出
- 統一格式
"""
import logging
from logging.handlers import RotatingFileHandler
from config import LOG_DIR, LOG_LEVEL

_initialized = False


def setup_logging(name: str = "leadflow"):
    """
    初始化全域日誌設定（只執行一次）

    Args:
        name: 日誌檔名前綴
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    log_file = LOG_DIR / f"{name}.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    # Console handler
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(log_format))
    root.addHandler(console)

    # File handler (rotating)
    file_handler = RotatingFileHandler(
        str(log_file),
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    root.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("streamlit").setLevel(logging.WARNING)
