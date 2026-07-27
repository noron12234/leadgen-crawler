**English** · [繁體中文](README.zh-TW.md)

# LeadGen — B2B Lead Pipeline
### B2B 名單開發系統

A production lead-generation system: crawls four recruiting platforms weekly, deduplicates across three layers, enriches companies with contact emails, and runs cold email campaigns with open/click tracking — all under daily quota control.

Built and operated for a real B2B distributor. Roughly 10,700 lines of Python, running on Fly.io.

---

## Why this exists

Sales teams buy lead lists that are stale, duplicated, and missing the one field that matters — a working email address. Meanwhile, every company actively hiring is publicly announcing budget, growth, and often their HR contact, on job boards.

This system treats job postings as the lead source: if a company is hiring, it's spending. It crawls, cleans, enriches, and turns that into a mailable list — then tracks what actually got opened.

## Architecture

```
  Crawlers (104 / Cake / LinkedIn / Yourator)   ← independent; one failing never blocks the others
       │  raw postings
       ▼
  Processors (cleaner · email_verifier · website_email_scanner)
       │  normalized, deduplicated, benefit-tagged, email-enriched
       ▼
  Database (SQLite WAL · thread-local connections · versioned migrations)
       │
       ▼
  Streamlit UI (leads · people · campaigns · analytics · admin)
       │
       ▼
  Mailer (SMTP / Gmail API / Resend)  →  Tracking server (open pixel + click rewrite)
```

### Design decisions worth explaining

**Crawler independence.** Each crawler is fully isolated. A selector change on one platform never blocks the other three — failures are logged and the run continues with whatever succeeded.

**Three-layer deduplication.** Crawler-level `seen_ids`, then normalized-name matching in the cleaner, then a `UNIQUE` constraint in the database. Each layer catches what the previous one couldn't.

**Schema migrations in a `_meta` table.** The DB carries its own version number and migrates forward on startup — currently v9. No migration framework, no drift between environments.

**Open-rate correction for machine prefetch.** Gmail's anti-phishing scanner fetches tracking pixels before a human ever sees the email, which inflates open rates badly — 31 of 48 open events in production came from `GoogleImageProxy`. The system filters these at query time using send-to-open latency and user-agent heuristics, without deleting the raw events. Measured open rate went from 64.5% to a truthful 48.4%.

**Send allowlist.** `EMAIL_ALLOWLIST` gates every one of the three sender backends before the SMTP/API call. Unset means normal operation; set means only listed addresses can receive. This exists because a staging environment that can email real prospects is a loaded gun.

**Destructive operations snapshot first.** Any clear/purge operation writes `pre-*.db` to the backup directory before deleting, and the rotation policy never removes `pre-*` files. Added after a test script wrote into a development database through a config-import fallback.

## Features

| Area | What it does |
|---|---|
| **Crawling** | Four platforms, weekly schedule via APScheduler, retry with backoff, benefit-tag extraction |
| **Enrichment** | Email verification, website email scanning, multi-email parsing per company |
| **Campaigns** | Templated email with version management, batch send with progress, dry-run mode, Ragic CRM exclusion |
| **Tracking** | Open pixel + click rewriting, prefetch filtering, per-email detail tables, reply detection over IMAP |
| **Analytics** | Funnel metrics, template A/B comparison, hot-lead ranking by reply > click > open |
| **Ops** | Multi-user auth with lockout, daily DB backup, staging environment, one-command promote with health check |
| **Deliverability** | `List-Unsubscribe` headers, auto unsubscribe footer, promotional-language stripping in default templates |

## Stack

Python 3.11 · Streamlit · Playwright · SQLite (WAL) · APScheduler · Docker · Fly.io

## Running it

```bash
pip install -r requirements.txt
cp users.yaml.example users.yaml     # add your users
streamlit run app.py                 # UI on :8501
python scheduler.py                  # weekly crawl (or `python scheduler.py now`)
python tracking_server.py            # open/click tracking endpoint
```

Environment:

```env
GMAIL_USER=you@example.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
BYCRAWL_API_KEY=                 # optional, LinkedIn crawler only
EMAIL_ALLOWLIST=                 # comma-separated; unset = send to anyone
TRACKING_BASE_URL=https://your-app.fly.dev:8443
STAGING_MODE=                    # 1 disables the scheduler
```

## Tests

```bash
pytest tests/ -v                          # 66 tests
pytest tests/test_data_safety.py -v       # snapshot + guard behaviour
pytest tests/test_allowlist.py -v         # verifies SMTP is never called when blocked
```

Tests include a hard guard that raises if a test ever points at a database path outside a temp directory. That guard exists because the alternative already happened once.

## Notes

Client identifiers, contracts, credentials, and business documents have been removed from this repository and from its history. What remains is the system.

## License

MIT — see [LICENSE](LICENSE).
