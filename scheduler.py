"""
自動排程模組
- 每週一早上 8:00 自動執行爬蟲 → 清洗 → 寫入 DB
- 每天中午 12:00 備份 SQLite DB 到 /data/backups/，保留最近 7 個
- 可手動觸發（CLI）
- 執行：python scheduler.py        # 啟動排程
       python scheduler.py now    # 立即跑爬蟲
       python scheduler.py backup # 立即備份
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# 切換到 feature1 目錄讓 imports 正常
os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 集中日誌
from logging_config import setup_logging
setup_logging(name="scheduler")

logger = logging.getLogger(__name__)

# 從 config 讀設定
try:
    from config import CRAWLER_DELAY
except ImportError:
    CRAWLER_DELAY = 0.6

DEFAULT_AREAS = ["6001001000", "6001002000"]
DEFAULT_MAX_PAGES = 3


def crawl_job():
    """排程執行的主函數"""
    logger.info("=" * 50)
    logger.info(f"排程爬蟲啟動：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        from crawlers.crawler_104 import crawl_snack_companies
        from crawlers.crawler_cake import crawl_cake_jobs
        from crawlers.crawler_yourator import crawl_yourator_companies
        from processors.cleaner import clean_and_merge
        from database.db import upsert_companies

        all_raw = []

        # 104 爬蟲
        logger.info("開始爬取 104...")
        r104 = crawl_snack_companies(areas=DEFAULT_AREAS, max_pages=DEFAULT_MAX_PAGES, delay=CRAWLER_DELAY)
        all_raw.extend(r104)
        logger.info(f"104 取得：{len(r104)} 家")

        # Cake 爬蟲
        try:
            logger.info("開始爬取 Cake.me...")
            rcake = crawl_cake_jobs()
            all_raw.extend(rcake)
            logger.info(f"Cake 取得：{len(rcake)} 家")
        except Exception as e:
            logger.warning(f"Cake 爬蟲失敗（不影響其他）：{e}")

        # Yourator 爬蟲
        try:
            logger.info("開始爬取 Yourator...")
            ryourator = crawl_yourator_companies()
            all_raw.extend(ryourator)
            logger.info(f"Yourator 取得：{len(ryourator)} 家")
        except Exception as e:
            logger.warning(f"Yourator 爬蟲失敗（不影響其他）：{e}")

        # 清洗與寫入
        cleaned = clean_and_merge(all_raw)
        logger.info(f"清洗後：{len(all_raw)} → {len(cleaned)} 家")

        new_count, updated_count = upsert_companies(cleaned)
        logger.info(f"DB：新增 {new_count} 家，更新 {updated_count} 家")
        logger.info("排程爬蟲完成")

    except Exception as e:
        logger.error(f"排程爬蟲發生錯誤：{e}", exc_info=True)


def run_now():
    """手動立即執行一次"""
    logger.info("手動觸發爬蟲...")
    crawl_job()


# ══════════════════════════════════════════════════════
# 資料庫備份 — 每天中午 12:00 自動備份，保留最近 7 個
# ══════════════════════════════════════════════════════
BACKUP_RETAIN = 7


def backup_job():
    """
    SQLite atomic 備份（不阻塞正在寫入的連線）。
    備份檔放 /data/backups/leads-YYYY-MM-DD_HHMM.db，保留最近 N 個。
    """
    logger.info("=" * 50)
    logger.info(f"DB 備份啟動：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    db_path = Path(os.getenv("DB_PATH", "data/leads.db"))
    backup_dir = db_path.parent / "backups"

    if not db_path.exists():
        logger.warning(f"備份略過：找不到 DB 檔案 {db_path}")
        return

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        backup_path = backup_dir / f"leads-{timestamp}.db"

        # SQLite Online Backup API：atomic、不會鎖讀寫
        src = sqlite3.connect(str(db_path))
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            src.close()
            dst.close()

        size_mb = backup_path.stat().st_size / 1024 / 1024
        logger.info(f"備份成功：{backup_path.name}（{size_mb:.2f} MB）")

        # 保留最近 N 個備份，舊的刪掉
        backups = sorted(
            backup_dir.glob("leads-*.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in backups[BACKUP_RETAIN:]:
            try:
                old.unlink()
                logger.info(f"刪除過期備份：{old.name}")
            except Exception as e:
                logger.warning(f"刪除過期備份失敗 {old.name}：{e}")

        # 列出目前還剩的備份（log 給維運看）
        remaining = sorted(backup_dir.glob("leads-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        logger.info(f"目前共 {len(remaining)} 個備份，最舊：{remaining[-1].name if remaining else '(無)'}")

    except Exception as e:
        logger.error(f"備份失敗：{e}", exc_info=True)


def backup_now():
    """手動立即備份一次（CLI: python scheduler.py backup）"""
    logger.info("手動觸發備份...")
    backup_job()


def start_scheduler(
    day_of_week: str = "mon",
    hour: int = 8,
    minute: int = 0,
):
    """啟動排程器"""
    scheduler = BlockingScheduler(timezone="Asia/Taipei")

    # 每週爬蟲
    scheduler.add_job(
        crawl_job,
        trigger=CronTrigger(
            day_of_week=day_of_week,
            hour=hour,
            minute=minute,
            timezone="Asia/Taipei",
        ),
        id="weekly_crawl",
        name="每週爬蟲",
        misfire_grace_time=3600,
    )

    # 每日 12:00 備份（白天客戶在用、機器是醒的，比凌晨可靠）
    scheduler.add_job(
        backup_job,
        trigger=CronTrigger(hour=12, minute=0, timezone="Asia/Taipei"),
        id="daily_backup",
        name="每日 DB 備份",
        misfire_grace_time=3600,
    )

    next_crawl = scheduler.get_job("weekly_crawl").next_run_time
    next_backup = scheduler.get_job("daily_backup").next_run_time
    logger.info(f"排程器啟動：")
    logger.info(f"  每週爬蟲 → 週{day_of_week} {hour:02d}:{minute:02d}（下次：{next_crawl}）")
    logger.info(f"  每日備份 → 12:00（下次：{next_backup}）")
    logger.info("按 Ctrl+C 停止排程器")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("排程器已停止")


if __name__ == "__main__":
    # 確保 data/ 目錄存在
    os.makedirs("data", exist_ok=True)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "now":
            run_now()
        elif cmd == "backup":
            backup_now()
        else:
            print(f"未知指令：{cmd}（可用：now / backup）")
            sys.exit(1)
    else:
        start_scheduler()
