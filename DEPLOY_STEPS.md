# LeadFlow 部署到 Fly.io — 實作步驟

> 目標：一次上線 Streamlit + 追蹤 server，拿到 HTTPS 網址交給the client使用
> 預估時間：30-60 分鐘（第一次）
> 月費：約 US$3-5（最小機型 shared CPU / 512 MB / 1GB volume）

---

## Step 0 · 準備（5 分鐘）

1. 註冊 Fly.io → <https://fly.io/app/sign-up>
2. **信用卡綁定**（Fly 要求，但小流量在免費額度內）
3. 裝 `flyctl`：
   ```powershell
   # PowerShell（以管理員執行）
   iwr https://fly.io/install.ps1 -useb | iex
   ```
   或 [官方指南](https://fly.io/docs/flyctl/install/)
4. 開新 terminal 測試：`fly version`

---

## Step 1 · 登入 Fly（1 分鐘）

```bash
cd C:\Users\user\Desktop\personal-website\fisrst-enterpuer\feature1_lead_scraper
fly auth login
```
瀏覽器會打開授權，按 Authorize 回來 terminal。

---

## Step 2 · 建立 app（3 分鐘）

```bash
fly launch --no-deploy --copy-config
```

回答：
- **Choose an app name**：建議 `leadgen-app`（會變 `leadgen-app.fly.dev`）
- **region**：`nrt`（Tokyo，對台灣最快）
- **Setup Postgres?**：`N`（我們用 SQLite）
- **Setup Redis?**：`N`
- **Deploy now?**：`N`（先不 deploy，要先設 secret）

---

## Step 3 · 建立 persistent volume（1 分鐘）

SQLite DB 要存在 volume 裡，機器重啟不遺失。

```bash
fly volumes create leadflow_data --region nrt --size 1
```
（1GB 足夠用 2 年，$0.15/月）

---

## Step 4 · 設環境變數（secret）（3 分鐘）

```bash
# 追蹤網址：改成剛剛 launch 時取的 app 名
fly secrets set TRACKING_BASE_URL="https://leadgen-app.fly.dev:8443"

# 登入開關（生產環境一定要開）
fly secrets set AUTH_ENABLED="true"

# Streamlit 優化
fly secrets set DAILY_EMAIL_QUOTA="50"

# 如果要用 LinkedIn 爬蟲才需要（選用）
# fly secrets set BYCRAWL_API_KEY="sk_byc_..."
```

---

## Step 5 · Deploy（5-10 分鐘首次 build）

```bash
fly deploy
```

等終端顯示 `deployed successfully`，然後：

```bash
fly status
fly logs
```

---

## Step 6 · 驗證部署（5 分鐘）

1. **Streamlit 主介面**：<https://leadgen-app.fly.dev>
   - 應該出現登入畫面
   - 用 `baralla` / `baralla_dev_2026_noron` 登入

2. **追蹤服務**：<https://leadgen-app.fly.dev:8443/health>
   - 應該回傳 `{"ok":true}`

3. **Pixel 測試**：打開一個瀏覽器分頁 →
   <https://leadgen-app.fly.dev:8443/t/open/TESTDEMO.gif>
   - 應該回傳一個 1x1 透明 gif
   - 然後登入 `baralla` → 管理後台 → 活動紀錄 → 應該看到 TESTDEMO 的 open 事件（進 SQLite）

4. **完整流程測試**：
   - 切換「Gmail 設定」→ 填你的 Gmail + App Password → 測試連線
   - 打開 Dry-run → 走一遍篩選 → 按「確認寄出」→ 確認沒報錯
   - 關閉 Dry-run → 寄測試信給自己 → Gmail 收信 → **等 10-20 秒** →
     回「追蹤分析」tab → **開信數 +1** ✅

---

## Step 7 · 交付給the client

提供給客戶：
- 網址：<https://leadgen-app.fly.dev>
- 帳號（各業務員一組）：`admin` / `sales1` / `sales2`（密碼從管理後台重設）
- 教學：系統內「❓ Gmail 設定教學」tab

---

## 日後改 code → 更新線上

只要在本機改完程式碼：

```bash
cd feature1_lead_scraper
fly deploy
```

約 2-5 分鐘會無縫更新，客戶重整頁面就用到新版。

---

## 疑難排解

| 狀況 | 解法 |
|---|---|
| `fly launch` 卡住 | `Ctrl+C` 重試，注意 app name 要全小寫、只能英數橫線 |
| Build 失敗：`No space left` | `fly machine status` 看機器，升級為 performance-1x |
| 容器啟動後 crash | `fly logs` 看 stack trace，80% 是 `.env` 變數沒設 |
| 追蹤 pixel 打不通 | 確認 `fly.toml` 有第二個 services 區塊（port 8443） |
| SQLite lock | volume 只能給單台機器；`fly.toml` 別設 `min_machines_running > 1` |

---

## 成本粗估（小團隊用量）

| 項目 | 月費 |
|---|---|
| shared-cpu-1x × 512MB（auto-stop） | 免費額度內 |
| 1GB volume | $0.15 |
| HTTPS / CDN | 免費 |
| 出站流量 前 160GB | 免費 |
| **合計** | **約 $0-3 USD/月** |

---

**次元創意有限公司 · CTO 林均融（芭樂）**
使用問題請聯絡 Email：your@email.com
