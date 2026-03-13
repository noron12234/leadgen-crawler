"""
爬蟲共用工具
- 指數退避重試
- 429 自動等待
- 統一錯誤處理
"""
import time
import random
import logging
import requests

logger = logging.getLogger(__name__)

try:
    from config import CRAWLER_MAX_RETRIES, CRAWLER_RETRY_BASE_DELAY
except ImportError:
    CRAWLER_MAX_RETRIES = 3
    CRAWLER_RETRY_BASE_DELAY = 2.0


def request_with_retry(
    url: str,
    method: str = "GET",
    max_retries: int = None,
    base_delay: float = None,
    **kwargs,
) -> requests.Response:
    """
    帶指數退避重試的 HTTP 請求

    - 429 Too Many Requests → 讀取 Retry-After header 或等待退避
    - ConnectionError / Timeout → 自動重試
    - 其他 HTTP 錯誤 → 直接拋出

    Args:
        url: 請求 URL
        method: HTTP method（GET/POST）
        max_retries: 最多重試幾次（預設從 config）
        base_delay: 基礎延遲秒數（預設從 config）
        **kwargs: 傳給 requests.request 的其他參數

    Returns:
        requests.Response

    Raises:
        requests.exceptions.HTTPError: 非重試錯誤
        requests.exceptions.ConnectionError: 重試耗盡後仍連線失敗
    """
    if max_retries is None:
        max_retries = CRAWLER_MAX_RETRIES
    if base_delay is None:
        base_delay = CRAWLER_RETRY_BASE_DELAY

    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(method, url, **kwargs)

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    wait = float(retry_after)
                else:
                    wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"429 Rate Limited: {url} → 等待 {wait:.1f}s（第 {attempt+1} 次）")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.HTTPError:
            raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if attempt < max_retries:
                wait = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"連線失敗: {url} → 等待 {wait:.1f}s 重試（{attempt+1}/{max_retries}）: {e}")
                time.sleep(wait)
            else:
                logger.error(f"重試耗盡: {url} → {e}")

    raise last_exc or requests.exceptions.ConnectionError(f"重試 {max_retries} 次後仍失敗: {url}")
