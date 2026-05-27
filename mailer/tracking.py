"""
開發信追蹤工具（需求規格）

- gen_tracking_uid(): 產生唯一追蹤碼
- inject_tracking(html, uid, base_url): 在 HTML body 注入 pixel + 改寫連結
- wrap_text_as_html(text): 把純文字內容包成 HTML（pixel 必須有 <img>，所以純文字信會自動升級）
"""
from __future__ import annotations

import re
import secrets
import urllib.parse
from html import escape


def gen_tracking_uid() -> str:
    """產生 22 字元 URL-safe 追蹤碼（~128-bit 熵，不易碰撞/猜測）"""
    return secrets.token_urlsafe(16)


# 抓 <a href="..."> — 不支援巢狀、不改寫錨點(#)、mailto、tel、cid
_LINK_RE = re.compile(r'(<a\b[^>]*\bhref=")([^"]+)(")', re.IGNORECASE)


def _should_rewrite(url: str) -> bool:
    if not url:
        return False
    lowered = url.strip().lower()
    if lowered.startswith(("#", "mailto:", "tel:", "cid:", "javascript:")):
        return False
    return lowered.startswith(("http://", "https://"))


def rewrite_links(html: str, uid: str, base_url: str) -> str:
    """把所有 http(s) 連結改寫為 /t/click/{uid}?u={encoded}"""
    base = base_url.rstrip("/")

    def _repl(m: re.Match) -> str:
        prefix, url, suffix = m.group(1), m.group(2), m.group(3)
        if not _should_rewrite(url):
            return m.group(0)
        tracked = f"{base}/t/click/{uid}?u={urllib.parse.quote(url, safe='')}"
        return f"{prefix}{tracked}{suffix}"

    return _LINK_RE.sub(_repl, html)


def inject_pixel(html: str, uid: str, base_url: str) -> str:
    """在 HTML body 末端注入 1x1 透明追蹤 pixel + 退訂 footer

    退訂 footer 配合 SMTP 端 List-Unsubscribe header 一起降低被 Gmail 進促銷分頁的機率。
    """
    base = base_url.rstrip("/")
    pixel = (
        f'<img src="{base}/t/open/{uid}.gif" '
        f'width="1" height="1" alt="" '
        f'style="display:block;width:1px;height:1px;border:0;" />'
    )
    # 退訂提示 — 一句話，直接告訴對方回信退訂；Gmail 看到「unsubscribe」線索會降促銷分頁機率
    unsub_footer = (
        '<div style="margin-top:28px;padding-top:12px;border-top:1px solid #eaeaea;'
        'font-size:11px;color:#888;line-height:1.5;">'
        '若不希望再收到類似來信，直接回信「退訂」即可，我們會立刻將您移除名單。'
        '</div>'
    )
    suffix = unsub_footer + pixel
    # 盡量塞到 </body> 之前；若沒有，直接 append
    if "</body>" in html.lower():
        # 保留原本大小寫的 </body>
        return re.sub(r"</body>", suffix + r"</body>", html, count=1, flags=re.IGNORECASE)
    return html + suffix


# 裸網址偵測（升級純文字信為 HTML 時，自動包 <a>，讓追蹤覆蓋到）
_BARE_URL_RE = re.compile(r'(https?://[^\s<>"\')（）【】]+)')


def _linkify(safe_html: str) -> str:
    """把已 escape 過的 HTML 中的裸網址轉成 <a href="...">...</a>"""
    return _BARE_URL_RE.sub(r'<a href="\1">\1</a>', safe_html)


def wrap_text_as_html(text: str) -> str:
    """把純文字內容包成 HTML（保留換行、自動連結化）"""
    safe = escape(text).replace("\n", "<br>")
    safe = _linkify(safe)
    return (
        '<!doctype html><html><body style="font-family:sans-serif;font-size:14px;line-height:1.6;color:#1a1a1a;">'
        f"<div>{safe}</div></body></html>"
    )


def inject_tracking(
    body: str,
    uid: str,
    base_url: str,
    is_html: bool,
) -> tuple[str, bool]:
    """
    在內文注入 open pixel + 改寫 http(s) 連結為可追蹤網址。

    - 純文字信：linkify 後改寫 → 升級為 HTML
    - HTML 信：直接改寫所有 <a href="http(s)://..."> → /t/click/{uid}?u=...
    - 無連結的信仍會注入 pixel，不影響開信偵測

    Returns:
        (new_body, is_html_after) — 純文字信會被升級為 HTML（pixel 必須 <img>）
    """
    if not base_url:
        return body, is_html

    html = body if is_html else wrap_text_as_html(body)
    html = rewrite_links(html, uid, base_url)
    html = inject_pixel(html, uid, base_url)
    return html, True
