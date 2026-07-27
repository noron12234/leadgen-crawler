[English](README.md) · **繁體中文**

# LeadGen — B2B 名單開發系統

一套上線運作的名單開發系統：每週爬四個招募平台、三層去重、補齊聯絡 email、寄送開發信並追蹤開信與點擊 —— 全部在每日配額控管之下。

為一間真實的 B2B 經銷商打造並實際營運。約 10,700 行 Python，跑在 Fly.io 上。

---

## 為什麼會有這個東西

業務團隊買來的名單通常是舊的、重複的，而且缺最關鍵的那一欄 —— 一個能寄得到的 email。但同時，每一間正在徵人的公司，都在公開宣告自己有預算、在成長，而且常常連 HR 聯絡方式都寫出來了。

這套系統把職缺當成名單來源：**會徵人，就代表在花錢。** 爬下來、清乾淨、補齊資料、變成可以寄信的名單，然後追蹤到底誰真的打開了。

## 架構

```
  爬蟲（104 / Cake / LinkedIn / Yourator）  ← 各自獨立，一個掛掉不影響其他三個
       │  原始職缺資料
       ▼
  處理器（cleaner · email_verifier · website_email_scanner）
       │  正規化、去重、福利標記、email 補齊
       ▼
  資料庫（SQLite WAL · thread-local 連線 · 版本化 migration）
       │
       ▼
  Streamlit 介面（名單 · 聯絡人 · 開發信 · 成效 · 管理後台）
       │
       ▼
  寄信模組（SMTP / Gmail API / Resend） → 追蹤服務（開信 pixel + 連結改寫）
```

### 幾個值得說明的設計決策

**爬蟲獨立性。** 每個爬蟲完全隔離。某個平台改了 selector 不會拖垮其他三個 —— 失敗會被記錄，這一輪繼續用成功的部分跑完。

**三層去重。** 爬蟲層的 `seen_ids`、cleaner 的正規化公司名比對、資料庫的 `UNIQUE` 約束。每一層攔下前一層漏掉的。

**Schema migration 放在 `_meta` 表。** 資料庫自己帶版本號，啟動時往前遷移，目前 v9。不用 migration 框架，環境之間也不會漂移。

**修正機器預掃造成的開信率虛高。** Gmail 的反釣魚掃描器會在真人看到信之前就抓取追蹤 pixel，把開信率灌得很難看 —— production 上 48 個開信事件裡有 31 個來自 `GoogleImageProxy`。系統在查詢時用「寄出到開信的間隔」加上 user-agent 特徵過濾掉這些，但**不刪除原始事件**。實測開信率從 64.5% 修正到誠實的 48.4%。

**寄信白名單。** `EMAIL_ALLOWLIST` 在三個寄信後端的 SMTP／API 呼叫**之前**就攔截。沒設 = 正常運作；設了 = 只有名單上的地址收得到。這個存在的理由是：一個能寄信給真實潛在客戶的測試環境，是一把上了膛的槍。

**破壞性操作先快照。** 任何清空類操作在刪除前會先把 `pre-*.db` 寫進備份目錄，而且輪替政策永遠不刪 `pre-*` 檔。這是在一支測試腳本透過 config-import fallback 誤寫進開發資料庫之後補上的。

## 功能

| 面向 | 內容 |
|---|---|
| **爬取** | 四個平台、APScheduler 每週排程、退避重試、福利標籤抽取 |
| **資料補齊** | Email 驗證、官網 email 掃描、單一公司多 email 解析 |
| **開發信** | 模板版本管理、批量寄送含進度條、Dry-run 模式、排除 Ragic CRM 既有客戶 |
| **追蹤** | 開信 pixel + 連結改寫、預掃過濾、每封信詳細表格、IMAP 回信偵測 |
| **成效分析** | 漏斗指標、模板 A/B 比較、熱門客戶排序（回信 > 點擊 > 開信） |
| **維運** | 多用戶認證含失敗鎖定、每日資料庫備份、staging 環境、一鍵 promote 含健康檢查 |
| **送達率** | `List-Unsubscribe` 標頭、自動退訂 footer、預設模板洗掉促銷用語 |

## 技術棧

Python 3.11 · Streamlit · Playwright · SQLite (WAL) · APScheduler · Docker · Fly.io

## 執行

```bash
pip install -r requirements.txt
cp users.yaml.example users.yaml     # 加入你的使用者
streamlit run app.py                 # 介面在 :8501
python scheduler.py                  # 每週爬取（或 `python scheduler.py now` 立即跑一次）
python tracking_server.py            # 開信／點擊追蹤端點
```

環境變數：

```env
GMAIL_USER=you@example.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
BYCRAWL_API_KEY=                 # 選用，只有 LinkedIn 爬蟲需要
EMAIL_ALLOWLIST=                 # 逗號分隔；不設 = 對所有人寄送
TRACKING_BASE_URL=https://your-app.fly.dev:8443
STAGING_MODE=                    # 設 1 會關掉排程器
```

## 測試

```bash
pytest tests/ -v                          # 66 個測試
pytest tests/test_data_safety.py -v       # 快照與 guard 行為
pytest tests/test_allowlist.py -v         # 驗證被擋時 SMTP 真的沒被呼叫
```

測試裡有一道硬性 guard：只要測試指向的資料庫路徑不在暫存目錄，直接 raise。這道 guard 之所以存在，是因為它要防的事已經發生過一次了。

## 說明

客戶識別資訊、合約、憑證、商業文件已從本 repository **及其 git 歷史**中完全移除。留下的是系統本身。

## 授權

MIT —— 見 [LICENSE](LICENSE)。
