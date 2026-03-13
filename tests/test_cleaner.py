"""
測試 processors/cleaner.py
- 去重邏輯
- 電話驗證與標準化
- 關鍵字標記
- 公司名稱標準化
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from processors.cleaner import (
    is_real_phone,
    clean_phone,
    has_snack_keywords,
    _normalize_name,
    deduplicate,
    enrich_snack_flag,
    clean_and_merge,
)


class TestIsRealPhone:
    def test_valid_phone(self):
        assert is_real_phone("02-12345678") is True
        assert is_real_phone("0912345678") is True
        assert is_real_phone("02-1234-5678") is True

    def test_fake_phone(self):
        assert is_real_phone("暫不提供") is False
        assert is_real_phone("不提供") is False
        assert is_real_phone("N/A") is False
        assert is_real_phone("") is False
        assert is_real_phone("無") is False

    def test_too_short(self):
        assert is_real_phone("123") is False


class TestCleanPhone:
    def test_standardize_landline(self):
        result = clean_phone("0212345678")
        assert result == "02-1234-5678"

    def test_standardize_mobile(self):
        result = clean_phone("0912345678")
        assert result == "0912-345-678"

    def test_fake_returns_empty(self):
        assert clean_phone("暫不提供") == ""
        assert clean_phone("") == ""


class TestNormalizeName:
    def test_chinese_suffix(self):
        assert _normalize_name("測試科技股份有限公司") == _normalize_name("測試科技")

    def test_english_suffix_case_insensitive(self):
        assert _normalize_name("Another Inc.") == _normalize_name("Another")
        assert _normalize_name("Test Corp") == _normalize_name("test")
        assert _normalize_name("ABC Ltd.") == _normalize_name("ABC")

    def test_empty(self):
        assert _normalize_name("") == ""

    def test_punctuation_removal(self):
        n1 = _normalize_name("A-B-C Tech")
        n2 = _normalize_name("A B C Tech")
        assert n1 == n2


class TestHasSnackKeywords:
    def test_match(self):
        assert has_snack_keywords("提供下午茶") is True
        assert has_snack_keywords("辦公室零食") is True
        assert has_snack_keywords("free coffee") is True

    def test_no_match(self):
        assert has_snack_keywords("彈性上班") is False
        assert has_snack_keywords("") is False
        assert has_snack_keywords(None) is False


class TestDeduplicate:
    def test_same_company_merged(self, sample_companies):
        result = deduplicate(sample_companies)
        names = [c["cust_name"] for c in result]
        # "測試科技股份有限公司" 和 "測試科技" 應該合併
        assert len(result) == 2

    def test_best_record_chosen(self, sample_companies):
        result = deduplicate(sample_companies)
        merged = [c for c in result if "測試" in c.get("cust_name", "")][0]
        assert merged["email"] == "hr@test-tech.com"
        assert merged["phone"] == "02-12345678"

    def test_empty_input(self):
        assert deduplicate([]) == []


class TestCleanAndMerge:
    def test_full_pipeline(self, sample_companies):
        result = clean_and_merge(sample_companies)
        assert len(result) >= 1
        # 零食公司排在前面
        if len(result) >= 2:
            assert result[0].get("has_snack_benefit") is True or result[0].get("phone")
