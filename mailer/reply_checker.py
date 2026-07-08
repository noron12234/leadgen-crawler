"""
回信偵測（IMAP）
- 用寄信同一組 Gmail 帳密登入 imap.gmail.com，掃收件匣最近 N 天
- 寄件人 email 對上 email_logs.recipient_email（曾寄出且有追蹤碼）→ 記 'reply' 事件
- 回信的公司自動標成熱門（record_email_event 內建）
- dedupe：回信的 IMAP Message-ID 存在 email_events.target_url，同一封不重複記
- 需要該 Gmail 帳號開啟 IMAP（設定 → 查看所有設定 → 轉寄和 POP/IMAP）
"""
from __future__ import annotations

import email
import imaplib
import logging
from datetime import datetime, timedelta
from email.utils import parseaddr, parsedate_to_datetime

logger = logging.getLogger(__name__)


def check_replies(days: int = 30, limit: int = 500) -> dict:
    """
    掃描收件匣找客戶回信。

    Returns:
        {"ok": bool, "scanned": int, "new_replies": int,
         "matched_emails": list[str], "message": str}
    """
    from mailer.gmail_sender import _get_credentials
    from database.db import get_connection, init_db, record_email_event

    result = {"ok": False, "scanned": 0, "new_replies": 0,
              "matched_emails": [], "message": ""}

    user, pwd = _get_credentials()
    if not user or not pwd:
        result["message"] = "未設定 GMAIL_USER / GMAIL_APP_PASSWORD"
        return result

    init_db()
    conn = get_connection()
    # 每個收件人取最近一筆帶追蹤碼的寄信 log（SQLite bare-column + MAX 取同列值）
    rows = conn.execute("""
        SELECT LOWER(TRIM(recipient_email)) AS email,
               tracking_uid, company_id, MAX(sent_at) AS sent_at
        FROM email_logs
        WHERE status = 'sent' AND tracking_uid IS NOT NULL AND tracking_uid != ''
        GROUP BY LOWER(TRIM(recipient_email))
    """).fetchall()
    targets = {r["email"]: r["tracking_uid"] for r in rows if r["email"]}
    if not targets:
        result["message"] = "還沒有寄出過帶追蹤碼的信，沒有可比對的收件人"
        return result

    seen_msgids = {
        r["target_url"]
        for r in conn.execute(
            "SELECT target_url FROM email_events WHERE event_type = 'reply'"
        ).fetchall()
    }

    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=20)
        imap.login(user, pwd)
        imap.select("INBOX", readonly=True)
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        _typ, data = imap.search(None, f'(SINCE "{since}")')
        ids = data[0].split()[-limit:]
        result["scanned"] = len(ids)

        for mid in ids:
            _typ, msg_data = imap.fetch(
                mid, "(BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID DATE SUBJECT)])"
            )
            if not msg_data or not msg_data[0] or not isinstance(msg_data[0], tuple):
                continue
            hdr = email.message_from_bytes(msg_data[0][1])
            from_addr = (parseaddr(hdr.get("From", ""))[1] or "").lower().strip()
            if not from_addr or from_addr == user.lower():
                continue
            uid = targets.get(from_addr)
            if not uid:
                continue
            msgid = (hdr.get("Message-ID") or "").strip() or f"imap-{mid.decode()}"
            if msgid in seen_msgids:
                continue
            occurred = ""
            try:
                occurred = (
                    parsedate_to_datetime(hdr.get("Date"))
                    .astimezone().replace(tzinfo=None).isoformat()
                )
            except Exception:
                pass  # 沒有合法 Date header 就用掃描當下時間
            record_email_event(uid, "reply", target_url=msgid,
                               user_agent="imap-reply-checker",
                               occurred_at=occurred)
            seen_msgids.add(msgid)
            result["new_replies"] += 1
            result["matched_emails"].append(from_addr)
            logger.info(f"[reply] 發現回信：{from_addr} → uid={uid[:8]}")

        imap.logout()
        result["ok"] = True
        result["message"] = (
            f"掃描 {result['scanned']} 封收件匣郵件，"
            f"發現 {result['new_replies']} 封新回信"
        )
    except imaplib.IMAP4.error as e:
        result["message"] = (
            f"IMAP 登入失敗：{e}（請確認該 Gmail 已開啟 IMAP："
            "設定 → 轉寄和 POP/IMAP → 啟用 IMAP）"
        )
        logger.warning(f"[reply] {result['message']}")
    except Exception as e:
        result["message"] = f"回信掃描失敗：{e}"
        logger.error(f"[reply] {result['message']}", exc_info=True)
    return result
