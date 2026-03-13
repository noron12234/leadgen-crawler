"""
資料清洗與去重模組
- 合併多平台資料
- 去除重複公司
- 標記茶水間關鍵字
- 清洗電話號碼格式
"""
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 茶水間/零食相關關鍵字
SNACK_KEYWORDS = [
    "零食", "茶水間", "下午茶", "飲料", "咖啡", "伙食",
    "餐費", "飲食", "snack", "beverage", "coffee", "pantry",
]

# 「不提供電話」的常見字串
FAKE_PHONE_PATTERNS = ["暫不提供", "不提供", "N/A", "na", "無", ""]


def is_real_phone(phone: str) -> bool:
    """判斷是否是真實電話號碼（非『暫不提供』等）"""
    if not phone:
        return False
    cleaned = phone.strip()
    if cleaned in FAKE_PHONE_PATTERNS:
        return False
    # 必須包含數字
    digits = re.sub(r"\D", "", cleaned)
    return len(digits) >= 6


def clean_phone(phone: str) -> str:
    """標準化電話格式：統一為 02-1234-5678 格式"""
    if not is_real_phone(phone):
        return ""
    cleaned = phone.strip()
    # 移除所有非數字字元
    digits = re.sub(r"\D", "", cleaned)
    # 手機 0912-345-678（優先檢查）
    if len(digits) == 10 and digits.startswith("09"):
        return f"{digits[:4]}-{digits[4:7]}-{digits[7:]}"
    # 台灣市話格式化
    if len(digits) == 10 and digits.startswith("0"):
        if digits.startswith("02"):
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
    if len(digits) == 9 and digits.startswith("0"):
        if digits.startswith("02"):
            return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
        return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
    # 其他保持原樣
    return cleaned


def has_snack_keywords(text: str) -> bool:
    """檢查文字中是否包含茶水間/零食相關關鍵字"""
    if not text:
        return False
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in SNACK_KEYWORDS)


def _normalize_name(name: str) -> str:
    """標準化公司名稱（用於去重比較）"""
    # 從長到短排序，避免短的先匹配長的子字串
    suffixes = [
        # 中文（長到短，只移除純法律後綴）
        "股份有限公司", "有限公司", "股份公司", "集團",
        # 英文（長到短，不分大小寫）
        "corporation", "limited", "group",
        "corp.", "corp", "inc.", "inc", "ltd.", "ltd",
        "l.l.c.", "llc", "co.", "co",
    ]
    normalized = name.strip()
    lower = normalized.lower()
    for s in suffixes:
        idx = lower.rfind(s)
        if idx >= 0:
            # 英文後綴：前面必須是空格或字串開頭
            if s.isascii():
                if idx == 0 or lower[idx - 1] == " ":
                    normalized = normalized[:idx] + normalized[idx + len(s):]
                    lower = normalized.lower()
            else:
                # 中文後綴：直接替換
                normalized = normalized[:idx] + normalized[idx + len(s):]
                lower = normalized.lower()
    # 移除多餘空格和標點
    normalized = re.sub(r"[,.\-_()（）]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().lower()


def deduplicate(companies: list[dict]) -> list[dict]:
    """
    去除重複公司
    - 同名公司只保留資料最完整的那筆
    - 優先保留有 email > 有電話 > 有 HR 姓名 > 有地址
    - 合併時從其他筆補充 email、website、hr_name
    """
    groups: dict[str, list[dict]] = {}

    for c in companies:
        key = _normalize_name(c.get("cust_name", ""))
        if not key:
            continue
        groups.setdefault(key, []).append(c)

    result = []
    for key, group in groups.items():
        # 排序：有 email > 有電話 > 有具名 HR > 有地址
        def score(c: dict) -> int:
            s = 0
            if c.get("email") and "@" in c.get("email", ""):
                s += 8
            if is_real_phone(c.get("phone", "")):
                s += 4
            if c.get("hr_name") and c["hr_name"] not in ("HR", "人力資源部", "人力資源處"):
                s += 2
            if c.get("address"):
                s += 1
            return s

        best = max(group, key=score)

        # 從其他筆補充 best 沒有的欄位
        for other in group:
            if other is best:
                continue
            if not best.get("email") and other.get("email") and "@" in other.get("email", ""):
                best["email"] = other["email"]
            if not best.get("website") and other.get("website"):
                best["website"] = other["website"]
            if not best.get("hr_name") and other.get("hr_name"):
                best["hr_name"] = other["hr_name"]
            if not best.get("phone") and is_real_phone(other.get("phone", "")):
                best["phone"] = other["phone"]

        result.append(best)

    logger.info(f"去重前 {len(companies)} 筆 → 去重後 {len(result)} 筆")
    return result


def enrich_snack_flag(companies: list[dict]) -> list[dict]:
    """
    增強「是否有零食/茶水間福利」的標記
    104 已有福利碼標記；其他平台透過關鍵字補充
    """
    for c in companies:
        if c.get("has_snack_benefit"):
            continue  # 已由 104 福利碼標記

        # 檢查 welfare_tags
        tags_text = " ".join(c.get("welfare_tags", []))
        if has_snack_keywords(tags_text):
            c["has_snack_benefit"] = True

    return companies


def clean_and_merge(all_companies: list[dict]) -> list[dict]:
    """
    主處理函數：清洗 + 合併 + 去重 + 標記

    Args:
        all_companies: 多平台爬蟲的原始結果合併清單

    Returns:
        清洗後的公司清單
    """
    cleaned = []
    for c in all_companies:
        # 清洗電話
        c["phone"] = clean_phone(c.get("phone", ""))
        # 清洗名稱
        c["cust_name"] = c.get("cust_name", "").strip()
        # 清洗 HR 名稱
        c["hr_name"] = c.get("hr_name", "").strip()
        if c["cust_name"]:
            cleaned.append(c)

    # 去重
    deduped = deduplicate(cleaned)

    # 補充零食標記
    enriched = enrich_snack_flag(deduped)

    # 排序：零食公司優先，然後按有無電話
    enriched.sort(
        key=lambda c: (
            -int(c.get("has_snack_benefit", False)),
            -int(is_real_phone(c.get("phone", ""))),
            -int(bool(c.get("hr_name"))),
        )
    )

    return enriched


# ── 快速測試 ─────────────────────────────────────────
if __name__ == "__main__":
    sample = [
        {"cust_name": "測試科技股份有限公司", "phone": "02-12345678", "hr_name": "林小姐",
         "source": "104", "has_snack_benefit": True, "welfare_tags": ["下午茶/零食飲料"],
         "address": "台北市", "industry": "軟體", "employee_count": "100",
         "website": "", "cust_id": "abc"},
        {"cust_name": "測試科技", "phone": "暫不提供", "hr_name": "HR",
         "source": "cake", "has_snack_benefit": False, "welfare_tags": [],
         "address": "台北市信義區", "industry": "", "employee_count": "",
         "website": "https://cake.me/companies/abc", "cust_id": "cake_abc"},
    ]
    result = clean_and_merge(sample)
    for c in result:
        print(c)
