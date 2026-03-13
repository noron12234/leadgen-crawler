"""
自動排程模組
- 每週一早上 8:00 自動執行爬蟲 → 清洗 → 寫入 DB
- 可手動觸發（CLI）
- 執行：python scheduler.py
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import os
import logging
from datetime import datetime
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


def start_scheduler(
    day_of_week: str = "mon",
    hour: int = 8,
    minute: int = 0,
):
    """啟動排程器"""
    scheduler = BlockingScheduler(timezone="Asia/Taipei")

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

    next_run = scheduler.get_job("weekly_crawl").next_run_time
    logger.info(f"排程器啟動：每週{day_of_week} {hour:02d}:{minute:02d} 自動執行")
    logger.info(f"下次執行時間：{next_run}")
    logger.info("按 Ctrl+C 停止排程器")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("排程器已停止")


if __name__ == "__main__":
    # 確保 data/ 目錄存在
    os.makedirs("data", exist_ok=True)

    if len(sys.argv) > 1 and sys.argv[1] == "now":
        run_now()
    else:
        start_scheduler()
