"""
Pytest fixtures — 共用的測試基礎設施
"""
import sys
import os
import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch

# 確保 feature1 modules 可被 import
FEATURE1_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(FEATURE1_DIR))


@pytest.fixture
def tmp_db(tmp_path):
    """建立臨時資料庫，測試完自動清除"""
    db_path = tmp_path / "test_leads.db"
    with patch("database.db.DB_PATH", db_path):
        # 清除 thread-local 連線
        import database.db as db_mod
        if hasattr(db_mod._local, "conn"):
            try:
                db_mod._local.conn.close()
            except Exception:
                pass
            db_mod._local.conn = None
        db_mod.DB_PATH = db_path
        db_mod.init_db()
        yield db_path
        # cleanup
        if hasattr(db_mod._local, "conn"):
            try:
                db_mod._local.conn.close()
            except Exception:
                pass
            db_mod._local.conn = None


@pytest.fixture
def sample_companies():
    """測試用公司資料"""
    return [
        {
            "cust_name": "測試科技股份有限公司",
            "phone": "02-12345678",
            "hr_name": "林小姐",
            "email": "hr@test-tech.com",
            "source": "104",
            "has_snack_benefit": True,
            "welfare_tags": ["下午茶/零食飲料"],
            "address": "台北市信義區",
            "industry": "軟體業",
            "employee_count": "100-500",
            "website": "https://test-tech.com",
            "cust_id": "abc123",
            "job_url": "",
            "company_url": "",
        },
        {
            "cust_name": "測試科技",
            "phone": "暫不提供",
            "hr_name": "HR",
            "email": "",
            "source": "cake",
            "has_snack_benefit": False,
            "welfare_tags": [],
            "address": "台北市信義區松仁路 100 號",
            "industry": "",
            "employee_count": "",
            "website": "https://cake.me/companies/test-tech",
            "cust_id": "cake_test-tech",
            "job_url": "",
            "company_url": "",
        },
        {
            "cust_name": "另一家公司 Inc.",
            "phone": "0912345678",
            "hr_name": "王先生",
            "email": "wang@another.com",
            "source": "yourator",
            "has_snack_benefit": False,
            "welfare_tags": [],
            "address": "台北市大安區",
            "industry": "電商",
            "employee_count": "50-100",
            "website": "",
            "cust_id": "yourator_another",
            "job_url": "",
            "company_url": "",
        },
    ]


@pytest.fixture
def mock_requests():
    """Mock requests.get for crawler tests"""
    with patch("requests.request") as mock_req:
        yield mock_req
