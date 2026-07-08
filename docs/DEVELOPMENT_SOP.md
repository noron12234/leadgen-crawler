# LeadFlow 正式開發 SOP — 動 code 前必讀

> 目的：**任何人（或 AI agent）改這個系統，客戶資料都不會不見、不會被污染。**
> 建立：2026-07-08（起因：測試腳本因 DB 路徑 fallback 誤寫進開發 DB）
> 姊妹文件：repo 根目錄 `AGENT_BACKUP_GUIDE.md`（備份系統全貌）、`BACKUP_RECOVERY.md`（災難還原）

---

## 1. 資料在哪、有幾層保護

```
prod DB = Fly.io volume /data/leads.db（app: leadgen-app）

保護層（由快到慢）：
① 破壞性操作自動快照     app 內清空類操作 → /data/backups/pre-*.db（永久保留，輪替不刪）
② 機器上每日備份         scheduler backup_job → /data/backups/leads-*.db（保留最近 N 份）
③ GitHub Actions 每日備份 daily-backup-leadflow.yml 10:00 → repo backups/ + Backblaze B2（60 天，git 歷史永久）
④ Fly volume 快照        平台自動每日，保留 30 天（flyctl volumes snapshots list）
⑤ promote 前手動備份     tools/backup_prod.sh → 本機 ~/Desktop/_backups + iCloud
```

還原指令：`BACKUP_RECOVERY.md`＋memory `ref_leadflow_prod_backup.md`。
**每月第一個週五要演習一次還原**（備份沒驗過 = 沒備份）。

## 2. 正式編程流程（改任何 code 都走這條）

```
改 code（本機）
  → pytest tests/ --ignore=tests/research 全綠
  → flyctl deploy --config fly.staging.toml     ← 部 staging
  → 人工在 staging 登入驗收（staging 有獨立 DB，怎麼玩都不傷 prod）
  → Lin 明確授權
  → ./tools/promote_prod.sh                      ← 一鍵：擋 WIP → 測試 → 備份 → 部署 → 健康檢查
  → 開 prod 抽查主要頁面
```

鐵則：
- **絕不手動 `flyctl deploy --config fly.toml`** — 一律走 `promote_prod.sh`，它會先備份、先擋未 commit 的檔案
- **staging 先行**，沒有例外；緊急 hotfix 也要 `SKIP_TESTS=1 ./tools/promote_prod.sh`（備份步驟不可跳）
- schema 改動走 `database/db.py` 的 `_run_migrations()`（只加不減：ALTER TABLE ADD COLUMN，不 DROP）
- **DB 永不 DROP TABLE / DROP COLUMN**；資料「清空」類功能一律先 `snapshot_db()`（已內建）

## 3. 防污染守則（本次事故的教訓）

1. **任何腳本 / 測試碰 DB 前，先確認實際路徑**。
   `database/db.py` 在 `config` 匯入失敗時會 fallback 到 `feature1_lead_scraper/data/leads.db` 並印警告 —
   看到那行警告就停下來。
2. **pytest 有硬 guard**：測試中若 DB 路徑不在暫存目錄，`get_connection()` 直接 raise。
   寫測試一律用 `tests/conftest.py` 的 `tmp_db` fixture。
3. **臨時腳本要驗證資料流**：用 `DATA_DIR=<暫存目錄>` 環境變數，跑完 `assert` DB 路徑。
4. **prod 資料只讀不寫**：查資料用 `flyctl ssh console` 跑唯讀 SELECT；
   要改 prod 資料 = 走 app 功能或明確授權的 migration，事前必有備份。
5. **staging DB 也當真資料對待**（它是 prod 的演練場，髒了會讓驗收失真）。

## 4. 破壞性操作清單（都已掛自動快照）

| 操作 | 位置 | 快照 tag |
|---|---|---|
| 整庫清空（重置系統） | 超管後台危險區 → `clear_all()` | `pre-clear-all-*` |
| 清空寄信紀錄 | 超管後台危險區 | `pre-clear-emails-*` |
| 清空活動紀錄 | 超管後台危險區 | `pre-clear-activity-*` |
| 清空 LinkedIn 人物 | `delete_linkedin_people_all()` | `pre-clear-linkedin-*` |

新增任何 DELETE / 清空類功能時：**先呼叫 `snapshot_db("你的tag")` 再刪**，並把該操作加進上表。
快照拍不成功會 raise — 拍不到照就不准刪資料，這是刻意設計。

## 5. 誤刪之後怎麼救（速查）

```bash
# 看機器上有哪些快照 / 備份
flyctl ssh console -a leadgen-app -C "ls -lt /data/backups" | head

# 還原某份快照（先停寫入，再覆蓋）
flyctl ssh console -a leadgen-app
  cp /data/backups/pre-clear-all-XXXX.db /data/leads.db
  exit
flyctl machine restart <machine-id> -a leadgen-app

# 機器整個炸了 → 從 GitHub / B2 拉（見 BACKUP_RECOVERY.md）
```
