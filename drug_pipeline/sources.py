"""
Drug Pipeline MCP — Data Sources Layer.

All data source fetchers. Every function returns raw structured data.
No hallucination — every result traces to a source API.
"""

import json
import os
import re as _re
import socket
import time
import urllib.parse
import urllib.request
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

_CLINICALTRIALS_BASE = "https://clinicaltrials.gov/api/v2"
_FDA_BASE = "https://api.fda.gov"
_RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
_PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_RATE_LIMIT_DELAY = 0.35  # ~3 requests/sec for openFDA
_last_call = 0.0
_DEFAULT_REQUEST_TIMEOUT = float(os.getenv("DRUG_PIPELINE_REQUEST_TIMEOUT", "8"))
_DEFAULT_EMA_DOWNLOAD_TIMEOUT = float(os.getenv("DRUG_PIPELINE_EMA_DOWNLOAD_TIMEOUT", "12"))
_MIN_NETWORK_TIMEOUT = 1.0
_REQUEST_DEADLINE: ContextVar[float | None] = ContextVar(
    "drug_pipeline_request_deadline", default=None
)

# ─────────────────────────────────────────────────────────────
# EMA Medicines Data — Daily XLSX Download
# ─────────────────────────────────────────────────────────────

_EMA_XLSX_PATH = os.path.join(os.path.dirname(__file__), "ema_medicines.xlsx")
_EMA_DOWNLOAD_URL = (
    "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx"
)
_EMA_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
_ema_cache: list[dict] | None = None
_ema_cache_time: float = 0.0  # timestamp of last successful load
_EMA_CACHE_TTL: float = 86400  # 24h in seconds


def set_request_deadline(timeout_seconds: float | None) -> Token:
    """Set a per-tool deadline so nested network calls can respect client budgets."""
    if timeout_seconds is None or timeout_seconds <= 0:
        return _REQUEST_DEADLINE.set(None)
    return _REQUEST_DEADLINE.set(time.monotonic() + timeout_seconds)


def reset_request_deadline(token: Token) -> None:
    """Restore the previous per-tool deadline."""
    _REQUEST_DEADLINE.reset(token)


def _remaining_request_budget() -> float | None:
    """Return remaining seconds for the active tool call, if any."""
    deadline = _REQUEST_DEADLINE.get()
    if deadline is None:
        return None
    return deadline - time.monotonic()


def _resolve_timeout(timeout: int | float | None = None) -> float:
    """Clamp per-request timeout to the active tool budget."""
    requested = float(timeout) if timeout is not None else _DEFAULT_REQUEST_TIMEOUT
    requested = max(_MIN_NETWORK_TIMEOUT, requested)

    remaining = _remaining_request_budget()
    if remaining is None:
        return requested
    if remaining <= (_MIN_NETWORK_TIMEOUT + 0.1):
        raise TimeoutError("Tool time budget exhausted before starting the next network request")

    return min(requested, remaining - 0.1)


def _download_ema_xlsx() -> bool:
    """Download the latest EMA medicines report. Returns True on success."""
    try:
        timeout = _resolve_timeout(_DEFAULT_EMA_DOWNLOAD_TIMEOUT)
        req = urllib.request.Request(
            _EMA_DOWNLOAD_URL, headers={"User-Agent": _EMA_USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        with open(_EMA_XLSX_PATH, "wb") as f:
            f.write(data)
        return True
    except Exception:
        return False


def _load_ema_data() -> list[dict]:
    """Lazy-load the EMA medicines index into memory.

    Refreshes from EMA if cache is missing or older than 24h.
    On download failure, falls back to stale cache if available.
    """
    global _ema_cache, _ema_cache_time
    now = time.time()

    # If cache exists and is fresh, return it
    if _ema_cache is not None and (now - _ema_cache_time) < _EMA_CACHE_TTL:
        return _ema_cache

    # Cache is missing or stale — try to download fresh data
    if _download_ema_xlsx():
        pass  # will set _ema_cache_time after successful parse below
    elif _ema_cache is not None:
        # Download failed but we have stale cache — keep it and log a warning
        return _ema_cache
    else:
        # No cache and download failed — empty
        _ema_cache = []
        _ema_cache_time = now
        return _ema_cache

    try:
        import openpyxl
    except ImportError:
        import logging

        logging.getLogger("drug_pipeline").warning(
            "openpyxl not installed — EMA data will not be available. "
            "Install with: pip install drug-pipeline-mcp or pip install openpyxl"
        )
        _ema_cache = []
        return _ema_cache

    try:
        wb = openpyxl.load_workbook(_EMA_XLSX_PATH, read_only=True, data_only=True)
        ws = wb["Medicine"]

        medicines = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i < 8:  # skip metadata rows 0-7, header at 8
                continue
            if not row or not row[1]:
                continue
            medicines.append(
                {
                    "category": str(row[0] or "") if row[0] else None,
                    "name": str(row[1] or "") if row[1] else None,
                    "ema_product_number": str(row[2] or "") if row[2] else None,
                    "status": str(row[3] or "") if row[3] else None,
                    "opinion_status": str(row[4] or "") if row[4] else None,
                    "procedure": str(row[5] or "") if row[5] else None,
                    "inn": str(row[6] or "") if row[6] else None,
                    "active_substance": str(row[7] or "") if row[7] else None,
                    "therapeutic_area": str(row[8] or "") if row[8] else None,
                    "atc_code": str(row[11] or "") if len(row) > 11 and row[11] else None,
                    "pharma_group": str(row[13] or "") if len(row) > 13 and row[13] else None,
                    "indication": str(row[15] or "") if len(row) > 15 and row[15] else None,
                    "accelerated_assessment": str(row[16] or "")
                    if len(row) > 16 and row[16]
                    else None,
                    "additional_monitoring": str(row[17] or "")
                    if len(row) > 17 and row[17]
                    else None,
                    "biosimilar": str(row[19] or "") if len(row) > 19 and row[19] else None,
                    "conditional_approval": str(row[20] or "")
                    if len(row) > 20 and row[20]
                    else None,
                    "orphan": str(row[23] or "") if len(row) > 23 and row[23] else None,
                }
            )

        wb.close()
        _ema_cache = medicines
        _ema_cache_time = time.time()
        return medicines
    except Exception:
        # Don't overwrite healthy cache on parse error
        if _ema_cache is None:
            _ema_cache = []
        return _ema_cache or []


def _rate_limited(url: str | None = None):
    """Apply rate limiting only to APIs that need it."""
    if not url or not url.startswith(_FDA_BASE):
        return

    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < _RATE_LIMIT_DELAY:
        sleep_for = _RATE_LIMIT_DELAY - elapsed
        remaining = _remaining_request_budget()
        if remaining is not None:
            sleep_for = min(sleep_for, max(0.0, remaining - 0.05))
        if sleep_for > 0:
            time.sleep(sleep_for)
    _last_call = time.time()


def _fetch(url: str, timeout: int = 15) -> dict | list | str:
    """Fetch a URL and parse JSON, with basic error handling."""
    try:
        resolved_timeout = _resolve_timeout(timeout)
        _rate_limited(url)
    except TimeoutError as e:
        return {
            "status": "error",
            "error_code": "TIMEOUT",
            "message": str(e),
            "source": url[:80],
        }

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "drug-pipeline-mcp/0.1"})
        with urllib.request.urlopen(req, timeout=resolved_timeout) as resp:
            body = resp.read().decode("utf-8")
            ct = resp.headers.get("Content-Type", "")
            if (
                "application/json" in ct
                or url.endswith("format=json")
                or url.endswith("&retmode=json")
            ):
                return json.loads(body)
            return body
    except urllib.error.HTTPError as e:
        return {
            "status": "error",
            "error_code": "HTTP_ERROR",
            "message": f"HTTP {e.code}: {e.reason}",
            "source": url[:80],
        }
    except socket.timeout:
        return {
            "status": "error",
            "error_code": "TIMEOUT",
            "message": f"Request timed out after {resolved_timeout:.1f}s",
            "source": url[:80],
        }
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError | socket.timeout) or "timed out" in str(
            e.reason
        ).lower():
            return {
                "status": "error",
                "error_code": "TIMEOUT",
                "message": f"Request timed out after {resolved_timeout:.1f}s",
                "source": url[:80],
            }
        return {
            "status": "error",
            "error_code": "NETWORK_ERROR",
            "message": str(e.reason),
            "source": url[:80],
        }
    except json.JSONDecodeError:
        return {
            "status": "error",
            "error_code": "PARSE_ERROR",
            "message": "Invalid JSON response",
            "source": url[:80],
        }
    except Exception as e:
        return {
            "status": "error",
            "error_code": "FETCH_ERROR",
            "message": str(e)[:200],
            "source": url[:80],
        }


def _is_error(result: Any) -> bool:
    """Check if result is an error dict."""
    return isinstance(result, dict) and result.get("status") == "error"


# ─────────────────────────────────────────────────────────────
# TTL Cache — Reduziert API-Latenz bei Wiederholungsanfragen
# ─────────────────────────────────────────────────────────────

_CACHE: dict[str, tuple[float, Any]] = {}  # key -> (expiry_time, value)
_CACHE_TTL: float = 300.0  # 5 Minuten Default


def _cached_fetch(url: str, ttl: float = _CACHE_TTL, timeout: int = 15) -> dict | list | str:
    """Fetch with TTL cache. Returns cached value if fresh, else fetches + caches."""
    now = time.time()
    if url in _CACHE:
        expiry, val = _CACHE[url]
        if now < expiry:
            return val
    result = _fetch(url, timeout=timeout)
    if not _is_error(result):
        _CACHE[url] = (now + ttl, result)
    return result


def _clear_cache(pattern: str | None = None) -> int:
    """Clear cache entries. If pattern given, clear URLs containing that string."""
    global _CACHE
    if pattern is None:
        count = len(_CACHE)
        _CACHE = {}
        return count
    before = len(_CACHE)
    _CACHE = {k: v for k, v in _CACHE.items() if pattern not in k}
    return before - len(_CACHE)


# ═════════════════════════════════════════════════════════════
# 1. ClinicalTrials.gov v2
# ═════════════════════════════════════════════════════════════

# Phase mapping for display
PHASE_MAP = {
    "EARLY1": "Phase 1 (Early)",
    "PHASE1": "Phase 1",
    "PHASE12": "Phase 1/2",
    "PHASE2": "Phase 2",
    "PHASE23": "Phase 2/3",
    "PHASE3": "Phase 3",
    "PHASE4": "Phase 4",
    "NA": "Not Applicable",
}

VALID_PHASES = list(PHASE_MAP.keys())

VALID_STATUSES = [
    "ACTIVE_NOT_RECRUITING",
    "COMPLETED",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
    "UNKNOWN",
    "AVAILABLE",
    "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE",
    "APPROVED_FOR_MARKETING",
]




def _escape(s: str) -> str:
    """URL-encode a string value for upstream HTTP queries."""
    return urllib.parse.quote(s)


# Internal modules keep the public import path stable while we split
# the implementation into smaller files for maintainability.
from ._sources_ctgov import get_trial_detail, get_trial_results, get_trial_sites, search_trials
from ._sources_pubmed import search_publications
from ._sources_ema import (
    _condition_match_score,
    _expand_tokens,
    _tokenize,
    approved_for_condition,
    get_eu_approvals,
    list_biosimilars,
    list_loss_of_exclusivity,
    list_orphan_drugs,
)
from ._sources_fda import (
    _resolve_faers_brand,
    detect_safety_signals,
    get_drug_interactions,
    get_drug_label,
    get_fda_approvals,
    get_patent_expiry,
    get_recalls,
    get_safety_data,
    search_drug,
)
from ._sources_registry import (
    _chembl_search,
    _search_orphan_by_condition,
    get_dailymed_label,
    get_drug_pricing,
    get_opentargets_drug,
    get_us_orphan_designations,
)
from ._sources_composite import (
    company_pipeline,
    compare_drugs,
    detect_combination_therapies,
    drug_pipeline_summary,
    find_investigators,
    pipeline_landscape,
)
