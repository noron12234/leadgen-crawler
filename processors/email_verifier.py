"""
Email 驗證模組
- 兩層驗證：格式 + DNS domain lookup
- 快速（無 SMTP，不發信）
- 結果：valid / suspect / invalid
"""
import socket
import re
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

# 常見免費信箱 domain（這些永遠有效，不用 DNS 查）
KNOWN_VALID_DOMAINS = {
    "gmail.com", "yahoo.com.tw", "yahoo.com", "outlook.com",
    "hotmail.com", "icloud.com", "msn.com", "live.com",
}


def _is_valid_format(email: str) -> bool:
    """格式檢查"""
    pattern = r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email.strip()))


def _check_domain(domain: str, timeout: float = 4.0) -> tuple[bool, str]:
    """DNS lookup：確認 domain 存在（thread-safe，不修改全域 socket timeout）"""
    if domain.lower() in KNOWN_VALID_DOMAINS:
        return True, "known provider"
    try:
        # 使用 getaddrinfo 搭配獨立 socket 來避免修改全域 timeout
        infos = socket.getaddrinfo(domain, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        if infos:
            return True, "dns ok"
        return False, "domain not found"
    except socket.gaierror:
        return False, "domain not found"
    except socket.timeout:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:30]


def verify_email(email: str) -> dict:
    """
    驗證單一 email（取多個 email 時驗第一個）

    Returns:
        {
            "email": "hr@company.com",
            "status": "valid" | "suspect" | "invalid",
            "reason": "dns ok" | "domain not found" | "invalid format" | ...
        }
    """
    if not email:
        return {"email": email, "status": "invalid", "reason": "empty"}

    # 多個 email 取第一個
    first = email.split(",")[0].strip()

    if not _is_valid_format(first):
        return {"email": first, "status": "invalid", "reason": "invalid format"}

    domain = first.split("@")[-1].lower()
    ok, reason = _check_domain(domain)

    if ok:
        return {"email": first, "status": "valid", "reason": reason}
    else:
        # DNS 失敗可能是暫時性（網路問題），標 suspect 不標 invalid
        return {"email": first, "status": "suspect", "reason": reason}


def verify_all(companies: list[dict], max_workers: int = 8) -> list[dict]:
    """
    批次驗證（多線程，快）

    為每個 company dict 加入 email_status / email_reason 欄位
    Returns: 原 companies 列表（in-place 修改）
    """
    emails_to_check = []
    for c in companies:
        raw = c.get("email") or ""
        if raw and "@" in raw:
            emails_to_check.append((c, raw.split(",")[0].strip()))
        else:
            c["email_status"] = "no_email"
            c["email_reason"] = ""

    if not emails_to_check:
        return companies

    def _check(item):
        company, email = item
        result = verify_email(email)
        return company, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_check, item): item for item in emails_to_check}
        for future in as_completed(futures):
            try:
                company, result = future.result()
                company["email_status"] = result["status"]
                company["email_reason"] = result["reason"]
            except Exception as e:
                item = futures[future]
                item[0]["email_status"] = "suspect"
                item[0]["email_reason"] = str(e)[:30]

    verified = sum(1 for c in companies if c.get("email_status") == "valid")
    suspect = sum(1 for c in companies if c.get("email_status") == "suspect")
    logger.info(f"Email 驗證完成：valid={verified}, suspect={suspect}")
    return companies
