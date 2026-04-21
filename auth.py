"""
登入認證模組（B2B 名單開發系統）
- streamlit-authenticator
- Session-based + Cookie 持久化
- bcrypt hashed passwords
- 登入前顯示品牌封面
"""
import streamlit as st
import yaml
from pathlib import Path

_AUTH_FILE = Path(__file__).parent / "users.yaml"


def _render_login_hero():
    """the client登入封面（hueapp.io 風格）"""
    st.markdown(
        """
        <link href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300..900;1,300..900&family=Noto+Sans+TC:wght@400;700;900&display=swap" rel="stylesheet">

        <style>
        /* ─── 全域深色底 + 頂部光暈 ─── */
        [data-testid="stAppViewContainer"] {
            background:
                radial-gradient(ellipse 80% 60% at 50% -20%,
                    rgba(251, 191, 36, 0.18) 0%,
                    rgba(239, 68, 68, 0.08) 28%,
                    transparent 60%),
                radial-gradient(circle at 85% 75%,
                    rgba(139, 92, 246, 0.07) 0%,
                    transparent 40%),
                radial-gradient(circle at 15% 85%,
                    rgba(59, 130, 246, 0.05) 0%,
                    transparent 40%),
                #0D0E12 !important;
        }

        /* DM Sans 沒中文字，必須 Noto Sans TC 放前面讓中文走台灣字型 */
        html, body, [class*="css"] {
            font-family: 'Noto Sans TC', 'DM Sans', -apple-system,
                         "PingFang TC", "Microsoft JhengHei", sans-serif !important;
        }

        /* Hide Streamlit chrome */
        #MainMenu, footer, [data-testid="stHeader"] { visibility: hidden; }

        /* ─── Hero ─── */
        .login-hero {
            max-width: 520px;
            margin: 60px auto 28px;
            text-align: center;
            animation: heroIn 700ms cubic-bezier(0.22, 1, 0.36, 1);
        }
        @keyframes heroIn {
            from { opacity: 0; transform: translateY(-16px); filter: blur(8px); }
            to   { opacity: 1; transform: translateY(0);    filter: blur(0); }
        }

        /* 浮空 icon — 模仿 hue 的膠囊 logo */
        .login-logo-wrap {
            position: relative;
            display: inline-block;
            margin-bottom: 24px;
        }
        .login-logo {
            width: 64px; height: 64px;
            border-radius: 20px;
            background: linear-gradient(135deg,
                #fbbf24 0%,
                #f59e0b 40%,
                #ef4444 100%);
            box-shadow:
                0 0 40px rgba(251, 191, 36, 0.45),
                0 0 80px rgba(239, 68, 68, 0.25),
                inset 0 1px 2px rgba(255, 255, 255, 0.35);
            display: inline-flex;
            align-items: center; justify-content: center;
            font-size: 2rem;
            position: relative;
            z-index: 1;
            animation: logo-float 4s ease-in-out infinite;
        }
        @keyframes logo-float {
            0%, 100% { transform: translateY(0) rotate(0); }
            50%      { transform: translateY(-6px) rotate(2deg); }
        }
        /* logo 光暈 */
        .login-logo-wrap::before {
            content: '';
            position: absolute;
            inset: -30px;
            background: radial-gradient(circle,
                rgba(251, 191, 36, 0.4) 0%,
                rgba(239, 68, 68, 0.2) 40%,
                transparent 70%);
            filter: blur(24px);
            z-index: 0;
            animation: logo-pulse 3s ease-in-out infinite;
        }
        @keyframes logo-pulse {
            0%, 100% { opacity: 0.6; transform: scale(1); }
            50%      { opacity: 1;   transform: scale(1.15); }
        }

        /* 品牌文字 */
        .login-brand-name {
            font-family: 'DM Sans', sans-serif;
            font-size: 0.78rem;
            font-weight: 500;
            letter-spacing: 0.14em;
            color: rgba(255, 255, 255, 0.55);
            text-transform: lowercase;
            margin-bottom: 8px;
        }
        .login-headline {
            font-family: 'Noto Sans TC', 'DM Sans', "PingFang TC",
                         "Microsoft JhengHei", sans-serif;
            font-size: 2.8rem;
            font-weight: 900;        /* 中文字型用 900 才夠重 */
            line-height: 1.25;
            letter-spacing: -0.02em;
            color: #ffffff;           /* 純白，對比拉滿 */
            margin: 0 0 18px;
            text-shadow: 0 2px 24px rgba(0, 0, 0, 0.4);
        }
        .login-headline .accent {
            display: inline-block;
            background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 45%, #ef4444 100%);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            /* 給漸層文字一層底光 */
            filter: drop-shadow(0 0 12px rgba(251, 191, 36, 0.25));
        }
        .login-subline {
            font-size: 0.85rem;
            font-weight: 400;
            color: rgba(255, 255, 255, 0.5);
            line-height: 1.8;
            max-width: 460px;
            margin: 0 auto 24px;
            display: flex;
            flex-wrap: wrap;
            justify-content: center;
            gap: 6px 12px;
        }
        .login-subline .feat {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 10px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 100px;
            font-size: 0.78rem;
            white-space: nowrap;
            transition: border-color 200ms, background 200ms;
        }
        .login-subline .feat:hover {
            border-color: rgba(251, 191, 36, 0.3);
            background: rgba(251, 191, 36, 0.04);
        }
        .login-badge {
            display: inline-flex;
            align-items: center; gap: 6px;
            font-size: 0.7rem; font-weight: 500;
            letter-spacing: 0.08em;
            color: rgba(147, 197, 253, 0.85);
            background: rgba(59, 130, 246, 0.06);
            border: 1px solid rgba(59, 130, 246, 0.18);
            border-radius: 100px;
            padding: 5px 12px;
            text-transform: uppercase;
        }
        .login-badge::before {
            content: '';
            width: 5px; height: 5px;
            border-radius: 50%;
            background: #22c55e;
            box-shadow: 0 0 8px rgba(34, 197, 94, 0.6);
            animation: dot-pulse 2s ease-in-out infinite;
        }
        @keyframes dot-pulse {
            0%, 100% { opacity: 1; }
            50%      { opacity: 0.4; }
        }

        /* ─── 主內容置中（雙保險：main block + form 外層 column）─── */
        [data-testid="stMainBlockContainer"],
        .main .block-container,
        [data-testid="stAppViewContainer"] > .main {
            padding-top: 20px !important;
            padding-bottom: 40px !important;
            max-width: 640px !important;
            margin: 0 auto !important;
        }
        /* 整個 Streamlit root 容器也強制置中 */
        [data-testid="stAppViewContainer"] > section.main {
            display: flex !important;
            flex-direction: column !important;
            align-items: center !important;
        }

        /* ─── 登入表單 ─── */
        [data-testid="stForm"] {
            max-width: 420px;
            width: 100%;
            margin-left: auto !important;
            margin-right: auto !important;
            background: rgba(255, 255, 255, 0.025);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 18px;
            padding: 32px 36px !important;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.4);
            animation: formIn 800ms cubic-bezier(0.22, 1, 0.36, 1) 200ms both;
        }
        /* Streamlit 會把 form 包在 column 裡，強制 column 也置中 */
        [data-testid="stForm"] > div {
            display: flex;
            flex-direction: column;
            gap: 14px;
        }
        /* 隱藏 Streamlit 自動產生的 Login 標題（我們自己提供 hero） */
        [data-testid="stForm"] > div > [data-testid="stMarkdownContainer"]:first-child h2,
        [data-testid="stForm"] > div > [data-testid="stMarkdownContainer"]:first-child h3 {
            text-align: center !important;
            font-size: 1rem !important;
            font-weight: 600 !important;
            color: rgba(255,255,255,0.7) !important;
            margin: 0 0 8px !important;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        @keyframes formIn {
            from { opacity: 0; transform: translateY(20px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        /* 表單 input 統一風格 */
        [data-testid="stForm"] input {
            background: rgba(255, 255, 255, 0.04) !important;
            border: 1px solid rgba(255, 255, 255, 0.08) !important;
            border-radius: 10px !important;
            color: #ebecef !important;
            padding: 10px 14px !important;
            font-size: 0.92rem !important;
            transition: border-color 200ms, background 200ms !important;
        }
        [data-testid="stForm"] input:focus {
            border-color: rgba(251, 191, 36, 0.4) !important;
            background: rgba(255, 255, 255, 0.06) !important;
            outline: none !important;
            box-shadow: 0 0 0 3px rgba(251, 191, 36, 0.08) !important;
        }
        [data-testid="stForm"] label {
            font-size: 0.75rem !important;
            font-weight: 500 !important;
            color: rgba(255, 255, 255, 0.55) !important;
            letter-spacing: 0.04em !important;
            text-transform: uppercase;
        }

        /* Submit 按鈕：漸層、有光暈 */
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button {
            width: 100%;
            background: linear-gradient(135deg, #fbbf24 0%, #f59e0b 50%, #ef4444 100%) !important;
            color: #0D0E12 !important;
            border: none !important;
            font-weight: 700 !important;
            font-size: 0.92rem !important;
            padding: 12px 20px !important;
            border-radius: 12px !important;
            letter-spacing: 0.02em;
            box-shadow: 0 10px 30px rgba(251, 191, 36, 0.25),
                        0 0 0 1px rgba(255, 255, 255, 0.1) inset !important;
            transition: transform 200ms cubic-bezier(0.22, 1, 0.36, 1),
                        box-shadow 200ms !important;
        }
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:hover {
            transform: translateY(-2px) !important;
            box-shadow: 0 16px 40px rgba(251, 191, 36, 0.4),
                        0 0 0 1px rgba(255, 255, 255, 0.15) inset !important;
        }
        [data-testid="stForm"] [data-testid="stFormSubmitButton"] button:active {
            transform: scale(0.98) !important;
        }

        /* 表單標題 "Login" */
        [data-testid="stForm"] h2,
        [data-testid="stForm"] h3 {
            display: none;  /* 隱藏 streamlit 預設 Login 標題 */
        }
        </style>

        <div class="login-hero">
            <div class="login-logo-wrap">
                <div class="login-logo">🥨</div>
            </div>
            <div class="login-brand-name">leadgen</div>
            <h1 class="login-headline">
                the client<br>
                <span class="accent">業務開發</span>就此升級
            </h1>
            <p class="login-subline">
                <span class="feat">🎯 104 / Cake / Yourator 自動採集</span>
                <span class="feat">✉️ Gmail 批次寄送開發信</span>
                <span class="feat">📊 即時追蹤開信點擊</span>
            </p>
            <div class="login-badge">LEADFLOW v3.0 — Online</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_login_footer():
    """登入頁底部次元創意開發字樣（hueapp 風）"""
    st.markdown(
        """
        <style>
        .login-credits {
            max-width: 520px;
            margin: 48px auto 20px;
            text-align: center;
            font-size: 0.72rem;
            line-height: 2;
            color: rgba(255, 255, 255, 0.32);
            font-family: 'DM Sans', 'Noto Sans TC', sans-serif;
            animation: creditsIn 1000ms cubic-bezier(0.22, 1, 0.36, 1) 400ms both;
        }
        @keyframes creditsIn {
            from { opacity: 0; }
            to   { opacity: 1; }
        }
        .login-credits .dot {
            display: inline-block;
            margin: 0 8px;
            opacity: 0.3;
        }
        .login-credits b {
            color: rgba(255, 255, 255, 0.55);
            font-weight: 500;
        }
        .login-credits a {
            color: #93c5fd;
            text-decoration: none;
            border-bottom: 1px solid transparent;
            transition: border-color 200ms;
        }
        .login-credits a:hover {
            border-bottom-color: #93c5fd;
        }
        .login-divider-mini {
            width: 1px; height: 14px;
            background: rgba(255, 255, 255, 0.15);
            display: inline-block;
            margin: 0 14px -3px;
        }
        </style>

        <div class="login-credits">
            Designed &amp; built by <b>次元創意有限公司</b>
            <span class="login-divider-mini"></span>
            CTO <b>林均融</b>（芭樂）
            <span class="login-divider-mini"></span>
            Email <b>your@email.com</b>
            <br>
            <span style="opacity:0.5">© 2026 LeadGen</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def check_auth() -> bool:
    """
    檢查使用者是否已登入。
    若未登入，顯示品牌登入頁並 st.stop()。
    回傳 True 表示已通過認證。
    """
    from config import AUTH_ENABLED

    if not AUTH_ENABLED:
        return True

    try:
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("請安裝 streamlit-authenticator：`pip install streamlit-authenticator`")
        st.stop()
        return False

    if not _AUTH_FILE.exists():
        st.warning("尚未設定帳號，請建立 `users.yaml`。目前暫時跳過登入。")
        return True

    with open(_AUTH_FILE, encoding="utf-8") as f:
        auth_config = yaml.safe_load(f)

    authenticator = stauth.Authenticate(
        auth_config["credentials"],
        auth_config["cookie"]["name"],
        auth_config["cookie"]["key"],
        auth_config["cookie"]["expiry_days"],
    )

    # 已登入 → 存 role / 顯示使用者資訊 + 登出按鈕
    if st.session_state.get("authentication_status"):
        uname = st.session_state.get("username", "")
        udata = auth_config["credentials"]["usernames"].get(uname, {})
        st.session_state["user_role"] = udata.get("role", "user")
        st.session_state["user_display_name"] = udata.get("name", uname)

        # 檢查帳號是否啟用（admin 可停用帳號，被停用者登入也會被踢出）
        if udata.get("enabled", True) is False:
            authenticator.logout(location="unrendered")  # 清掉登入狀態
            st.error(
                f"⛔ 帳號「{udata.get('name', uname)}」已被停用，"
                f"請聯繫管理員（Email: your@email.com）"
            )
            st.stop()
            return False

        # 心跳：每次 rerun 寫一次，讓其他人知道我在線上
        try:
            from database.db import heartbeat as _hb
            _hb(uname, page=st.session_state.get("_current_page", ""))
        except Exception:
            pass

        # 記錄登入活動（只在首次 rerun 記錄，避免重複）
        if not st.session_state.get("_logged_activity"):
            try:
                from database.db import log_activity
                log_activity(uname, "login", f"登入：{udata.get('name','')}")
                st.session_state["_logged_activity"] = True
            except Exception:
                pass

        with st.sidebar:
            st.markdown(
                f"""
                <div style="padding: 8px 12px; background: rgba(34,197,94,0.08);
                            border-left: 3px solid #22c55e; border-radius: 0 6px 6px 0;
                            margin-bottom: 10px;">
                    <div style="font-size: 0.7rem; opacity: 0.5;">目前使用者</div>
                    <div style="font-size: 0.9rem; font-weight: 700;">
                        {st.session_state.get('name', '')}
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            authenticator.logout("登出", key="logout_btn")
        return True

    # 未登入 → 顯示封面 + 登入表單
    _render_login_hero()
    authenticator.login(location="main")
    _render_login_footer()

    if st.session_state.get("authentication_status") is False:
        st.error("帳號或密碼錯誤")
        st.stop()
        return False
    else:
        # None = 未嘗試登入，仍顯示表單
        st.stop()
        return False
