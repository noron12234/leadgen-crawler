"""
Gmail API 寄信模組（OAuth2）
- 比 SMTP 快 10x（不需每封建立 TLS 連線）
- OAuth2 安全認證
- 需先在 Google Cloud Console 設定 → 下載 credentials.json
"""
import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_gmail_service():
    """取得 Gmail API service（自動處理 OAuth 授權流程）"""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        raise ImportError(
            "請安裝 Gmail API 依賴：pip install google-api-python-client google-auth-oauthlib"
        )

    from config import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH

    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds = None

    if GMAIL_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GMAIL_TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GMAIL_CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"找不到 credentials.json：{GMAIL_CREDENTIALS_PATH}\n"
                    "請從 Google Cloud Console 下載 OAuth2 憑證"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GMAIL_CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        GMAIL_TOKEN_PATH.parent.mkdir(exist_ok=True)
        with open(GMAIL_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def test_connection() -> tuple[bool, str]:
    """測試 Gmail API 連線"""
    try:
        service = _get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        email = profile.get("emailAddress", "unknown")
        return True, f"Gmail API 連線成功（{email}）"
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Gmail API 連線失敗：{str(e)[:80]}"


def send_email(
    to: str,
    subject: str,
    body: str,
    sender_name: str = "",
    html: bool = False,
) -> tuple[bool, str]:
    """
    透過 Gmail API 寄送單封郵件

    Returns:
        (True, "寄送成功") 或 (False, "錯誤原因")
    """
    try:
        service = _get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        from_email = profile.get("emailAddress", "")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = formataddr((sender_name or from_email, from_email))
        msg["To"] = to
        # Gmail 2024/02 新規：List-Unsubscribe 對 < 5000/日 也是 quality signal
        msg["List-Unsubscribe"] = f"<mailto:{from_email}?subject=unsubscribe>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        mime_type = "html" if html else "plain"
        msg.attach(MIMEText(body, mime_type, "utf-8"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        logger.info(f"[Gmail API] 郵件已寄出：{to} | 主旨：{subject}")
        return True, "寄送成功（Gmail API）"

    except Exception as e:
        logger.error(f"[Gmail API] 寄信失敗 → {to}：{e}")
        return False, str(e)[:80]


def send_batch(
    recipients: list[dict],
    subject_template: str,
    body_template: str,
    sender_name: str = "",
    html: bool = False,
    delay_seconds: float = 0.3,
) -> list[dict]:
    """
    批次寄信（Gmail API 版，比 SMTP 快）

    Args:
        recipients: list of {"email": str, "hr_name": str, "cust_name": str, ...}
        subject_template: 主旨模板
        body_template:    內文模板
        sender_name:      寄件人名稱
        html:             是否為 HTML 格式
        delay_seconds:    每封信之間的延遲（API 版可以更短）

    Returns:
        list of {"email": str, "cust_name": str, "success": bool, "message": str}
    """
    import time
    from mailer.tracking import gen_tracking_uid, inject_tracking
    try:
        from config import TRACKING_BASE_URL
    except ImportError:
        TRACKING_BASE_URL = ""

    results = []
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

        ok, msg = send_email(
            to=email,
            subject=subject,
            body=body_to_send,
            sender_name=sender_name,
            html=is_html_after,
        )
        results.append({**r, "success": ok, "message": msg})

        # 寫入 email_logs
        company_id = r.get("id")
        if company_id:
            try:
                from database.db import log_email_sent
                log_email_sent(
                    company_id=company_id,
                    recipient_email=email,
                    subject=subject,
                    status="sent" if ok else "failed",
                    error_message="" if ok else msg,
                    template_used=subject_template,
                    tracking_uid=uid if ok and TRACKING_BASE_URL else "",
                    body_html=is_html_after,
                )
            except Exception as log_err:
                logger.debug(f"寫入 email_log 失敗：{log_err}")

        if delay_seconds > 0:
            time.sleep(delay_seconds)

    sent = sum(1 for r in results if r["success"])
    logger.info(f"[Gmail API] 批次寄信完成：成功 {sent}/{len(results)}")
    return results
