"""
登入認證模組
- streamlit-authenticator
- Session-based + Cookie 持久化
- bcrypt hashed passwords
"""
import streamlit as st
import yaml
from pathlib import Path

_AUTH_FILE = Path(__file__).parent / "users.yaml"


def check_auth() -> bool:
    """
    檢查使用者是否已登入。
    若未登入，顯示登入表單並 st.stop()。
    回傳 True 表示已通過認證。
    """
    from config import AUTH_ENABLED

    if not AUTH_ENABLED:
        return True

    try:
        import streamlit_authenticator as stauth
    except ImportError:
        st.error("請安裝 streamlit-authenticator: `pip install streamlit-authenticator`")
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

    authenticator.login()

    if st.session_state.get("authentication_status"):
        with st.sidebar:
            st.write(f"**{st.session_state.get('name', '')}**")
            authenticator.logout("登出", key="logout_btn")
        return True
    elif st.session_state.get("authentication_status") is False:
        st.error("帳號或密碼錯誤")
        st.stop()
        return False
    else:
        st.info("請登入以繼續使用系統")
        st.stop()
        return False
