"""
SQLite 持久儲存模組（企業版）
- Schema migration（自動升級）
- Thread-local 連線重用
- 累積爬蟲結果（不重複）
- 追蹤已聯繫狀態
- 每日信件限額追蹤
"""
import sqlite3
import json
import logging
import threading
from pathlib import Path
from datetime import datetime, date, timedelta
import sys
import os

# 加入父目錄到 sys.path（從 app.py 呼叫時需要）
sys.path.insert(0, str(Path(__file__).parent.parent))
from processors.cleaner import _normalize_name, is_real_phone

logger = logging.getLogger(__name__)

# ── 設定 ──
try:
    from config import DB_PATH
except ImportError:
    # 這個 fallback 曾造成事故：外部腳本以為指到暫存 DB，實際寫進開發 DB。
    # fallback 觸發時大聲講，讓跑腳本的人（或 agent）第一時間看到
    DB_PATH = Path(__file__).parent.parent / "data" / "leads.db"
    logging.getLogger(__name__).warning(
        f"config 匯入失敗（通常是缺 python-dotenv 等依賴），"
        f"DB 路徑 fallback 到 {DB_PATH} — 如果你以為自己連的是別的 DB，現在就停下來"
    )

CURRENT_SCHEMA_VERSION = 9

# ── Thread-local 連線池 ──
_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """取得 thread-local 連線（重用避免 database locked）"""
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")
            return conn
        except sqlite3.ProgrammingError:
            _local.conn = None

    db_path = Path(DB_PATH)

    # 測試防污染 guard：pytest 執行中絕不允許連到真實 DB。
    # 正確做法是用 tests/conftest.py 的 tmp_db fixture（會 patch DB_PATH 到暫存目錄）
    if os.getenv("PYTEST_CURRENT_TEST"):
        _p = str(db_path).lower()
        if not any(k in _p for k in ("pytest", "test", "tmp", "temp")):
            raise RuntimeError(
                f"測試中拒絕連到真實 DB：{db_path}\n"
                f"請用 tmp_db fixture，或把 DATA_DIR 指到暫存目錄。"
            )

    db_path.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _local.conn = conn
    return conn


# ══════════════════════════════════════════════════════
# Schema Migration
# ══════════════════════════════════════════════════════

def _get_schema_version(conn: sqlite3.Connection) -> int:
    """取得目前 schema version"""
    try:
        row = conn.execute("SELECT version FROM _meta WHERE key = 'schema_version'").fetchone()
        return int(row["version"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _set_schema_version(conn: sqlite3.Connection, version: int):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _meta (
            key TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            updated_at TEXT
        )
    """)
    conn.execute("""
        INSERT OR REPLACE INTO _meta (key, version, updated_at)
        VALUES ('schema_version', ?, ?)
    """, (version, datetime.now().isoformat()))


def _run_migrations(conn: sqlite3.Connection):
    """依序執行 migration"""
    current = _get_schema_version(conn)

    if current < 1:
        # v1: 基礎 schema（初始建立）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                normalized_name   TEXT UNIQUE NOT NULL,
                source            TEXT,
                cust_id           TEXT,
                cust_name         TEXT,
                industry          TEXT,
                employee_count    TEXT,
                address           TEXT,
                phone             TEXT,
                hr_name           TEXT,
                email             TEXT,
                website           TEXT,
                job_url           TEXT,
                company_url       TEXT,
                has_snack_benefit INTEGER DEFAULT 0,
                welfare_tags      TEXT,
                first_seen        TEXT,
                last_seen         TEXT,
                contacted         INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS linkedin_people (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        TEXT UNIQUE NOT NULL,
                name            TEXT,
                headline        TEXT,
                location        TEXT,
                companies       TEXT,
                profile_url     TEXT,
                profile_pic     TEXT,
                search_keyword  TEXT,
                notes           TEXT DEFAULT '',
                starred         INTEGER DEFAULT 0,
                created_at      TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_logs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                company_id      INTEGER NOT NULL,
                recipient_email TEXT NOT NULL,
                subject         TEXT,
                sent_at         TEXT NOT NULL,
                status          TEXT NOT NULL DEFAULT 'sent',
                error_message   TEXT,
                template_used   TEXT,
                FOREIGN KEY (company_id) REFERENCES companies(id)
            )
        """)
        _set_schema_version(conn, 1)
        logger.info("Migration v1: 基礎 schema 建立完成")

    if current < 2:
        # v2: 新增 description + job_titles 欄位（LinkedIn 爬蟲需要）
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "description" not in existing_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN description TEXT DEFAULT ''")
        if "job_titles" not in existing_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN job_titles TEXT DEFAULT ''")
        _set_schema_version(conn, 2)
        logger.info("Migration v2: 新增 description, job_titles 欄位")

    if current < 3:
        # v3: 開發信追蹤（需求規格）
        email_log_cols = {row[1] for row in conn.execute("PRAGMA table_info(email_logs)").fetchall()}
        if "tracking_uid" not in email_log_cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN tracking_uid TEXT")
        if "body_html" not in email_log_cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN body_html INTEGER DEFAULT 0")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_logs_uid ON email_logs(tracking_uid)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                tracking_uid TEXT NOT NULL,
                event_type   TEXT NOT NULL,  -- 'open' | 'click'
                occurred_at  TEXT NOT NULL,
                target_url   TEXT,           -- click 事件的原始連結
                user_agent   TEXT,
                ip_hash      TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_events_uid ON email_events(tracking_uid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_email_events_type ON email_events(event_type)")

        company_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "is_hot_lead" not in company_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN is_hot_lead INTEGER DEFAULT 0")
        _set_schema_version(conn, 3)
        logger.info("Migration v3: 新增追蹤欄位（email_events, tracking_uid, is_hot_lead）")

    if current < 4:
        # v4: 多人協作審計欄位
        email_log_cols = {row[1] for row in conn.execute("PRAGMA table_info(email_logs)").fetchall()}
        if "sent_by" not in email_log_cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN sent_by TEXT DEFAULT ''")

        # companies 加「誰爬到這家公司」
        company_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "crawled_by" not in company_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN crawled_by TEXT DEFAULT ''")

        # 通用活動 log（爬蟲、寄信、登入、匯出等）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT NOT NULL,
                action      TEXT NOT NULL,      -- 'login' | 'crawl' | 'send_email' | 'export' | ...
                detail      TEXT,               -- 自由文字描述
                occurred_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(username)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_action ON activity_log(action)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(occurred_at DESC)")

        _set_schema_version(conn, 4)
        logger.info("Migration v4: 多人協作欄位（sent_by, activity_log）")

    if current < 5:
        # v5: 協作鎖 + 在線狀態
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                username        TEXT PRIMARY KEY,
                last_heartbeat  TEXT NOT NULL,
                current_page    TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resource_locks (
                lock_name   TEXT PRIMARY KEY,   -- 'crawl' | 'email'
                locked_by   TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                note        TEXT DEFAULT ''
            )
        """)
        _set_schema_version(conn, 5)
        logger.info("Migration v5: 協作鎖與在線狀態（user_sessions, resource_locks）")

    if current < 6:
        # v6: email_logs 儲存完整內文 + 收件人名稱（為「每封信詳細追蹤」顯示用）
        email_log_cols = {row[1] for row in conn.execute("PRAGMA table_info(email_logs)").fetchall()}
        if "body_snapshot" not in email_log_cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN body_snapshot TEXT DEFAULT ''")
        if "recipient_name" not in email_log_cols:
            conn.execute("ALTER TABLE email_logs ADD COLUMN recipient_name TEXT DEFAULT ''")
        _set_schema_version(conn, 6)
        logger.info("Migration v6: email_logs 加 body_snapshot + recipient_name")

    if current < 7:
        # v7: 範本版本管理 — 存多版本 + 用 template_used 串到 email_logs 做成效追蹤
        conn.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                name        TEXT NOT NULL UNIQUE,
                subject     TEXT NOT NULL,
                body        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                created_by  TEXT DEFAULT '',
                is_archived INTEGER DEFAULT 0
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tpl_archived ON email_templates(is_archived)")
        _set_schema_version(conn, 7)
        logger.info("Migration v7: email_templates 表（範本版本管理）")

    if current < 8:
        # v8: 全公司共用設定（共用 Gmail 等）— key/value store
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key         TEXT PRIMARY KEY,
                value       TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                updated_by  TEXT DEFAULT ''
            )
        """)
        _set_schema_version(conn, 8)
        logger.info("Migration v8: app_settings 表（共用 Gmail 等）")

    if current < 9:
        # v9: email 驗證結果落地（原本只存 session、重開就消失）
        #     + email_events.event_type 開放 'reply'（IMAP 回信偵測）
        company_cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        if "email_status" not in company_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN email_status TEXT DEFAULT ''")
        if "email_checked_at" not in company_cols:
            conn.execute("ALTER TABLE companies ADD COLUMN email_checked_at TEXT DEFAULT ''")
        _set_schema_version(conn, 9)
        logger.info("Migration v9: companies 加 email_status / email_checked_at")

    conn.commit()


def init_db():
    """建立資料表 + 執行 migration"""
    conn = get_connection()
    _run_migrations(conn)


# ══════════════════════════════════════════════════════
# Companies CRUD
# ══════════════════════════════════════════════════════

def upsert_companies(companies: list[dict], crawled_by: str = "") -> tuple[int, int]:
    """
    批次插入或更新公司資料
    - 新公司：直接插入（記錄 crawled_by）
    - 既有公司：補充空白欄位（email/phone/hr_name），更新 last_seen

    Returns:
        (new_count, updated_count)
    """
    init_db()
    new_count = 0
    updated_count = 0
    now = datetime.now().isoformat()

    conn = get_connection()
    for c in companies:
        key = _normalize_name(c.get("cust_name", ""))
        if not key:
            continue

        existing = conn.execute(
            "SELECT id, email, phone, hr_name, website FROM companies WHERE normalized_name = ?",
            (key,)
        ).fetchone()

        if existing is None:
            conn.execute("""
                INSERT INTO companies
                (normalized_name, source, cust_id, cust_name, industry, employee_count,
                 address, phone, hr_name, email, website, job_url, company_url,
                 has_snack_benefit, welfare_tags, first_seen, last_seen, contacted,
                 description, job_titles, crawled_by)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?,?)
            """, (
                key,
                c.get("source", ""),
                c.get("cust_id", ""),
                c.get("cust_name", ""),
                c.get("industry", ""),
                c.get("employee_count", ""),
                c.get("address", ""),
                c.get("phone", ""),
                c.get("hr_name", ""),
                c.get("email", ""),
                c.get("website", ""),
                c.get("job_url", ""),
                c.get("company_url", ""),
                1 if c.get("has_snack_benefit") else 0,
                json.dumps(c.get("welfare_tags", []), ensure_ascii=False),
                now,
                now,
                c.get("description", ""),
                c.get("job_titles", ""),
                crawled_by,
            ))
            new_count += 1
        else:
            # 更新 last_seen，並補充之前沒有的欄位
            updates: dict = {"last_seen": now}
            if not existing["email"] and c.get("email") and "@" in c.get("email", ""):
                updates["email"] = c["email"]
            if not existing["phone"] and is_real_phone(c.get("phone", "")):
                updates["phone"] = c["phone"]
            if not existing["hr_name"] and c.get("hr_name"):
                updates["hr_name"] = c["hr_name"]
            if not existing["website"] and c.get("website"):
                updates["website"] = c["website"]

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE companies SET {set_clause} WHERE normalized_name = ?",
                list(updates.values()) + [key],
            )
            updated_count += 1

    conn.commit()
    logger.info(f"upsert 完成：新增 {new_count}，更新 {updated_count}")
    return new_count, updated_count


def get_all_companies(only_not_contacted: bool = False) -> list[dict]:
    """
    取得所有公司資料
    排序：零食福利 > 有 email > 有電話 > 最新爬到
    """
    init_db()
    where = "WHERE contacted = 0" if only_not_contacted else ""

    conn = get_connection()
    rows = conn.execute(f"""
        SELECT * FROM companies
        {where}
        ORDER BY
            has_snack_benefit DESC,
            CASE WHEN email IS NOT NULL AND email LIKE '%@%' THEN 0 ELSE 1 END,
            CASE WHEN phone IS NOT NULL AND phone != '' THEN 0 ELSE 1 END,
            last_seen DESC
    """).fetchall()

    result = []
    for row in rows:
        d = dict(row)
        try:
            d["welfare_tags"] = json.loads(d.get("welfare_tags") or "[]")
        except Exception:
            d["welfare_tags"] = []
        d["has_snack_benefit"] = bool(d.get("has_snack_benefit"))
        result.append(d)
    return result


def get_stats() -> dict:
    """取得資料庫統計摘要"""
    init_db()
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    has_email = conn.execute(
        "SELECT COUNT(*) FROM companies WHERE email IS NOT NULL AND email != '' AND email LIKE '%@%'"
    ).fetchone()[0]
    has_phone = conn.execute(
        "SELECT COUNT(*) FROM companies WHERE phone IS NOT NULL AND phone != ''"
    ).fetchone()[0]
    contacted = conn.execute(
        "SELECT COUNT(*) FROM companies WHERE contacted = 1"
    ).fetchone()[0]
    return {
        "total": total,
        "has_email": has_email,
        "has_phone": has_phone,
        "contacted": contacted,
        "remaining": total - contacted,
    }


def save_email_statuses(companies: list[dict]) -> int:
    """把 email 驗證結果寫回 companies，重開頁面不再消失。回傳更新筆數。"""
    init_db()
    conn = get_connection()
    now = datetime.now().isoformat()
    n = 0
    for c in companies:
        if c.get("id") and c.get("email_status"):
            conn.execute(
                "UPDATE companies SET email_status = ?, email_checked_at = ? WHERE id = ?",
                (c["email_status"], now, c["id"]),
            )
            n += 1
    conn.commit()
    return n


def mark_contacted(company_id: int, contacted: bool = True):
    """標記公司為已聯繫 / 未聯繫"""
    init_db()
    conn = get_connection()
    conn.execute(
        "UPDATE companies SET contacted = ? WHERE id = ?",
        (1 if contacted else 0, company_id),
    )
    conn.commit()


# ══════════════════════════════════════════════════════
# Email Logs + Quota
# ══════════════════════════════════════════════════════

def log_email_sent(
    company_id: int,
    recipient_email: str,
    subject: str,
    status: str = "sent",
    error_message: str = "",
    template_used: str = "",
    tracking_uid: str = "",
    body_html: bool = False,
    sent_by: str = "",
    body_snapshot: str = "",
    recipient_name: str = "",
) -> int:
    """記錄一筆寄信 log，回傳 email_log id（供追蹤用）
    status: 'sent' | 'failed' | 'dry_run' | 'test'
    - dry_run / test 時 company_id 可為 0（非真實客戶）
    - body_snapshot: 存信件原文方便日後查看
    """
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO email_logs
        (company_id, recipient_email, subject, sent_at, status,
         error_message, template_used, tracking_uid, body_html, sent_by,
         body_snapshot, recipient_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (company_id or 0, recipient_email, subject, now, status,
          error_message, template_used, tracking_uid,
          1 if body_html else 0, sent_by,
          (body_snapshot or "")[:5000], recipient_name or ""))
    conn.commit()
    return cur.lastrowid


# ══════════════════════════════════════════════════════
# 活動 Log（給超管後台用）
# ══════════════════════════════════════════════════════

def log_activity(username: str, action: str, detail: str = ""):
    """記錄使用者活動（登入、爬蟲、寄信、匯出等）"""
    if not username:
        return
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO activity_log (username, action, detail, occurred_at)
            VALUES (?, ?, ?, ?)
        """, (username, action, detail[:500], now))
        conn.commit()
    except Exception as e:
        logger.debug(f"log_activity 失敗：{e}")


def get_user_stats() -> list[dict]:
    """超管用：所有使用者的統計摘要"""
    init_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            COALESCE(NULLIF(sent_by, ''), '（未標記）') AS username,
            COUNT(*) AS total_sent,
            SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) AS success,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
            MAX(sent_at) AS last_sent_at
        FROM email_logs
        GROUP BY username
        ORDER BY total_sent DESC
    """).fetchall()
    return [dict(r) for r in rows]


def get_activity_log(limit: int = 200, username: str = "") -> list[dict]:
    """取得活動紀錄（可依使用者過濾）"""
    init_db()
    conn = get_connection()
    if username:
        rows = conn.execute("""
            SELECT * FROM activity_log
            WHERE username = ?
            ORDER BY occurred_at DESC
            LIMIT ?
        """, (username, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM activity_log
            ORDER BY occurred_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_user_email_breakdown() -> list[dict]:
    """每位使用者寄的信的追蹤成效"""
    init_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            COALESCE(NULLIF(el.sent_by, ''), '（未標記）') AS username,
            COUNT(*) AS sent,
            COUNT(DISTINCT CASE WHEN ev.event_type IN ('open','click') THEN el.tracking_uid END) AS opened,
            COUNT(DISTINCT CASE WHEN ev.event_type='click' THEN el.tracking_uid END) AS clicked
        FROM email_logs el
        LEFT JOIN email_events ev ON ev.tracking_uid = el.tracking_uid
        WHERE el.status='sent'
        GROUP BY username
        ORDER BY sent DESC
    """).fetchall()
    result = []
    for r in rows:
        r = dict(r)
        sent = r.get("sent", 0) or 0
        r["open_rate"]  = round((r.get("opened") or 0) / sent * 100, 1) if sent else 0
        r["click_rate"] = round((r.get("clicked") or 0) / sent * 100, 1) if sent else 0
        result.append(r)
    return result


def get_daily_email_count() -> int:
    """取得今天已寄出的信件數"""
    init_db()
    today = date.today().isoformat()
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM email_logs WHERE status = 'sent' AND sent_at >= ?",
        (today,)
    ).fetchone()
    return row[0] if row else 0


def can_send_emails(count: int) -> tuple[bool, int, int]:
    """
    檢查是否可以寄出 count 封信

    Returns:
        (可以寄, 今日已寄, 每日限額)
    """
    try:
        from config import DAILY_EMAIL_QUOTA
    except ImportError:
        DAILY_EMAIL_QUOTA = 100

    sent_today = get_daily_email_count()
    return (sent_today + count) <= DAILY_EMAIL_QUOTA, sent_today, DAILY_EMAIL_QUOTA


def get_email_logs(limit: int = 100) -> list[dict]:
    """取得寄信歷史，最新在前"""
    init_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT el.*, c.cust_name
        FROM email_logs el
        LEFT JOIN companies c ON el.company_id = c.id
        ORDER BY el.sent_at DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(row) for row in rows]


def get_email_log_stats() -> dict:
    """取得寄信統計"""
    init_db()
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM email_logs").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM email_logs WHERE status = 'sent'").fetchone()[0]
    failed = conn.execute("SELECT COUNT(*) FROM email_logs WHERE status = 'failed'").fetchone()[0]
    return {"total": total, "sent": sent, "failed": failed}


def snapshot_db(tag: str = "manual") -> str:
    """
    破壞性操作前的自動快照（SQLite online backup，不鎖表）。
    存到 <DB 同層>/backups/pre-{tag}-{時間}.db。
    scheduler 的輪替只刪 leads-*.db，pre-* 檔不會被輪掉 = 永久保留。
    快照失敗會 raise — 拍不到照就不准刪資料。
    """
    init_db()
    db_path = Path(DB_PATH)
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_path = backup_dir / f"pre-{tag}-{ts}.db"
    src = get_connection()
    dst = sqlite3.connect(str(snap_path))
    try:
        src.backup(dst)
    finally:
        dst.close()
    logger.info(f"破壞性操作前快照：{snap_path}")
    return str(snap_path)


def clear_all():
    """清空所有公司資料與寄信記錄（會先自動拍快照）"""
    init_db()
    snapshot_db("clear-all")
    conn = get_connection()
    conn.execute("DELETE FROM email_events")
    conn.execute("DELETE FROM email_logs")
    conn.execute("DELETE FROM companies")
    conn.commit()
    logger.info("資料庫已清空")


# ══════════════════════════════════════════════════════
# 範本版本管理（feature #5）
# ══════════════════════════════════════════════════════

def save_template(name: str, subject: str, body: str, username: str = "") -> int:
    """存範本。同名會覆蓋（UPSERT 概念，用 INSERT OR REPLACE）。"""
    init_db()
    if not name.strip():
        raise ValueError("範本名稱不可空")
    now = datetime.now().isoformat()
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO email_templates (name, subject, body, created_at, created_by, is_archived)
        VALUES (?, ?, ?, ?, ?, 0)
        ON CONFLICT(name) DO UPDATE SET
            subject = excluded.subject,
            body = excluded.body,
            created_at = excluded.created_at,
            created_by = excluded.created_by,
            is_archived = 0
    """, (name.strip(), subject, body, now, username))
    conn.commit()
    row = conn.execute("SELECT id FROM email_templates WHERE name = ?", (name.strip(),)).fetchone()
    return row["id"] if row else cur.lastrowid


def get_templates(include_archived: bool = False) -> list[dict]:
    """取得所有範本，最新在前。"""
    init_db()
    conn = get_connection()
    sql = "SELECT * FROM email_templates"
    if not include_archived:
        sql += " WHERE is_archived = 0"
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def archive_template(template_id: int):
    """軟刪除範本（保留歷史成效資料）。"""
    init_db()
    conn = get_connection()
    conn.execute("UPDATE email_templates SET is_archived = 1 WHERE id = ?", (template_id,))
    conn.commit()


# ══════════════════════════════════════════════════════
# 全公司共用設定（共用 Gmail 等）
# ══════════════════════════════════════════════════════

def get_setting(key: str, default: str = "") -> str:
    """讀取全公司共用設定"""
    init_db()
    conn = get_connection()
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str, username: str = ""):
    """寫入全公司共用設定（會覆蓋既有值）"""
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO app_settings (key, value, updated_at, updated_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at,
            updated_by = excluded.updated_by
    """, (key, value, now, username))
    conn.commit()


def get_shared_gmail() -> dict:
    """一次拿全公司共用 Gmail 設定（給 app 啟動時填回 session_state）"""
    return {
        "gmail_user": get_setting("shared_gmail_user"),
        "gmail_pwd": get_setting("shared_gmail_pwd"),
        "sender_name": get_setting("shared_gmail_sender_name"),
    }


def get_server_backups(backup_dir: str = "/data/backups") -> list[dict]:
    """列出 server 端 daily backup（scheduler.py 每天 4AM 寫的）。
    回傳 [{file, size_kb, mtime, age_hours}, ...] 最新在前。
    """
    import os, time
    from pathlib import Path
    p = Path(backup_dir)
    if not p.is_dir():
        return []
    now = time.time()
    rows = []
    for f in p.glob("leads-*.db"):
        st = f.stat()
        rows.append({
            "file": f.name,
            "size_kb": round(st.st_size / 1024, 1),
            "mtime": st.st_mtime,
            "mtime_iso": datetime.fromtimestamp(st.st_mtime).isoformat(),
            "age_hours": round((now - st.st_mtime) / 3600, 1),
        })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


# ══════════════════════════════════════════════════════
# 開發信追蹤（需求規格）
# ══════════════════════════════════════════════════════

# 只擋「確定是掃描器」的 UA（企業反釣魚產品），這類不代表有人看信。
# 不擋 Gmail / Outlook image proxy — 因為它們 cache 住所有圖片載入，
# 擋了會讓正常使用者打開信也偵測不到（多數郵件服務用這種 proxy 架構）。
# 代價：pre-fetch 會造成「寄出後幾秒就標開信」— 可接受，業界標準行為。
_SCANNER_UA_PATTERNS = (
    "proofpoint",
    "mimecast",
    "barracuda",
    "symantec",
    "sophos",
    "trendmicro",
)


def _is_scanner_ua(user_agent: str) -> bool:
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(p in ua for p in _SCANNER_UA_PATTERNS)


def record_email_event(
    tracking_uid: str,
    event_type: str,
    target_url: str = "",
    user_agent: str = "",
    ip_hash: str = "",
    occurred_at: str = "",
):
    """
    記錄一筆開信/點擊/回信事件，並在必要時將該公司標記為熱門客戶。
    event_type: 'open' | 'click' | 'reply'
    occurred_at: 事件實際發生時間（ISO），空值用現在 — 回信偵測要帶信件的 Date

    只會過濾企業反釣魚掃描器（Proofpoint / Mimecast 等）的 UA，其餘都記。
    Gmail / Outlook 的 image proxy 會把 open pixel 提早觸發，接受這個誤差 —
    業界郵件追蹤工具都這樣做。
    """
    if event_type not in ("open", "click", "reply"):
        return
    init_db()
    conn = get_connection()
    now = occurred_at or datetime.now().isoformat()

    if event_type == "open" and _is_scanner_ua(user_agent):
        logger.info(f"略過反釣魚掃描器 open: uid={tracking_uid[:8]} ua={user_agent[:60]}")
        return

    # Dedupe：同 uid+type+ip 在 30 秒內的重複事件視為同一次（擋洗 event DoS）
    # ip_hash 空時跳過 dedupe（測試或無 IP 資訊的情境）
    if ip_hash:
        last = conn.execute(
            "SELECT occurred_at FROM email_events "
            "WHERE tracking_uid = ? AND event_type = ? AND ip_hash = ? "
            "ORDER BY occurred_at DESC LIMIT 1",
            (tracking_uid, event_type, ip_hash),
        ).fetchone()
        if last and last["occurred_at"]:
            try:
                last_at = datetime.fromisoformat(last["occurred_at"])
                if (datetime.now() - last_at).total_seconds() < 30:
                    logger.info(f"dedupe {event_type} event: uid={tracking_uid[:8]} ip_hash={ip_hash[:8]}")
                    return
            except (ValueError, TypeError):
                pass

    conn.execute("""
        INSERT INTO email_events (tracking_uid, event_type, occurred_at, target_url, user_agent, ip_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (tracking_uid, event_type, now, target_url, user_agent, ip_hash))

    # 熱門客戶：點擊任一連結、或回信，即標記
    if event_type in ("click", "reply"):
        row = conn.execute(
            "SELECT company_id FROM email_logs WHERE tracking_uid = ?", (tracking_uid,)
        ).fetchone()
        if row and row["company_id"]:
            conn.execute("UPDATE companies SET is_hot_lead = 1 WHERE id = ?", (row["company_id"],))
    conn.commit()


# ──────────────────────────────────────────────────────
# 預掃過濾邏輯
# ──────────────────────────────────────────────────────
# 問題：Gmail 收信時，伺服器端反釣魚 / image proxy 會「預先抓 pixel」
#       導致客戶根本沒打開、系統卻記為已開信。
# 過濾規則（任一條成立視為預掃）：
#   1. 寄出後 < 10 秒就 open → 99% 是 Google 伺服器預掃
#   2. 寄出後 < 60 秒 且 UA 含 GoogleImageProxy / ggpht.com → 同上
#   3. UA 為已知反釣魚產品（既有 _SCANNER_UA_PATTERNS）
# Click 事件不過濾 — 機器掃描不會點連結，所有 click 都是真實互動。
_PROXY_UA_PATTERNS = ("googleimageproxy", "ggpht.com",
                      "microsoft outlook protection", "atplinks", "safelinks")

# 「真實開信」判斷片段 — 需要查詢裡有 ev（email_events）、el（email_logs）兩個 alias。
# 所有要算開信數的地方（總覽 / 模板比較 / 熱門客戶）都引用這段，口徑才會一致。
_REAL_OPEN_COND = """
      (
          ev.event_type IN ('click','reply')
          OR (
              ev.event_type = 'open'
              AND (CAST((julianday(ev.occurred_at) - julianday(el.sent_at)) * 86400 AS INTEGER)) >= 10
              AND NOT (
                  LOWER(COALESCE(ev.user_agent, '')) LIKE '%googleimageproxy%'
                  AND (CAST((julianday(ev.occurred_at) - julianday(el.sent_at)) * 86400 AS INTEGER)) < 60
              )
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%proofpoint%'
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%mimecast%'
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%barracuda%'
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%symantec%'
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%sophos%'
              AND LOWER(COALESCE(ev.user_agent, '')) NOT LIKE '%safelinks%'
          )
      )
"""

_REAL_OPEN_SQL = f"""
    SELECT DISTINCT ev.tracking_uid
    FROM email_events ev
    JOIN email_logs el ON ev.tracking_uid = el.tracking_uid
    WHERE ev.event_type IN ('open','click','reply')
      AND el.tracking_uid IS NOT NULL AND el.tracking_uid != ''
      AND {_REAL_OPEN_COND}
"""

_ALL_OPEN_SQL = """
    SELECT DISTINCT tracking_uid FROM email_events
    WHERE event_type IN ('open','click')
"""


def get_tracking_stats() -> dict:
    """
    整體追蹤統計：開信率、點擊率、熱門客戶數
    返回兩種開信數：
      - opened: 過濾預掃後的「確認開信」（KPI 用）
      - opened_raw: 不過濾的原始事件（diagnostic）
    Click 不過濾 — 點連結必須真人。
    """
    init_db()
    conn = get_connection()
    sent = conn.execute(
        "SELECT COUNT(*) FROM email_logs WHERE status IN ('sent','test') AND tracking_uid IS NOT NULL AND tracking_uid != ''"
    ).fetchone()[0]

    opened = conn.execute(f"SELECT COUNT(*) FROM ({_REAL_OPEN_SQL})").fetchone()[0]
    opened_raw = conn.execute(f"SELECT COUNT(*) FROM ({_ALL_OPEN_SQL})").fetchone()[0]
    clicked = conn.execute(
        "SELECT COUNT(DISTINCT tracking_uid) FROM email_events WHERE event_type='click'"
    ).fetchone()[0]
    replied = conn.execute(
        "SELECT COUNT(DISTINCT tracking_uid) FROM email_events WHERE event_type='reply'"
    ).fetchone()[0]
    hot = conn.execute("SELECT COUNT(*) FROM companies WHERE is_hot_lead = 1").fetchone()[0]

    def _pct(n, d):
        return round(n / d * 100, 1) if d else 0.0

    return {
        "sent": sent,
        "opened": opened,
        "opened_raw": opened_raw,
        "prefetch_filtered": opened_raw - opened,
        "clicked": clicked,
        "replied": replied,
        "hot_leads": hot,
        "open_rate": _pct(opened, sent),
        "open_rate_raw": _pct(opened_raw, sent),
        "click_rate": _pct(clicked, sent),
        "click_to_open_rate": _pct(clicked, opened),
    }


def get_template_stats() -> list[dict]:
    """各模板成效比較：寄出 / 開信（過濾預掃）/ 點擊"""
    init_db()
    conn = get_connection()
    # 開信過濾直接引用 _REAL_OPEN_COND，與總覽/熱門客戶同一口徑
    rows = conn.execute(f"""
        SELECT
            COALESCE(NULLIF(template_used, ''), '（未分類）') AS template,
            COUNT(*) AS sent,
            SUM(CASE WHEN EXISTS (
                SELECT 1 FROM email_events ev
                WHERE ev.tracking_uid = el.tracking_uid
                  AND {_REAL_OPEN_COND}
            ) THEN 1 ELSE 0 END) AS opened,
            SUM(CASE WHEN EXISTS (
                SELECT 1 FROM email_events ev WHERE ev.tracking_uid = el.tracking_uid AND ev.event_type='click'
            ) THEN 1 ELSE 0 END) AS clicked
        FROM email_logs el
        WHERE status='sent' AND tracking_uid IS NOT NULL AND tracking_uid != ''
        GROUP BY template
        ORDER BY sent DESC
    """).fetchall()
    result = []
    for r in rows:
        sent = r["sent"] or 0
        opened = r["opened"] or 0
        clicked = r["clicked"] or 0
        result.append({
            "template": r["template"],
            "sent": sent,
            "opened": opened,
            "clicked": clicked,
            "open_rate": round(opened / sent * 100, 1) if sent else 0.0,
            "click_rate": round(clicked / sent * 100, 1) if sent else 0.0,
        })
    return result


def get_hot_leads() -> list[dict]:
    """列出熱門客戶（有點擊過），依點擊次數排序"""
    init_db()
    conn = get_connection()
    # open_count 套用與總覽相同的預掃過濾（_REAL_OPEN_COND），
    # 不然匯出到 ERP 的開信數會比儀表板「確認開信」偏高、對不上
    rows = conn.execute(f"""
        SELECT c.*,
               COUNT(DISTINCT CASE WHEN ev.event_type='open' AND {_REAL_OPEN_COND}
                     THEN ev.id END) AS open_count,
               COUNT(DISTINCT CASE WHEN ev.event_type='click' THEN ev.id END) AS click_count,
               COUNT(DISTINCT CASE WHEN ev.event_type='reply' THEN ev.id END) AS reply_count,
               MAX(ev.occurred_at) AS last_event_at
        FROM companies c
        JOIN email_logs el ON el.company_id = c.id
        JOIN email_events ev ON ev.tracking_uid = el.tracking_uid
        WHERE c.is_hot_lead = 1
        GROUP BY c.id
        ORDER BY reply_count DESC, click_count DESC, open_count DESC, last_event_at DESC
    """).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        try:
            d["welfare_tags"] = json.loads(d.get("welfare_tags") or "[]")
        except Exception:
            d["welfare_tags"] = []
        result.append(d)
    return result


def get_events_for_uid(tracking_uid: str) -> list[dict]:
    """取得某封信的所有追蹤事件"""
    init_db()
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM email_events WHERE tracking_uid = ? ORDER BY occurred_at ASC",
        (tracking_uid,),
    ).fetchall()
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════
# LinkedIn 人物
# ══════════════════════════════════════════════════════

def save_linkedin_people(people: list[dict], keyword: str = "") -> int:
    """儲存 LinkedIn 人物搜尋結果，回傳新增筆數"""
    init_db()
    now = datetime.now().isoformat()
    saved = 0

    conn = get_connection()
    for p in people:
        username = p.get("username", "").strip()
        if not username:
            continue
        try:
            conn.execute("""
                INSERT OR IGNORE INTO linkedin_people
                (username, name, headline, location, companies, profile_url, profile_pic, search_keyword, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                username,
                p.get("name", ""),
                p.get("headline", ""),
                p.get("location", ""),
                p.get("companies", ""),
                p.get("profile_url", ""),
                p.get("profile_pic", ""),
                keyword,
                now,
            ))
            saved += conn.total_changes
        except Exception:
            pass
    conn.commit()

    return saved


def get_linkedin_people() -> list[dict]:
    """取得所有已儲存的 LinkedIn 人物"""
    init_db()
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM linkedin_people
        ORDER BY starred DESC, created_at DESC
    """).fetchall()
    return [dict(row) for row in rows]


def toggle_person_star(person_id: int, starred: bool):
    """切換人物星號標記"""
    init_db()
    conn = get_connection()
    conn.execute(
        "UPDATE linkedin_people SET starred = ? WHERE id = ?",
        (1 if starred else 0, person_id),
    )
    conn.commit()


def update_person_notes(person_id: int, notes: str):
    """更新人物備註"""
    init_db()
    conn = get_connection()
    conn.execute(
        "UPDATE linkedin_people SET notes = ? WHERE id = ?",
        (notes, person_id),
    )
    conn.commit()


def delete_linkedin_people_all():
    """清空所有 LinkedIn 人物（會先自動拍快照）"""
    init_db()
    snapshot_db("clear-linkedin")
    conn = get_connection()
    conn.execute("DELETE FROM linkedin_people")
    conn.commit()


# ══════════════════════════════════════════════════════
# 在線狀態 + 協作鎖（多人同時使用）
# ══════════════════════════════════════════════════════

_HEARTBEAT_TTL = 180     # 超過 180 秒（3 分鐘）沒心跳視為離線
_LOCK_TTL      = 900     # 鎖最多 15 分鐘自動過期（避免卡死）


def heartbeat(username: str, page: str = ""):
    """使用者心跳（每次 rerun 呼叫）"""
    if not username:
        return
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO user_sessions (username, last_heartbeat, current_page)
        VALUES (?, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            last_heartbeat = excluded.last_heartbeat,
            current_page = excluded.current_page
    """, (username, now, page))
    conn.commit()


def get_online_users() -> list[dict]:
    """取得目前在線使用者（近 60 秒內有心跳）"""
    init_db()
    cutoff = (datetime.now() - timedelta(seconds=_HEARTBEAT_TTL)).isoformat()
    conn = get_connection()
    rows = conn.execute("""
        SELECT username, last_heartbeat, current_page
        FROM user_sessions
        WHERE last_heartbeat >= ?
        ORDER BY last_heartbeat DESC
    """, (cutoff,)).fetchall()
    return [dict(r) for r in rows]


def acquire_lock(lock_name: str, username: str, note: str = "") -> tuple[bool, str]:
    """
    嘗試取得鎖；回傳 (是否成功, 訊息)。
    如果有別人佔用、且鎖未過期 → 失敗
    自己已經持有 → 視為成功（續約）
    """
    init_db()
    now_dt = datetime.now()
    now = now_dt.isoformat()
    expires = (now_dt + timedelta(seconds=_LOCK_TTL)).isoformat()

    conn = get_connection()
    row = conn.execute(
        "SELECT locked_by, expires_at FROM resource_locks WHERE lock_name = ?",
        (lock_name,),
    ).fetchone()

    if row:
        if row["expires_at"] < now:
            # 已過期，可接管
            pass
        elif row["locked_by"] != username:
            return False, f"{row['locked_by']} 正在使用中（到 {row['expires_at'][:16].replace('T',' ')}）"
        else:
            # 自己已持有 → 續約
            conn.execute(
                "UPDATE resource_locks SET acquired_at=?, expires_at=?, note=? WHERE lock_name=?",
                (now, expires, note, lock_name),
            )
            conn.commit()
            return True, "已取得"

    conn.execute("""
        INSERT INTO resource_locks (lock_name, locked_by, acquired_at, expires_at, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lock_name) DO UPDATE SET
            locked_by = excluded.locked_by,
            acquired_at = excluded.acquired_at,
            expires_at = excluded.expires_at,
            note = excluded.note
    """, (lock_name, username, now, expires, note))
    conn.commit()
    return True, "已取得"


def release_lock(lock_name: str, username: str):
    """釋放鎖（只有持有者能釋放）"""
    init_db()
    conn = get_connection()
    conn.execute(
        "DELETE FROM resource_locks WHERE lock_name = ? AND locked_by = ?",
        (lock_name, username),
    )
    conn.commit()


def get_lock_holder(lock_name: str) -> dict | None:
    """查看誰正在持有某個鎖（若已過期回 None）"""
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    row = conn.execute("""
        SELECT locked_by, acquired_at, expires_at, note
        FROM resource_locks
        WHERE lock_name = ? AND expires_at >= ?
    """, (lock_name, now)).fetchone()
    return dict(row) if row else None


def admin_force_release_lock(lock_name: str):
    """超管強制釋放（卡住時救命）"""
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM resource_locks WHERE lock_name = ?", (lock_name,))
    conn.commit()
