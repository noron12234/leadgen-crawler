"""
Gmail 寄信模組（SMTP + App Password）
- 不需要 OAuth，只要 Gmail 應用程式密碼
- 支援 HTML 或純文字
- SMTP 批次共用連線（不再每封重建）
- 智慧路由：可自動切換 Gmail API / SMTP
"""
import smtplib
import logging
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger(__name__)


def _get_credentials() -> tuple[str, str]:
    """從 config 或環境變數取 Gmail 帳號和應用程式密碼

    Google 產生的 App Password 中間有空格（例：`xxxx xxxx xxxx xxxx`）
    SMTP login 必須拿掉空格才能通過，這裡統一清理。
    """
    try:
        from config import GMAIL_USER, GMAIL_APP_PASSWORD
        user = GMAIL_USER or os.getenv("GMAIL_USER", "")
        pwd = GMAIL_APP_PASSWORD or os.getenv("GMAIL_APP_PASSWORD", "")
    except ImportError:
        user = os.getenv("GMAIL_USER", "")
        pwd = os.getenv("GMAIL_APP_PASSWORD", "")
    # 清理 App Password 的空格與前後空白
    pwd = (pwd or "").replace(" ", "").replace("\t", "").strip()
    user = (user or "").strip()
    return user, pwd


def test_connection() -> tuple[bool, str]:
    """
    測試 Gmail 連線是否正常

    Returns:
        (True, "連線成功") 或 (False, "錯誤原因")
    """
    user, pwd = _get_credentials()
    if not user or not pwd:
        return False, "未設定 GMAIL_USER 或 GMAIL_APP_PASSWORD"
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
        return True, f"SMTP 連線成功（{user}）"
    except smtplib.SMTPAuthenticationError:
        return False, "帳號或應用程式密碼錯誤（請確認已開啟兩步驟驗證）"
    except Exception as e:
        return False, str(e)


def send_email(
    to: str,
    subject: str,
    body: str,
    sender_name: str = "",
    html: bool = False,
) -> tuple[bool, str]:
    """
    寄送單封郵件

    Returns:
        (True, "寄送成功") 或 (False, "錯誤原因")
    """
    user, pwd = _get_credentials()
    if not user or not pwd:
        return False, "未設定 GMAIL_USER 或 GMAIL_APP_PASSWORD"

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name or user, user))
        msg["To"] = to
        # Reply-To 給 Gmail 一個明確的回覆對象 — 降低「冷郵件」分類權重
        msg["Reply-To"] = user
        # RFC 8058 List-Unsubscribe — Gmail 看到這個會大幅降低「進促銷分頁」機率
        # one-click unsubscribe via mailto；POST 表示支援一鍵退訂
        import urllib.parse as _up
        unsub_mailto = f"mailto:{user}?subject={_up.quote('Unsubscribe')}"
        msg["List-Unsubscribe"] = f"<{unsub_mailto}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        # 表明這是商業郵件而非垃圾，幫 Gmail 正確分類
        msg["Precedence"] = "bulk"

        mime_type = "html" if html else "plain"
        msg.attach(MIMEText(body, mime_type, "utf-8"))

        with smtplib.SMTP("smtp.gmail.com", 587, timeout=15) as smtp:
            smtp.starttls()
            smtp.login(user, pwd)
            smtp.sendmail(user, [to], msg.as_string())

        logger.info(f"[SMTP] 郵件已寄出：{to} | 主旨：{subject}")
        return True, "寄送成功"

    except smtplib.SMTPRecipientsRefused:
        return False, f"收件人被拒絕：{to}"
    except smtplib.SMTPAuthenticationError:
        return False, "Gmail 認證失敗"
    except Exception as e:
        logger.error(f"[SMTP] 寄信失敗 → {to}：{e}")
        return False, str(e)[:80]


def send_batch(
    recipients: list[dict],
    subject_template: str,
    body_template: str,
    sender_name: str = "",
    html: bool = False,
    delay_seconds: float = 1.5,
) -> list[dict]:
    """
    批次寄信（共用單一 SMTP 連線，不再每封重建）

    Returns:
        list of {"email": str, "cust_name": str, "success": bool, "message": str}
    """
    import time

    user, pwd = _get_credentials()
    if not user or not pwd:
        return [{**r, "success": False, "message": "未設定 GMAIL 帳密"} for r in recipients]

    results = []
    smtp_conn = None

    try:
        smtp_conn = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
        smtp_conn.starttls()
        smtp_conn.login(user, pwd)
    except Exception as e:
        logger.error(f"[SMTP] 建立連線失敗：{e}")
        return [{**r, "success": False, "message": f"SMTP 連線失敗：{str(e)[:50]}"} for r in recipients]

    try:
        from mailer.tracking import gen_tracking_uid, inject_tracking
        try:
            from config import TRACKING_BASE_URL
        except ImportError:
            TRACKING_BASE_URL = ""

        for r in recipients:
            email = r.get("email", "").strip()
            if not email or "@" not in email:
                results.append({**r, "success": False, "message": "無效 email"})
                continue

            ctx = {
                "hr_name": r.get("hr_name") or "您好",
                "company": r.get("cust_name") or "貴公司",
            }
            subject = subject_template.format(**ctx)
            body = body_template.format(**ctx)

            # ── 注入追蹤（pixel + 連結改寫）──
            uid = gen_tracking_uid()
            body_to_send, is_html_after = inject_tracking(body, uid, TRACKING_BASE_URL, html)

            try:
                msg = MIMEMultipart("alternative")
                msg["Subject"] = subject
                msg["From"] = formataddr((sender_name or user, user))
                msg["To"] = email
                # Gmail 2024/02 新規：List-Unsubscribe 對 < 5000/日 也是 quality signal
                msg["List-Unsubscribe"] = f"<mailto:{user}?subject=unsubscribe>"
                msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

                mime_type = "html" if is_html_after else "plain"
                msg.attach(MIMEText(body_to_send, mime_type, "utf-8"))

                smtp_conn.sendmail(user, [email], msg.as_string())
                ok, send_msg = True, "寄送成功"
                logger.info(f"[SMTP] 郵件已寄出：{email}")
            except Exception as e:
                ok, send_msg = False, str(e)[:80]
                logger.error(f"[SMTP] 寄信失敗 → {email}：{e}")

            results.append({**r, "success": ok, "message": send_msg})

            company_id = r.get("id")
            if company_id:
                try:
                    from database.db import log_email_sent
                    log_email_sent(
                        company_id=company_id,
                        recipient_email=email,
                        subject=subject,
                        status="sent" if ok else "failed",
                        error_message="" if ok else send_msg,
                        template_used=subject_template,
                        tracking_uid=uid if ok and TRACKING_BASE_URL else "",
                        body_html=is_html_after,
                    )
                except Exception as log_err:
                    logger.debug(f"寫入 email_log 失敗：{log_err}")

            if delay_seconds > 0:
                time.sleep(delay_seconds)
    finally:
        if smtp_conn:
            try:
                smtp_conn.quit()
            except Exception:
                pass

    sent = sum(1 for r in results if r["success"])
    logger.info(f"[SMTP] 批次寄信完成：成功 {sent}/{len(results)}")
    return results


def get_sender():
    """
    智慧路由：根據設定自動選擇 Gmail API 或 SMTP sender

    Returns:
        module with send_email(), send_batch(), test_connection() functions
    """
    try:
        from config import USE_GMAIL_API
    except ImportError:
        USE_GMAIL_API = False

    if USE_GMAIL_API:
        try:
            from mailer import gmail_api_sender
            return gmail_api_sender
        except ImportError:
            logger.warning("Gmail API 模組載入失敗，降級使用 SMTP")

    # Fallback: 回傳自己（SMTP）
    import mailer.gmail_sender as self_module
    return self_module
