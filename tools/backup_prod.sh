#!/bin/bash
# LeadFlow Production 備份 — 完整 SOP 看 docs/internal/BACKUP_SOP.md
# 設計成 launchd 每天自動跑、結果寫 log + macOS notification
set -euo pipefail

APP="leadgen-app"
FLYCTL="$HOME/.fly/bin/flyctl"
TS=$(date +%Y%m%d_%H%M)
DEST="$HOME/Desktop/_backups/leadflow_prod_${TS}"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs/_project_backups"
LOG_DIR="$HOME/Desktop/_backups/_logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/backup_${TS}.log"

# 所有輸出同時寫螢幕 + log file
exec > >(tee -a "$LOG") 2>&1

# macOS notification 函數
notify() {
  local title="$1"
  local message="$2"
  local sound="${3:-default}"
  osascript -e "display notification \"$message\" with title \"$title\" sound name \"$sound\"" 2>/dev/null || true
}

# 任何步驟失敗就跳 notify
on_fail() {
  local exit_code=$?
  notify "❌ LeadFlow 備份失敗" "看 $LOG 找原因" "Basso"
  echo ""
  echo "❌ 備份失敗（exit code $exit_code）"
  exit $exit_code
}
trap on_fail ERR

# 前置檢查
[[ -x "$FLYCTL" ]] || { echo "❌ flyctl not found at $FLYCTL"; exit 1; }
"$FLYCTL" auth whoami >/dev/null 2>&1 || { echo "❌ flyctl not logged in"; exit 1; }

mkdir -p "$DEST" && cd "$DEST"
echo "→ 抓 prod DB 到 $DEST"

# 1. 主 DB + WAL + shm + users
for f in /data/leads.db /data/leads.db-wal /data/leads.db-shm /data/users.yaml; do
  "$FLYCTL" ssh sftp get "$f" --app "$APP" 2>&1 | grep -v "Metrics token" || true
done

# 2. 順手抓 server 端今晨 4AM snapshot
TODAY=$(date +%Y-%m-%d)
"$FLYCTL" ssh sftp get "/data/backups/leads-${TODAY}_0400.db" --app "$APP" 2>&1 | grep -v "Metrics token" || \
  echo "  (沒有今天的 4AM snapshot，可能 scheduler 沒跑)"

# 3. Checkpoint WAL
sqlite3 leads.db "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null

# 4. 驗證
echo ""
echo "→ 資料驗證："
COMPANIES=$(sqlite3 leads.db "SELECT COUNT(*) FROM companies")
LOGS=$(sqlite3 leads.db "SELECT COUNT(*) FROM email_logs")
EVENTS=$(sqlite3 leads.db "SELECT COUNT(*) FROM email_events")
ACTIVITY=$(sqlite3 leads.db "SELECT COUNT(*) FROM activity_log")
echo "  companies (業務名單): $COMPANIES 筆"
echo "  email_logs (寄信): $LOGS 筆"
echo "  email_events (開信點擊): $EVENTS 筆"
echo "  activity_log: $ACTIVITY 筆"

# 5. tar 壓縮 + iCloud
cd "$HOME/Desktop/_backups"
tar -czf "leadflow_prod_${TS}.tar.gz" "leadflow_prod_${TS}/"
mkdir -p "$ICLOUD"
cp "leadflow_prod_${TS}.tar.gz" "$ICLOUD/"

# 6. 清理 — 本機只留 60 天、iCloud 只留 90 天（節省空間）
find "$HOME/Desktop/_backups" -maxdepth 1 -name "leadflow_prod_*.tar.gz" -mtime +60 -delete 2>/dev/null || true
find "$HOME/Desktop/_backups" -maxdepth 1 -name "leadflow_prod_*" -type d -mtime +14 -exec rm -rf {} + 2>/dev/null || true
find "$ICLOUD" -name "leadflow_prod_*.tar.gz" -mtime +90 -delete 2>/dev/null || true
find "$LOG_DIR" -name "backup_*.log" -mtime +30 -delete 2>/dev/null || true

echo ""
echo "✓ 備份完成"
echo "  本機 raw:  $DEST"
echo "  本機 tar:  $HOME/Desktop/_backups/leadflow_prod_${TS}.tar.gz"
echo "  iCloud:    $ICLOUD/leadflow_prod_${TS}.tar.gz"

notify "✅ LeadFlow 備份完成" "公司 $COMPANIES · 信 $LOGS · 開信點擊 $EVENTS"
