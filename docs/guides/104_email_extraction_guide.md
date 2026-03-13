# 104 人力銀行 Email 擷取技術指南

> 最後更新：2026-02-28

## 目標

從 104 人力銀行抓取「有提供零食/飲料/伙食福利」的公司聯絡資訊，包含 **Email、電話、HR 姓名**。
Email 填充率約 **80%**，電話接近 **100%**。

---

## 整體流程

```
Step 1: 搜尋 API（用福利碼篩選職缺）
         ↓
Step 2: 從職缺結果解出 cust_id（公司 ID）和 job_id（職缺 ID）
         ↓
Step 3: 打公司詳細 API → 取得電話、HR、地址
         ↓
Step 4: 打職缺詳細 API → 取得 Email（核心！）
         ↓
Step 5: 合併資料、去重
```

---

## Step 1：搜尋職缺（取得公司清單）

### API Endpoint

```
GET https://www.104.com.tw/jobs/search/api/jobs
```

### 必要參數

| 參數 | 值 | 說明 |
|------|-----|------|
| `welfare` | `wf27` | 福利碼篩選（見下方對照表） |
| `area` | `6001001000` | 地區碼（台北市） |
| `page` | `1` | 頁碼 |
| `perPage` | `30` | 每頁筆數（最大 30） |
| `ro` | `0` | 固定值 |
| `order` | `15` | 排序方式 |
| `asc` | `0` | 降冪 |
| `s9` | `1` | 固定值 |

### 福利碼對照表（我們用的）

| 碼 | 意思 | 用途 |
|----|------|------|
| `wf27` | 下午茶/零食飲料 | **主力篩選** |
| `wf19` | 伙食津貼 | 補充 |
| `wf18` | 餐費補助 | 補充 |

### 必要 Headers

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.104.com.tw/jobs/search/"   # ← 必須帶！
}
```

> **重點**：`Referer` 必須帶，否則會被 403。

### 回傳結構

```json
{
  "metadata": { "total": 1234 },
  "data": {
    "list": [
      {
        "custName": "某某公司",
        "custNo": "abc123",
        "coIndustryDesc": "資訊科技業",
        "employeeCount": "100-200人",
        "jobAddrNoDesc": "台北市信義區",
        "link": {
          "cust": "/company/abc123",
          "job": "/job/xyz789"
        },
        "tags": { "wf27": "下午茶/零食飲料", "wf9": "週休二日" }
      }
    ]
  }
}
```

### 從回傳解出的關鍵欄位

- **`cust_id`**：從 `link.cust` 解析 → `/company/{cust_id}` 裡的 `{cust_id}`
- **`job_id`**：從 `link.job` 解析 → `/job/{job_id}` 裡的 `{job_id}`

```python
# 解出 cust_id
cust_url = job["link"]["cust"]         # "/company/abc123"
cust_id = cust_url.split("/company/")[-1].split("?")[0]  # "abc123"

# 解出 job_id
job_path = job["link"]["job"]          # "/job/xyz789"
job_id = job_path.split("/job/")[-1].split("?")[0]       # "xyz789"
job_url = f"https://www.104.com.tw{job_path}"
```

---

## Step 2：打公司詳細 API（電話 + HR 姓名）

### API Endpoint

```
GET https://www.104.com.tw/company/ajax/content/{cust_id}
```

### 必要 Headers

```python
headers = {
    **HEADERS,
    "Referer": f"https://www.104.com.tw/company/{cust_id}"   # ← 必須是對應公司頁
}
```

### 回傳結構（`data` 欄位內）

```json
{
  "data": {
    "phone": "02-12345678",
    "hrName": "王小明",
    "address": "台北市信義區信義路五段7號",
    "corpLink1": "https://www.company.com",
    "corpLink2": null,
    "corpLink3": null
  }
}
```

### 取得的欄位

| 欄位 | Key | 填充率 | 說明 |
|------|-----|--------|------|
| 電話 | `phone` | ~100% | 幾乎都有 |
| HR 姓名 | `hrName` | ~80% | 部分公司不填 |
| 地址 | `address` | ~95% | |
| 官網 | `corpLink1` | ~50% | 最多三個連結 |

---

## Step 3：打職缺詳細 API（Email！）

> **這是取得 Email 的關鍵步驟。**

### API Endpoint

```
GET https://www.104.com.tw/job/ajax/content/{job_id}
```

### 必要 Headers

```python
headers = {
    **HEADERS,
    "Referer": job_url   # ← 必須是該職缺的完整 URL
}
```

> **重點**：`Referer` 必須是 `https://www.104.com.tw/job/{job_id}`，否則拿不到資料。

### 回傳結構（我們要的部分）

```json
{
  "data": {
    "contact": {
      "email": "hr@company.com",
      "hrName": "王小明",
      "phone": ["02-12345678", "0912-345678"]
    }
  }
}
```

### 取得的欄位

| 欄位 | Key | 填充率 | 說明 |
|------|-----|--------|------|
| **Email** | `contact.email` | **~80%** | 公開欄位，不需登入 |
| HR 姓名 | `contact.hrName` | ~80% | 可補充公司層級沒有的 |
| 電話 | `contact.phone` | ~60% | 陣列格式，可補充 |

---

## 完整程式碼範例（最小可執行版）

```python
import requests
import time

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-TW,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}


def crawl_104_emails(max_pages=1):
    """最小範例：從 104 抓有零食福利的公司 Email"""
    results = []
    seen = set()

    for page in range(1, max_pages + 1):
        # ─── Step 1: 搜尋職缺 ───
        resp = requests.get(
            "https://www.104.com.tw/jobs/search/api/jobs",
            params={
                "welfare": "wf27",          # 零食福利碼
                "area": "6001001000",       # 台北市
                "page": str(page),
                "perPage": "30",
                "ro": "0", "order": "15", "asc": "0", "s9": "1",
            },
            headers={**HEADERS, "Referer": "https://www.104.com.tw/jobs/search/"},
            timeout=15,
        )
        jobs = resp.json().get("data", {}).get("list", [])
        if not jobs:
            break

        for job in jobs:
            # ─── Step 2: 解出 ID ───
            link = job.get("link", {})
            cust_url = link.get("cust", "")
            job_path = link.get("job", "")

            if "/company/" not in cust_url:
                continue
            cust_id = cust_url.split("/company/")[-1].split("?")[0]
            if cust_id in seen:
                continue
            seen.add(cust_id)

            job_id = job_path.split("/job/")[-1].split("?")[0] if "/job/" in job_path else ""
            job_url = f"https://www.104.com.tw{job_path}"

            # ─── Step 3: 公司詳細（電話、HR） ───
            time.sleep(0.6)
            comp = requests.get(
                f"https://www.104.com.tw/company/ajax/content/{cust_id}",
                headers={**HEADERS, "Referer": f"https://www.104.com.tw/company/{cust_id}"},
                timeout=10,
            ).json().get("data", {})

            phone = comp.get("phone", "")
            hr_name = comp.get("hrName", "")

            # ─── Step 4: 職缺詳細（Email！） ───
            email = ""
            if job_id:
                time.sleep(0.6)
                contact = requests.get(
                    f"https://www.104.com.tw/job/ajax/content/{job_id}",
                    headers={**HEADERS, "Referer": job_url},
                    timeout=10,
                ).json().get("data", {}).get("contact", {})

                email = contact.get("email", "")
                if not hr_name:
                    hr_name = contact.get("hrName", "")

            results.append({
                "公司": job.get("custName"),
                "Email": email,
                "電話": phone,
                "HR": hr_name,
                "產業": job.get("coIndustryDesc"),
            })
            print(f"✓ {job.get('custName')} | {email or '無Email'} | {phone}")

    return results


if __name__ == "__main__":
    data = crawl_104_emails(max_pages=1)
    print(f"\n共 {len(data)} 家，有 Email: {sum(1 for d in data if d['Email'])} 家")
```

---

## 地區碼參考

| 地區 | 碼 |
|------|-----|
| 台北市 | `6001001000` |
| 新北市 | `6001002000` |
| 桃園市 | `6001003000` |
| 台中市 | `6001005000` |
| 高雄市 | `6001010000` |

> 多個地區用迴圈分別打即可，不支援單次多地區查詢。

---

## 注意事項

### 反爬機制

1. **Referer 驗證**：每個 API 都要帶正確的 `Referer`，否則 403 或空資料
2. **頻率限制**：建議每次請求間隔 **0.5~1 秒**，太快會被暫時封鎖
3. **User-Agent**：用正常瀏覽器的 UA，不要用 python-requests 預設的

### Email 取得的限制

- Email 來自「職缺聯絡人」欄位，是**公開資訊**，不需登入
- 約 80% 的職缺有填 Email，20% 會留空
- 如果一家公司有多個職缺，不同職缺可能有不同的聯絡 Email
- 目前只取每家公司的第一個職缺的 Email

### 去重邏輯

- 用 `cust_id`（公司 ID）去重，同一家公司只取一次
- 三個福利碼（wf27/wf19/wf18）會有重疊，去重後約為最大碼的 1.3 倍

---

## API 路徑速查表

| 用途 | Method | URL | 回傳的關鍵欄位 |
|------|--------|-----|---------------|
| 搜尋職缺 | GET | `/jobs/search/api/jobs?welfare=wf27&area=...` | `data.list[].link.cust`, `link.job` |
| 公司詳細 | GET | `/company/ajax/content/{cust_id}` | `data.phone`, `data.hrName` |
| **職缺詳細** | GET | `/job/ajax/content/{job_id}` | **`data.contact.email`** |

---

## 資料流向圖

```
                    104 搜尋 API
                   (welfare=wf27)
                        │
                   回傳 30 筆職缺
                        │
              ┌─────────┼─────────┐
              │                   │
         解出 cust_id         解出 job_id
              │                   │
              ▼                   ▼
     公司 Detail API        職缺 Detail API
     (/company/ajax/)       (/job/ajax/)
              │                   │
     ┌───────┴───────┐     ┌─────┴─────┐
     │ phone         │     │ email  ◀──── 目標！
     │ hrName        │     │ hrName     │
     │ address       │     │ phone      │
     └───────────────┘     └───────────┘
              │                   │
              └─────────┬─────────┘
                        │
                   合併 + 去重
                        │
                    最終名單
           (公司名/Email/電話/HR/產業)
```
