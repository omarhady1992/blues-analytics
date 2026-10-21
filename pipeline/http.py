"""A tiny HTTP client with an on-disk JSON cache and per-host rate limiting.

Every response is saved under data/raw/<source>/<cache_key>.json. Finished
matches never change much, so once cached they are read from disk instead of
hitting the source again (pass refresh=True to force a re-download).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from curl_cffi import requests as cffi_requests

from .config import MIN_REQUEST_INTERVAL, RAW_DIR

_last_call: dict[str, float] = {}


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_call.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    _last_call[host] = time.monotonic()


class CachedClient:
    def __init__(self, source: str, headers: dict | None = None, impersonate: bool = False):
        self.source = source
        self.dir: Path = RAW_DIR / source
        self.dir.mkdir(parents=True, exist_ok=True)
        self.impersonate = impersonate  # some sites need a browser-like TLS fingerprint
        self.headers = {"User-Agent": "Mozilla/5.0 (blues-analytics hobby project)", **(headers or {})}
        self.session = None if impersonate else requests.Session()
        self.network_calls = 0

    def get_json(self, url: str, cache_key: str, params: dict | None = None, refresh: bool = False):
        path = self.dir / f"{cache_key}.json"
        if path.exists() and not refresh:
            return json.loads(path.read_text())
        data = self._fetch(url, params)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return data

    def _fetch(self, url: str, params: dict | None):
        last_err = None
        headers = dict(self.headers)
        for attempt in range(6):  # 5xx errors from these APIs are usually transient
            _throttle(url)
            try:
                self.network_calls += 1
                if self.impersonate:
                    r = cffi_requests.get(url, params=params, headers=headers,
                                          impersonate="chrome", timeout=40)
                else:
                    r = self.session.get(url, params=params, headers=headers, timeout=40)
                if r.status_code == 200:
                    return r.json()
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code in (400, 401, 403, 404):
                    break  # retrying will not help
                if r.status_code >= 500:
                    # Seen on the PL API: the CDN's gzip copy of a page can be broken
                    # while the uncompressed copy works, so ask for that on retry.
                    headers["Accept-Encoding"] = "identity"
            except Exception as e:  # network hiccup / timeout
                last_err = repr(e)
            time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"[{self.source}] GET {url} failed: {last_err}")
