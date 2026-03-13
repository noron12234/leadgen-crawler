"""
LeadFlow — 業務開發名單系統（企業版）
Dark Aurora Theme · Inspired by ByCrawl
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import streamlit as st
import pandas as pd
import io
import time
from pathlib import Path

# ── 集中設定 + 日誌 ──
sys.path.insert(0, str(Path(__file__).parent))
from logging_config import setup_logging
setup_logging()

import logging
logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
# PAGE CONFIG
# ══════════════════════════════════════════════════════
st.set_page_config(
    page_title="LeadFlow | 業務開發名單系統",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════
# LOAD EXTERNAL CSS
# ══════════════════════════════════════════════════════
css_path = Path(__file__).parent / "static" / "style.css"
if css_path.exists():
    st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# Aurora blobs (injected via HTML)
st.markdown("""
<div class="aurora-blob-2"></div>
<div class="aurora-blob-3"></div>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# AUTH CHECK
# ══════════════════════════════════════════════════════
from auth import check_auth
check_auth()

# ══════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════
for key, default in [
    ("last_run_result", None),
    ("last_run_time", None),
    ("estimated_total", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


# ══════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════
def run_crawlers(area: str, max_pages: int, run_cake: bool, run_yourator: bool, run_linkedin: bool = False) -> dict:
    from crawlers.crawler_104 import crawl_snack_companies
    from crawlers.crawler_cake import crawl_cake_jobs
    from crawlers.crawler_yourator import crawl_yourator_companies
    from processors.cleaner import clean_and_merge
    from database.db import upsert_companies

    all_raw = []

    with st.spinner("正在爬取 104 人力銀行..."):
        r104 = crawl_snack_companies(areas=[area], max_pages=max_pages, delay=0.5)
        all_raw.extend(r104)
        st.success(f"104：取得 {len(r104)} 家")

    if run_cake:
        with st.spinner("正在爬取 Cake.me..."):
            rcake = crawl_cake_jobs(keyword="HR", location="taipei")
            all_raw.extend(rcake)
            st.success(f"Cake：取得 {len(rcake)} 家")

    if run_yourator:
        with st.spinner("正在爬取 Yourator..."):
            ryourator = crawl_yourator_companies()
            all_raw.extend(ryourator)
            st.success(f"Yourator：取得 {len(ryourator)} 家")

    if run_linkedin:
        with st.spinner("正在搜尋 LinkedIn（行政/總務職缺）..."):
            from crawlers.crawler_linkedin import crawl_linkedin_companies
            rlinkedin = crawl_linkedin_companies(area=area, max_results_per_keyword=50, delay=1.0)
            all_raw.extend(rlinkedin)
            st.success(f"LinkedIn：取得 {len(rlinkedin)} 家")

    with st.spinner("清洗與去重中..."):
        cleaned = clean_and_merge(all_raw)
        st.success(f"清洗完成：{len(all_raw)} → {len(cleaned)} 家")

    with st.spinner("寫入資料庫..."):
        new_count, updated_count = upsert_companies(cleaned)
        st.success(f"新增 {new_count} 家，更新 {updated_count} 家")

    return {"new": new_count, "updated": updated_count, "total_crawled": len(cleaned)}


def fetch_estimated_total(area_code: str):
    from crawlers.crawler_104 import get_estimated_total
    try:
        return get_estimated_total(area=area_code)
    except Exception:
        return {}


def to_excel(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="業務名單")
    return output.getvalue()


# ══════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div class="sidebar-brand">
        <div class="logo-mark">LF</div>
        <div class="name">LeadFlow</div>
        <div class="tagline">業務開發名單系統</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 搜尋設定 ──
    st.markdown('<p class="sidebar-section">搜尋設定</p>', unsafe_allow_html=True)

    area_options = {
        "台北市": "6001001000",
        "新北市": "6001002000",
        "桃園市": "6001003000",
        "台中市": "6001006000",
    }
    selected_area_name = st.selectbox("目標地區", list(area_options.keys()), key="area")
    area_code = area_options[selected_area_name]
    max_pages = st.slider("每平台最多爬幾頁", min_value=1, max_value=10, value=3, key="max_pages")

    # ── 資料來源 ──
    st.markdown('<p class="sidebar-section">資料來源</p>', unsafe_allow_html=True)
    use_cake = st.checkbox("Cake.me", value=True, key="use_cake")
    use_yourator = st.checkbox("Yourator", value=True, key="use_yourator")
    use_linkedin = st.checkbox("LinkedIn", value=False, key="use_linkedin",
                               help="透過 ByCrawl API 搜尋行政/總務職缺，發現潛在客戶")

    st.divider()

    # ── 開始抓取 ──
    if st.button("開始抓取", type="primary", use_container_width=True, key="btn_crawl"):
        with st.status("執行中...", expanded=True):
            result = run_crawlers(
                area=area_code,
                max_pages=max_pages,
                run_cake=use_cake,
                run_yourator=use_yourator,
                run_linkedin=use_linkedin,
            )
            st.session_state.last_run_result = result
            st.session_state.last_run_time = time.strftime("%Y-%m-%d %H:%M")
        st.rerun()

    if st.session_state.last_run_time:
        st.caption(f"上次更新：{st.session_state.last_run_time}")

    st.divider()

    # ── 預估 ──
    if st.button("預估可爬數量", use_container_width=True, key="btn_estimate"):
        with st.spinner("查詢中..."):
            est = fetch_estimated_total(area_code)
            st.session_state.estimated_total = est

    if st.session_state.estimated_total:
        est = st.session_state.estimated_total
        st.markdown(f"""
        <div class="est-card">
            <div class="est-title">{selected_area_name} 預估可爬量</div>
            <div class="est-row"><span>下午茶 / 零食</span><span class="val">{est.get('wf27', 0)}</span></div>
            <div class="est-row"><span>伙食津貼</span><span class="val">{est.get('wf19', 0)}</span></div>
            <div class="est-row"><span>餐費補助</span><span class="val">{est.get('wf18', 0)}</span></div>
            <div class="est-highlight">約 {est.get('estimated_unique', 0)} 家公司</div>
        </div>
        """, unsafe_allow_html=True)

    # ── 工具 ──
    st.markdown('<p class="sidebar-section">輔助工具</p>', unsafe_allow_html=True)

    if st.button("驗證 Email（DNS）", use_container_width=True, key="btn_verify"):
        from database.db import get_all_companies
        from processors.email_verifier import verify_all
        clist = get_all_companies()
        has_email = [c for c in clist if c.get("email") and "@" in c.get("email", "")]
        if not has_email:
            st.warning("目前 DB 沒有 email 資料")
        else:
            with st.spinner(f"驗證 {len(has_email)} 個 email 中..."):
                verified = verify_all(has_email, max_workers=10)
            valid_n = sum(1 for c in verified if c.get("email_status") == "valid")
            suspect_n = sum(1 for c in verified if c.get("email_status") == "suspect")
            invalid_n = sum(1 for c in verified if c.get("email_status") == "invalid")
            st.success(f"有效 {valid_n} · 疑似 {suspect_n} · 無效 {invalid_n}")
            st.session_state["email_verify_result"] = verified

    if st.button("官網 Email 補充", use_container_width=True, key="btn_scan_web",
                 help="掃描有官網但沒 email 的公司首頁"):
        from processors.website_email_scanner import scan_and_update_db
        with st.spinner("掃描官網中..."):
            result = scan_and_update_db(max_workers=5)
        st.success(f"掃描 {result['scanned']} 家 · 找到 {result['found']} 個 · 更新 {result['updated']} 筆")
        if result['updated'] > 0:
            st.rerun()

    # ── 系統 ──
    st.markdown('<p class="sidebar-section">系統管理</p>', unsafe_allow_html=True)
    with st.expander("危險操作"):
        if st.button("清空資料庫", type="secondary", use_container_width=True, key="btn_clear"):
            from database.db import clear_all
            clear_all()
            st.session_state.last_run_result = None
            st.success("資料庫已清空")
            st.rerun()


# ══════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════

# ── Header ──
st.markdown("""
<div class="app-header">
    <div class="brand">
        <div class="logo">LF</div>
        <div>
            <h1>LeadFlow</h1>
            <p class="subtitle"><span class="live-dot"></span>自動從 104、Cake、Yourator 累積企業聯絡名單</p>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── 載入資料 ──
from database.db import get_all_companies, get_stats

db_stats = get_stats()
companies = get_all_companies()

# ── 上次爬蟲結果 ──
if st.session_state.last_run_result:
    r = st.session_state.last_run_result
    st.markdown(f"""
    <div class="result-banner">
        <div class="result-item new">
            <div class="num">{r['new']}</div>
            <div class="lbl">本次新增</div>
        </div>
        <div class="result-item upd">
            <div class="num">{r['updated']}</div>
            <div class="lbl">更新既有</div>
        </div>
        <div class="result-item total">
            <div class="num">{r['total_crawled']}</div>
            <div class="lbl">爬取總數</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── KPI 指標卡 ──
pct_email = round(db_stats['has_email'] / max(db_stats['total'], 1) * 100)
pct_phone = round(db_stats['has_phone'] / max(db_stats['total'], 1) * 100)

st.markdown(f"""
<div class="kpi-row">
    <div class="kpi-card blue">
        <div class="kpi-value">{db_stats['total']}</div>
        <div class="kpi-label">公司總數</div>
        <div class="kpi-sub">database records</div>
    </div>
    <div class="kpi-card green">
        <div class="kpi-value">{db_stats['has_email']}</div>
        <div class="kpi-label">有 Email</div>
        <div class="kpi-sub">{pct_email}% coverage</div>
        <div class="kpi-bar"><div class="kpi-bar-fill green" style="width: {pct_email}%"></div></div>
    </div>
    <div class="kpi-card cyan">
        <div class="kpi-value">{db_stats['has_phone']}</div>
        <div class="kpi-label">有電話</div>
        <div class="kpi-sub">{pct_phone}% coverage</div>
        <div class="kpi-bar"><div class="kpi-bar-fill cyan" style="width: {pct_phone}%"></div></div>
    </div>
    <div class="kpi-card rose">
        <div class="kpi-value">{db_stats['contacted']}</div>
        <div class="kpi-label">已聯繫</div>
        <div class="kpi-sub">outreach done</div>
    </div>
    <div class="kpi-card violet">
        <div class="kpi-value">{db_stats['remaining']}</div>
        <div class="kpi-label">待開發</div>
        <div class="kpi-sub">ready to go</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── 空狀態 ──
if db_stats["total"] == 0:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">📋</div>
        <h3>資料庫是空的</h3>
        <p>使用左側面板的「開始抓取」，開始累積您的業務名單</p>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ══════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════
tab_leads, tab_people, tab_email, tab_history = st.tabs(["📋 名單管理", "🔍 LinkedIn 人物", "📨 開發信", "📊 歷史紀錄"])

# ── TAB 1：名單管理 ──
with tab_leads:
    with st.container(border=True):
        fcol1, fcol2, fcol3, fcol4, fcol5 = st.columns(5)
        with fcol1:
            filter_snack = st.toggle("零食福利", value=False, key="filter_snack")
        with fcol2:
            filter_phone = st.toggle("有電話", value=False, key="filter_phone")
        with fcol3:
            filter_email = st.toggle("有 Email", value=False, key="filter_email")
        with fcol4:
            filter_not_contacted = st.toggle("隱藏已聯繫", value=True, key="filter_contacted")
        with fcol5:
            search_text = st.text_input("搜尋", placeholder="輸入公司名稱...",
                                        key="search", label_visibility="collapsed")

        fcol6, _ = st.columns([1, 2])
        with fcol6:
            all_sources = sorted(set(c.get("source", "").upper() for c in companies if c.get("source")))
            filter_sources = st.multiselect("來源平台", all_sources, default=all_sources, key="filter_source")

    # 套用篩選
    filtered = companies[:]
    if filter_snack:
        filtered = [c for c in filtered if c.get("has_snack_benefit")]
    if filter_phone:
        filtered = [c for c in filtered if c.get("phone")]
    if filter_email:
        filtered = [c for c in filtered if c.get("email") and "@" in c.get("email", "")]
    if filter_not_contacted:
        filtered = [c for c in filtered if not c.get("contacted")]
    if filter_sources:
        filtered = [c for c in filtered if c.get("source", "").upper() in filter_sources]
    if search_text:
        filtered = [c for c in filtered if search_text.lower() in c.get("cust_name", "").lower()]

    st.caption(f"顯示 {len(filtered)} / {db_stats['total']} 筆　·　Email 覆蓋率 {pct_email}%")

    verify_map: dict = {}
    if "email_verify_result" in st.session_state:
        for vc in st.session_state["email_verify_result"]:
            verify_map[vc.get("id")] = vc.get("email_status", "")
    EMAIL_STATUS_ICON = {"valid": "✅", "suspect": "⚠️", "invalid": "❌", "no_email": "—", "": ""}

    if not filtered:
        st.warning("沒有符合篩選條件的公司")
    else:
        df = pd.DataFrame([
            {
                "ID": c.get("id"),
                "公司名稱": c.get("cust_name", ""),
                "HR 姓名": c.get("hr_name") or "—",
                "Email": c.get("email") or "—",
                "驗證": EMAIL_STATUS_ICON.get(verify_map.get(c.get("id"), ""), ""),
                "電話": c.get("phone") or "—",
                "產業別": c.get("industry", ""),
                "員工數": c.get("employee_count", ""),
                "地址": c.get("address", ""),
                "零食": "⭐" if c.get("has_snack_benefit") else "",
                "福利標籤": "、".join(c.get("welfare_tags", [])),
                "職缺連結": c.get("job_url", ""),
                "公司頁面": c.get("company_url", ""),
                "官網": c.get("website", ""),
                "已聯繫": bool(c.get("contacted")),
                "來源": c.get("source", "").upper(),
                "首次爬取": (c.get("first_seen") or "")[:10],
            }
            for c in filtered
        ])

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            height=520,
            disabled=["ID", "公司名稱", "HR 姓名", "Email", "驗證", "電話",
                       "產業別", "員工數", "地址", "零食", "福利標籤",
                       "職缺連結", "公司頁面", "官網", "來源", "首次爬取"],
            hide_index=True,
            column_config={
                "ID":       st.column_config.NumberColumn(width="small"),
                "公司名稱": st.column_config.TextColumn(width="medium"),
                "HR 姓名":  st.column_config.TextColumn(width="small"),
                "Email":    st.column_config.TextColumn(width="large"),
                "驗證":     st.column_config.TextColumn(width="small",
                            help="✅ 有效　⚠️ 疑似　❌ 無效"),
                "電話":     st.column_config.TextColumn(width="medium"),
                "零食":     st.column_config.TextColumn(width="small"),
                "已聯繫":   st.column_config.CheckboxColumn(width="small"),
                "職缺連結": st.column_config.LinkColumn(display_text="查看", width="small"),
                "公司頁面": st.column_config.LinkColumn(display_text="查看", width="small"),
                "官網":     st.column_config.LinkColumn(width="medium"),
                "首次爬取": st.column_config.TextColumn(width="small"),
            },
            key="company_editor",
        )

        from database.db import mark_contacted
        for idx, row in edited_df.iterrows():
            original = df.loc[idx, "已聯繫"] if idx in df.index else None
            current = row["已聯繫"]
            if original is not None and current != original:
                cid = row["ID"]
                if cid:
                    mark_contacted(int(cid), contacted=bool(current))

        col_dl, col_info = st.columns([1, 3])
        with col_dl:
            excel_bytes = to_excel(df.drop(columns=["ID"]))
            st.download_button(
                label="匯出 Excel",
                data=excel_bytes,
                file_name=f"業務名單_{time.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        with col_info:
            if db_stats["total"] > 0:
                st.info(
                    f"Email 覆蓋率 **{pct_email}%**（{db_stats['has_email']}/{db_stats['total']}）　·　"
                    f"待開發 **{db_stats['remaining']}** 家"
                )


# ── TAB 2：LinkedIn 人物搜尋 ──
with tab_people:
    st.markdown("""
    <div class="section-header">
        <h3>LinkedIn 人物搜尋</h3>
        <p style="color: var(--text-secondary); margin-top: 4px;">搜尋決策者：總務、行政、Office Manager、Engineer（僅支援英文關鍵字）</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 搜尋列 ──
    pcol1, pcol2, pcol3 = st.columns([3, 1, 1])
    with pcol1:
        people_keyword = st.text_input(
            "搜尋關鍵字",
            placeholder="例如：engineer, office manager, procurement, designer",
            key="people_keyword",
        )
    with pcol2:
        people_count = st.number_input("最多幾筆", min_value=5, max_value=100, value=25, key="people_count")
    with pcol3:
        st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
        btn_search_people = st.button("搜尋", type="primary", use_container_width=True, key="btn_search_people")

    # ── 執行搜尋 ──
    if btn_search_people and people_keyword.strip():
        with st.spinner(f"正在搜尋 LinkedIn「{people_keyword}」..."):
            from crawlers.crawler_linkedin import search_linkedin_people
            results = search_linkedin_people(people_keyword.strip(), count=people_count)

            if results:
                from database.db import save_linkedin_people
                save_linkedin_people(results, keyword=people_keyword.strip())
                st.success(f"找到 {len(results)} 人，已儲存到資料庫")
            else:
                st.warning("未找到結果。請嘗試其他英文關鍵字（如 engineer, manager, designer）")
        st.rerun()
    elif btn_search_people:
        st.warning("請輸入搜尋關鍵字")

    st.divider()

    # ── 已儲存的人物 ──
    from database.db import get_linkedin_people, toggle_person_star, update_person_notes
    saved_people = get_linkedin_people()

    if not saved_people:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">🔍</div>
            <h3>尚未搜尋任何人物</h3>
            <p>輸入英文關鍵字開始搜尋 LinkedIn 上的專業人士</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # 篩選列
        pfcol1, pfcol2, pfcol3 = st.columns([1, 1, 2])
        with pfcol1:
            show_starred_only = st.checkbox("僅顯示星號標記", key="show_starred_only")
        with pfcol2:
            all_keywords = sorted(set(p.get("search_keyword", "") for p in saved_people if p.get("search_keyword")))
            filter_kw = st.multiselect("搜尋關鍵字篩選", all_keywords, default=all_keywords, key="filter_people_kw")
        with pfcol3:
            people_search = st.text_input("搜尋姓名/公司", key="people_filter_text", placeholder="快速搜尋...")

        # 套用篩選
        filtered_people = saved_people[:]
        if show_starred_only:
            filtered_people = [p for p in filtered_people if p.get("starred")]
        if filter_kw:
            filtered_people = [p for p in filtered_people if p.get("search_keyword", "") in filter_kw]
        if people_search.strip():
            q = people_search.strip().lower()
            filtered_people = [
                p for p in filtered_people
                if q in (p.get("name", "") or "").lower()
                or q in (p.get("companies", "") or "").lower()
                or q in (p.get("location", "") or "").lower()
            ]

        st.caption(f"共 {len(filtered_people)} 人（資料庫共 {len(saved_people)} 人）")

        # 人物表格
        if filtered_people:
            people_df = pd.DataFrame([
                {
                    "ID": p["id"],
                    "⭐": "⭐" if p.get("starred") else "",
                    "姓名": p.get("name", ""),
                    "公司": p.get("companies", "") or "",
                    "地點": p.get("location", ""),
                    "關鍵字": p.get("search_keyword", ""),
                    "LinkedIn": p.get("profile_url", ""),
                    "備註": p.get("notes", "") or "",
                }
                for p in filtered_people
            ])

            edited_people = st.data_editor(
                people_df,
                column_config={
                    "ID": st.column_config.NumberColumn("ID", width="small"),
                    "⭐": st.column_config.TextColumn("⭐", width="small"),
                    "姓名": st.column_config.TextColumn("姓名", width="medium"),
                    "公司": st.column_config.TextColumn("公司", width="medium"),
                    "地點": st.column_config.TextColumn("地點", width="medium"),
                    "關鍵字": st.column_config.TextColumn("關鍵字", width="small"),
                    "LinkedIn": st.column_config.LinkColumn("LinkedIn", width="medium"),
                    "備註": st.column_config.TextColumn("備註", width="large"),
                },
                use_container_width=True,
                hide_index=True,
                height=450,
                disabled=["ID", "⭐", "姓名", "公司", "地點", "關鍵字", "LinkedIn"],
                key="people_editor",
            )

            # 星號標記按鈕
            st.markdown("---")
            star_col1, star_col2, star_col3 = st.columns([1, 1, 2])
            with star_col1:
                star_id = st.number_input("人物 ID", min_value=1, step=1, key="star_person_id")
            with star_col2:
                st.markdown("<div style='height: 28px'></div>", unsafe_allow_html=True)
                scol1, scol2 = st.columns(2)
                with scol1:
                    if st.button("⭐ 標記", key="btn_star"):
                        toggle_person_star(star_id, True)
                        st.rerun()
                with scol2:
                    if st.button("取消標記", key="btn_unstar"):
                        toggle_person_star(star_id, False)
                        st.rerun()


# ── TAB 3：開發信 ──
with tab_email:
    st.markdown("""
    <div class="section-header">
        <h3>寄送開發信</h3>
    </div>
    """, unsafe_allow_html=True)

    # ── Gmail 設定 ──
    with st.expander("Gmail 設定", expanded=False):
        from config import GMAIL_USER, GMAIL_APP_PASSWORD, USE_GMAIL_API, SENDER_NAME as DEFAULT_SENDER

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            gmail_user = st.text_input(
                "Gmail 帳號", value=GMAIL_USER,
                placeholder="your@gmail.com", key="gmail_user"
            )
        with col_g2:
            gmail_pwd = st.text_input(
                "應用程式密碼", value=GMAIL_APP_PASSWORD,
                placeholder="xxxx-xxxx-xxxx-xxxx", type="password", key="gmail_pwd"
            )

        col_g3, col_g4 = st.columns([2, 1])
        with col_g3:
            sender_name = st.text_input(
                "寄件人名稱", value=DEFAULT_SENDER,
                key="sender_name"
            )
        with col_g4:
            st.write("")
            st.write("")
            if st.button("測試連線", key="test_gmail"):
                import os
                os.environ["GMAIL_USER"] = gmail_user
                os.environ["GMAIL_APP_PASSWORD"] = gmail_pwd
                from mailer.gmail_sender import get_sender
                sender = get_sender()
                ok, msg = sender.test_connection()
                if ok:
                    st.success(f"連線成功：{msg}")
                else:
                    st.error(f"連線失敗：{msg}")

        # Gmail API 狀態
        if USE_GMAIL_API:
            st.info("Gmail API 模式已啟用（OAuth2）")
        else:
            st.caption("目前使用 SMTP 模式。設定 USE_GMAIL_API=true 啟用 Gmail API。")

    # ── 每日限額 ──
    from database.db import can_send_emails, get_daily_email_count
    sent_today = get_daily_email_count()
    try:
        from config import DAILY_EMAIL_QUOTA
    except ImportError:
        DAILY_EMAIL_QUOTA = 100
    st.caption(f"今日已寄出：{sent_today} / {DAILY_EMAIL_QUOTA} 封")

    email_targets = [c for c in filtered if c.get("email") and "@" in c.get("email", "")]

    if not email_targets:
        st.info("目前篩選結果中沒有含 Email 的公司，請調整篩選條件")
    else:
        st.markdown(f"""
        <div class="section-header">
            <h3>撰寫信件</h3>
            <span class="badge">{len(email_targets)} 個目標</span>
        </div>
        """, unsafe_allow_html=True)

        default_subject = "【零食飲料服務】為貴公司打造辦公室幸福感"
        subject = st.text_input("信件主旨", value=default_subject, key="email_subject")
        st.caption("可用變數：`{hr_name}`、`{company}`")

        default_body = """您好，{hr_name}，

我是冰山程式的業務代表。

我們為 {company} 這樣規模的企業提供辦公室零食飲料定期配送服務，讓您的團隊在工作時隨時補充能量。

✦ 彈性方案，按月訂閱，隨時調整品項
✦ 統一月結發票，省去採購麻煩
✦ 首月免費試用，確認滿意再合作

若有興趣，歡迎回信或來電洽談，期待有機會為 {company} 服務！

祝商祺
"""
        body = st.text_area("信件內容", value=default_body, height=220, key="email_body")

        with st.container(border=True):
            col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
            with col_s1:
                send_limit = st.number_input(
                    "最多寄幾封", min_value=1, max_value=len(email_targets),
                    value=min(10, len(email_targets)), step=1, key="send_limit"
                )
            with col_s2:
                send_delay = st.slider("間隔秒數", 1.0, 5.0, 2.0, step=0.5, key="send_delay")
            with col_s3:
                st.write("")
                st.write("")

                # 限額檢查
                can_send, _, quota = can_send_emails(send_limit)
                if not can_send:
                    st.warning(f"超出每日限額（{quota} 封）")

                if st.button(f"開始寄信（{send_limit} 封）", type="primary", key="send_btn", disabled=not can_send):
                    import os
                    os.environ["GMAIL_USER"] = st.session_state.get("gmail_user", "")
                    os.environ["GMAIL_APP_PASSWORD"] = st.session_state.get("gmail_pwd", "")

                    from mailer.gmail_sender import get_sender
                    from database.db import mark_contacted

                    sender = get_sender()
                    targets = email_targets[:send_limit]
                    with st.spinner(f"寄信中（共 {len(targets)} 封）..."):
                        results = sender.send_batch(
                            recipients=targets,
                            subject_template=subject,
                            body_template=body,
                            sender_name=st.session_state.get("sender_name", "業務部門"),
                            delay_seconds=send_delay,
                        )

                    sent_ok = [r for r in results if r["success"]]
                    sent_fail = [r for r in results if not r["success"]]

                    for r in sent_ok:
                        if r.get("id"):
                            mark_contacted(r["id"])

                    st.success(f"成功 {len(sent_ok)} 封　·　失敗 {len(sent_fail)} 封")

                    if sent_fail:
                        with st.expander("失敗明細"):
                            for r in sent_fail:
                                st.write(f"- {r.get('cust_name')} ({r.get('email')})：{r.get('message')}")
                    st.rerun()


# ── TAB 4：歷史紀錄 ──
with tab_history:
    st.markdown("""
    <div class="section-header">
        <h3>寄信歷史</h3>
    </div>
    """, unsafe_allow_html=True)

    from database.db import get_email_logs, get_email_log_stats

    log_stats = get_email_log_stats()
    if log_stats["total"] == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">📬</div>
            <h3>尚未寄出任何信件</h3>
            <p>前往「開發信」分頁開始您的業務開發</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        lcol1, lcol2, lcol3 = st.columns(3)
        lcol1.metric("總寄出", log_stats["total"])
        lcol2.metric("成功", log_stats["sent"])
        lcol3.metric("失敗", log_stats["failed"])

        logs = get_email_logs(limit=50)
        if logs:
            log_df = pd.DataFrame([
                {
                    "時間": (log.get("sent_at") or "")[:16].replace("T", " "),
                    "公司": log.get("cust_name") or f"ID:{log.get('company_id')}",
                    "收件人": log.get("recipient_email", ""),
                    "主旨": log.get("subject", "")[:40],
                    "狀態": "✅" if log.get("status") == "sent" else "❌",
                    "錯誤訊息": log.get("error_message") or "",
                }
                for log in logs
            ])
            st.dataframe(log_df, use_container_width=True, height=350, hide_index=True)

# ── Footer ──
st.markdown("""
<div class="app-footer">
    LeadFlow v3.0 Enterprise　·　Powered by Python & Streamlit　·　即時更新
</div>
""", unsafe_allow_html=True)
