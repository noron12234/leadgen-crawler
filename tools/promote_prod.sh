#!/bin/bash
# LeadFlow staging → prod 一鍵 promote
# 把「人肉記得備份」變成「不備份就部不出去」。
#
# 流程（任一步失敗即中止，不會部署）：
#   1. git 檢查 — feature1 有未 commit 改動就擋（fly deploy 吃整個工作目錄）
#   2. 跑測試 — 全綠才放行（SKIP_TESTS=1 可跳過，僅限緊急 hotfix）
#   3. 備份 prod DB — 跑既有 tools/backup_prod.sh（本機 + iCloud）
#   4. 部署 prod
#   5. 部署後健康檢查 — Streamlit health + 追蹤 server health
#
# 用法：cd feature1_lead_scraper && ./tools/promote_prod.sh
set -euo pipefail

cd "$(dirname "$0")/.."   # 定位到 feature1_lead_scraper/
APP="leadgen-app"
FLYCTL="${FLYCTL:-$HOME/.fly/bin/flyctl}"

echo "══════════════════════════════════════════"
echo " LeadFlow promote → prod ($APP)"
echo "══════════════════════════════════════════"

# ── 1. git 乾淨度：只允許 feature1 目錄全部已 commit ──
DIRTY=$(git status --porcelain -- . | grep -v "^??" || true)
if [[ -n "$DIRTY" ]]; then
  echo "❌ feature1_lead_scraper 有未 commit 的改動，fly deploy 會把它們一起推上 prod："
  echo "$DIRTY"
  echo "→ 先 commit 或 stash，再跑一次。"
  exit 1
fi
echo "✅ 1/5 git 乾淨（未 commit 的改動不會被夾帶上線）"

# ── 2. 測試 ──
if [[ "${SKIP_TESTS:-0}" == "1" ]]; then
  echo "⚠️  2/5 SKIP_TESTS=1 — 跳過測試（僅限緊急 hotfix，事後補跑）"
else
  PY="${PYTEST_PYTHON:-python3}"
  if ! "$PY" -m pytest tests/ -q --ignore=tests/research; then
    echo "❌ 測試未全綠，不部署。修完再來。"
    exit 1
  fi
  echo "✅ 2/5 測試全綠"
fi

# ── 3. 備份 prod DB（既有腳本：拉 /data → 本機 + iCloud）──
./tools/backup_prod.sh
echo "✅ 3/5 prod DB 已備份"

# ── 4. 部署 ──
"$FLYCTL" deploy --config fly.toml --app "$APP" --yes
echo "✅ 4/5 部署完成"

# ── 5. 部署後健康檢查 ──
sleep 5
ST=$(curl -s -o /dev/null -w "%{http_code}" "https://${APP}.fly.dev/_stcore/health" || echo "000")
TR=$(curl -s -o /dev/null -w "%{http_code}" "https://${APP}.fly.dev:8443/health" || echo "000")
echo "Streamlit health: $ST · Tracking health: $TR"
if [[ "$ST" != "200" ]]; then
  echo "❌ Streamlit 健康檢查失敗！立刻檢查： $FLYCTL logs --app $APP"
  echo "   需要回滾： $FLYCTL releases --app $APP → $FLYCTL deploy --image <上一版 image>"
  exit 1
fi
if [[ "$TR" != "200" ]]; then
  echo "⚠️  追蹤 server 健康檢查失敗（開信/點擊追蹤會停擺）— 檢查 logs"
fi
echo "✅ 5/5 健康檢查通過"
echo ""
echo "🎉 promote 完成。最後一步（人工）：開 https://${APP}.fly.dev 登入抽查主要頁面。"
