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
    initial_sidebar_state="collapsed",
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
    ("last_run_status", None),   # 'success' | 'error'
    ("last_run_error", None),
    ("last_run_duration", None),
    ("estimated_total", None),
    ("_crawling", False),
    ("_crawl_latch", False),      # 爬蟲剛結束：下一輪 rerun 仍 disable 按鈕以吸收 queued clicks
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Latch 判斷：若上一輪 run 是在爬蟲，這一輪的按鈕仍 disable（吸收 queued clicks）
_absorb_queued_clicks = bool(st.session_state.get("_crawl_latch", False))
if _absorb_queued_clicks:
    st.session_state["_crawl_latch"] = False  # 用完即清


# ══════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════
class _StreamlitLogHandler(logging.Handler):
    """即時把 crawler 的 logger.info 推到 Streamlit placeholder"""
    def __init__(self, log_placeholder, lines_ref: list, max_lines: int = 12):
        super().__init__(level=logging.INFO)
        self.box = log_placeholder
        self.lines = lines_ref
        self.max_lines = max_lines

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = time.strftime("%H:%M:%S")
            name = record.name.rsplit(".", 1)[-1]
            self.lines.append(f"[{ts}] {name}　{record.getMessage()}")
            del self.lines[: -self.max_lines]
            self.box.code("\n".join(self.lines), language="log")
        except Exception:
            pass


def run_crawlers(areas: list[str], max_pages: int, run_cake: bool, run_yourator: bool, progress_slot=None) -> dict:
    from crawlers.crawler_104 import crawl_snack_companies
    from crawlers.crawler_cake import crawl_cake_jobs
    from crawlers.crawler_yourator import crawl_yourator_companies
    from processors.cleaner import clean_and_merge
    from database.db import upsert_companies

    # ── 階段規劃：動態建立（依 checkbox）──
    phases = [("104 人力銀行", None)]
    if run_cake:     phases.append(("Cake.me", None))
    if run_yourator: phases.append(("Yourator", None))
    phases.append(("清洗去重", None))
    phases.append(("寫入資料庫", None))
    total_phases = len(phases)

    # ── 進度 UI：放主畫面的 container（建在 script 最上方）──
    outer_slot = st.session_state.get("_crawl_progress_slot")
    if outer_slot is not None:
        panel = outer_slot.container(border=True)
    else:
        panel = st.container(border=True)

    header          = panel.empty()
    progress        = panel.progress(0, text="準備開始…")
    company_counter = panel.empty()
    log_box         = panel.empty()
    log_lines: list[str] = []
    started_at = time.time()
    crawled_so_far = [0]

    # 掛上 log handler（只抓 crawlers.* 的 logger）
    handler = _StreamlitLogHandler(log_box, log_lines)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("crawlers")
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    # ETA 快取：只在「階段完成」時重算，避免同階段內 avg 被 elapsed 拉爆
    eta_cache = {"text": ""}

    def _tick(step_idx: int, label: str, note: str = "", done: bool = False):
        """
        step_idx: 1-based（第 1 階段 = 1）
        done=True 表示該階段已完成，pct 進到下一階段起點
        """
        elapsed = time.time() - started_at
        # 進度：用 (step_idx - 1 + 0.5 or 1.0) / total 確保一啟動就 > 0
        virt = step_idx - (0 if done else 0.5)
        pct = max(2, min(99, int(virt / total_phases * 100)))
        if step_idx >= total_phases and done:
            pct = 100

        # ETA：只在某階段「真的完成」那一刻重算（基於已完成階段的平均時間）
        # 同階段內只顯示快取值，避免 avg = elapsed/step_idx 持續變大
        if done and step_idx > 0 and step_idx < total_phases:
            avg = elapsed / step_idx
            remaining = max(0, avg * (total_phases - step_idx))
            eta_cache["text"] = f" · 預估剩餘 {int(remaining)} 秒" if remaining > 0 else ""
        elif done and step_idx >= total_phases:
            eta_cache["text"] = ""  # 全部完成，清空

        header.markdown(
            f"<div style='font-size:1rem;font-weight:600;margin-bottom:4px'>"
            f"階段 {step_idx}/{total_phases}　{label}</div>"
            f"<div style='font-size:0.82rem;opacity:0.65'>{note}</div>",
            unsafe_allow_html=True,
        )
        progress.progress(pct, text=f"{pct}%　·　已跑 {int(elapsed)} 秒{eta_cache['text']}")

    all_raw = []
    step = 1  # 1-based 階段編號
    try:
        # ── 階段 1：104 ──
        _tick(step, "104 人力銀行", "搜尋有零食/伙食福利的公司…")

        def _on_company(name, email):
            crawled_so_far[0] += 1
            n = crawled_so_far[0]
            tag = "✉️" if email else "　"
            company_counter.markdown(
                f"<div style='font-size:0.85rem;opacity:0.75;margin-top:4px'>"
                f"已抓 <b style='color:#fbbf24'>{n}</b> 家　最新：{tag} {name[:28]}"
                f"</div>",
                unsafe_allow_html=True,
            )
            # 同步更新進度條文字（讓秒數在長時間階段內持續走動）
            # ETA 沿用 eta_cache，不在單一階段內重算（否則 avg=elapsed/step 會越跑越大）
            _elapsed = time.time() - started_at
            _virt = step - 0.5
            _pct = max(2, min(99, int(_virt / total_phases * 100)))
            progress.progress(_pct, text=f"{_pct}%　·　已跑 {int(_elapsed)} 秒{eta_cache['text']}")

        r104 = crawl_snack_companies(areas=areas, max_pages=max_pages, delay=0.4,
                                      progress_callback=_on_company)
        all_raw.extend(r104)
        company_counter.empty()
        _tick(step, "104 人力銀行", f"✓ 取得 {len(r104)} 家", done=True)
        step += 1

        # ── 階段 2：Cake ──
        if run_cake:
            _tick(step, "Cake.me", "搜尋中…")
            rcake = crawl_cake_jobs(keyword="HR", location="taipei")
            all_raw.extend(rcake)
            _tick(step, "Cake.me", f"✓ 取得 {len(rcake)} 家", done=True)
            step += 1

        # ── 階段 3：Yourator ──
        if run_yourator:
            _tick(step, "Yourator", "搜尋中…")
            ryourator = crawl_yourator_companies()
            all_raw.extend(ryourator)
            _tick(step, "Yourator", f"✓ 取得 {len(ryourator)} 家", done=True)
            step += 1

        # ── 階段 N-1：清洗 ──
        _tick(step, "清洗去重", f"處理 {len(all_raw)} 筆原始資料…")
        cleaned = clean_and_merge(all_raw)
        _tick(step, "清洗去重", f"✓ 合併為 {len(cleaned)} 家", done=True)
        step += 1

        # ── 階段 N：寫 DB ──
        _tick(step, "寫入資料庫", "同步到資料庫…")
        _crawler_user = st.session_state.get("username", "")
        new_count, updated_count = upsert_companies(cleaned, crawled_by=_crawler_user)
        try:
            from database.db import log_activity
            log_activity(_crawler_user, "crawl",
                         f"爬取 {len(areas)} 區 · 新增 {new_count} 家 · 更新 {updated_count} 家")
        except Exception:
            pass

        duration = int(time.time() - started_at)
        progress.progress(100, text=f"🎉 全部完成　·　共花 {duration} 秒")
        header.markdown(
            f"<div style='font-size:1.05rem;font-weight:700;color:#22c55e'>"
            f"✅ 完成：新增 <b>{new_count}</b> 家　·　更新 <b>{updated_count}</b> 家　·　"
            f"共 <b>{len(cleaned)}</b> 家</div>",
            unsafe_allow_html=True,
        )
    finally:
        root.removeHandler(handler)

    return {
        "new": new_count,
        "updated": updated_count,
        "total_crawled": len(cleaned),
        "duration_sec": duration,
    }


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


def parse_emails(email_str: str) -> list[str]:
    """解析 company.email 欄位（可能是逗號/分號/空白分隔的多 email）→ 回傳乾淨 list。
    第一個是「主要」、後面是「次要」。"""
    if not email_str:
        return []
    import re as _re_pe
    parts = _re_pe.split(r"[,;\s]+", email_str.strip())
    out = []
    for p in parts:
        p = p.strip().strip(".,;")
        if "@" in p and p not in out:
            out.append(p)
    return out


# 爬蟲進度區 slot 改到 control panel 下方建立（見下面 CONTROL PANEL 區塊）


# ══════════════════════════════════════════════════════
# 📖 新手教學彈窗（5 步圖文流程）
# ══════════════════════════════════════════════════════
@st.dialog("新手教學", width="large")
def show_tutorial():
    st.markdown("""
    <style>
    .tut-step {
        display: flex; gap: 14px; margin: 10px 0;
        background: rgba(255,255,255,0.02);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 8px;
        padding: 14px 16px;
    }
    .tut-num {
        flex-shrink: 0;
        width: 28px; height: 28px; border-radius: 6px;
        background: #6366f1;
        display: flex; align-items: center; justify-content: center;
        color: #fff; font-weight: 700; font-size: 0.88rem;
    }
    .tut-body { flex: 1; font-size: 0.88rem; line-height: 1.7; color: #e4e4e7; }
    .tut-title { font-weight: 600; margin-bottom: 2px; color: #fafafa; }
    .tut-body code {
        background: rgba(99,102,241,0.15); color: #c7d2fe;
        padding: 1px 8px; border-radius: 4px; font-size: 0.82rem;
    }
    .tut-tip {
        background: rgba(251,191,36,0.05);
        border: 1px solid rgba(251,191,36,0.2);
        border-radius: 6px;
        padding: 10px 14px;
        margin: 14px 0 4px;
        font-size: 0.82rem; line-height: 1.7; color: #e4e4e7;
    }
    </style>

    <p style="font-size:0.86rem;color:#a1a1aa;margin:0 0 14px">
      跟著這四步走一遍，從找公司到寄完信大概 10 分鐘。
    </p>

    <div class="tut-step">
      <div class="tut-num">1</div>
      <div class="tut-body">
        <div class="tut-title">載入 10 家示範公司</div>
        去 <code>開發信</code> 最上面展開「第一次用？」，<b>填你自己的 Gmail</b>，
        按「載入 10 家示範公司」。10 封信會用 <code>你的信箱+lead01~10</code> 寄出，
        全部都會進到你原本信箱，只是收件人看起來不一樣，方便分辨。
      </div>
    </div>

    <div class="tut-step">
      <div class="tut-num">2</div>
      <div class="tut-body">
        <div class="tut-title">設定寄件 Gmail</div>
        在 <code>開發信</code> 展開「Gmail 設定」，填 Gmail 和應用程式密碼。
        不會設就看 <code>Gmail 設定</code> 分頁，有圖解 5 步驟。
      </div>
    </div>

    <div class="tut-step">
      <div class="tut-num">3</div>
      <div class="tut-body">
        <div class="tut-title">勾選公司 → 寄送</div>
        回 <code>名單</code> 勾選「測試公司 01~10」→ 切到開發信 →
        寫主旨和內文 → 按「確認寄出」。
      </div>
    </div>

    <div class="tut-step">
      <div class="tut-num">4</div>
      <div class="tut-body">
        <div class="tut-title">去信箱打開 → 回系統看結果</div>
        打開 Gmail，會收到 10 封示範公司寄來的信。打開幾封、點一下信裡的連結。<br>
        回系統「<code>寄信成效</code>」分頁，會看到哪些被打開、哪些被點過。
        點過連結的客戶會自動標成「熱門」 — 業務該優先聯絡這些。
      </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("關閉", type="primary", use_container_width=True):
        st.rerun()


# ══════════════════════════════════════════════════════
# TOP NAV — 品牌列 + 使用者資訊 + 登出
# ══════════════════════════════════════════════════════
_nav_left, _nav_right = st.columns([3, 2], vertical_alignment="center")

with _nav_left:
    st.markdown("""
    <div class="topnav-brand">
        <div class="topnav-logo">LF</div>
        <div class="topnav-title">
            <div class="topnav-name">LeadFlow</div>
            <div class="topnav-tag">業務開發名單系統</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

with _nav_right:
    # 在線人數 + 使用者名稱 + 登出按鈕
    try:
        from database.db import get_online_users as _gou, heartbeat as _hb
        # 每次 rerun 打一次心跳，60s 內有心跳的使用者算「在線」
        _hb(st.session_state.get("username", ""))
        _online = _gou()
        _online_n = len(_online)
    except Exception:
        _online = []
        _online_n = 0

    _me_display = st.session_state.get("name", "") or st.session_state.get("username", "—")
    _me_role = st.session_state.get("user_role", "user")
    _role_label = "Admin" if _me_role == "superadmin" else "成員"

    # 右上排列：[🟢 在線] [使用者 chip] [登出]
    _r_a, _r_b, _r_c = st.columns([1.1, 1.4, 0.7], vertical_alignment="center")
    with _r_a:
        _online_label = f"{_online_n} 人在線" if _online_n else "僅你在線"
        _online_title = "、".join(u["username"] for u in _online) if _online else ""
        st.markdown(
            f'<div class="topnav-chip online" title="{_online_title}">'
            f'<span class="status-dot"></span>{_online_label}</div>',
            unsafe_allow_html=True,
        )
    with _r_b:
        st.markdown(
            f'<div class="topnav-chip user">'
            f'<span class="topnav-avatar">{(_me_display[:1] or "·").upper()}</span>'
            f'<div class="topnav-user-meta">'
            f'<div class="topnav-user-name">{_me_display}</div>'
            f'<div class="topnav-user-role">{_role_label}</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    with _r_c:
        st.markdown('<div class="logout-slot"></div>', unsafe_allow_html=True)
        _authenticator = st.session_state.get("_authenticator")
        if _authenticator:
            _authenticator.logout("登出", key="logout_btn")

# ══════════════════════════════════════════════════════
# HERO — 大標題 + 教學按鈕（並排）
# ══════════════════════════════════════════════════════
st.markdown('<div class="hero-divider"></div>', unsafe_allow_html=True)
_hero_left, _hero_right = st.columns([4, 1.2], vertical_alignment="center")
with _hero_left:
    st.markdown("""
    <div class="hero-copy">
        <h1>找客戶、寄信、看誰打開了</h1>
        <p><span class="live-dot"></span>從 104、Cake、Yourator 找有零食福利的公司，整理成名單直接寄開發信</p>
    </div>
    """, unsafe_allow_html=True)
with _hero_right:
    if st.button("第一次用？看教學", use_container_width=True, key="btn_tutorial"):
        show_tutorial()

# ══════════════════════════════════════════════════════
# CONTROL PANEL — 爬蟲控制台（原 sidebar 核心）
# ══════════════════════════════════════════════════════
# 104 官方地區代碼（來源：https://static.104.com.tw/category-tool/json/Area.json）
AREA_OPTIONS = {
    "🌏 全台灣（會跑 20 次，約 20-40 分）": "__ALL__",
    "台北市": "6001001000",
    "新北市": "6001002000",
    "桃園市": "6001005000",
    "台中市": "6001008000",
    "台南市": "6001014000",
    "高雄市": "6001016000",
    "基隆市": "6001004000",
    "新竹縣市": "6001006000",
    "嘉義縣市": "6001013000",
    "宜蘭縣": "6001003000",
    "苗栗縣": "6001007000",
    "彰化縣": "6001010000",
    "南投縣": "6001011000",
    "雲林縣": "6001012000",
    "屏東縣": "6001018000",
    "台東縣": "6001019000",
    "花蓮縣": "6001020000",
    "澎湖縣": "6001021000",
    "金門縣": "6001022000",
    "連江縣": "6001023000",
}
_ALL_TW_CODES = [v for k, v in AREA_OPTIONS.items() if v != "__ALL__"]

# 檢查爬蟲鎖
from database.db import get_lock_holder, acquire_lock, release_lock
_crawl_holder = get_lock_holder("crawl")
_me = st.session_state.get("username", "")
_crawl_locked_by_other = bool(_crawl_holder) and _crawl_holder["locked_by"] != _me
_panel_disabled = _absorb_queued_clicks or _crawl_locked_by_other

with st.container(border=True):
    st.markdown('<div class="ctrl-title">找新客戶</div>', unsafe_allow_html=True)

    # ── 第一列：參數設定 ──
    _p1, _p2, _p3 = st.columns([2.2, 1.3, 1.3])
    with _p1:
        selected_area_names = st.multiselect(
            "在哪些地區找（可複選）",
            list(AREA_OPTIONS.keys()),
            default=["台北市"],
            placeholder="選一個或多個縣市",
            key="area",
        )
        if any(AREA_OPTIONS[n] == "__ALL__" for n in selected_area_names):
            area_codes = _ALL_TW_CODES
            _area_label = "🌏 全台灣"
        else:
            area_codes = [AREA_OPTIONS[n] for n in selected_area_names]
            _area_label = "／".join(selected_area_names) if selected_area_names else "（未選）"

        if len(area_codes) >= 10:
            st.caption(f"選了 {len(area_codes)} 區，會跑 20-40 分鐘，建議夜間再開")
        elif len(area_codes) >= 4:
            st.caption(f"選了 {len(area_codes)} 區，會跑 5-15 分鐘")
    with _p2:
        max_pages = st.slider("搜尋深度（每個網站翻幾頁）",
                              min_value=1, max_value=10, value=3, key="max_pages")
    with _p3:
        st.markdown('<p class="ctrl-subhead">除了 104 還要找哪裡</p>', unsafe_allow_html=True)
        use_cake = st.checkbox("Cake.me", value=True, key="use_cake")
        use_yourator = st.checkbox("Yourator", value=True, key="use_yourator")

    # ── 鎖狀態提示 ──
    if _crawl_locked_by_other:
        st.markdown(
            f"""
            <div class='ctrl-lock'>
                <b>{_crawl_holder['locked_by']}</b> 正在搜尋中
                <span class='ctrl-lock-meta'>{_crawl_holder.get('note', '')}　·　請稍候</span>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ── 第二列：動作鈕 ──
    _a1, _a2, _a3 = st.columns([1.6, 1.3, 3.1])
    with _a1:
        _crawl_btn_clicked = st.button(
            "開始找客戶" if not _crawl_locked_by_other else "其他人正在找",
            type="primary", use_container_width=True, key="btn_crawl",
            disabled=_panel_disabled,
        )
    with _a2:
        _est_btn = st.button(
            "估算能找幾家", use_container_width=True,
            key="btn_estimate", disabled=_panel_disabled,
        )
    with _a3:
        st.caption("每次找到新公司都會加進名單，重複執行不會洗掉舊資料；同一時間只能一人執行")

    # ── 爬蟲進度顯示區（按鈕下方，爬蟲執行時會寫入這裡） ──
    _crawl_slot = st.empty()
    st.session_state["_crawl_progress_slot"] = _crawl_slot

    # ── 預估邏輯 ──
    if _est_btn:
        if not area_codes:
            st.warning("先選一個地區")
        else:
            with st.spinner(f"查詢 {len(area_codes)} 區..."):
                totals = {"estimated_unique": 0}
                for _code in area_codes:
                    _est = fetch_estimated_total(_code) or {}
                    totals["estimated_unique"] += _est.get("estimated_unique", 0) or 0
                st.session_state.estimated_total = totals

    # ── 執行爬蟲 ──
    if _crawl_btn_clicked:
        if not area_codes:
            st.error("先選一個地區")
            st.stop()
        ok, msg = acquire_lock("crawl", _me,
                                note=f"找 {_area_label} {max_pages} 頁")
        if not ok:
            st.error(f"無法開始：{msg}")
        else:
            st.session_state["_crawling"] = True
            try:
                with st.status("⚙️ 執行中…", expanded=False) as status:
                    result = run_crawlers(
                        areas=area_codes,
                        max_pages=max_pages,
                        run_cake=use_cake,
                        run_yourator=use_yourator,
                    )
                    status.update(label=f"✅ 完成：新增 {result['new']} / 更新 {result['updated']}", state="complete")
                st.session_state.last_run_result = result
                st.session_state.last_run_time = time.strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.last_run_status = "success"
                st.session_state.last_run_duration = result.get("duration_sec", 0)
                st.session_state.last_run_error = None
                st.toast(f"找完了：新增 {result['new']} 家，更新 {result['updated']} 家", icon="✅")
            except Exception as e:
                logger.exception("搜尋失敗")
                st.session_state.last_run_result = None
                st.session_state.last_run_status = "error"
                st.session_state.last_run_error = str(e)[:200]
                st.session_state.last_run_time = time.strftime("%Y-%m-%d %H:%M:%S")
                st.toast(f"失敗：{str(e)[:80]}", icon="⚠️")
            finally:
                release_lock("crawl", _me)
                st.session_state["_crawling"] = False
                st.session_state["_crawl_latch"] = True
            st.rerun()

    # ── 持久狀態卡 + 預估卡（並排） ──
    _status_col, _est_col = st.columns(2)
    with _status_col:
        if st.session_state.last_run_status == "success" and st.session_state.last_run_result:
            r = st.session_state.last_run_result
            st.markdown(
                f"""
                <div class="run-status run-status-ok">
                    <div class="run-status-head">上次找完客戶</div>
                    <div class="run-status-body">
                        <span>新增 <b>{r.get('new', 0)}</b> 家</span>　·
                        <span>更新 <b>{r.get('updated', 0)}</b> 家</span>　·
                        <span>共 <b>{r.get('total_crawled', 0)}</b> 家</span>
                        <div class="run-status-meta">⏱ {r.get('duration_sec', 0)} 秒　·　{st.session_state.last_run_time}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        elif st.session_state.last_run_status == "error":
            st.markdown(
                f"""
                <div class="run-status run-status-err">
                    <div class="run-status-head">上次失敗</div>
                    <div class="run-status-body">
                        <div>{st.session_state.last_run_error or '未知錯誤'}</div>
                        <div class="run-status-meta">{st.session_state.last_run_time}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with _est_col:
        if st.session_state.estimated_total:
            est = st.session_state.estimated_total
            total_est = est.get("estimated_unique", 0)
            from database.db import get_stats as _gs
            _db_total = _gs().get("total", 0)
            already_in_db = _db_total
            remaining_est = max(total_est - already_in_db, 0)
            pct_done = min(round(already_in_db / max(total_est, 1) * 100), 100)

            st.markdown(f"""
            <div class="est-card">
                <div class="est-title">{_area_label} · 進度</div>
                <div class="est-row"><span>估計可爬</span><span class="val">~{total_est:,}</span></div>
                <div class="est-row"><span>已在 DB</span><span class="val" style="color:#22c55e">{already_in_db:,}</span></div>
                <div class="est-row"><span>估計還剩</span><span class="val" style="color:#f59e0b">~{remaining_est:,}</span></div>
                <div style="margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.07)">
                    <div style="display:flex;justify-content:space-between;font-size:0.72rem;opacity:0.55;margin-bottom:4px">
                        <span>進度</span><span>{pct_done}%</span>
                    </div>
                    <div style="height:4px;background:rgba(255,255,255,0.08);border-radius:2px;overflow:hidden">
                        <div style="width:{pct_done}%;height:100%;background:linear-gradient(90deg,#3b82f6,#22c55e);border-radius:2px;transition:width 0.6s"></div>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

# ══════════════════════════════════════════════════════
# 輔助工具 & 系統管理（可收合）
# ══════════════════════════════════════════════════════
_is_admin_nav = st.session_state.get("user_role") == "superadmin"

with st.expander("更多工具", expanded=False):
    _tc1, _tc2, _tc3, _tc4 = st.columns(4)
    with _tc1:
        if st.button("檢查 email 是否有效", use_container_width=True, key="btn_verify",
                     disabled=_panel_disabled):
            from database.db import get_all_companies as _gac
            from processors.email_verifier import verify_all
            clist = _gac()
            has_email = [c for c in clist if c.get("email") and "@" in c.get("email", "")]
            if not has_email:
                st.warning("目前 DB 沒有 email 資料")
            else:
                with st.spinner(f"驗證 {len(has_email)} 個 email 中..."):
                    verified = verify_all(has_email, max_workers=10)
                valid_n = sum(1 for c in verified if c.get("email_status") == "valid")
                suspect_n = sum(1 for c in verified if c.get("email_status") == "suspect")
                invalid_n = sum(1 for c in verified if c.get("email_status") == "invalid")
                from database.db import save_email_statuses
                _saved_n = save_email_statuses(verified)
                st.success(f"有效 {valid_n} · 疑似 {suspect_n} · 無效 {invalid_n}"
                           f"（{_saved_n} 筆結果已存檔，重開頁面不會消失）")
                st.session_state["email_verify_result"] = verified

    with _tc2:
        if st.button("從官網找 email", use_container_width=True, key="btn_scan_web",
                     help="對有官網但沒 email 的公司，自動掃描首頁找聯絡信箱",
                     disabled=_panel_disabled):
            from processors.website_email_scanner import scan_and_update_db
            with st.spinner("掃描官網中..."):
                result = scan_and_update_db(max_workers=5)
            st.success(f"掃描 {result['scanned']} 家 · 找到 {result['found']} 個 · 更新 {result['updated']} 筆")
            if result['updated'] > 0:
                st.rerun()

    with _tc3:
        if _online:
            _me_username = st.session_state.get("username", "")
            _online_items = []
            for u in _online:
                uname = u["username"]
                is_me = (uname == _me_username)
                _online_items.append(
                    f'<span class="online-pill{" me" if is_me else ""}">'
                    f'<span class="status-dot"></span>{uname}{"（你）" if is_me else ""}'
                    f'</span>'
                )
            st.markdown(
                '<div class="online-wrap">🟢 目前在線：' + "".join(_online_items) + '</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("🟢 只有你在線")

    with _tc4:
        if _is_admin_nav:
            if st.button("清空所有資料", type="secondary", use_container_width=True, key="btn_clear"):
                from database.db import clear_all
                clear_all()
                st.session_state.last_run_result = None
                st.success("資料已清空")
                st.rerun()
        else:
            st.caption("")


# ══════════════════════════════════════════════════════
# MAIN AREA
# ══════════════════════════════════════════════════════

# ── 載入資料 ──
from database.db import get_all_companies, get_stats

db_stats = get_stats()
companies = get_all_companies()

# ── 上次爬蟲結果 ──
if st.session_state.last_run_result:
    r = st.session_state.last_run_result
    rcol1, rcol2, rcol3 = st.columns(3)
    rcol1.metric("本次新增", r['new'], f"共 {r['total_crawled']} 家爬到")
    rcol2.metric("更新既有", r['updated'], "補充 email / 電話")
    rcol3.metric("耗時", f"{r.get('duration_sec', 0)} 秒",
                 st.session_state.get("last_run_time", ""))

    # 顯示最新新增的公司（按 first_seen 排序最新 N 筆）
    if r['new'] > 0:
        newest = sorted(
            [c for c in companies if c.get("first_seen")],
            key=lambda x: x.get("first_seen", ""),
            reverse=True,
        )[:r['new']]

        with st.expander(f"🆕 本次新增 {r['new']} 家公司（點此展開）", expanded=True):
            new_df = pd.DataFrame([
                {
                    "公司名稱": c.get("cust_name", ""),
                    "HR Email": c.get("email") or "—",
                    "電話": c.get("phone") or "—",
                    "產業": c.get("industry", "") or "—",
                    "員工數": c.get("employee_count", "") or "—",
                    "來源": c.get("source", "").upper(),
                }
                for c in newest
            ])
            st.dataframe(new_df, use_container_width=True, hide_index=True,
                         height=min(400, 60 + 35 * len(new_df)))
    st.divider()

# ── KPI 指標卡（CRM strip 樣式） ──
pct_email    = round(db_stats['has_email'] / max(db_stats['total'], 1) * 100)
pct_phone    = round(db_stats['has_phone'] / max(db_stats['total'], 1) * 100)
pct_contacted= round(db_stats['contacted'] / max(db_stats['total'], 1) * 100)

_kpi_cells = [
    ("", "公司總數", db_stats['total'], "資料庫累積"),
    ("blue", "有 Email", db_stats['has_email'], f"覆蓋率 {pct_email}%"),
    ("amber", "有電話", db_stats['has_phone'], f"覆蓋率 {pct_phone}%"),
    ("violet", "已聯繫", db_stats['contacted'], f"占比 {pct_contacted}%"),
    ("green", "待開發", db_stats['remaining'], "可立即開信"),
]
st.markdown(
    '<div class="kpi-strip">' + "".join(
        f'<div class="kpi-cell {_c}">'
        f'<div class="kpi-lbl">{_l}</div>'
        f'<div class="kpi-val">{_v:,}</div>'
        f'<div class="kpi-sub">{_s}</div>'
        f'</div>'
        for _c, _l, _v, _s in _kpi_cells
    ) + '</div>',
    unsafe_allow_html=True,
)

# ── 空狀態 ──
if db_stats["total"] == 0:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">📋</div>
        <h3>資料庫還沒有資料</h3>
        <p>在上方選地區、按「開始找客戶」，系統會自動從 104、Cake、Yourator 找公司</p>
        <span class="hint">↑ 看頁面頂端的控制台</span>
    </div>
    """, unsafe_allow_html=True)
    st.stop()

# ══════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════
_is_admin = st.session_state.get("user_role") == "superadmin"

if _is_admin:
    tab_leads, tab_email, tab_history, tab_analytics, tab_guide, tab_backup, tab_admin = st.tabs(
        ["名單", "開發信", "寄信紀錄", "寄信成效", "Gmail 設定", "🔒 資料安全", "管理後台"]
    )
else:
    tab_leads, tab_email, tab_history, tab_analytics, tab_guide, tab_backup = st.tabs(
        ["名單", "開發信", "寄信紀錄", "寄信成效", "Gmail 設定", "🔒 資料安全"]
    )
    tab_admin = None

# ── TAB 1：名單管理 ──
with tab_leads:
    with st.container(border=True):
        fcol_search, fcol_source = st.columns([2, 3], vertical_alignment="bottom")
        with fcol_search:
            search_text = st.text_input(
                "搜尋公司名稱",
                placeholder="輸入關鍵字快速過濾...",
                key="search",
            )
        with fcol_source:
            all_sources = sorted(set(c.get("source", "").upper() for c in companies if c.get("source")))
            filter_sources = st.multiselect("來源平台", all_sources, default=all_sources, key="filter_source")

        tcol1, tcol2, tcol3, tcol4, tcol5 = st.columns(5)
        with tcol1:
            filter_snack = st.toggle("零食福利", value=False, key="filter_snack")
        with tcol2:
            filter_phone = st.toggle("有電話", value=False, key="filter_phone")
        with tcol3:
            filter_email = st.toggle("有 Email", value=False, key="filter_email")
        with tcol4:
            filter_not_contacted = st.toggle("隱藏已聯繫", value=True, key="filter_contacted")
        with tcol5:
            filter_hot = st.toggle("只看熱門", value=False, key="filter_hot",
                                   help="點過開發信連結的客戶")

        # ── 第二列：產業別 + 地區 ──
        icol, acol = st.columns(2)

        with icol:
            all_industries = sorted({
                c.get("industry", "").strip()
                for c in companies
                if c.get("industry", "").strip()
            })
            filter_industries = st.multiselect(
                f"產業別（{len(all_industries)} 種）",
                options=all_industries,
                default=[],
                placeholder="不選 = 顯示全部",
                key="filter_industry",
            )

        with acol:
            # 從 address 抓中文縣市（避開英文前綴 Tai/New/Hsi）
            import re
            _CITY_RE = re.compile(r"(臺北市|台北市|新北市|桃園市|台中市|臺中市|台南市|臺南市|高雄市|基隆市|新竹市|新竹縣|苗栗縣|彰化縣|南投縣|雲林縣|嘉義市|嘉義縣|屏東縣|宜蘭縣|花蓮縣|台東縣|臺東縣|澎湖縣|金門縣|連江縣)")

            def _extract_city(addr: str) -> str:
                if not addr: return ""
                m = _CITY_RE.search(addr)
                if m:
                    # 正規化「臺」→「台」
                    return m.group(1).replace("臺", "台")
                return ""

            city_set = {_extract_city(c.get("address") or "") for c in companies}
            city_set.discard("")
            all_cities = sorted(city_set)
            filter_cities = st.multiselect(
                f"地區（{len(all_cities)} 個）",
                options=all_cities,
                default=[],
                placeholder="不選 = 全部地區",
                key="filter_city",
            )

    # ── 📥 匯入 Excel/CSV 名單 ──
    with st.expander("📥 匯入名單（Excel / CSV）", expanded=False):
        st.caption("欄位對應：公司名稱（必須）/ Email / 聯絡人 / 電話 / 產業 / 地址 / 來源。"
                   "其他欄位會略過。重名公司會合併（補空欄位、不覆蓋已有資料）。")
        _imp_file = st.file_uploader(
            "選檔（.xlsx / .csv）",
            type=["xlsx", "xls", "csv"],
            key="leads_import_file",
        )
        if _imp_file is not None:
            try:
                if _imp_file.name.lower().endswith(".csv"):
                    _imp_df = pd.read_csv(_imp_file)
                else:
                    _imp_df = pd.read_excel(_imp_file)
            except Exception as _e_imp:
                st.error(f"讀檔失敗：{_e_imp}")
                _imp_df = None

            if _imp_df is not None:
                st.write(f"預覽前 5 筆（共 {len(_imp_df)} 筆）：")
                st.dataframe(_imp_df.head(), use_container_width=True, hide_index=True)

                _col_alias = {
                    "公司名稱": "cust_name", "公司名": "cust_name", "公司": "cust_name",
                    "名稱": "cust_name", "客戶名稱": "cust_name", "客戶": "cust_name",
                    "Email": "email", "email": "email", "信箱": "email", "電子信箱": "email",
                    "聯絡人": "hr_name", "HR": "hr_name", "姓名": "hr_name", "聯絡": "hr_name",
                    "電話": "phone", "Phone": "phone", "聯絡電話": "phone",
                    "產業": "industry", "Industry": "industry",
                    "地址": "address", "Address": "address",
                    "來源": "source", "Source": "source",
                    "網站": "website", "官網": "website", "Website": "website",
                }
                # 自動 mapping
                _mapped_df = _imp_df.rename(columns=lambda c: _col_alias.get(str(c).strip(), str(c).strip()))

                if "cust_name" not in _mapped_df.columns:
                    st.error("找不到「公司名稱」欄位。請確認 Excel 有「公司」或「公司名稱」這個欄位。")
                else:
                    _i_btn1, _i_btn2 = st.columns([1, 3])
                    with _i_btn1:
                        if st.button("🚀 匯入", type="primary", key="leads_do_import",
                                     use_container_width=True):
                            _cleaned = []
                            for _row in _mapped_df.to_dict(orient="records"):
                                _cleaned.append({
                                    "cust_name": str(_row.get("cust_name", "") or "").strip(),
                                    "email": str(_row.get("email", "") or "").strip(),
                                    "hr_name": str(_row.get("hr_name", "") or "").strip(),
                                    "phone": str(_row.get("phone", "") or "").strip(),
                                    "industry": str(_row.get("industry", "") or "").strip(),
                                    "address": str(_row.get("address", "") or "").strip(),
                                    "website": str(_row.get("website", "") or "").strip(),
                                    "source": str(_row.get("source", "") or "import").strip().upper(),
                                })
                            _cleaned = [c for c in _cleaned if c["cust_name"]]
                            _new_n, _upd_n = upsert_companies(
                                _cleaned, crawled_by=st.session_state.get("username", "")
                            )
                            st.success(f"✅ 匯入完成：新增 {_new_n} 筆 / 更新 {_upd_n} 筆")
                            st.rerun()
                    with _i_btn2:
                        st.caption("匯入後系統會自動依公司名稱去重；email 欄位支援多 email（用逗號分隔）。")

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
    if filter_hot:
        filtered = [c for c in filtered if c.get("is_hot_lead")]
    if filter_sources:
        filtered = [c for c in filtered if c.get("source", "").upper() in filter_sources]
    if filter_industries:
        filtered = [c for c in filtered if c.get("industry", "").strip() in filter_industries]
    if filter_cities:
        filtered = [c for c in filtered
                    if _extract_city(c.get("address") or "") in filter_cities]
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
                "熱門": "熱門" if c.get("is_hot_lead") else "",
                "HR 姓名": c.get("hr_name") or "—",
                "Email": c.get("email") or "—",
                # 這次 session 剛驗完的優先，否則用 DB 存的上次結果
                "驗證": EMAIL_STATUS_ICON.get(
                    verify_map.get(c.get("id")) or c.get("email_status") or "", ""),
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
                "誰抓的": c.get("crawled_by", "") or "—",
                "首次爬取": (c.get("first_seen") or "")[:10],
            }
            for c in filtered
        ])

        # ── 表格操作提示 ──
        st.markdown("""
        <div style="display:flex;align-items:center;gap:16px;font-size:0.75rem;
                    opacity:0.45;margin-bottom:6px;padding:6px 10px;
                    background:rgba(255,255,255,0.03);border-radius:8px;
                    border:1px solid rgba(255,255,255,0.07);">
            <span>🖱️ 點擊儲存格選取</span>
            <span>⌨️ <kbd style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:0.72rem;">←</kbd>
            <kbd style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:0.72rem;">→</kbd>
            <kbd style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:0.72rem;">↑</kbd>
            <kbd style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:0.72rem;">↓</kbd>
            方向鍵移動</span>
            <span>📋 <kbd style="background:rgba(255,255,255,0.1);border:1px solid rgba(255,255,255,0.2);border-radius:4px;padding:1px 6px;font-size:0.72rem;">Ctrl+C</kbd> 複製儲存格</span>
            <span style="margin-left:auto;color:#3b82f6;">→ 往右還有更多欄位</span>
        </div>
        """, unsafe_allow_html=True)

        edited_df = st.data_editor(
            df,
            use_container_width=True,
            height=520,
            disabled=["ID", "公司名稱", "熱門", "HR 姓名", "Email", "驗證", "電話",
                       "產業別", "員工數", "地址", "零食", "福利標籤",
                       "職缺連結", "公司頁面", "官網", "來源", "誰抓的", "首次爬取"],
            hide_index=True,
            column_config={
                "ID":       st.column_config.NumberColumn(width="small"),
                "公司名稱": st.column_config.TextColumn(width="medium"),
                "熱門":     st.column_config.TextColumn(width="small",
                            help="點過開發信連結 = 熱門客戶，優先跟進"),
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

        col_dl, col_info = st.columns([1, 3], vertical_alignment="center")
        with col_dl:
            excel_bytes = to_excel(df.drop(columns=["ID"]))
            st.download_button(
                label="匯出 Excel",
                data=excel_bytes,
                file_name=f"業務名單_{time.strftime('%Y%m%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
        with col_info:
            if db_stats["total"] > 0:
                st.caption(
                    f"Email 覆蓋率 {pct_email}%（{db_stats['has_email']}/{db_stats['total']}） · "
                    f"待開發 {db_stats['remaining']} 家 · 本次篩選 {len(filtered)} 筆"
                )




# ── TAB 2：開發信 ──
with tab_email:
    st.markdown("""
    <div class="section-header">
        <h3>寄送開發信</h3>
    </div>
    """, unsafe_allow_html=True)

    # ══════════════════════════════════════════════
    # 🎬 新手示範：一鍵載入 10 家測試公司（email 分流到兩個真信箱）
    # ══════════════════════════════════════════════
    from database.db import get_stats as _db_get_stats
    try:
        _total_companies = _db_get_stats().get("total_companies", 0)
    except Exception:
        _total_companies = 0

    _first_time = (_total_companies == 0)
    with st.expander(
        ("第一次用？載入 10 家示範公司試試看"
         if _first_time else
         "載入 10 家示範公司（測試用）"),
        expanded=_first_time,
    ):
        st.markdown(
            "填你自己的 Gmail，系統會建 10 家測試公司到名單裡，"
            "然後勾選它們按寄送，10 封信都會進到你信箱。"
            "這是拿來試流程的，隨時可以清掉。"
        )

        # ── 兩個收件信箱：使用者自己填 ──
        _default_primary = (
            st.session_state.get("demo_inbox_primary")
            or st.session_state.get("sender_email")
            or ""
        )
        _default_secondary = st.session_state.get("demo_inbox_secondary", "")
        _ic1, _ic2 = st.columns(2)
        _demo_primary = _ic1.text_input(
            "你的 Gmail（必填）",
            value=_default_primary,
            placeholder="you@gmail.com",
            help="10 封信都會進到這個信箱，每封收件人會顯示不一樣的地址方便分辨",
            key="demo_inbox_primary",
        )
        _demo_secondary = _ic2.text_input(
            "第二個信箱（選填）",
            value=_default_secondary,
            placeholder="留空就全進主信箱；填了就後 5 封進這個",
            help="想同時測兩個信箱就填",
            key="demo_inbox_secondary",
        )

        _dc1, _dc2, _dc3 = st.columns([1, 1, 2])
        if _dc1.button("載入 10 家示範公司", type="primary",
                        use_container_width=True, key="btn_load_demo_email"):
            try:
                from demo_data import seed_demo_companies, build_demo_companies
                _new_n, _upd_n = seed_demo_companies(
                    inbox_primary=_demo_primary,
                    inbox_secondary=_demo_secondary or None,
                    crawled_by=st.session_state.get("username", "demo"),
                )
                st.success(
                    f"已載入：新增 {_new_n} 家、更新 {_upd_n} 家。"
                    "往下滾動找到「測試公司 01~10」→ 勾選 → 按寄送。"
                )
                with st.container():
                    st.caption("10 封信會寄到下面這些地址（全部都進到你填的信箱）：")
                    for _c in build_demo_companies(
                        inbox_primary=_demo_primary,
                        inbox_secondary=_demo_secondary or None,
                    ):
                        st.markdown(f"- **{_c['cust_name']}** → `{_c['email']}`")
            except ValueError as _ve:
                st.error(f"{_ve}")
            except Exception as _e:
                st.error(f"載入失敗：{_e}")
        if _dc2.button("清除示範資料", use_container_width=True, key="btn_clear_demo_email"):
            try:
                from demo_data import clear_demo_companies
                _n = clear_demo_companies()
                # 清掉示範公司留下的寄信紀錄（company_id=0 的測試信 + 對應 events）
                from database.db import get_connection as _cdc
                _c = _cdc()
                _seed_logs = _c.execute(
                    "SELECT tracking_uid FROM email_logs "
                    "WHERE company_id = 0 OR status = 'test'"
                ).fetchall()
                _seed_uids = [r[0] for r in _seed_logs if r[0]]
                if _seed_uids:
                    _q = ",".join("?" * len(_seed_uids))
                    _c.execute(f"DELETE FROM email_events WHERE tracking_uid IN ({_q})", _seed_uids)
                _c.execute("DELETE FROM email_logs WHERE company_id = 0 OR status = 'test'")
                _c.commit()
                st.success(f"已刪除 {_n} 家示範公司、相關測試寄信紀錄也清掉了")
                st.rerun()
            except Exception as _e:
                st.error(f"清除失敗：{_e}")
        _dc3.caption(
            "示範公司和真實客戶是分開的，不會互相影響。"
        )

    # ── Gmail 設定 ──
    with st.expander("Gmail 設定", expanded=False):
        from config import GMAIL_USER, GMAIL_APP_PASSWORD, USE_GMAIL_API, SENDER_NAME as DEFAULT_SENDER
        from database.db import get_setting as _db_get_setting, set_setting as _db_set_setting

        # 全公司共用 Gmail 提示
        _is_superadmin = st.session_state.get("user_role") == "superadmin"
        _shared_user = _db_get_setting("shared_gmail_user")
        _shared_updated_by = _db_get_setting("shared_gmail_updated_by")
        _shared_updated_at = _db_get_setting("shared_gmail_updated_at")
        if _shared_user:
            st.info(
                f"🔗 **全公司共用 Gmail 已設定**：`{_shared_user}` "
                f"（{_shared_updated_by or '?'} 於 {(_shared_updated_at or '?')[:10]} 設定，"
                f"登入時會自動帶入，不用每次手動填）"
            )
        else:
            if _is_superadmin:
                st.warning("尚未設定全公司共用 Gmail。下方填好後勾選「設為全公司共用」，業務員下次登入就會自動帶入。")
            else:
                st.caption("（業務員：登入後系統會自動帶入超管設好的共用 Gmail，不用每次重填）")

        col_g1, col_g2 = st.columns(2)
        with col_g1:
            gmail_user = st.text_input(
                "Gmail 帳號", value=st.session_state.get("gmail_user") or GMAIL_USER,
                placeholder="your@gmail.com", key="gmail_user"
            )
        with col_g2:
            gmail_pwd = st.text_input(
                "應用程式密碼", value=st.session_state.get("gmail_pwd") or GMAIL_APP_PASSWORD,
                placeholder="xxxx-xxxx-xxxx-xxxx", type="password", key="gmail_pwd"
            )

        col_g3, col_g4 = st.columns([2, 1], vertical_alignment="bottom")
        with col_g3:
            sender_name = st.text_input(
                "寄件人名稱", value=st.session_state.get("sender_name") or DEFAULT_SENDER,
                key="sender_name"
            )
        with col_g4:
            if st.button("測試連線", key="test_gmail", use_container_width=True):
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

        # 超管才能設「共用 Gmail」
        if _is_superadmin:
            st.divider()
            _share_col1, _share_col2 = st.columns([3, 1])
            with _share_col1:
                _set_as_shared = st.checkbox(
                    "✅ 把上方 Gmail 設為全公司共用（所有業務員登入後會自動帶入這組）",
                    value=False,
                    key="set_gmail_as_shared",
                )
            with _share_col2:
                if st.button("💾 儲存共用設定", key="save_shared_gmail",
                             use_container_width=True, disabled=not _set_as_shared):
                    if not gmail_user or not gmail_pwd:
                        st.error("Gmail 帳號和密碼都要填")
                    else:
                        from datetime import datetime as _dt_sg
                        _u_sg = st.session_state.get("username", "")
                        _db_set_setting("shared_gmail_user", gmail_user, _u_sg)
                        _db_set_setting("shared_gmail_pwd", gmail_pwd, _u_sg)
                        _db_set_setting("shared_gmail_sender_name", sender_name or DEFAULT_SENDER, _u_sg)
                        _db_set_setting("shared_gmail_updated_by", _u_sg, _u_sg)
                        _db_set_setting("shared_gmail_updated_at", _dt_sg.now().isoformat(), _u_sg)
                        st.success(f"✅ 已設為共用 Gmail：{gmail_user}（業務員下次登入自動帶入）")
                        try:
                            from database.db import log_activity as _la_sg
                            _la_sg(_u_sg, "set_shared_gmail", f"設定共用 Gmail = {gmail_user}")
                        except Exception:
                            pass
                        st.rerun()
            if _shared_user:
                if st.button("🗑 清掉共用設定", key="clear_shared_gmail",
                             help="業務員下次登入就不會自動帶入 Gmail"):
                    for _k in ("shared_gmail_user", "shared_gmail_pwd",
                               "shared_gmail_sender_name", "shared_gmail_updated_by",
                               "shared_gmail_updated_at"):
                        _db_set_setting(_k, "", st.session_state.get("username", ""))
                    st.success("已清掉共用設定")
                    st.rerun()

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
    quota_pct = round(sent_today / max(DAILY_EMAIL_QUOTA, 1) * 100)
    quota_color = "#10b981" if quota_pct < 70 else ("#f59e0b" if quota_pct < 100 else "#f43f5e")
    st.markdown(f"""
    <div class="info-banner" style="border-left-color:{quota_color};">
        <div>
            今日已寄出　<strong style="color:var(--text-primary)">{sent_today}</strong>
            <span style="color:var(--text-muted)"> / {DAILY_EMAIL_QUOTA} 封</span>
            <span style="margin-left:8px;color:{quota_color};font-family:'SF Mono',monospace;font-size:0.78rem">{quota_pct}%</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 寄信對象條件篩選（跟名單管理一樣的 UX）──
    with st.container(border=True):
        st.markdown(
            "<div style='font-size:0.85rem;font-weight:600;margin-bottom:8px'>"
            "🎯 挑選寄信對象</div>"
            "<div style='font-size:0.75rem;opacity:0.55;margin-bottom:10px'>"
            "從資料庫的有 email 公司中篩選。篩完下面會即時顯示數量</div>",
            unsafe_allow_html=True,
        )

        # 第一列：搜尋 + 產業
        er1, er2 = st.columns([2, 3], vertical_alignment="bottom")
        with er1:
            email_search = st.text_input(
                "🔍 搜尋公司名稱",
                placeholder="輸入關鍵字",
                key="ef_search",
            )
        with er2:
            all_email_industries = sorted({
                c.get("industry", "").strip()
                for c in companies
                if c.get("industry", "").strip() and c.get("email")
            })
            email_filter_industry = st.multiselect(
                f"🏭 產業別（{len(all_email_industries)} 種）",
                all_email_industries, default=[], key="ef_industry",
                placeholder="不選 = 全部產業",
            )

        # 第二列：地區 + 特性
        er3, er4 = st.columns([3, 2], vertical_alignment="bottom")
        with er3:
            all_email_cities = sorted({
                _extract_city(c.get("address") or "")
                for c in companies
                if c.get("email") and _extract_city(c.get("address") or "")
            })
            email_filter_city = st.multiselect(
                f"📍 地區（{len(all_email_cities)} 個）",
                all_email_cities, default=[], key="ef_city",
                placeholder="不選 = 全部地區",
            )
        with er4:
            email_filter_snack = st.toggle("有零食福利", value=False, key="ef_snack")

    # ── 🔍 比對 Ragic / 已合作客戶名單（排除這些公司不寄）──
    with st.expander("🔍 比對 Ragic 客戶名單（排除已合作公司）", expanded=False):
        st.caption("上傳 Ragic 客戶 Excel/CSV（要有「公司名稱」欄位）。系統會依公司名稱比對，"
                   "排除這些公司不出現在批量寄送清單。")
        _rag_file = st.file_uploader(
            "Ragic 客戶 Excel/CSV",
            type=["xlsx", "xls", "csv"],
            key="ragic_exclude_file",
        )
        _exc_col1, _exc_col2 = st.columns([3, 1])
        if _rag_file is not None:
            try:
                if _rag_file.name.lower().endswith(".csv"):
                    _rag_df = pd.read_csv(_rag_file)
                else:
                    _rag_df = pd.read_excel(_rag_file)
                _name_col = None
                for _c in _rag_df.columns:
                    if str(_c).strip() in ("公司名稱", "公司名", "公司", "客戶名稱", "客戶"):
                        _name_col = _c
                        break
                if _name_col is None:
                    st.error("找不到「公司名稱」欄位，請確認 Ragic 匯出表有這欄。")
                else:
                    from processors.cleaner import _normalize_name as _norm
                    _names = _rag_df[_name_col].dropna().astype(str).tolist()
                    _exc_set = {_norm(n) for n in _names if n.strip()}
                    st.session_state["ragic_excluded_names"] = _exc_set
                    _exc_col1.success(f"已載入 {len(_exc_set)} 家 Ragic 客戶，下方寄送清單會自動排除")
                    if _exc_col2.button("清掉排除清單", key="ragic_clear"):
                        st.session_state.pop("ragic_excluded_names", None)
                        st.rerun()
            except Exception as _e_rag:
                st.error(f"讀檔失敗：{_e_rag}")
        else:
            _exc_set_cur = st.session_state.get("ragic_excluded_names")
            if _exc_set_cur:
                _exc_col1.info(f"目前排除 {len(_exc_set_cur)} 家（之前載入的清單仍生效）")
                if _exc_col2.button("清掉排除清單", key="ragic_clear2"):
                    st.session_state.pop("ragic_excluded_names", None)
                    st.rerun()

    # 從整個資料庫的有 email 公司開始篩（不再綁名單管理的篩選）
    email_targets = [c for c in companies if c.get("email") and "@" in c.get("email", "")]
    # 排除已聯繫
    email_targets = [c for c in email_targets if not c.get("contacted")]
    # 排除 Ragic 客戶
    _ragic_set = st.session_state.get("ragic_excluded_names") or set()
    if _ragic_set:
        from processors.cleaner import _normalize_name as _norm_filter
        email_targets = [c for c in email_targets
                         if _norm_filter(c.get("cust_name", "")) not in _ragic_set]
    # 套用條件
    if email_search.strip():
        q = email_search.strip().lower()
        email_targets = [c for c in email_targets if q in c.get("cust_name", "").lower()]
    if email_filter_industry:
        email_targets = [c for c in email_targets if c.get("industry","").strip() in email_filter_industry]
    if email_filter_city:
        email_targets = [c for c in email_targets if _extract_city(c.get("address") or "") in email_filter_city]
    if email_filter_snack:
        email_targets = [c for c in email_targets if c.get("has_snack_benefit")]

    # ── 即時顯示篩選結果數量（大顆顯眼）──
    _total_db = sum(1 for c in companies if c.get("email") and not c.get("contacted"))
    _hit = len(email_targets)
    _hit_color = "#22c55e" if _hit > 0 else "#ef4444"
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:16px;padding:12px 18px;
                    background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
                    border-left:3px solid {_hit_color};
                    border-radius:10px;margin:12px 0 4px">
            <div>
                <div style="font-size:0.7rem;opacity:0.5;text-transform:uppercase;letter-spacing:0.1em">
                    符合條件
                </div>
                <div style="font-size:1.6rem;font-weight:800;color:{_hit_color};line-height:1.1;margin-top:2px">
                    {_hit} 家
                </div>
            </div>
            <div style="font-size:0.78rem;opacity:0.55;line-height:1.6;border-left:1px solid rgba(255,255,255,0.1);padding-left:16px">
                資料庫有 email 且未聯繫：<b style="color:#f5f5f5">{_total_db}</b> 家<br>
                過濾後剩 <b style="color:{_hit_color}">{_hit}</b> 家可以逐封寄
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not email_targets:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">📭</div>
            <h3>目前篩選結果中沒有含 Email 的公司</h3>
            <p>請到「名單管理」開啟「有 Email」篩選條件</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # ── 信件模板（預設） ──
        # 預設範本（已洗過 Gmail 促銷分頁觸發字眼：
        #   - 拿掉「免費」「按月訂閱」「【...】」「產品目錄」「✦」項目符號 等促銷信典型 pattern
        #   - 縮短內文 + 自然斷句，看起來像真人寫的）
        DEFAULT_SUBJECT = "{hr_name} 您好，請教 {company} 辦公室零食供應一事"
        DEFAULT_BODY = """您好 {hr_name}：

我是the client的小編，看到 {company} 在 104 上的徵才訊息，想請教一下。

我們是專做辦公室零食飲料定期配送的廠商，剛好台北幾家規模相近的公司也是我們合作對象。月配方案彈性可調品項、統一月結，採購流程能省下不少時間。

如果方便，可以先看一下我們的合作說明：https://leadgen.tw

任何問題直接回信給我即可，謝謝。"""

        # ── 範本版本管理 ──
        from database.db import get_templates as _get_tpls, save_template as _save_tpl, archive_template as _arc_tpl
        _all_templates = _get_tpls()
        _tpl_options = ["（預設 — 未存）"] + [t["name"] for t in _all_templates]

        _tpl_col1, _tpl_col2 = st.columns([3, 2])
        with _tpl_col1:
            _selected_tpl = st.selectbox(
                "📝 信件範本（選不同版本可比較成效）",
                _tpl_options,
                key="tpl_selector",
                help="存多個版本後，在「寄信成效」可以看到每版的開信率/點擊率",
            )
        with _tpl_col2:
            _sub_col1, _sub_col2 = st.columns(2)
            _sub_col1.caption(f"目前 {len(_all_templates)} 個版本")
            if _selected_tpl != "（預設 — 未存）":
                if _sub_col2.button("🗑 封存", key="tpl_archive", help="軟刪除，舊紀錄保留"):
                    _t_id = next((t["id"] for t in _all_templates if t["name"] == _selected_tpl), None)
                    if _t_id:
                        _arc_tpl(_t_id)
                        st.session_state["tpl_selector"] = "（預設 — 未存）"
                        st.session_state.pop("_last_tpl_loaded", None)
                        st.rerun()

        # 選變了：把範本套到 subject/body 欄位
        if _selected_tpl != st.session_state.get("_last_tpl_loaded"):
            st.session_state["_last_tpl_loaded"] = _selected_tpl
            if _selected_tpl == "（預設 — 未存）":
                st.session_state["email_subject"] = DEFAULT_SUBJECT
                st.session_state["email_body"] = DEFAULT_BODY
            else:
                _tpl_obj = next((t for t in _all_templates if t["name"] == _selected_tpl), None)
                if _tpl_obj:
                    st.session_state["email_subject"] = _tpl_obj["subject"]
                    st.session_state["email_body"] = _tpl_obj["body"]
            st.rerun()

        with st.expander("✏️ 編輯範本內容（這裡改完按「存為版本」才會保留）", expanded=False):
            subject_tpl = st.text_input(
                "主旨模板",
                value=st.session_state.get("email_subject", DEFAULT_SUBJECT),
                key="email_subject",
            )
            st.caption("可用變數：`{hr_name}`（HR 姓名）、`{company}`（公司名稱）")
            body_tpl = st.text_area(
                "內文模板",
                value=st.session_state.get("email_body", DEFAULT_BODY),
                height=240,
                key="email_body",
            )

            import re as _re
            _has_link = bool(_re.search(r"https?://\S+", body_tpl))
            if _has_link:
                st.caption("✓ 模板有連結。客戶一點連結就會被標成「熱門客戶」，你會在「寄信成效」看到。")
            else:
                st.warning(
                    "模板裡沒有放連結 — 這樣只能知道對方有沒有打開信，沒辦法知道有沒有興趣。\n"
                    "建議貼一個官網或產品頁連結（例如：`https://leadgen.tw`），"
                    "系統會自動改寫成追蹤網址。"
                )

            # 存為新版本
            _save_col1, _save_col2 = st.columns([3, 1])
            with _save_col1:
                _new_tpl_name = st.text_input(
                    "存為新版本（命名）",
                    value=(_selected_tpl if _selected_tpl != "（預設 — 未存）" else ""),
                    key="tpl_new_name",
                    placeholder="例：v1_短版 / v2_含優惠碼 / 春節版",
                )
            with _save_col2:
                if st.button("💾 存為版本", key="tpl_save_btn", use_container_width=True):
                    if not _new_tpl_name.strip():
                        st.warning("請輸入範本名稱")
                    else:
                        try:
                            _save_tpl(_new_tpl_name.strip(), subject_tpl, body_tpl,
                                      st.session_state.get("username", ""))
                            st.success(f"✅ 已存為「{_new_tpl_name}」")
                            st.session_state["tpl_selector"] = _new_tpl_name.strip()
                            st.session_state["_last_tpl_loaded"] = _new_tpl_name.strip()
                            st.rerun()
                        except Exception as _e_save:
                            st.error(f"存範本失敗：{_e_save}")

            st.caption("每封信會自動帶入對應公司資訊，你也可以在下方逐封修改。")

        # 寄信時這個 name 會寫入 email_logs.template_used，成效 tab 可以分組
        _tpl_name_for_log = (_selected_tpl if _selected_tpl != "（預設 — 未存）" else "(預設未命名)")

        st.markdown(f"""
        <div class="section-header">
            <h3>逐封確認寄送</h3>
            <span class="badge">{len(email_targets)} 封待寄</span>
        </div>
        <p style="font-size:0.82rem;opacity:0.55;margin:-8px 0 16px">
        每封信都可以在寄出前直接修改主旨和內文，確認沒問題再按「寄出」。
        </p>
        """, unsafe_allow_html=True)

        # ── 寄信鎖檢查（避免兩人同時寄信造成 Gmail 異常登入警告）──
        from database.db import get_lock_holder as _glh, acquire_lock as _al, release_lock as _rl
        _me_mail = st.session_state.get("username", "")
        _mail_holder = _glh("email")
        _mail_locked_by_other = bool(_mail_holder) and _mail_holder["locked_by"] != _me_mail
        if _mail_locked_by_other:
            st.markdown(
                f"""
                <div style='background:rgba(245,158,11,0.08);border-left:3px solid #f59e0b;
                            padding:12px 16px;border-radius:0 10px 10px 0;margin-bottom:14px'>
                    🔒 <b>{_mail_holder['locked_by']}</b> 正在寄信中
                    <div style='font-size:0.78rem;opacity:0.6;margin-top:3px'>
                        為避免 Gmail 偵測到異常登入把帳號鎖住，同時只允許一人寄信。
                        <br>請等 ta 結束、或請超管到「管理後台」強制解鎖。
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        # ── 統一寄信函數（單封 + 批量共用）──
        def _do_send(to_email, subj, body, cid, cust_name, tpl):
            """實際寄信。
            - 真實寄 (cid truthy)：注入 open pixel + 改寫連結 → 寄 → log status='sent'
            - 測試信 (cid=None)：注入 open pixel + 改寫連結 → 真的寄給自己 → log status='test'
            """
            from database.db import log_activity, log_email_sent, mark_contacted
            from mailer.tracking import gen_tracking_uid, inject_tracking
            try:
                from config import TRACKING_BASE_URL
            except ImportError:
                TRACKING_BASE_URL = ""
            _username = st.session_state.get("username", "")

            import os
            os.environ["GMAIL_USER"]         = st.session_state.get("gmail_user", "")
            os.environ["GMAIL_APP_PASSWORD"]  = st.session_state.get("gmail_pwd", "")

            uid = gen_tracking_uid() if TRACKING_BASE_URL else ""
            body_to_send, is_html = inject_tracking(body, uid, TRACKING_BASE_URL, is_html=False)

            from mailer.gmail_sender import get_sender
            sender = get_sender()
            ok, msg = sender.send_email(
                to=to_email, subject=subj, body=body_to_send,
                sender_name=st.session_state.get("sender_name", "業務部門"),
                html=is_html,
            )
            if ok:
                if cid:
                    log_email_sent(
                        company_id=cid, recipient_email=to_email,
                        subject=subj, status="sent", template_used=tpl,
                        tracking_uid=uid, sent_by=_username,
                        body_snapshot=body, recipient_name=cust_name or "",
                    )
                    mark_contacted(cid)
                    log_activity(_username, "send_email",
                                 f"寄給 {cust_name or to_email}")
                else:
                    log_email_sent(
                        company_id=0, recipient_email=to_email,
                        subject=f"[測試] {subj}", status="test",
                        template_used=tpl, tracking_uid=uid, sent_by=_username,
                        body_snapshot=body, recipient_name="(自己)",
                    )
                    log_activity(_username, "send_test_email",
                                 f"[測試] 寄給 {to_email}（追蹤 uid={uid[:8]}）")
            else:
                log_email_sent(
                    company_id=cid or 0, recipient_email=to_email,
                    subject=subj, status="failed", error_message=msg[:200],
                    template_used=tpl, tracking_uid=uid, sent_by=_username,
                    body_snapshot=body, recipient_name=cust_name or "",
                )
            return ok, msg

        # ── 游標 ──
        if "email_cursor" not in st.session_state:
            st.session_state.email_cursor = 0
        if st.session_state.email_cursor >= len(email_targets):
            st.success("🎉 這批名單已全部看完！")
            if st.button("↺ 從頭開始", key="btn_restart"):
                st.session_state.email_cursor = 0
                st.rerun()
        else:
            cursor = st.session_state.email_cursor
            target = email_targets[cursor]
            ctx = {
                "hr_name": target.get("hr_name") or "您好",
                "company": target.get("cust_name") or "貴公司",
            }

            # ── 收件人資訊卡（加上快速連結，方便業務員查公司背景再決定）──
            website     = target.get("website", "")
            job_url     = target.get("job_url", "")
            company_url = target.get("company_url", "")
            phone       = target.get("phone") or ""
            address     = target.get("address", "") or ""
            welfare_tags = target.get("welfare_tags") or []

            links_parts = []
            if website:
                links_parts.append(f'<a href="{website}" target="_blank" class="ep-link">🌐 官網</a>')
            if company_url:
                links_parts.append(f'<a href="{company_url}" target="_blank" class="ep-link">🏢 104 公司頁</a>')
            if job_url:
                links_parts.append(f'<a href="{job_url}" target="_blank" class="ep-link">💼 職缺頁</a>')
            links_html = "".join(links_parts) if links_parts else \
                '<span style="opacity:0.4;font-size:0.78rem">（此公司沒有網站連結）</span>'

            tags_html = ""
            if welfare_tags:
                tag_spans = "".join(f'<span class="ep-tag">{t}</span>' for t in welfare_tags[:6])
                tags_html = f'<div class="ep-tags">{tag_spans}</div>'

            _target_emails = parse_emails(target.get("email", ""))
            _emails_disp = (
                f"{_target_emails[0]} <span style='opacity:0.55;font-size:0.78rem'>＋{len(_target_emails)-1} 個次要</span>"
                if len(_target_emails) > 1 else (_target_emails[0] if _target_emails else "（無）")
            )
            meta_row = (
                f"<b>收件人：</b>{target.get('hr_name') or '（無姓名）'} &nbsp;·&nbsp; "
                f"<b>Email：</b>{_emails_disp} &nbsp;·&nbsp; "
                f"{target.get('industry', '') or '—'} &nbsp;·&nbsp; "
                f"{target.get('employee_count', '') or '—'} 人"
            )
            if phone:
                meta_row += f' &nbsp;·&nbsp; ☎ {phone}'

            address_html = f'<div class="ep-address">📍 {address}</div>' if address else ''

            # 把整塊組成一行字串避免 markdown parser 縮排誤判
            card_html = (
                '<div class="email-preview-card">'
                f'<div class="ep-company">{target.get("cust_name", "")}</div>'
                f'<div class="ep-meta">{meta_row}</div>'
                f'{address_html}'
                f'{tags_html}'
                f'<div class="ep-links">{links_html}</div>'
                '</div>'
                f'<div class="email-counter">第 {cursor + 1} 封 / 共 {len(email_targets)} 封　·　建議寄信前點「官網」快速確認公司類型合適</div>'
            )
            st.markdown(card_html, unsafe_allow_html=True)

            # ── 可直接編輯的主旨 + 內文 ──
            edit_subject = st.text_input(
                "主旨（可直接修改這封）",
                value=subject_tpl.format(**ctx),
                key=f"send_subject_{cursor}",
            )
            edit_body = st.text_area(
                "內文（可直接修改這封）",
                value=body_tpl.format(**ctx),
                height=240,
                key=f"send_body_{cursor}",
                help="內文裡可以直接貼網址（公司簡介、產品頁、預約連結…）— 對方點開後會自動記錄到「寄信成效」，你能看到誰點了什麼連結。",
            )
            st.caption("內文可放網址。寄出時會改寫成追蹤連結，對方一點你就會在「寄信成效」看到，那個客戶也會自動標成熱門。")

            # ── 多 email 公司：選擇要寄哪些 ──
            if len(_target_emails) > 1:
                _send_emails = st.multiselect(
                    f"這家公司有 {len(_target_emails)} 個 email，要寄到哪幾個？",
                    options=_target_emails,
                    default=[_target_emails[0]],
                    key=f"send_email_pick_{cursor}",
                    help="預設只寄主要（第一個）。勾選多個會分別寄出、各自追蹤開信。",
                )
            else:
                _send_emails = _target_emails

            # ── 操作按鈕 ──
            bc1, bc2, bc3, bc4 = st.columns([3, 2, 2, 1])

            with bc1:
                _n_to_send = max(len(_send_emails), 1)
                can_send, _, _ = can_send_emails(_n_to_send)
                _no_email = len(_send_emails) == 0
                _btn_disabled = (not can_send) or _mail_locked_by_other or _no_email
                _btn_label = (
                    "⏳ 其他人寄信中" if _mail_locked_by_other
                    else ("⛔ 沒選 email" if _no_email
                          else ("⛔ 今日超量" if not can_send
                                else (f"✅ 確認寄出 {_n_to_send} 封" if _n_to_send > 1 else "✅ 確認寄出")))
                )
                if st.button(_btn_label, type="primary", key=f"btn_send_{cursor}",
                             disabled=_btn_disabled, use_container_width=True):
                    _ok_lock, _lock_msg = _al("email", _me_mail,
                                                note=f"寄信給 {target.get('cust_name','')}")
                    if not _ok_lock:
                        st.error(f"無法寄信：{_lock_msg}")
                    else:
                        try:
                            _send_results = []
                            for _email_addr in _send_emails:
                                _ok, _msg = _do_send(
                                    _email_addr, edit_subject, edit_body,
                                    target.get("id"), target.get("cust_name"), _tpl_name_for_log,
                                )
                                _send_results.append((_email_addr, _ok, _msg))
                            _ok_n = sum(1 for _, o, _ in _send_results if o)
                            _fail_n = len(_send_results) - _ok_n
                            if _ok_n and not _fail_n:
                                st.success(f"✅ 已寄出給 {target.get('cust_name')}（{_ok_n} 個 email）")
                                st.session_state.email_cursor = cursor + 1
                                st.rerun()
                            elif _ok_n and _fail_n:
                                st.warning(f"部分成功：{_ok_n} 成功 / {_fail_n} 失敗。失敗詳情："
                                           + "; ".join(f"{e}:{m}" for e, o, m in _send_results if not o))
                            else:
                                st.error("全部寄送失敗：" + "; ".join(f"{e}:{m}" for e, _, m in _send_results))
                        finally:
                            _rl("email", _me_mail)

            with bc2:
                if st.button("⏭ 跳過這封", key=f"btn_skip_{cursor}", use_container_width=True):
                    try:
                        from database.db import log_email_sent as _log_skip, log_activity as _log_act
                        _u_skip = st.session_state.get("username", "")
                        _log_skip(
                            company_id=target.get("id") or 0,
                            recipient_email=target.get("email", "") or "",
                            subject=edit_subject,
                            status="skipped",
                            template_used=_tpl_name_for_log,
                            sent_by=_u_skip,
                            recipient_name=target.get("cust_name") or "",
                        )
                        _log_act(_u_skip, "skip_email",
                                 f"跳過 {target.get('cust_name') or target.get('email')}")
                    except Exception as _e_skip:
                        logger.warning(f"記錄跳過失敗：{_e_skip}")
                    st.session_state.email_cursor = cursor + 1
                    st.rerun()

            with bc3:
                if cursor > 0:
                    if st.button("◀ 上一封", key=f"btn_prev_{cursor}", use_container_width=True):
                        st.session_state.email_cursor = cursor - 1
                        st.rerun()

            with bc4:
                if st.button("↺", key=f"btn_reset_{cursor}", help="從頭開始",
                             use_container_width=True):
                    st.session_state.email_cursor = 0
                    st.rerun()

            # ── 測試：寄給自己 ──
            st.divider()
            st.caption("🧪 **測試模式**：確認信件長相正常再寄給客戶")
            test_col1, test_col2 = st.columns([3, 1], vertical_alignment="bottom")
            with test_col1:
                test_email = st.text_input(
                    "測試收件地址（寄給自己）",
                    value=st.session_state.get("gmail_user", ""),
                    key="test_email_addr",
                    placeholder="your@gmail.com",
                )
            with test_col2:
                if st.button("寄測試信", key=f"btn_test_{cursor}", use_container_width=True):
                    if test_email and "@" in test_email:
                        ok, msg = _do_send(
                            test_email,
                            f"[測試] {edit_subject}",
                            edit_body,
                            None, None, _tpl_name_for_log,
                        )
                        if ok:
                            st.success(f"測試信已寄到 {test_email}，去收信確認吧！")
                        else:
                            st.error(f"寄送失敗：{msg}")
                    else:
                        st.warning("請輸入有效的 Email 地址")

        # ══════════════════════════════════════════════════════
        # 📦 批量寄送模式 — 勾選多筆一次寄
        # ══════════════════════════════════════════════════════
        st.divider()
        with st.expander(f"📦 批量寄送（從目前 {len(email_targets)} 家裡勾選多筆）", expanded=False):
            st.caption("勾選下表多列 → 系統用上方「信件模板」自動套用 {hr_name}/{company} 寄給每一家。"
                       "為避免 Gmail 異常登入鎖、每封間隔 2 秒。")

            _batch_df = pd.DataFrame([
                {
                    "公司": t.get("cust_name") or "—",
                    "Email": (lambda emls: emls[0] + (f" (+{len(emls)-1})" if len(emls) > 1 else ""))(parse_emails(t.get("email", ""))) if parse_emails(t.get("email", "")) else "",
                    "聯絡人": t.get("hr_name") or "—",
                    "產業": t.get("industry") or "—",
                    "_target_id": i,
                }
                for i, t in enumerate(email_targets)
            ])

            _selection = st.dataframe(
                _batch_df.drop(columns=["_target_id"]),
                use_container_width=True,
                height=320,
                hide_index=True,
                on_select="rerun",
                selection_mode="multi-row",
                key="batch_picker",
            )
            _selected_rows = _selection.selection.rows if _selection else []
            _selected_targets = [email_targets[i] for i in _selected_rows]

            # 多 email 寄信策略
            _multi_strategy = st.radio(
                "多 email 公司怎麼寄？",
                ["只寄主要 email", "寄給所有 email"],
                horizontal=True,
                key="batch_multi_strategy",
            )

            # 計算實際會寄出的總封數（多 email 公司會發多封）
            _actual_emails = []  # list of (target, email_addr)
            for _t in _selected_targets:
                _emls = parse_emails(_t.get("email", ""))
                if not _emls:
                    continue
                if _multi_strategy == "寄給所有 email":
                    for _e in _emls:
                        _actual_emails.append((_t, _e))
                else:
                    _actual_emails.append((_t, _emls[0]))

            _bcol1, _bcol2, _bcol3 = st.columns([2, 2, 3])
            _bcol1.metric("已選公司", len(_selected_targets))
            _can_bulk, _bulk_left, _bulk_quota = can_send_emails(len(_actual_emails) or 1)
            _bcol2.metric("實際寄出 / 剩餘", f"{len(_actual_emails)} / {_bulk_left}")

            with _bcol3:
                _bulk_disabled = (
                    len(_actual_emails) == 0
                    or not _can_bulk
                    or _mail_locked_by_other
                )
                _bulk_label = (
                    "勾選至少一筆" if not _actual_emails
                    else ("⏳ 其他人寄信中" if _mail_locked_by_other
                          else (f"⛔ 超量（剩 {_bulk_left}）" if not _can_bulk
                                else f"✅ 批量寄出 {len(_actual_emails)} 封"))
                )

                if st.button(_bulk_label, type="primary", key="btn_batch_send",
                             disabled=_bulk_disabled, use_container_width=True):
                    _bulk_username = st.session_state.get("username", "")
                    _ok_lock, _lock_msg = _al("email", _me_mail,
                                              note=f"批量寄信 {len(_actual_emails)} 封")
                    if not _ok_lock:
                        st.error(f"無法寄信：{_lock_msg}")
                    else:
                        try:
                            import time as _t_batch
                            _prog = st.progress(0, text="準備批量寄送...")
                            _bulk_results = {"sent": 0, "failed": 0, "errors": []}
                            _total = len(_actual_emails)
                            for _i, (_bt, _email_to) in enumerate(_actual_emails):
                                _ctx = {
                                    "hr_name": _bt.get("hr_name") or "您好",
                                    "company": _bt.get("cust_name") or "貴公司",
                                }
                                try:
                                    _bs = subject_tpl.format(**_ctx)
                                    _bb = body_tpl.format(**_ctx)
                                except Exception as _e_fmt:
                                    _bulk_results["failed"] += 1
                                    _bulk_results["errors"].append(
                                        f"{_bt.get('cust_name')}: 模板套用失敗 ({_e_fmt})"
                                    )
                                    continue
                                _ok, _msg = _do_send(
                                    _email_to, _bs, _bb,
                                    _bt.get("id"), _bt.get("cust_name"), _tpl_name_for_log,
                                )
                                if _ok:
                                    _bulk_results["sent"] += 1
                                else:
                                    _bulk_results["failed"] += 1
                                    _bulk_results["errors"].append(
                                        f"{_bt.get('cust_name')} ({_email_to}): {_msg}"
                                    )
                                _prog.progress((_i + 1) / _total,
                                               text=f"第 {_i+1} / {_total} 封：{_bt.get('cust_name')} → {_email_to}")
                                if _i < _total - 1:
                                    _t_batch.sleep(2)  # 間隔避免被 Gmail 擋
                            _prog.empty()
                            st.success(
                                f"批量寄送完成：✅ {_bulk_results['sent']} 成功 "
                                f"／ ❌ {_bulk_results['failed']} 失敗"
                            )
                            if _bulk_results["errors"]:
                                with st.expander(f"看 {_bulk_results['failed']} 筆失敗詳情"):
                                    for _err in _bulk_results["errors"]:
                                        st.write(f"- {_err}")
                            from database.db import log_activity as _la_bulk
                            _la_bulk(_bulk_username, "bulk_send",
                                     f"批量 {_bulk_results['sent']}/{_total} 成功")
                        finally:
                            _rl("email", _me_mail)


# ── TAB 4：歷史紀錄 ──
with tab_history:
    st.markdown("""
    <div class="section-header">
        <h3>寄信歷史</h3>
    </div>
    """, unsafe_allow_html=True)

    from database.db import get_email_logs, get_email_log_stats, get_connection as _hc

    logs_all = get_email_logs(limit=200)
    real_logs = [l for l in logs_all if l.get("status") in ("sent", "failed")]
    test_logs = [l for l in logs_all if l.get("status") == "test"]
    skipped_logs = [l for l in logs_all if l.get("status") == "skipped"]

    if not logs_all:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">📬</div>
            <h3>還沒寄過信</h3>
            <p>去「開發信」挑公司按寄送，紀錄會自動出現</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # 抓 open / click 紀錄；open 套用預掃過濾
        # 預掃定義：寄出 <10s OR (<60s 且 UA 含 GoogleImageProxy)
        _uids = [l.get("tracking_uid") for l in logs_all if l.get("tracking_uid")]
        _opened_uids = set()
        _opened_raw_uids = set()  # 原始（含預掃）— 給 diagnostic 用
        _clicked_uids = set()
        if _uids:
            _placeholders = ",".join("?" * len(_uids))
            # 帶上 sent_at + UA 才能判斷預掃
            _rows = _hc().execute(
                f"""SELECT ev.tracking_uid, ev.event_type, ev.user_agent, ev.occurred_at, el.sent_at
                    FROM email_events ev
                    LEFT JOIN email_logs el ON ev.tracking_uid = el.tracking_uid
                    WHERE ev.event_type IN ('open','click')
                      AND ev.tracking_uid IN ({_placeholders})""",
                _uids,
            ).fetchall()
            from datetime import datetime as _dt_pf
            for _u, _ev, _ua, _occ, _sent in _rows:
                if _ev == "click":
                    _clicked_uids.add(_u)
                    _opened_uids.add(_u)  # 點過必然真開
                    _opened_raw_uids.add(_u)
                else:  # open
                    _opened_raw_uids.add(_u)
                    _is_prefetch = False
                    try:
                        _d = (_dt_pf.fromisoformat(_occ) - _dt_pf.fromisoformat(_sent)).total_seconds()
                    except Exception:
                        _d = 9999
                    _ua_l = (_ua or "").lower()
                    if _d < 10:
                        _is_prefetch = True
                    elif _d < 60 and "googleimageproxy" in _ua_l:
                        _is_prefetch = True
                    elif any(p in _ua_l for p in ("proofpoint", "mimecast", "safelinks", "barracuda")):
                        _is_prefetch = True
                    if not _is_prefetch:
                        _opened_uids.add(_u)

        _open_count = sum(1 for l in logs_all if l.get("tracking_uid") in _opened_uids)
        _click_count = sum(1 for l in logs_all if l.get("tracking_uid") in _clicked_uids)
        _open_raw_count = sum(1 for l in logs_all if l.get("tracking_uid") in _opened_raw_uids)
        _prefetch_count = _open_raw_count - _open_count

        lcol1, lcol2, lcol3, lcol4, lcol5 = st.columns(5)
        lcol1.metric("正式寄出",
                     sum(1 for l in real_logs if l.get("status") == "sent"))
        lcol2.metric("被打開",
                     _open_count,
                     delta=f"-{_prefetch_count} 預掃" if _prefetch_count else None,
                     delta_color="off",
                     help="只算「真實開信」— 寄出 10 秒後、且不是 Google 反釣魚預掃的 open 事件才算。")
        lcol3.metric("寄送失敗",
                     sum(1 for l in real_logs if l.get("status") == "failed"))
        lcol4.metric("測試信", len(test_logs))
        lcol5.metric("已跳過", len(skipped_logs))

        _filter_col1, _filter_col2 = st.columns(2)
        _show_test = _filter_col1.checkbox("顯示測試信", value=True, key="hist_show_test")
        _show_skipped = _filter_col2.checkbox("顯示已跳過", value=True, key="hist_show_skipped")

        _status_label = {"sent": "正式", "failed": "失敗", "test": "測試", "skipped": "已跳過"}
        _filtered = [
            l for l in logs_all
            if l.get("status") in ("sent", "failed")
            or (l.get("status") == "test" and _show_test)
            or (l.get("status") == "skipped" and _show_skipped)
        ]
        if _filtered:
            log_df = pd.DataFrame([
                {
                    "時間": (log.get("sent_at") or "")[:16].replace("T", " "),
                    "類型": _status_label.get(log.get("status"), log.get("status", "")),
                    "開信": "✓" if log.get("tracking_uid") in _opened_uids else "",
                    "點連結": "✓" if log.get("tracking_uid") in _clicked_uids else "",
                    "公司": log.get("cust_name") or ("—" if not log.get("company_id") else f"ID:{log.get('company_id')}"),
                    "收件人": log.get("recipient_email", ""),
                    "主旨": log.get("subject", "")[:40],
                    "寄件者": log.get("sent_by") or "—",
                    "錯誤訊息": log.get("error_message") or "",
                }
                for log in _filtered
            ])
            st.dataframe(log_df, use_container_width=True, height=400, hide_index=True)

            # ── 匯出 Excel ──
            st.markdown("##### 下載寄信歷史")
            _dl_col1, _dl_col2 = st.columns([2, 3])
            _dl_scope = _dl_col1.radio(
                "下載範圍",
                ["全部目前顯示", "只有開信過", "只有點連結過"],
                horizontal=False,
                key="hist_dl_scope",
                label_visibility="collapsed",
            )
            if _dl_scope == "只有開信過":
                _dl_df = log_df[log_df["開信"] == "✓"]
            elif _dl_scope == "只有點連結過":
                _dl_df = log_df[log_df["點連結"] == "✓"]
            else:
                _dl_df = log_df
            with _dl_col2:
                if len(_dl_df) > 0:
                    st.download_button(
                        label=f"⬇ 匯出 Excel（{len(_dl_df)} 筆）",
                        data=to_excel(_dl_df),
                        file_name=f"寄信歷史_{_dl_scope}_{time.strftime('%Y%m%d_%H%M')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="hist_excel_download",
                    )
                else:
                    st.caption(f"目前篩選後沒有符合「{_dl_scope}」的紀錄")
        else:
            st.info("沒有符合條件的紀錄")


# ── TAB 4b：寄信成效（需求規格） ──
with tab_analytics:
    _hc_top1, _hc_top2 = st.columns([5, 1], vertical_alignment="bottom")
    with _hc_top1:
        st.markdown("""
        <div class="section-header">
            <h3>寄信成效</h3>
            <p class="section-sub">看每封信被打開沒、哪些連結被點了、哪些客戶最有興趣。客戶在信箱開信或點連結後，按右邊重新整理才會看到最新數字。</p>
        </div>
        """, unsafe_allow_html=True)
    with _hc_top2:
        if st.button("重新整理", key="analytics_refresh", use_container_width=True,
                     help="客戶剛開信或點連結，按這個重抓資料"):
            st.rerun()

    from database.db import (
        get_tracking_stats,
        get_template_stats,
        get_hot_leads,
        get_events_for_uid,
        get_email_logs as _ga_logs,
    )

    _tstats = get_tracking_stats()

    if _tstats["sent"] == 0:
        st.markdown("""
        <div class="empty-state">
            <div class="icon">📊</div>
            <h3>還沒有成效資料</h3>
            <p>寄出第一封信之後，這裡會顯示開信率、點擊率、最熱門的客戶</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # ── KPI 卡 ──
        _a_kpi = [
            ("",       "寄出總數", _tstats["sent"],      "含測試信"),
            ("blue",   "確認開信",   _tstats["opened"],
                f"開信率 {_tstats['open_rate']}% "
                f"（原始 {_tstats['opened_raw']} 筆，過濾掉 {_tstats['prefetch_filtered']} 筆預掃）"),
            ("violet", "點了連結", _tstats["clicked"],   f"點擊率 {_tstats['click_rate']}%"),
            ("amber",  "已回信",   _tstats.get("replied", 0), "用「掃描回信」更新"),
            ("green",  "熱門客戶", _tstats["hot_leads"], "點過連結或回信就算熱門"),
        ]
        st.markdown(
            '<div class="kpi-strip">' + "".join(
                f'<div class="kpi-cell {_c}">'
                f'<div class="kpi-lbl">{_l}</div>'
                f'<div class="kpi-val">{_v:,}</div>'
                f'<div class="kpi-sub">{_s}</div>'
                f'</div>'
                for _c, _l, _v, _s in _a_kpi
            ) + '</div>',
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

        # ── 模板效果比較 ──
        _tpl_rows = get_template_stats()
        ac_tpl, ac_hot = st.columns([5, 4], gap="large")

        with ac_tpl:
            st.markdown("#### 不同模板比較")
            if _tpl_rows:
                tpl_df = pd.DataFrame([
                    {
                        "模板": r["template"],
                        "寄出": r["sent"],
                        "開信": r["opened"],
                        "開信率": f"{r['open_rate']}%",
                        "點擊": r["clicked"],
                        "點擊率": f"{r['click_rate']}%",
                    }
                    for r in _tpl_rows
                ])
                st.dataframe(tpl_df, use_container_width=True, hide_index=True,
                             height=min(320, 60 + 36 * len(tpl_df)))
                st.caption("用哪個模板開信率最高、點擊率最高一眼看完")
            else:
                st.caption("還沒有正式寄信的資料。寄過之後這裡會列出每個模板的成效。")

        with ac_hot:
            st.markdown("#### 熱門客戶")
            _hot_all = get_hot_leads()
            _hide_contacted = st.toggle(
                "隱藏已聯繫", value=False, key="hot_hide_contacted",
                help="跟進完把名單頁的「已聯繫」打勾，這裡就能收起來，熱門名單不會越積越多")
            _hot = ([h for h in _hot_all if not h.get("contacted")]
                    if _hide_contacted else _hot_all)
            if _hot:
                hot_df = pd.DataFrame([
                    {
                        "公司": h.get("cust_name", ""),
                        "回信": h.get("reply_count", 0),
                        "點擊數": h.get("click_count", 0),
                        "開信數": h.get("open_count", 0),
                        "最近互動": (h.get("last_event_at") or "")[:16].replace("T", " "),
                        "HR Email": h.get("email") or "—",
                    }
                    for h in _hot
                ])
                st.dataframe(hot_df, use_container_width=True, hide_index=True,
                             height=min(320, 60 + 36 * len(hot_df)))
                st.caption("回過信 > 點過連結 > 開過信，由熱到冷排序。"
                           "開信數為估計值（郵件服務的圖片代理會影響精度）")

                hot_full_df = pd.DataFrame([
                    {
                        "公司名稱": h.get("cust_name", ""),
                        "回信數": h.get("reply_count", 0),
                        "點擊數": h.get("click_count", 0),
                        "開信數": h.get("open_count", 0),
                        "最近互動": (h.get("last_event_at") or "")[:16].replace("T", " "),
                        "HR 姓名": h.get("hr_name") or "—",
                        "Email": h.get("email") or "—",
                        "Email 驗證": {"valid": "有效", "suspect": "疑似",
                                       "invalid": "無效"}.get(h.get("email_status") or "", ""),
                        "電話": h.get("phone") or "—",
                        "產業別": h.get("industry", ""),
                        "員工數": h.get("employee_count", ""),
                        "地址": h.get("address", ""),
                        "零食": "⭐" if h.get("has_snack_benefit") else "",
                        "福利標籤": "、".join(h.get("welfare_tags", [])),
                        "職缺連結": h.get("job_url", ""),
                        "公司頁面": h.get("company_url", ""),
                        "官網": h.get("website", ""),
                        "已聯繫": bool(h.get("contacted")),
                        "來源": (h.get("source") or "").upper(),
                        "誰抓的": h.get("crawled_by") or "—",
                        "首次爬取": (h.get("first_seen") or "")[:10],
                    }
                    for h in _hot
                ])
                st.download_button(
                    label="匯出熱門客戶 Excel",
                    data=to_excel(hot_full_df),
                    file_name=f"熱門客戶_{time.strftime('%Y%m%d')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    key="dl_hot_leads",
                    help="含名單全部欄位 + 點擊數/開信數，可直接匯入 ERP",
                )
            else:
                st.caption("還沒有客戶點過連結或回信。客戶一點連結、或回你的信，就會自動進這個列表。")

            if st.button("📨 掃描回信", key="btn_scan_replies", use_container_width=True,
                         help="登入寄信 Gmail 的收件匣，比對最近 30 天有沒有客戶回信；"
                              "有回信的客戶自動標成熱門"):
                import os as _os_rc
                if st.session_state.get("gmail_user"):
                    _os_rc.environ["GMAIL_USER"] = st.session_state["gmail_user"]
                if st.session_state.get("gmail_pwd"):
                    _os_rc.environ["GMAIL_APP_PASSWORD"] = st.session_state["gmail_pwd"]
                from mailer.reply_checker import check_replies
                with st.spinner("連線 Gmail 收件匣掃描中..."):
                    _rr = check_replies(days=30)
                if not _rr["ok"]:
                    st.warning(_rr["message"])
                elif _rr["new_replies"]:
                    st.success(_rr["message"] + "：" + "、".join(_rr["matched_emails"][:5]))
                    st.rerun()
                else:
                    st.info(_rr["message"])

        st.divider()

        # ── 信件分區：未打開 / 已打開 / 已點擊 ──
        st.markdown("#### 每封信的追蹤狀況")
        st.caption("依狀態分三區，點任一封展開看收件人、打開時間、點過的連結、信的內容")

        _all_logs = _ga_logs(limit=300)
        _tracked_logs = [l for l in _all_logs if l.get("tracking_uid")]

        if not _tracked_logs:
            st.info("還沒有帶追蹤碼的寄信紀錄。")
        else:
            # 一次抓所有 uid 的 events，分類
            _uid_list = [l["tracking_uid"] for l in _tracked_logs]
            _q_marks = ",".join("?" * len(_uid_list))
            from database.db import get_connection as _gc
            _ev_rows = _gc().execute(
                f"SELECT tracking_uid, event_type, occurred_at, target_url "
                f"FROM email_events WHERE tracking_uid IN ({_q_marks}) "
                f"ORDER BY occurred_at ASC",
                _uid_list,
            ).fetchall()
            _by_uid = {}
            for r in _ev_rows:
                _by_uid.setdefault(r["tracking_uid"], []).append(dict(r))

            _pending, _opened, _clicked = [], [], []
            for l in _tracked_logs:
                evs = _by_uid.get(l["tracking_uid"], [])
                has_click = any(e["event_type"] == "click" for e in evs)
                has_open  = any(e["event_type"] == "open"  for e in evs)
                entry = (l, evs)
                if has_click:
                    _clicked.append(entry)
                elif has_open:
                    _opened.append(entry)
                else:
                    _pending.append(entry)

            def _render_detail(_log, _evs):
                _opens  = [e for e in _evs if e["event_type"] == "open"]
                _clicks = [e for e in _evs if e["event_type"] == "click"]

                dcol1, dcol2, dcol3 = st.columns(3)
                dcol1.metric("被打開次數", len(_opens))
                dcol2.metric("連結被點次數", len(_clicks))
                dcol3.metric("狀態", "點過連結" if _clicks else ("已打開" if _opens else "尚未打開"))

                m_meta, m_body = st.columns([1, 2], gap="large")
                with m_meta:
                    st.markdown("**基本資訊**")
                    st.markdown(
                        f"- 寄出時間：{(_log.get('sent_at') or '')[:19].replace('T', ' ')}\n"
                        f"- 收件人：{_log.get('recipient_email', '—')}\n"
                        f"- 公司：{_log.get('cust_name') or '—'}\n"
                        f"- 模板：{_log.get('template_used') or '—'}\n"
                        f"- 主旨：{_log.get('subject') or '—'}\n"
                        f"- 寄件者：{_log.get('sent_by') or '—'}"
                    )
                    if _opens:
                        st.markdown("**打開時間**")
                        for _e in _opens[:20]:
                            st.caption("· " + (_e.get("occurred_at") or "")[:19].replace("T", " "))
                    if _clicks:
                        st.markdown("**點過的連結**")
                        for _e in _clicks[:20]:
                            _u = _e.get("target_url") or ""
                            _t = (_e.get("occurred_at") or "")[:16].replace("T", " ")
                            st.caption(f"· {_t}  —  {_u[:70]}")
                with m_body:
                    st.markdown("**信的內容**")
                    _body = _log.get("body_html")
                    if _body:
                        st.code(_body, language="html")
                    else:
                        st.caption("（系統沒存下這封信的內容）")

            def _render_section(title, entries, badge_color, hint):
                _n = len(entries)
                st.markdown(
                    f"<div class='analytics-section-title'>"
                    f"<span class='dot dot-{badge_color}'></span>"
                    f"{title}"
                    f"<span class='count-pill'>{_n}</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                if not entries:
                    st.caption(hint)
                    return
                for _log, _evs in entries:
                    _t = (_log.get("sent_at") or "")[:16].replace("T", " ")
                    _who = _log.get("cust_name") or _log.get("recipient_email", "—")
                    _sub = (_log.get("subject") or "")[:40]
                    _label = f"{_t}　·　{_who}　·　{_sub}"
                    with st.expander(_label, expanded=False):
                        _render_detail(_log, _evs)

            _sec_tabs = st.tabs([
                f"尚未打開 ({len(_pending)})",
                f"已打開 ({len(_opened)})",
                f"點過連結 ({len(_clicked)})",
            ])
            with _sec_tabs[0]:
                _render_section("尚未打開", _pending, "gray",
                                "目前每封信都至少被打開過了")
            with _sec_tabs[1]:
                _render_section("已打開（還沒點連結）", _opened, "blue",
                                "目前沒有「只打開沒點連結」的信")
            with _sec_tabs[2]:
                _render_section("點過連結（熱門客戶）", _clicked, "green",
                                "還沒有人點過你信裡的連結。模板裡要放連結才偵測得到。")


# ── TAB 5：Gmail 設定教學 ──
with tab_guide:
    st.markdown("""
    <style>
    .guide-wrap { max-width: 820px; margin: 0 auto; padding: 8px 0; }
    .guide-wrap h2 { font-size: 1.4rem; margin: 24px 0 8px; font-weight: 700; }
    .guide-wrap p  { font-size: 0.9rem; line-height: 1.8; opacity: 0.82; margin: 4px 0 8px; }
    .step-card {
        display: flex; gap: 20px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.10);
        border-left: 3px solid #3b82f6;
        border-radius: 12px;
        padding: 20px 24px;
        margin: 16px 0;
        animation: stepIn 500ms cubic-bezier(0.22,1,0.36,1) both;
    }
    .step-card:nth-child(1) { animation-delay: 0.05s; }
    .step-card:nth-child(2) { animation-delay: 0.2s; }
    .step-card:nth-child(3) { animation-delay: 0.35s; }
    .step-card:nth-child(4) { animation-delay: 0.5s; }
    .step-card:nth-child(5) { animation-delay: 0.65s; }
    @keyframes stepIn {
        from { opacity: 0; transform: translateX(-16px); }
        to   { opacity: 1; transform: translateX(0); }
    }
    .step-num {
        flex-shrink: 0;
        width: 40px; height: 40px;
        border-radius: 50%;
        background: linear-gradient(135deg, #3b82f6, #8b5cf6);
        color: #fff;
        font-weight: 800; font-size: 1.1rem;
        display: flex; align-items: center; justify-content: center;
        box-shadow: 0 4px 16px rgba(59,130,246,0.4);
    }
    .step-body { flex: 1; }
    .step-title { font-size: 1rem; font-weight: 700; margin-bottom: 4px; }
    .step-desc  { font-size: 0.86rem; line-height: 1.7; opacity: 0.75; }
    .step-desc code {
        background: rgba(59,130,246,0.15); color: #93c5fd;
        padding: 2px 8px; border-radius: 4px; font-size: 0.82rem;
    }
    .step-desc a { color: #60a5fa; text-decoration: none; border-bottom: 1px dashed #60a5fa; }
    .step-desc a:hover { color: #93c5fd; }
    .step-mock {
        margin-top: 10px;
        background: #0a0a0a;
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 8px;
        padding: 12px 14px;
        font-family: 'SF Mono','Consolas',monospace;
        font-size: 0.78rem;
    }
    .step-mock .mock-row {
        display: flex; justify-content: space-between; align-items: center;
        padding: 4px 0;
    }
    .step-mock .mock-row .lbl { opacity: 0.55; }
    .step-mock .mock-row .val { font-weight: 600; color: #93c5fd; }
    .alert-box {
        background: rgba(245,158,11,0.08);
        border-left: 3px solid #f59e0b;
        padding: 14px 18px;
        border-radius: 0 8px 8px 0;
        margin: 20px 0;
        font-size: 0.86rem; line-height: 1.8;
    }
    .alert-box.green {
        background: rgba(34,197,94,0.08);
        border-left-color: #22c55e;
    }
    .kbd-key {
        display: inline-block;
        background: rgba(255,255,255,0.12);
        border: 1px solid rgba(255,255,255,0.22);
        border-bottom-width: 2px;
        border-radius: 4px;
        padding: 1px 8px; font-size: 0.78rem;
        margin: 0 2px;
    }
    .pulse-arrow {
        display: inline-block; color: #3b82f6;
        animation: arrow-pulse 1.5s ease-in-out infinite;
    }
    @keyframes arrow-pulse {
        0%, 100% { transform: translateX(0); opacity: 0.6; }
        50%      { transform: translateX(4px); opacity: 1; }
    }
    </style>

    <div class="guide-wrap">

    <h2>📧 五步驟設定 Gmail 寄信</h2>
    <p style="opacity:0.6">不用 Gmail 登入密碼，用 Google 專門給程式用的<strong>「應用程式密碼」</strong>，更安全。</p>

    <div class="alert-box">
    ⚠️ <strong>重要前提：你的 Google 帳號必須先開啟兩步驟驗證</strong>，否則看不到「應用程式密碼」選項。
    </div>

    <div class="step-card">
      <div class="step-num">1</div>
      <div class="step-body">
        <div class="step-title">開啟兩步驟驗證</div>
        <div class="step-desc">
          前往 <a href="https://myaccount.google.com/security" target="_blank">myaccount.google.com/security</a>
          <span class="pulse-arrow">→</span>
          找到「兩步驟驗證」並啟用（用手機號碼/Google Authenticator 都可以）
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">2</div>
      <div class="step-body">
        <div class="step-title">建立應用程式密碼</div>
        <div class="step-desc">
          到 <a href="https://myaccount.google.com/apppasswords" target="_blank">myaccount.google.com/apppasswords</a>
          <br>名稱填 <code>LeadFlow</code> → 按「建立」
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">3</div>
      <div class="step-body">
        <div class="step-title">複製 16 位數密碼</div>
        <div class="step-desc">
          Google 會顯示一組 <strong>16 位英文字母密碼</strong>（不是你的登入密碼！）
        </div>
        <div class="step-mock">
          <div class="mock-row"><span class="lbl">您的應用程式密碼</span></div>
          <div class="mock-row" style="margin-top:6px">
            <span class="val" style="letter-spacing:3px;font-size:1.1rem">xxxx xxxx xxxx xxxx</span>
            <span style="font-size:0.7rem;opacity:0.5">← 複製這一串（有無空格都 OK）</span>
          </div>
        </div>
        <div class="step-desc" style="margin-top:8px;font-size:0.8rem;opacity:0.65">
          💡 Google 顯示的密碼為了好讀會有空格，<strong>不管你有沒有把空格拿掉，系統都會自動處理</strong>。
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">4</div>
      <div class="step-body">
        <div class="step-title">貼到系統的「Gmail 設定」</div>
        <div class="step-desc">
          切到「📨 開發信」分頁 → 展開「Gmail 設定」→ 填兩個欄位：
        </div>
        <div class="step-mock">
          <div class="mock-row">
            <span class="lbl">Gmail 帳號</span>
            <span class="val">your@gmail.com</span>
          </div>
          <div class="mock-row">
            <span class="lbl">應用程式密碼</span>
            <span class="val">xxxx xxxx xxxx xxxx</span>
          </div>
          <div class="mock-row">
            <span class="lbl">寄件人名稱</span>
            <span class="val">the client 業務部</span>
          </div>
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">5</div>
      <div class="step-body">
        <div class="step-title">測試連線 + 寄測試信給自己</div>
        <div class="step-desc">
          按「<strong>測試連線</strong>」確認綠色成功訊息 <span class="pulse-arrow">→</span>
          往下滾，每封信旁邊有「<strong>寄測試信</strong>」，填自己的 email 先寄一封看長相。
          <br>確認信件到自己信箱沒問題，才開始寄給客戶。
        </div>
      </div>
    </div>

    <div class="alert-box green">
    ✅ <strong>為什麼這樣設計？</strong>
    <br>&nbsp;&nbsp;• 不用把 Gmail 登入密碼交給系統（安全）
    <br>&nbsp;&nbsp;• 應用程式密碼可以隨時撤銷，不影響主帳號
    <br>&nbsp;&nbsp;• Google 官方推薦做法，支援 Workspace（企業 Gmail）
    </div>

    <h2 style="margin-top:32px">⭐ 強烈建議：升級 Google Workspace</h2>

    <div class="alert-box green">
    <b>為什麼要升級？</b><br>
    用 <code>@gmail.com</code> 寄開發信，客戶收到第一眼就知道「這是一般個人信箱」，開信率會掉 3 成。<br>
    用自有網域 <code>sales@leadgen.com</code>（Google Workspace），<b>送達率從 40% 飆升到 95%</b>，客戶信任度直接翻倍。
    </div>

    <div class="step-card">
      <div class="step-num">1</div>
      <div class="step-body">
        <div class="step-title">先有一個網域</div>
        <div class="step-desc">
          例如 <code>leadgen.com</code>。如果還沒有：
          <a href="https://gandi.net" target="_blank">Gandi</a> /
          <a href="https://cloudflare.com/products/registrar/" target="_blank">Cloudflare Registrar</a>
          註冊約 NT$400/年。
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">2</div>
      <div class="step-body">
        <div class="step-title">申請 Google Workspace</div>
        <div class="step-desc">
          到 <a href="https://workspace.google.com" target="_blank">workspace.google.com</a> 註冊 →
          選 <code>Business Starter</code>（<strong>每人 NT$180/月</strong>）→ 綁上你的網域
          <br>→ 建立第一個帳號，例如 <code>sales@leadgen.com</code>
        </div>
        <div class="step-mock">
          <div class="mock-row"><span class="lbl">完整帳號</span><span class="val">sales@leadgen.com</span></div>
          <div class="mock-row"><span class="lbl">初始密碼</span><span class="val">（註冊時自己設）</span></div>
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">3</div>
      <div class="step-body">
        <div class="step-title">驗證網域（DNS 設定）</div>
        <div class="step-desc">
          Google 會給你 1-4 筆 DNS 記錄（TXT / MX）貼到網域 DNS 後台，約 10-60 分鐘生效<br>
          建議一併設好 <code>SPF</code> + <code>DKIM</code> + <code>DMARC</code>（<b>信件不被標垃圾的關鍵</b>）<br>
          <a href="https://support.google.com/a/topic/2716885" target="_blank">官方設定教學 →</a>
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">4</div>
      <div class="step-body">
        <div class="step-title">新帳號設定兩步驟驗證 + App Password</div>
        <div class="step-desc">
          用 <code>sales@leadgen.com</code> 登入 Gmail → 照上面的「1-4 步」設定 App Password →
          填到這個系統的 Gmail 設定
        </div>
      </div>
    </div>

    <div class="step-card">
      <div class="step-num">5</div>
      <div class="step-body">
        <div class="step-title">寄件人名稱改得專業一點</div>
        <div class="step-desc">
          在系統「Gmail 設定」裡，「寄件人名稱」填 <code>the client 業務部</code><br>
          客戶信箱裡會顯示「<b>the client 業務部</b> &lt;sales@leadgen.com&gt;」— 比 <code>noron12334</code> 好太多
        </div>
      </div>
    </div>

    <div class="alert-box">
    💰 <b>成本比較</b>
    <br>&nbsp;&nbsp;• 免費 Gmail：$0／封，但 ~40% 進垃圾桶
    <br>&nbsp;&nbsp;• Workspace：NT$180/月，送達率 95%+，客戶信任度 UP
    <br>&nbsp;&nbsp;• 多買 1 個帳號可以讓業務 A 和業務 B 各自用自己的 email 寄信
    </div>

    <h2 style="margin-top:32px">🚫 避免信件被標 Spam</h2>
    <p>Gmail 2024/02 新規：大量寄信者要符合三個標準</p>
    <div class="step-card">
      <div class="step-num">✓</div>
      <div class="step-body">
        <div class="step-title">每日上限 50 封以內</div>
        <div class="step-desc">系統預設 100 封/日，建議先從 20-30 封開始（warmup），兩週後再拉到 50</div>
      </div>
    </div>
    <div class="step-card">
      <div class="step-num">✓</div>
      <div class="step-body">
        <div class="step-title">每封信間隔 2-5 秒</div>
        <div class="step-desc">系統已內建（逐封確認的模式天然避免）。不要一分鐘狂寄 10 封</div>
      </div>
    </div>
    <div class="step-card">
      <div class="step-num">✓</div>
      <div class="step-body">
        <div class="step-title">用 Google Workspace 更好</div>
        <div class="step-desc">自有網域 <code>sales@yourdomain.com</code> 比 <code>@gmail.com</code> 送達率高 10 倍，若要大量寄信建議升級（$6/月）</div>
      </div>
    </div>

    </div>
    """, unsafe_allow_html=True)


# ── TAB 5.5：資料安全（所有登入使用者都看得到，含客戶）──
with tab_backup:
    from database.db import get_server_backups as _gsb
    from datetime import datetime as _dt_bk, timedelta as _td_bk

    st.markdown("""
    <div class="section-header">
        <h3>🔒 您的客戶資料是怎麼被保護的</h3>
        <p class="section-sub">我們設了五層備份，每天自動跑、不靠任何人手動操作。下面是即時狀態。</p>
    </div>
    """, unsafe_allow_html=True)

    # ── 取最新備份時間 ──
    _server_backups = _gsb("/data/backups")
    _latest_server = _server_backups[0] if _server_backups else None

    # ── KPI 條 ──
    _now_bk = _dt_bk.now()
    if _latest_server:
        _hrs_since = _latest_server["age_hours"]
        if _hrs_since < 26:
            _status_emoji = "✅"
            _status_text = "正常"
            _status_color = "#22c55e"
        elif _hrs_since < 48:
            _status_emoji = "⚠️"
            _status_text = "稍微落後"
            _status_color = "#f59e0b"
        else:
            _status_emoji = "🚨"
            _status_text = "需要檢查"
            _status_color = "#ef4444"
    else:
        _status_emoji = "—"
        _status_text = "尚未備份"
        _status_color = "#71717a"
        _hrs_since = None

    bk_c1, bk_c2, bk_c3, bk_c4 = st.columns(4)
    bk_c1.metric("整體狀態", f"{_status_emoji} {_status_text}",
                 delta=f"{_hrs_since:.1f} 小時前" if _hrs_since is not None else "—",
                 delta_color="off")
    bk_c2.metric("server 端保留", f"{len(_server_backups)} 份",
                 delta="最近 7 天", delta_color="off")
    bk_c3.metric("已涵蓋業務名單", f"{db_stats.get('total', 0):,} 家")
    bk_c4.metric("整體資料安全", "5 層備份",
                 delta="多重防護", delta_color="off")

    st.markdown("---")

    # ── 五層防護視覺化 ──
    st.markdown("### 五層備份防護")
    _layers = [
        ("☁️", "Fly 雲端 volume 自動快照", "每天自動", "30 天", "Fly.io 內建，整顆儲存掛掉時可回滾"),
        ("📦", "Server 自動每日備份", "每天 04:00", "7 天", f"目前 {len(_server_backups)} 份（看下方明細）"),
        ("💻", "開發者 Mac 本機備份", "每天 18:00", "60 天", "本機 + iCloud 跨裝置同步"),
        ("🔗", "GitHub 雲端離站備份", "每天 10:00 AM", "60 天", "完全離開 Fly、不依賴開發者電腦"),
        ("📁", "原始資料夾備份", "手動觸發", "永久", "備份指令隨時可跑、即時取最新狀態"),
    ]
    for emoji, name, freq, retention, note in _layers:
        with st.container(border=True):
            cc1, cc2, cc3, cc4 = st.columns([0.5, 3, 2, 4])
            cc1.markdown(f"<div style='font-size:1.6rem;text-align:center'>{emoji}</div>", unsafe_allow_html=True)
            cc2.markdown(f"**{name}**")
            cc3.caption(f"頻率：{freq}　·　保留：{retention}")
            cc4.caption(note)

    st.markdown("---")

    # ── Server 端每日備份明細 ──
    st.markdown("### 📋 Server 自動每日備份明細")
    if _server_backups:
        bk_df = pd.DataFrame([
            {
                "備份檔案": b["file"],
                "備份時間": b["mtime_iso"][:16].replace("T", " "),
                "距現在":   f"{b['age_hours']:.1f} 小時前",
                "大小":     f"{b['size_kb']:.1f} KB",
                "狀態":     "✓" if b["age_hours"] < 26 + 24 * i else "—",
            }
            for i, b in enumerate(_server_backups[:14])
        ])
        st.dataframe(bk_df, use_container_width=True, hide_index=True,
                     height=min(450, 60 + 36 * len(bk_df)))
        st.caption("Server 端每天 04:00 由 scheduler 自動執行；只保留最近 7 天（節省空間，外面還有 4 層備份）")
    else:
        st.warning("⚠️ Server 端 `/data/backups/` 目前沒有任何備份檔。"
                   "若 scheduler 正常運作、明天 04:00 應該會出現第一份。")

    # ── 萬一出事怎麼救（給 Lin 看的、客戶看不懂沒關係）──
    if _is_admin:
        st.markdown("---")
        with st.expander("👑 出事時還原步驟（僅開發者）", expanded=False):
            st.markdown("""
            **情境 1：客戶不小心刪了一些公司 / 一筆寄信紀錄**

            ```bash
            # 拉昨天 04:00 的 server 端 snapshot 回本機看
            ~/.fly/bin/flyctl ssh sftp get /data/backups/leads-YYYY-MM-DD_0400.db --app leadgen-app
            # 開來看 → 確認沒問題 → 推回 prod 蓋過
            ~/.fly/bin/flyctl scale count 0 --app leadgen-app --yes  # 停 app
            ~/.fly/bin/flyctl ssh sftp put leads.db /data/leads.db --app leadgen-app
            ~/.fly/bin/flyctl scale count 1 --app leadgen-app --region nrt --yes
            ```

            **情境 2：Fly volume 整顆壞掉**

            ```bash
            # 用 Fly 內建 snapshot 還原（30 天內任一天）
            ~/.fly/bin/flyctl volumes list --app leadgen-app
            ~/.fly/bin/flyctl volumes snapshots list <vol-id>
            ~/.fly/bin/flyctl volumes fork --snapshot-id <snap-id> ...
            ```

            **情境 3：Fly 整個帳號 / 公司倒了**

            ```bash
            # 從 GitHub backups/ 拉最新 .tar.gz
            git clone https://github.com/your-contact4/waiting-list.git
            tar xzf waiting-list/backups/leadflow-prod/leadflow_prod_*.tar.gz
            # 在 Render / Railway / Heroku 新建一個 Fly-like app，把 leads.db 放到 /data/
            # Update DNS → 完成搬家
            ```

            **完整 SOP**：`feature1_lead_scraper/docs/internal/BACKUP_SOP.md`
            """)

    # ── 給客戶看的友善說明 ──
    st.markdown("---")
    st.markdown("### 💬 給您的承諾")
    st.markdown("""
    <div style="background:rgba(34,197,94,0.05);border-left:3px solid #22c55e;padding:14px 18px;border-radius:8px;font-size:0.92rem;line-height:1.65;">
    我們知道業務名單、寄信記錄、開信點擊資料是您每天累積的成果，不能說沒就沒。<br>
    所以我們不是只做一次備份，而是把備份散在 <b>五個不同的地方</b>（雲端硬碟自動快照、Server 自帶副本、開發者本機、iCloud、GitHub）。<br>
    每一份每天自動更新，任何一層出事，其他四層還在。<br>
    您不需要做任何事 — 系統幫您顧好。
    </div>
    """, unsafe_allow_html=True)


# ── TAB 6：管理後台（僅 superadmin）──
if tab_admin is not None:
    with tab_admin:
        st.markdown("""
        <div class="section-header">
            <h3>👑 管理後台　<span class="badge" style="background:rgba(251,191,36,0.15);color:#fbbf24;border-color:rgba(251,191,36,0.3)">僅開發者可見</span></h3>
            <span class="desc">追蹤所有使用者活動、管理帳號、數據儀表板</span>
        </div>
        """, unsafe_allow_html=True)

        from database.db import (
            get_user_stats, get_activity_log, get_user_email_breakdown,
            get_stats as _db_stats, get_all_companies as _all_c,
        )
        import yaml as _yaml
        from collections import Counter
        from datetime import datetime, timedelta

        _admin_tabs = st.tabs(["📊 儀表板", "👥 帳號管理", "📝 活動紀錄", "⚠️ 危險區"])

        # ──────── 1. 儀表板 ────────
        with _admin_tabs[0]:
            # ── 目前在線 ──
            from database.db import get_online_users as _gou_admin
            _now_online = _gou_admin()
            st.markdown("#### 目前在線")
            if _now_online:
                online_df = pd.DataFrame([
                    {
                        "使用者":     u["username"],
                        "最後活動":   (u.get("last_heartbeat") or "")[:19].replace("T", " "),
                        "目前頁面":   u.get("current_page") or "—",
                    }
                    for u in _now_online
                ])
                st.dataframe(online_df, use_container_width=True, hide_index=True,
                             height=min(260, 50 + 36 * len(online_df)))
                st.caption(f"共 {len(online_df)} 人 · 3 分鐘內有活動算在線（沒人按按鈕只是看頁面也會超時）")
            else:
                st.info("目前只有你登入。其他人沒上線或閒置超過 3 分鐘。")

            st.markdown("---")

            s = _db_stats()
            all_comps = _all_c()
            user_email = get_user_email_breakdown()

            # 本週活躍度
            logs_all = get_activity_log(limit=2000)
            now_dt = datetime.now()
            week_ago = (now_dt - timedelta(days=7)).isoformat()

            week_logs = [l for l in logs_all if (l.get("occurred_at") or "") >= week_ago]
            week_senders = Counter(l["username"] for l in week_logs if l.get("action") == "send_email")
            week_crawlers = Counter(l["username"] for l in week_logs if l.get("action") == "crawl")
            total_sent_week = sum(week_senders.values())
            total_crawl_week = sum(week_crawlers.values())

            mc1, mc2, mc3, mc4 = st.columns(4)
            mc1.metric("資料庫公司總數", f"{s['total']:,}", f"有 email {s['has_email']}")
            mc2.metric("本週寄信數",     total_sent_week, f"{len(week_senders)} 人活躍")
            mc3.metric("本週搜尋次數",   total_crawl_week, f"{len(week_crawlers)} 人操作")
            mc4.metric("總活動筆數",     f"{len(logs_all):,}", "最近 2000 筆")

            st.markdown("---")

            # 各使用者寄信成效圖表
            st.markdown("#### 各業務員寄信成效")
            if user_email:
                _df = pd.DataFrame([
                    {
                        "使用者":   u["username"],
                        "寄出":     u["sent"],
                        "開信":     u["opened"] or 0,
                        "開信率":   u["open_rate"],
                    }
                    for u in user_email
                ])
                col_c, col_t = st.columns([2, 3])
                with col_c:
                    st.bar_chart(_df.set_index("使用者")[["寄出", "開信"]], height=260)
                with col_t:
                    _df_display = _df.copy()
                    _df_display["開信率"] = _df_display["開信率"].map(lambda x: f"{x}%")
                    st.dataframe(_df_display, use_container_width=True, hide_index=True,
                                 height=260)
            else:
                st.info("還沒有人寄信")

            st.markdown("#### 各業務員找到的公司數")
            crawler_count = Counter(c.get("crawled_by") or "（未標記）" for c in all_comps)
            if crawler_count:
                cr_df = pd.DataFrame(
                    [{"使用者": k, "爬到的公司數": v}
                     for k, v in crawler_count.most_common()]
                )
                col_a, col_b = st.columns([2, 3])
                with col_a:
                    st.bar_chart(cr_df.set_index("使用者"), height=220)
                with col_b:
                    st.dataframe(cr_df, use_container_width=True, hide_index=True, height=220)

            st.markdown("#### 📅 本週每日活動（動作類型）")
            day_action = Counter(
                (l.get("occurred_at", "")[:10], l.get("action", ""))
                for l in week_logs
            )
            if day_action:
                dates = sorted({d for d, _ in day_action.keys()})
                actions = sorted({a for _, a in day_action.keys()})
                trend_df = pd.DataFrame(
                    {a: [day_action.get((d, a), 0) for d in dates] for a in actions},
                    index=dates,
                )
                st.line_chart(trend_df, height=240)
            else:
                st.caption("本週還沒有活動")

            # ── 📨 最近寄信明細（誰寄給誰、開了沒） ──
            st.markdown("---")
            st.markdown("#### 📨 最近寄信明細")
            from database.db import get_email_logs as _gel_admin, get_connection as _gc_admin
            _admin_logs = _gel_admin(limit=100)
            _admin_real = [l for l in _admin_logs if l.get("status") in ("sent", "failed")]
            if _admin_real:
                # 算誰開了 / 點了（套用 prefetch filter — 寄出 <10s 不算真開）
                _uids = [l["tracking_uid"] for l in _admin_real if l.get("tracking_uid")]
                _opened, _clicked = set(), set()
                if _uids:
                    _ph = ",".join("?" * len(_uids))
                    _ev_rows = _gc_admin().execute(
                        f"""SELECT ev.tracking_uid, ev.event_type, ev.user_agent,
                                   ev.occurred_at, el.sent_at
                            FROM email_events ev
                            LEFT JOIN email_logs el ON ev.tracking_uid = el.tracking_uid
                            WHERE ev.tracking_uid IN ({_ph})""",
                        _uids,
                    ).fetchall()
                    for _u, _ev, _ua, _occ, _sent in _ev_rows:
                        if _ev == "click":
                            _clicked.add(_u); _opened.add(_u)
                        else:
                            try:
                                _d = (datetime.fromisoformat(_occ) - datetime.fromisoformat(_sent)).total_seconds()
                            except Exception:
                                _d = 9999
                            _ua_l = (_ua or "").lower()
                            if _d >= 10 and not (_d < 60 and "googleimageproxy" in _ua_l):
                                _opened.add(_u)

                _admin_send_df = pd.DataFrame([
                    {
                        "時間":   (l.get("sent_at") or "")[:16].replace("T", " "),
                        "寄件者": l.get("sent_by") or "—",
                        "公司":   l.get("cust_name") or (f"ID:{l.get('company_id')}" if l.get("company_id") else "—"),
                        "收件人": l.get("recipient_email") or "",
                        "範本":   l.get("template_used") or "—",
                        "結果":   "✅ 成功" if l.get("status") == "sent" else "❌ 失敗",
                        "開信":   "✓" if l.get("tracking_uid") in _opened else "",
                        "點連結": "✓" if l.get("tracking_uid") in _clicked else "",
                    }
                    for l in _admin_real[:50]
                ])
                st.dataframe(_admin_send_df, use_container_width=True, hide_index=True,
                             height=min(400, 60 + 36 * len(_admin_send_df)))
                st.caption(f"顯示最近 {len(_admin_send_df)} 筆（共 {len(_admin_real)} 筆正式寄信）")
            else:
                st.info("還沒有正式寄信紀錄")

        # ──────── 2. 帳號管理 ────────
        with _admin_tabs[1]:
            st.markdown("#### 新增業務員帳號")
            st.caption("新帳號會直接寫入 `users.yaml`（姓名必填，系統顯示用）")

            with st.form("add_user_form", clear_on_submit=True):
                ac1, ac2 = st.columns(2)
                with ac1:
                    new_uname = st.text_input(
                        "帳號（英文）", placeholder="例：sales3",
                        help="只能英數底線，登入用"
                    )
                with ac2:
                    new_name = st.text_input(
                        "姓名（會顯示在系統上）", placeholder="例：張小美"
                    )
                ac3, ac4 = st.columns(2)
                with ac3:
                    new_email = st.text_input("Email", placeholder="sales3@leadgen.com")
                with ac4:
                    new_pwd = st.text_input("初始密碼", placeholder="至少 6 字",
                                            type="password")
                submit_add = st.form_submit_button("➕ 建立帳號", type="primary",
                                                     use_container_width=True)

            if submit_add:
                errs = []
                if not new_uname or not new_uname.replace("_", "").isalnum():
                    errs.append("帳號只能英數底線")
                if not new_name.strip():
                    errs.append("姓名必填")
                if not new_email or "@" not in new_email:
                    errs.append("Email 格式錯誤")
                if len(new_pwd) < 6:
                    errs.append("密碼至少 6 字")

                try:
                    import bcrypt as _bc, yaml as _yl
                    with open("users.yaml", encoding="utf-8") as f:
                        _conf = _yl.safe_load(f)
                    if new_uname in _conf["credentials"]["usernames"]:
                        errs.append(f"帳號 {new_uname} 已存在")
                except Exception as e:
                    errs.append(f"讀取 users.yaml 失敗：{e}")

                if errs:
                    for e in errs:
                        st.error(e)
                else:
                    pwd_hash = _bc.hashpw(new_pwd.encode(), _bc.gensalt(12)).decode()
                    _conf["credentials"]["usernames"][new_uname] = {
                        "name": new_name.strip(),
                        "email": new_email.strip(),
                        "role": "user",
                        "password": pwd_hash,
                    }
                    with open("users.yaml", "w", encoding="utf-8") as f:
                        _yl.dump(_conf, f, allow_unicode=True, sort_keys=False)
                    st.success(f"✅ 帳號 {new_uname}（{new_name}）已建立")
                    try:
                        from database.db import log_activity
                        log_activity(st.session_state.get("username", "baralla"),
                                     "admin_add_user",
                                     f"新增使用者 {new_uname} ({new_name})")
                    except Exception:
                        pass
                    st.rerun()

            st.markdown("---")
            st.markdown("#### 現有帳號（可啟用 / 停用）")
            st.caption("取消勾選 = 停用帳號，該使用者無法登入且正在使用中的會被踢出")
            try:
                with open("users.yaml", encoding="utf-8") as f:
                    _conf_now = _yaml.safe_load(f)
                _users = _conf_now["credentials"]["usernames"]

                users_df = pd.DataFrame([
                    {
                        "帳號":   uname,
                        "姓名":   d.get("name", ""),
                        "Email":  d.get("email", ""),
                        "角色":   d.get("role", "user"),
                        "啟用":   bool(d.get("enabled", True)),
                    }
                    for uname, d in _users.items()
                ])
                edited_users = st.data_editor(
                    users_df,
                    use_container_width=True, hide_index=True,
                    height=min(320, 60 + 35 * len(users_df)),
                    disabled=["帳號", "姓名", "Email", "角色"],
                    column_config={
                        "啟用": st.column_config.CheckboxColumn(
                            "啟用", help="取消勾選 = 停用帳號（該使用者無法登入）"
                        ),
                    },
                    key="users_editor",
                )
                # 檢查變更、寫回 yaml
                changed = False
                for _, row in edited_users.iterrows():
                    u = row["帳號"]
                    new_state = bool(row["啟用"])
                    if _users[u].get("enabled", True) != new_state:
                        _users[u]["enabled"] = new_state
                        changed = True
                if changed:
                    with open("users.yaml", "w", encoding="utf-8") as f:
                        _yaml.dump(_conf_now, f, allow_unicode=True, sort_keys=False)
                    st.success("帳號狀態已更新")
                    try:
                        from database.db import log_activity
                        log_activity(st.session_state.get("username",""),
                                     "admin_toggle_user", "更新帳號啟用狀態")
                    except Exception:
                        pass
                    st.rerun()
            except Exception as e:
                st.error(f"讀取失敗：{e}")

            # ── 協作鎖管理 ──
            st.markdown("---")
            st.markdown("#### 🔓 協作鎖狀態")
            st.caption("卡住時可強制解除")
            from database.db import get_lock_holder as _glh2, admin_force_release_lock
            lc1, lc2 = st.columns(2)
            for i, (lock, col) in enumerate([("crawl", lc1), ("email", lc2)]):
                with col:
                    h = _glh2(lock)
                    label = "搜尋中" if lock == "crawl" else "寄信中"
                    if h:
                        st.markdown(
                            f'<div style="background:rgba(245,158,11,0.08);border:1px solid rgba(245,158,11,0.3);'
                            f'border-radius:8px;padding:10px 14px;font-size:0.82rem">'
                            f'🔒 <b>{label}</b><br>'
                            f'<span style="opacity:0.65">持有者：<b>{h["locked_by"]}</b></span><br>'
                            f'<span style="opacity:0.5;font-size:0.72rem">'
                            f'{h["acquired_at"][:16].replace("T"," ")} ~ {h["expires_at"][:16].replace("T"," ")}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                        if st.button(f"💥 強制釋放 {label}", key=f"force_release_{lock}",
                                     use_container_width=True):
                            admin_force_release_lock(lock)
                            st.success(f"{label} 已釋放")
                            st.rerun()
                    else:
                        st.markdown(
                            f'<div style="background:rgba(34,197,94,0.06);border:1px solid rgba(34,197,94,0.25);'
                            f'border-radius:8px;padding:10px 14px;font-size:0.82rem">'
                            f'🟢 <b>{label}</b>　空閒'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

        # ──────── 3. 活動紀錄 ────────
        with _admin_tabs[2]:
            fcol1, fcol2 = st.columns([2, 1])
            with fcol1:
                filter_user = st.text_input(
                    "篩選使用者（留空 = 全部）", value="", key="admin_filter_user",
                    placeholder="例：sales1"
                )
            with fcol2:
                if st.button("🔄 重整", key="admin_refresh", use_container_width=True):
                    st.rerun()

            logs = get_activity_log(limit=200, username=filter_user.strip())
            if logs:
                ACTION_ICON = {
                    "login": "登入",
                    "crawl": "找客戶",
                    "send_email": "寄信",
                    "export": "匯出",
                    "admin_add_user": "新增使用者",
                    "scan_web": "找 email",
                    "verify_email": "驗 email",
                    "clear_db": "清資料庫",
                }
                logs_df = pd.DataFrame([
                    {
                        "時間":    (l.get("occurred_at") or "")[:19].replace("T", " "),
                        "使用者": l.get("username", ""),
                        "動作":    ACTION_ICON.get(l.get("action", ""), l.get("action", "")),
                        "說明":    l.get("detail", ""),
                    }
                    for l in logs
                ])
                st.dataframe(logs_df, use_container_width=True, hide_index=True,
                             height=520)
                st.caption(f"顯示最近 {len(logs)} 筆（最新在最上）")
            else:
                st.info("目前沒有活動紀錄")

        # ──────── 4. 危險區 ────────
        with _admin_tabs[3]:
            st.warning("⚠️ 以下操作不可復原，請謹慎")
            dz1, dz2 = st.columns(2)

            with dz1:
                if st.button("清空所有活動紀錄", key="admin_clear_activity",
                             use_container_width=True):
                    from database.db import get_connection
                    get_connection().execute("DELETE FROM activity_log")
                    get_connection().commit()
                    st.success("已清空活動紀錄")
                    st.rerun()

            with dz2:
                if st.button("清空所有寄信紀錄", key="admin_clear_emails",
                             use_container_width=True):
                    from database.db import get_connection as _gc_ae
                    _c = _gc_ae()
                    _c.execute("DELETE FROM email_events")
                    _c.execute("DELETE FROM email_logs")
                    _c.commit()
                    st.success("已清空寄信紀錄與追蹤事件")
                    st.rerun()

            st.divider()
            st.markdown("**整個資料庫清空（重置系統）**")
            st.caption("包含：所有公司、所有寄信紀錄、所有追蹤事件、熱門標記。爬蟲、活動紀錄、帳號不動。")

            _confirm_key = "admin_wipe_confirm"
            _confirm = st.text_input(
                "要清空全部資料，在這格輸入「WIPE」確認",
                key=_confirm_key,
                placeholder="輸入 WIPE 才會啟用下面的按鈕",
            )
            if st.button(
                "清空整個資料庫",
                key="admin_wipe_all",
                type="primary",
                disabled=(_confirm.strip().upper() != "WIPE"),
                use_container_width=True,
            ):
                from database.db import clear_all as _wipe_all, log_activity as _la
                _wipe_all()
                _la(st.session_state.get("username", ""), "wipe_db", "清空整個資料庫")
                st.session_state.last_run_result = None
                st.session_state[_confirm_key] = ""
                st.success("資料庫已清空。")
                st.rerun()


# ── Footer ──
st.markdown("""
<div class="app-footer">
    LeadFlow v3.0　·　此系統由 <b>次元創意有限公司</b> 製作　·　CTO 林均融（芭樂）
    &nbsp;·&nbsp; 使用問題請聯絡 Email：<b>your@email.com</b>
    &nbsp;·&nbsp; Powered by Python &amp; Streamlit
</div>
""", unsafe_allow_html=True)
