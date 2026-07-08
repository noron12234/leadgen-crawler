"""
資料安全制度測試（docs/DEVELOPMENT_SOP.md）
- 破壞性操作前自動快照
- pytest 防污染 guard
"""
import sqlite3
from pathlib import Path

import pytest


class TestSnapshotBeforeDestructive:
    def test_clear_all_takes_snapshot_first(self, tmp_db, sample_companies):
        from database.db import upsert_companies, get_all_companies, clear_all

        upsert_companies([sample_companies[0]])
        assert len(get_all_companies()) == 1

        clear_all()
        assert len(get_all_companies()) == 0

        # 快照檔存在，且裡面留著被清掉的資料
        snaps = list((tmp_db.parent / "backups").glob("pre-clear-all-*.db"))
        assert len(snaps) == 1
        snap_conn = sqlite3.connect(str(snaps[0]))
        n = snap_conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
        snap_conn.close()
        assert n == 1  # 誤按清空也能從快照撈回來

    def test_delete_linkedin_all_takes_snapshot(self, tmp_db):
        from database.db import save_linkedin_people, get_linkedin_people, delete_linkedin_people_all

        save_linkedin_people([{"username": "u1", "name": "測試人"}])
        assert len(get_linkedin_people()) == 1

        delete_linkedin_people_all()
        assert len(get_linkedin_people()) == 0
        assert list((tmp_db.parent / "backups").glob("pre-clear-linkedin-*.db"))

    def test_snapshot_db_returns_path(self, tmp_db):
        from database.db import snapshot_db
        p = snapshot_db("unittest")
        assert Path(p).exists()
        assert "pre-unittest-" in p


class TestPytestPollutionGuard:
    def test_refuses_real_db_path_under_pytest(self):
        """pytest 執行中，DB 路徑不在暫存目錄 → get_connection 必須拒連"""
        import database.db as db_mod

        orig_path = db_mod.DB_PATH
        orig_conn = getattr(db_mod._local, "conn", None)
        db_mod._local.conn = None
        db_mod.DB_PATH = Path("/Users/someone/Desktop/production/leads.db")
        try:
            with pytest.raises(RuntimeError, match="拒絕連到真實 DB"):
                db_mod.get_connection()
        finally:
            db_mod.DB_PATH = orig_path
            db_mod._local.conn = orig_conn
