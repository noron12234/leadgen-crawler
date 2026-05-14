#!/bin/bash
# LeadFlow Production 備份 — 完整 SOP 看 docs/internal/BACKUP_SOP.md
set -euo pipefail

APP="leadgen-app"
FLYCTL="$HOME/.fly/bin/flyctl"
TS=$(date +%Y%m%d_%H%M)
DEST="$HOME/Desktop/_backups/leadflow_prod_${TS}"
ICLOUD="$HOME/Library/Mobile Documents/com~apple~CloudDocs/_project_backups"

# 前置檢查
[[ -x "$FLYCTL" ]] || { echo "❌ flyctl not found at $FLYCTL — 跑 curl -L https://fly.io/install.sh | sh"; exit 1; }
"$FLYCTL" auth whoami >/dev/null 2>&1 || { echo "❌ flyctl not logged in — 跑 $FLYCTL auth login"; exit 1; }

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
sqlite3 leads.db "SELECT '  companies (業務名單): ' || (SELECT COUNT(*) FROM companies) || ' 筆' ||
                         CHAR(10) || '  email_logs (寄信): ' || (SELECT COUNT(*) FROM email_logs) || ' 筆' ||
                         CHAR(10) || '  email_events (開信點擊): ' || (SELECT COUNT(*) FROM email_events) || ' 筆' ||
                         CHAR(10) || '  activity_log: ' || (SELECT COUNT(*) FROM activity_log) || ' 筆';"

# 5. tar 壓縮 + iCloud
cd "$HOME/Desktop/_backups"
tar -czf "leadflow_prod_${TS}.tar.gz" "leadflow_prod_${TS}/"
mkdir -p "$ICLOUD"
cp "leadflow_prod_${TS}.tar.gz" "$ICLOUD/"

echo ""
echo "✓ 備份完成"
echo "  本機 raw:  $DEST"
echo "  本機 tar:  $HOME/Desktop/_backups/leadflow_prod_${TS}.tar.gz"
echo "  iCloud:    $ICLOUD/leadflow_prod_${TS}.tar.gz"
