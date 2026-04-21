"""
開發信追蹤 HTTP 服務（需求規格）

提供兩個端點：
  GET /t/open/{uid}.gif  → 1x1 透明 GIF，寫入 open 事件
  GET /t/click/{uid}?u=<encoded>  → 302 轉址到原網址，寫入 click 事件

執行：
  uvicorn tracking_server:app --host 0.0.0.0 --port 8503
"""
from __future__ import annotations

import hashlib
import logging
import urllib.parse
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

import sys

sys.path.insert(0, str(Path(__file__).parent))
from database.db import record_email_event, init_db
from logging_config import setup_logging

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title="LeadFlow Tracking", version="1.0")

# 1x1 透明 GIF（43 bytes）
_TRANSPARENT_GIF = bytes.fromhex(
    "47494638396101000100800000ffffff00000021f90401000000002c00000000010001000002024401003b"
)


def _hash_ip(ip: str) -> str:
    """只保留 IP 雜湊，避免 PII 落地"""
    if not ip:
        return ""
    return hashlib.sha256(ip.encode("utf-8")).hexdigest()[:16]


def _client_info(request: Request) -> tuple[str, str]:
    ua = request.headers.get("user-agent", "")[:200]
    # 支援反向代理
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    return ua, _hash_ip(ip)


@app.on_event("startup")
def _startup():
    init_db()
    logger.info("Tracking server ready")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/t/open/{uid}.gif")
def track_open(uid: str, request: Request):
    ua, ip_hash = _client_info(request)
    try:
        record_email_event(uid, "open", user_agent=ua, ip_hash=ip_hash)
    except Exception as e:
        logger.warning(f"[open] 寫入失敗 uid={uid}：{e}")
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    return Response(content=_TRANSPARENT_GIF, media_type="image/gif", headers=headers)


@app.get("/t/click/{uid}")
def track_click(uid: str, u: str, request: Request):
    target = urllib.parse.unquote(u or "")
    if not target.lower().startswith(("http://", "https://")):
        target = "https://" + target if target else "about:blank"

    ua, ip_hash = _client_info(request)
    try:
        record_email_event(uid, "click", target_url=target, user_agent=ua, ip_hash=ip_hash)
    except Exception as e:
        logger.warning(f"[click] 寫入失敗 uid={uid}：{e}")

    return RedirectResponse(url=target, status_code=302)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tracking_server:app", host="0.0.0.0", port=8503, reload=False)
