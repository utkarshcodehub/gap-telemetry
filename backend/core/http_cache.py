"""
A small on-disk HTTP response cache, shared by both GitHub fetchers.

Why this exists. `/analyze` makes two GitHub passes: the evidence collector
(`core/evidence/github.py`, already cached) and the legacy README-keyword fetcher
that feeds the pre-evidence-model score. The second was uncached, so every
analysis of the same profile re-fetched a repo list plus up to twenty READMEs --
measured at **14.8 seconds and ~24 requests** even when the evidence half was
served instantly from cache.

That matters for two reasons beyond speed. The GitHub rate limit is shared across
every analysis, so an uncached pass spends a budget other users need. And the
evidence block is gated on the legacy fetch succeeding, which put the slow,
rate-limit-exposed call on the critical path for the feature it gates.

Caches successful responses only. A 404 or a rate-limit response must never be
cached: the first is cheap to repeat and the second would freeze a transient
failure in place for a day.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TTL_SECONDS = 24 * 3600

_session: requests.Session | None = None


def session() -> requests.Session:
    """Process-wide pooled session with retries.

    A profile fetch is dozens of sequential requests; opening a fresh TLS
    connection for each is slow and occasionally fails outright. 403/429 are
    deliberately NOT retried -- hammering a rate limit is how you stay
    rate-limited.
    """
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=3, connect=3, read=3, backoff_factor=0.6,
                      status_forcelist=(500, 502, 503, 504),
                      allowed_methods=frozenset({"GET"}), raise_on_status=False)
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        s.mount("https://", adapter)
        _session = s
    return _session


def _path_for(cache_dir: Path, url: str) -> Path:
    key = re.sub(r"[^A-Za-z0-9]+", "_", url)[-180:]
    return cache_dir / f"{key}.json"


def read(cache_dir: Path | None, url: str,
         ttl: int = DEFAULT_TTL_SECONDS) -> str | None:
    if cache_dir is None:
        return None
    p = _path_for(cache_dir, url)
    if not p.exists() or time.time() - p.stat().st_mtime > ttl:
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))["body"]
    except (json.JSONDecodeError, KeyError, OSError):
        return None


def write(cache_dir: Path | None, url: str, body: str) -> None:
    if cache_dir is None:
        return
    p = _path_for(cache_dir, url)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"url": url, "body": body}), encoding="utf-8")


def get_text(url: str, *, headers: dict, timeout: int,
             cache_dir: Path | None, params: dict | None = None,
             ttl: int = DEFAULT_TTL_SECONDS) -> tuple[int, str]:
    """Return (status_code, body). A cache hit reports 200 without a request."""
    full = url
    if params:
        from urllib.parse import urlencode
        full = f"{url}?{urlencode(params)}"

    hit = read(cache_dir, full, ttl)
    if hit is not None:
        return 200, hit

    resp = session().get(url, headers=headers, params=params, timeout=timeout)
    if resp.status_code == 200:
        write(cache_dir, full, resp.text)
    return resp.status_code, resp.text


def get_json(url: str, **kw):
    """As get_text, decoding the body. Returns (status_code, parsed_or_None)."""
    status, text = get_text(url, **kw)
    if status != 200:
        return status, None
    try:
        return status, json.loads(text)
    except json.JSONDecodeError:
        return status, None
