"""
寄信收件人白名單守門員

用 env var `EMAIL_ALLOWLIST` 控制：
  - 未設定（None / 空字串）   → 全放行（prod 預設行為，不改變既有流程）
  - 設定（"a@b.com,c@d.com"） → 只放行白名單，其他一律 BLOCKED 不寄

用途：staging / preview / 本機跑 E2E 時不誤寄真信給真客戶。
2026-06-25 加入，補上 STAGING_SOP.md 早就寫但 code 沒實作的機制。
"""
import os
import logging
from typing import Iterable

logger = logging.getLogger(__name__)

_ENV_VAR = "EMAIL_ALLOWLIST"


def _load_allowlist() -> set[str]:
    raw = os.getenv(_ENV_VAR, "").strip()
    if not raw:
        return set()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def is_enabled() -> bool:
    """白名單是否啟用（env var 有值就是啟用）"""
    return bool(_load_allowlist())


def is_allowed(email: str) -> bool:
    """收件人是否被允許寄出

    - 白名單未啟用 → True（不改變既有行為）
    - 啟用 → 只有白名單內 email 為 True，大小寫不敏感
    """
    allowlist = _load_allowlist()
    if not allowlist:
        return True
    return (email or "").strip().lower() in allowlist


def filter_recipients(recipients: Iterable[dict], email_key: str = "email") -> tuple[list[dict], list[dict]]:
    """把 recipients 切成 (allowed, blocked) 兩串

    blocked 的 dict 會加 `success=False, message="BLOCKED by EMAIL_ALLOWLIST"`
    讓 caller 直接 append 到 results、UI 看得到。
    """
    if not is_enabled():
        return list(recipients), []
    allowed, blocked = [], []
    for r in recipients:
        email = (r.get(email_key) or "").strip()
        if is_allowed(email):
            allowed.append(r)
        else:
            blocked.append({**r, "success": False, "message": f"BLOCKED by {_ENV_VAR}: {email}"})
    if blocked:
        logger.warning(f"[ALLOWLIST] 擋下 {len(blocked)} 封不在白名單的信，放行 {len(allowed)} 封")
    return allowed, blocked


def block_message(email: str) -> str:
    """單封 send_email 被擋時的標準訊息"""
    return f"BLOCKED by {_ENV_VAR}: {email}"
