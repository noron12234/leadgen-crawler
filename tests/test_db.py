"""
測試 database/db.py
- CRUD 操作
- Migration 機制
- Email quota
"""
import sys
from pathlib import Path
from datetime import datetime, date
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMigration:
    def test_init_creates_tables(self, tmp_db):
        import database.db as db
        conn = db.get_connection()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t["name"] for t in tables}
        assert "companies" in table_names
        assert "linkedin_people" in table_names
        assert "email_logs" in table_names
        assert "_meta" in table_names

    def test_schema_version(self, tmp_db):
        import database.db as db
        conn = db.get_connection()
        version = db._get_schema_version(conn)
        assert version == db.CURRENT_SCHEMA_VERSION

    def test_description_column_exists(self, tmp_db):
        import database.db as db
        conn = db.get_connection()
        cols = {row[1] for row in conn.execute("PRAGMA table_info(companies)").fetchall()}
        assert "description" in cols
        assert "job_titles" in cols


class TestUpsert:
    def test_insert_new(self, tmp_db, sample_companies):
        import database.db as db
        new, updated = db.upsert_companies(sample_companies)
        assert new >= 1
        all_companies = db.get_all_companies()
        assert len(all_companies) >= 1

    def test_upsert_updates_existing(self, tmp_db, sample_companies):
        import database.db as db
        db.upsert_companies(sample_companies)
        # Insert again
        new2, updated2 = db.upsert_companies(sample_companies)
        assert new2 == 0
        assert updated2 >= 1


class TestStats:
    def test_empty_stats(self, tmp_db):
        import database.db as db
        stats = db.get_stats()
        assert stats["total"] == 0
        assert stats["has_email"] == 0

    def test_stats_after_insert(self, tmp_db, sample_companies):
        import database.db as db
        db.upsert_companies(sample_companies)
        stats = db.get_stats()
        assert stats["total"] >= 1


class TestEmailQuota:
    def test_daily_count_zero(self, tmp_db):
        import database.db as db
        assert db.get_daily_email_count() == 0

    def test_can_send(self, tmp_db):
        import database.db as db
        can, sent, quota = db.can_send_emails(10)
        assert can is True
        assert sent == 0
        assert quota > 0

    def test_log_and_count(self, tmp_db, sample_companies):
        import database.db as db
        db.upsert_companies(sample_companies)
        companies = db.get_all_companies()
        if companies:
            db.log_email_sent(
                company_id=companies[0]["id"],
                recipient_email="test@test.com",
                subject="Test",
            )
            assert db.get_daily_email_count() == 1


class TestMarkContacted:
    def test_mark_and_check(self, tmp_db, sample_companies):
        import database.db as db
        db.upsert_companies(sample_companies)
        companies = db.get_all_companies()
        if companies:
            cid = companies[0]["id"]
            db.mark_contacted(cid, True)
            stats = db.get_stats()
            assert stats["contacted"] >= 1


class TestClearAll:
    def test_clear(self, tmp_db, sample_companies):
        import database.db as db
        db.upsert_companies(sample_companies)
        db.clear_all()
        assert db.get_stats()["total"] == 0
