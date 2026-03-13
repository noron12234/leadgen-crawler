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
from datetime import datetime, date
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
    DB_PATH = Path(__file__).parent.parent / "data" / "leads.db"

CURRENT_SCHEMA_VERSION = 2

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

    conn.commit()


def init_db():
    """建立資料表 + 執行 migration"""
    conn = get_connection()
    _run_migrations(conn)


# ══════════════════════════════════════════════════════
# Companies CRUD
# ══════════════════════════════════════════════════════

def upsert_companies(companies: list[dict]) -> tuple[int, int]:
    """
    批次插入或更新公司資料
    - 新公司：直接插入
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
                 description, job_titles)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)
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
):
    """記錄一筆寄信 log"""
    init_db()
    now = datetime.now().isoformat()
    conn = get_connection()
    conn.execute("""
        INSERT INTO email_logs (company_id, recipient_email, subject, sent_at, status, error_message, template_used)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (company_id, recipient_email, subject, now, status, error_message, template_used))
    conn.commit()


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


def clear_all():
    """清空所有公司資料與寄信記錄"""
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM email_logs")
    conn.execute("DELETE FROM companies")
    conn.commit()
    logger.info("資料庫已清空")


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
    """清空所有 LinkedIn 人物"""
    init_db()
    conn = get_connection()
    conn.execute("DELETE FROM linkedin_people")
    conn.commit()
