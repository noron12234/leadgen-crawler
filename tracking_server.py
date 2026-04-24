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

from collections import defaultdict
from time import time

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response

import sys

sys.path.insert(0, str(Path(__file__).parent))
from database.db import record_email_event, init_db, get_connection
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


def _client_info(request: Request) -> tuple[str, str, str]:
    ua = request.headers.get("user-agent", "")[:200]
    # 支援反向代理
    xff = request.headers.get("x-forwarded-for", "")
    ip = xff.split(",")[0].strip() if xff else (request.client.host if request.client else "")
    return ua, _hash_ip(ip), ip


# ─── In-memory per-IP rate limit（擋洗 event / DoS）───
# 60 req / 60s per IP。Fly.io 單一 VM 夠用；多副本時需換 Redis。
_RL_LIMIT = 60
_RL_WIN = 60.0
_rate_buckets: dict[str, list[float]] = defaultdict(list)


def _rate_limit_ok(ip: str) -> bool:
    if not ip:
        return True  # 無 IP 資訊時放行（不擋正常流量）
    now = time()
    bucket = _rate_buckets[ip]
    # 清掉過期戳記
    bucket[:] = [t for t in bucket if now - t < _RL_WIN]
    if len(bucket) >= _RL_LIMIT:
        return False
    bucket.append(now)
    return True


def _is_url_in_original_email(uid: str, target: str) -> bool:
    """
    驗證 target URL 確實來自當初寄出該 uid 的那封信。
    擋 Open Redirect：攻擊者塞 ?u=https://phish.com 會被拒絕。
    """
    if not uid or not target:
        return False
    row = get_connection().execute(
        "SELECT body_snapshot FROM email_logs WHERE tracking_uid = ?", (uid,)
    ).fetchone()
    if not row or not row["body_snapshot"]:
        return False
    return target in row["body_snapshot"]


@app.on_event("startup")
def _startup():
    init_db()
    logger.info("Tracking server ready")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/t/open/{uid}.gif")
def track_open(uid: str, request: Request):
    ua, ip_hash, ip = _client_info(request)
    headers = {
        "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    # Rate limit：爆量請求仍回 gif（不讓攻擊者知道被擋）但不寫入 DB
    if _rate_limit_ok(ip):
        try:
            record_email_event(uid, "open", user_agent=ua, ip_hash=ip_hash)
        except Exception as e:
            logger.warning(f"[open] 寫入失敗 uid={uid}：{e}")
    else:
        logger.info(f"[open] rate limited ip={ip[:15]} uid={uid[:8]}")
    return Response(content=_TRANSPARENT_GIF, media_type="image/gif", headers=headers)


@app.get("/t/click/{uid}")
def track_click(uid: str, u: str, request: Request):
    target = urllib.parse.unquote(u or "")
    if not target.lower().startswith(("http://", "https://")):
        # 不補 scheme — 擋 Open Redirect 的第一道牆
        logger.warning(f"[click] 拒絕非 http(s) target: uid={uid[:8]} u={target[:60]}")
        return Response(status_code=400, content="Invalid target URL")

    # 擋 Open Redirect：target 必須是當初寄這封信時 body 裡的 URL
    if not _is_url_in_original_email(uid, target):
        logger.warning(f"[click] URL 不在原信中，拒絕 redirect: uid={uid[:8]} u={target[:60]}")
        return Response(status_code=400, content="URL mismatch")

    ua, ip_hash, ip = _client_info(request)
    if _rate_limit_ok(ip):
        try:
            record_email_event(uid, "click", target_url=target, user_agent=ua, ip_hash=ip_hash)
        except Exception as e:
            logger.warning(f"[click] 寫入失敗 uid={uid}：{e}")
    else:
        logger.info(f"[click] rate limited ip={ip[:15]} uid={uid[:8]}")

    return RedirectResponse(url=target, status_code=302)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("tracking_server:app", host="0.0.0.0", port=8503, reload=False)
