"""
示範資料 — 10 家測試公司，email 分流到使用者自己輸入的真實信箱（用 + alias）

給兩個地方共用：
- tools/seed_fake_leads.py（命令列，需帶 --inbox）
- app.py「開發信」tab 的「🎬 載入示範公司」按鈕（UI 會要求輸入）

客戶 demo / E2E 驗證專用，source='seed_test' 方便之後清除。
"""
import re
from database.db import upsert_companies, get_connection, init_db

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _alias(inbox: str, tag: str) -> str:
    user, domain = inbox.split("@", 1)
    return f"{user}+{tag}@{domain}"


def _validate(inbox: str, label: str) -> str:
    inbox = (inbox or "").strip()
    if not inbox:
        raise ValueError(f"{label} 不能空白")
    if not _EMAIL_RE.match(inbox):
        raise ValueError(f"{label} 格式錯誤：{inbox}")
    return inbox


_RAW = [
    ("測試公司01_晶華科技股份有限公司", "半導體業", "100-500人", "台北市信義區松仁路100號",
     "02-2722-0001", "林小瑜", "https://test01.example.com", "IC 設計與晶圓代工",
     "資深韌體工程師／FAE 工程師"),
    ("測試公司02_台灣雲端服務有限公司", "軟體／網路相關業", "50-100人", "台北市中山區南京東路二段200號",
     "02-2568-0002", "王人資", "https://test02.example.com", "SaaS 平台開發",
     "後端工程師／DevOps"),
    ("測試公司03_綠野生技股份有限公司", "生技醫療業", "30-50人", "新竹市東區光復路一段300號",
     "03-5712-0003", "陳經理", "https://test03.example.com", "新藥研發",
     "實驗室助理／研究員"),
    ("測試公司04_城市物流股份有限公司", "物流／倉儲業", "500-1000人", "桃園市中壢區中正路400號",
     "03-4533-0004", "李招募", "https://test04.example.com", "最後一哩宅配",
     "倉管組長／配送司機"),
    ("測試公司05_好食光飲品股份有限公司", "食品飲料業", "100-300人", "台中市西屯區台灣大道500號",
     "04-2253-0005", "張 HR", "https://test05.example.com", "連鎖手搖飲品牌",
     "門市儲備幹部／行銷專員"),
    ("測試公司06_藍海電商有限公司", "批發／零售／通路業", "50-100人", "台北市內湖區瑞光路600號",
     "02-8751-0006", "周招聘", "https://test06.example.com", "跨境電商品牌",
     "電商營運／商品企劃"),
    ("測試公司07_翔宇顧問股份有限公司", "一般服務業", "10-30人", "台北市大安區敦化南路700號",
     "02-2700-0007", "黃 Jessica", "https://test07.example.com", "人資顧問／招募外包",
     "獵才顧問"),
    ("測試公司08_星辰遊戲股份有限公司", "遊戲產業", "100-200人", "高雄市左營區博愛三路800號",
     "07-5587-0008", "徐人資長", "https://test08.example.com", "手遊開發與發行",
     "Unity 工程師／遊戲企劃"),
    ("測試公司09_昇揚教育科技有限公司", "教育／學習服務業", "30-100人", "台北市中正區羅斯福路900號",
     "02-2365-0009", "吳主任", "https://test09.example.com", "線上家教平台",
     "課程企劃／業務開發"),
    ("測試公司10_森綠建材股份有限公司", "建築營造業", "200-500人", "新北市板橋區文化路1000號",
     "02-2959-0010", "蔡副理", "https://test10.example.com", "綠建築材料",
     "結構工程師／業務助理"),
]


def build_demo_companies(
    inbox_primary: str,
    inbox_secondary: str | None = None,
) -> list[dict]:
    """
    回傳 10 筆 company dict，email 使用傳入的信箱 + alias 分流。

    - 只給 inbox_primary：10 筆全部用 primary+lead01 ~ primary+lead10
    - 兩個都給：1~5 用 primary，6~10 用 secondary
    """
    primary = _validate(inbox_primary, "主要收件信箱")
    secondary = _validate(inbox_secondary, "次要收件信箱") if inbox_secondary else None

    out = []
    for i, row in enumerate(_RAW, 1):
        tag = f"lead{i:02d}"
        inbox = secondary if (secondary and i > 5) else primary
        email = _alias(inbox, tag)
        out.append({
            "cust_id": f"SEED{i:02d}",
            "cust_name": row[0],
            "industry": row[1],
            "employee_count": row[2],
            "address": row[3],
            "phone": row[4],
            "hr_name": row[5],
            "website": row[6],
            "description": row[7],
            "job_titles": row[8],
            "email": email,
            "source": "seed_test",
            "has_snack_benefit": True,
            "welfare_tags": ["零食飲料", "伙食津貼"],
            "job_url": f"https://example.com/job/seed{i:02d}",
            "company_url": f"https://example.com/company/seed{i:02d}",
        })
    return out


def seed_demo_companies(
    inbox_primary: str,
    inbox_secondary: str | None = None,
    crawled_by: str = "demo",
) -> tuple[int, int]:
    """灌 10 家進 DB。回傳 (新增, 更新) 數量。"""
    init_db()
    return upsert_companies(
        build_demo_companies(inbox_primary, inbox_secondary),
        crawled_by=crawled_by,
    )


def clear_demo_companies() -> int:
    """刪除所有 source='seed_test' 的測試公司，回傳刪除筆數。"""
    conn = get_connection()
    n = conn.execute("DELETE FROM companies WHERE source = 'seed_test'").rowcount
    conn.commit()
    return n
