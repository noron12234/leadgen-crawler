"""
開發信追蹤測試（需求規格）
"""
import pytest

from mailer.tracking import (
    gen_tracking_uid,
    inject_pixel,
    rewrite_links,
    inject_tracking,
    wrap_text_as_html,
)


# ══════════════════════════════════════════════════════
# tracking.py — 純函式測試
# ══════════════════════════════════════════════════════

class TestGenUid:
    def test_unique(self):
        uids = {gen_tracking_uid() for _ in range(1000)}
        assert len(uids) == 1000

    def test_url_safe(self):
        uid = gen_tracking_uid()
        # url-safe base64 只有 A-Za-z0-9_- 這些字元
        assert all(c.isalnum() or c in "-_" for c in uid)
        assert len(uid) >= 20


class TestRewriteLinks:
    BASE = "https://track.example.com"

    def test_rewrites_http(self):
        html = '<a href="https://example.com/page?x=1">click</a>'
        out = rewrite_links(html, "UID1", self.BASE)
        assert "https://track.example.com/t/click/UID1?u=" in out
        assert "example.com%2Fpage%3Fx%3D1" in out

    def test_preserves_non_http(self):
        html = (
            '<a href="mailto:a@b.com">m</a>'
            '<a href="tel:0912">t</a>'
            '<a href="#anchor">a</a>'
        )
        out = rewrite_links(html, "UID1", self.BASE)
        assert "/t/click/" not in out
        assert "mailto:" in out and "tel:" in out

    def test_multiple_links(self):
        html = (
            '<a href="https://a.com">A</a>'
            '<a href="https://b.com">B</a>'
        )
        out = rewrite_links(html, "UID1", self.BASE)
        assert out.count("/t/click/UID1") == 2

    def test_case_insensitive_href(self):
        html = '<A HREF="https://x.com">x</A>'
        out = rewrite_links(html, "UID1", self.BASE)
        assert "/t/click/UID1" in out


class TestInjectPixel:
    BASE = "https://track.example.com"

    def test_before_body_close(self):
        html = "<html><body>hi</body></html>"
        out = inject_pixel(html, "UID1", self.BASE)
        assert "/t/open/UID1.gif" in out
        assert out.index(".gif") < out.lower().index("</body>")

    def test_no_body_tag_appends(self):
        out = inject_pixel("<p>hi</p>", "UID1", self.BASE)
        assert out.endswith('/>')
        assert "/t/open/UID1.gif" in out


class TestInjectTracking:
    BASE = "https://track.example.com"

    def test_plain_text_upgraded_to_html(self):
        body, is_html = inject_tracking(
            "您好\n歡迎點 https://example.com",
            "UID1", self.BASE, is_html=False,
        )
        assert is_html is True
        assert "/t/open/UID1.gif" in body
        assert "<br>" in body
        # 裸網址應被 linkify 並導向追蹤 endpoint
        assert "/t/click/UID1" in body

    def test_html_body_gets_pixel_and_rewritten_links(self):
        html = (
            '<html><body>Hi <a href="https://foo.com">link</a></body></html>'
        )
        out, is_html = inject_tracking(html, "UID1", self.BASE, is_html=True)
        assert is_html is True
        assert "/t/click/UID1" in out
        assert "/t/open/UID1.gif" in out

    def test_empty_base_url_skips(self):
        html = '<a href="https://foo.com">x</a>'
        out, is_html = inject_tracking(html, "UID1", "", is_html=True)
        assert out == html
        assert is_html is True

    def test_wrap_text_escapes_html(self):
        out = wrap_text_as_html("<script>x</script>")
        assert "&lt;script&gt;" in out
        assert "<script>x" not in out


# ══════════════════════════════════════════════════════
# db.py — 追蹤相關函式
# ══════════════════════════════════════════════════════

class TestTrackingDb:
    def _seed_email(self, sample_companies):
        """插入公司 + 寄信 log，回傳 (company_id, uid)"""
        from database.db import upsert_companies, get_all_companies, log_email_sent
        upsert_companies([sample_companies[0]])
        cid = get_all_companies()[0]["id"]
        uid = "TESTUID123"
        log_email_sent(
            company_id=cid,
            recipient_email="hr@test-tech.com",
            subject="【測試主旨】模板A",
            status="sent",
            template_used="【測試主旨】模板A",
            tracking_uid=uid,
        )
        return cid, uid

    def test_open_event_increments_stats(self, tmp_db, sample_companies):
        from database.db import record_email_event, get_tracking_stats
        _, uid = self._seed_email(sample_companies)

        stats = get_tracking_stats()
        assert stats["sent"] == 1
        assert stats["opened"] == 0

        record_email_event(uid, "open", user_agent="Mozilla/5.0")
        record_email_event(uid, "open", user_agent="Mozilla/5.0")  # 同 uid 重複 open 仍只算一人

        stats = get_tracking_stats()
        assert stats["opened"] == 1
        assert stats["open_rate"] == 100.0
        assert stats["hot_leads"] == 0  # 還沒點擊

    def test_open_by_enterprise_scanner_is_ignored(self, tmp_db, sample_companies):
        """企業反釣魚掃描器（Proofpoint）的 open 不應被記為真實開信"""
        from database.db import record_email_event, get_tracking_stats
        _, uid = self._seed_email(sample_companies)

        record_email_event(uid, "open",
                           user_agent="Mozilla/5.0 (compatible; Proofpoint-LinkScanner/1.0)")
        assert get_tracking_stats()["opened"] == 0  # 被過濾

        record_email_event(uid, "open",
                           user_agent="Mozilla/5.0 (via GoogleImageProxy)")
        assert get_tracking_stats()["opened"] == 1  # Gmail proxy 現在算開信（業界慣例）

    def test_click_event_marks_hot_lead(self, tmp_db, sample_companies):
        from database.db import record_email_event, get_tracking_stats, get_hot_leads
        cid, uid = self._seed_email(sample_companies)

        record_email_event(uid, "click", target_url="https://foo.com/promo")

        stats = get_tracking_stats()
        assert stats["clicked"] == 1
        assert stats["click_rate"] == 100.0
        assert stats["hot_leads"] == 1

        hot = get_hot_leads()
        assert len(hot) == 1
        assert hot[0]["id"] == cid
        assert hot[0]["click_count"] == 1

    def test_dedupe_same_ip_within_window(self, tmp_db, sample_companies):
        """同 uid+type+ip 在 30 秒內視為同一次事件，避免洗 event"""
        from database.db import record_email_event, get_tracking_stats
        _, uid = self._seed_email(sample_companies)

        record_email_event(uid, "open", user_agent="Real/1.0", ip_hash="abc123")
        # 同 IP + 同 UID + 同 type 連續 → dedupe 只寫 1 筆
        record_email_event(uid, "open", user_agent="Real/1.0", ip_hash="abc123")
        record_email_event(uid, "open", user_agent="Real/1.0", ip_hash="abc123")
        assert get_tracking_stats()["opened"] == 1

        # 不同 IP 的開信另算
        record_email_event(uid, "open", user_agent="Real/1.0", ip_hash="def456")
        assert get_tracking_stats()["opened"] == 1  # distinct uid 計數仍 1（同封信）

    def test_invalid_event_type_is_ignored(self, tmp_db, sample_companies):
        from database.db import record_email_event, get_tracking_stats
        _, uid = self._seed_email(sample_companies)
        record_email_event(uid, "bogus")  # should no-op
        stats = get_tracking_stats()
        assert stats["opened"] == 0
        assert stats["clicked"] == 0

    def test_template_stats_groups_correctly(self, tmp_db, sample_companies):
        from database.db import upsert_companies, get_all_companies, log_email_sent, record_email_event, get_template_stats

        upsert_companies(sample_companies)
        ids = [c["id"] for c in get_all_companies()]
        # sample_companies[0] 與 [1] 是同公司（dedup 合併），只剩兩間
        assert len(ids) == 2
        cid_a, cid_b = ids[0], ids[1]

        # 模板A 寄 2 封（1 開信 + 1 點擊 + 1 只開信）
        # 模板B 寄 1 封（0 事件）
        log_email_sent(cid_a, "a@x.com", "s", template_used="模板A", tracking_uid="U1")
        log_email_sent(cid_b, "b@x.com", "s", template_used="模板A", tracking_uid="U2")
        log_email_sent(cid_a, "a2@x.com", "s", template_used="模板B", tracking_uid="U3")

        record_email_event("U1", "open")
        record_email_event("U1", "click", target_url="https://foo")
        record_email_event("U2", "open")

        rows = {r["template"]: r for r in get_template_stats()}
        assert rows["模板A"]["sent"] == 2
        assert rows["模板A"]["opened"] == 2
        assert rows["模板A"]["clicked"] == 1
        assert rows["模板A"]["open_rate"] == 100.0
        assert rows["模板A"]["click_rate"] == 50.0

        assert rows["模板B"]["sent"] == 1
        assert rows["模板B"]["opened"] == 0
