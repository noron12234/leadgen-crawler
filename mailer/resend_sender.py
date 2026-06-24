"""
Resend 寄信模組
- 專業 email API（送達率 95%+）
- 需綁自訂網域（e.g. sales@leadgen.com）
- 免費 3,000 封/月
- 對外介面跟 gmail_sender.py 一致
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _get_config() -> tuple[str, str, str]:
    """
    取得 Resend 設定。
    Returns: (api_key, from_email, from_name)
    """
    try:
        from config import RESEND_API_KEY, RESEND_FROM_EMAIL, SENDER_NAME
        api = RESEND_API_KEY or os.getenv("RESEND_API_KEY", "")
        frm = RESEND_FROM_EMAIL or os.getenv("RESEND_FROM_EMAIL", "")
        name = SENDER_NAME or os.getenv("SENDER_NAME", "業務部門")
    except ImportError:
        api = os.getenv("RESEND_API_KEY", "")
        frm = os.getenv("RESEND_FROM_EMAIL", "")
        name = os.getenv("SENDER_NAME", "業務部門")
    return api.strip(), frm.strip(), name.strip()


def _get_client():
    """Lazy import，避免沒裝 resend 套件時整個 app 爆掉"""
    try:
        import resend
    except ImportError:
        raise ImportError("請先安裝 resend：pip install resend")
    api_key, _, _ = _get_config()
    if not api_key:
        raise ValueError("未設定 RESEND_API_KEY")
    resend.api_key = api_key
    return resend


def test_connection() -> tuple[bool, str]:
    """測試 Resend API 連線（用查詢 domains 當 ping）"""
    try:
        api_key, from_email, _ = _get_config()
        if not api_key:
            return False, "未設定 RESEND_API_KEY"
        if not from_email or "@" not in from_email:
            return False, "未設定 RESEND_FROM_EMAIL（需填 sales@yourdomain.com）"

        client = _get_client()
        # 查詢已驗證的 domain 列表，確認 api_key 有效
        domains = client.Domains.list()
        domain_list = domains.get("data", []) if isinstance(domains, dict) else domains
        verified = [d.get("name") for d in (domain_list or [])
                    if d.get("status") == "verified"]

        sender_domain = from_email.split("@")[1]
        if sender_domain not in verified:
            return False, (
                f"寄件網域 {sender_domain} 尚未在 Resend 驗證。"
                f"已驗證的網域：{', '.join(verified) if verified else '（無）'}。"
                f"請到 resend.com/domains 新增並設定 DNS 記錄。"
            )
        return True, f"Resend 連線成功（{from_email}）"
    except ImportError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Resend 連線失敗：{str(e)[:100]}"


def send_email(
    to: str,
    subject: str,
    body: str,
    sender_name: str = "",
    html: bool = False,
    reply_to: Optional[str] = None,
) -> tuple[bool, str]:
    """
    用 Resend 寄單封信。
    Returns: (True, "寄送成功") 或 (False, "錯誤訊息")
    """
    from mailer.allowlist import is_allowed, block_message
    if not is_allowed(to):
        logger.warning(f"[Resend] [ALLOWLIST] BLOCKED → {to}")
        return False, block_message(to)

    try:
        client = _get_client()
    except (ImportError, ValueError) as e:
        return False, str(e)

    _, from_email, default_name = _get_config()
    if not from_email or "@" not in from_email:
        return False, "未設定寄件 Email（RESEND_FROM_EMAIL）"

    display_name = sender_name or default_name
    from_field = f"{display_name} <{from_email}>" if display_name else from_email

    params = {
        "from": from_field,
        "to": [to],
        "subject": subject,
        # Resend 需要 html 或 text 擇一
        "html" if html else "text": body,
        # 加 List-Unsubscribe header（Gmail 2024 規範）
        "headers": {
            "List-Unsubscribe": f"<mailto:{from_email}?subject=unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    }
    if reply_to:
        params["reply_to"] = reply_to

    try:
        result = client.Emails.send(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", "")
        logger.info(f"[Resend] 寄出 → {to} (id={email_id})")
        return True, f"寄送成功（Resend id={email_id[:8]}…）"
    except Exception as e:
        err = str(e)[:120]
        logger.error(f"[Resend] 寄信失敗 → {to}：{err}")
        return False, err


def send_batch(
    recipients: list[dict],
    subject_template: str,
    body_template: str,
    sender_name: str = "",
    html: bool = False,
    delay_seconds: float = 0.3,
) -> list[dict]:
    """
    批次寄信（逐封呼叫 send_email，Resend 本身沒 rate limit 壓力但為禮貌加小延遲）
    """
    import time
    from mailer.tracking import gen_tracking_uid, inject_tracking

    try:
        from config import TRACKING_BASE_URL
    except ImportError:
        TRACKING_BASE_URL = ""

    results = []
    for r in recipients:
        email = (r.get("email") or "").strip()
        if not email or "@" not in email:
            results.append({**r, "success": False, "message": "無效 email"})
            continue

        ctx = {
            "hr_name": r.get("hr_name") or "您好",
            "company": r.get("cust_name") or "貴公司",
        }
        subject = subject_template.format(**ctx)
        body = body_template.format(**ctx)

        uid = gen_tracking_uid()
        body_to_send, is_html_after = inject_tracking(body, uid, TRACKING_BASE_URL, html)

        ok, msg = send_email(
            to=email, subject=subject, body=body_to_send,
            sender_name=sender_name, html=is_html_after,
        )
        results.append({**r, "success": ok, "message": msg})

        # 寫 email_logs
        cid = r.get("id")
        if cid:
            try:
                from database.db import log_email_sent
                log_email_sent(
                    company_id=cid, recipient_email=email,
                    subject=subject,
                    status="sent" if ok else "failed",
                    error_message="" if ok else msg,
                    template_used=subject_template,
                    tracking_uid=uid if ok and TRACKING_BASE_URL else "",
                    body_html=is_html_after,
                )
            except Exception as log_err:
                logger.debug(f"[Resend] 寫 log 失敗：{log_err}")

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    sent = sum(1 for r in results if r["success"])
    logger.info(f"[Resend] 批次寄信完成：{sent}/{len(results)}")
    return results
