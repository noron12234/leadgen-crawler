"""
測 mailer.allowlist 守門員 + 3 個 sender 入口確實會擋下不在白名單的信。

跑法：
  cd feature1_lead_scraper
  pytest tests/test_allowlist.py -v
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mailer import allowlist


# ── allowlist 本體 ────────────────────────────────────────────

class TestAllowlistCore:
    def setup_method(self):
        os.environ.pop("EMAIL_ALLOWLIST", None)

    def test_empty_env_allows_everyone(self):
        assert allowlist.is_enabled() is False
        assert allowlist.is_allowed("anyone@anywhere.com") is True
        assert allowlist.is_allowed("") is True  # 空 email 也放行，留給後續 validator

    def test_single_email_allowlist(self):
        os.environ["EMAIL_ALLOWLIST"] = "noron12334@gmail.com"
        assert allowlist.is_enabled() is True
        assert allowlist.is_allowed("noron12334@gmail.com") is True
        assert allowlist.is_allowed("evil@hacker.com") is False

    def test_multiple_emails(self):
        os.environ["EMAIL_ALLOWLIST"] = "a@b.com,c@d.com, e@f.com "
        assert allowlist.is_allowed("a@b.com") is True
        assert allowlist.is_allowed("c@d.com") is True
        assert allowlist.is_allowed("e@f.com") is True
        assert allowlist.is_allowed("x@y.com") is False

    def test_case_insensitive(self):
        os.environ["EMAIL_ALLOWLIST"] = "Noron12334@Gmail.com"
        assert allowlist.is_allowed("noron12334@gmail.com") is True
        assert allowlist.is_allowed("NORON12334@GMAIL.COM") is True

    def test_filter_recipients_returns_blocked(self):
        os.environ["EMAIL_ALLOWLIST"] = "ok@me.com"
        recipients = [
            {"email": "ok@me.com", "cust_name": "Me"},
            {"email": "external@client.com", "cust_name": "Client"},
        ]
        allowed, blocked = allowlist.filter_recipients(recipients)
        assert len(allowed) == 1
        assert allowed[0]["email"] == "ok@me.com"
        assert len(blocked) == 1
        assert blocked[0]["email"] == "external@client.com"
        assert blocked[0]["success"] is False
        assert "BLOCKED" in blocked[0]["message"]

    def test_filter_passthrough_when_disabled(self):
        recipients = [{"email": "a@b.com"}, {"email": "c@d.com"}]
        allowed, blocked = allowlist.filter_recipients(recipients)
        assert len(allowed) == 2
        assert blocked == []


# ── 3 個 sender 真的會擋 ────────────────────────────────────

class TestSendersRespectAllowlist:
    def setup_method(self):
        os.environ["EMAIL_ALLOWLIST"] = "noron12334@gmail.com"
        os.environ["GMAIL_USER"] = "noron12334@gmail.com"
        os.environ["GMAIL_APP_PASSWORD"] = "fake-app-pwd-for-test"

    def teardown_method(self):
        os.environ.pop("EMAIL_ALLOWLIST", None)

    @patch("smtplib.SMTP")
    def test_gmail_smtp_blocks_external(self, mock_smtp):
        from mailer import gmail_sender
        ok, msg = gmail_sender.send_email("external@client.com", "test", "body")
        assert ok is False
        assert "BLOCKED" in msg
        mock_smtp.assert_not_called()  # SMTP 沒被開啟 = 真的擋下了

    @patch("smtplib.SMTP")
    def test_gmail_smtp_allows_whitelisted(self, mock_smtp):
        from mailer import gmail_sender
        mock_conn = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_conn

        ok, msg = gmail_sender.send_email("noron12334@gmail.com", "test", "body")
        assert ok is True
        mock_conn.sendmail.assert_called_once()  # 真的有寄

    @patch("smtplib.SMTP")
    def test_gmail_smtp_batch_filters_recipients(self, mock_smtp):
        from mailer import gmail_sender
        mock_conn = MagicMock()
        mock_smtp.return_value = mock_conn

        results = gmail_sender.send_batch(
            recipients=[
                {"email": "noron12334@gmail.com", "cust_name": "Me", "id": 1},
                {"email": "external@client.com", "cust_name": "Client", "id": 2},
            ],
            subject_template="hi {company}",
            body_template="hello {hr_name}",
            delay_seconds=0,
        )
        # 2 個 recipient → 1 sent + 1 blocked
        sent = [r for r in results if r["success"]]
        blocked = [r for r in results if not r["success"]]
        assert len(sent) == 1
        assert len(blocked) == 1
        assert sent[0]["email"] == "noron12334@gmail.com"
        assert blocked[0]["email"] == "external@client.com"
        assert "BLOCKED" in blocked[0]["message"]

    @patch("mailer.resend_sender._get_client")
    @patch("mailer.resend_sender._get_config", return_value=("fake-key", "noreply@me.com", "Me"))
    def test_resend_blocks_external(self, _cfg, mock_client):
        from mailer import resend_sender
        ok, msg = resend_sender.send_email("external@client.com", "test", "body")
        assert ok is False
        assert "BLOCKED" in msg
        mock_client.assert_not_called()  # Resend client 沒被建 = 真的擋下了

    @patch("mailer.gmail_api_sender._get_gmail_service")
    def test_gmail_api_blocks_external(self, mock_service):
        from mailer import gmail_api_sender
        ok, msg = gmail_api_sender.send_email("external@client.com", "test", "body")
        assert ok is False
        assert "BLOCKED" in msg
        mock_service.assert_not_called()
