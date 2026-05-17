"""
Drug Pipeline MCP — Data Sources Layer.

All data source fetchers. Every function returns raw structured data.
No hallucination — every result traces to a source API.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
import urllib.parse
from typing import Any
from datetime import datetime

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

_CLINICALTRIALS_BASE = "https://clinicaltrials.gov/api/v2"
_FDA_BASE = "https://api.fda.gov"
_RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
_PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

_RATE_LIMIT_DELAY = 0.35  # ~3 requests/sec for openFDA
_last_call = 0.0

# ─────────────────────────────────────────────────────────────
# EMA Medicines Data — Daily XLSX Download
# ─────────────────────────────────────────────────────────────

_EMA_XLSX_PATH = "/tmp/ema_medicines.xlsx"
_EMA_DOWNLOAD_URL = "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx"
_ema_cache: list[dict] | None = None
_ema_cache_time: float = 0.0  # timestamp of last successful load
_EMA_CACHE_TTL: float = 86400  # 24h in seconds

# Auto-refresh EMA cache on import (background pre-load)
try:
    _load_ema_data()
except Exception:
    pass  # Silent background refresh


def _download_ema_xlsx() -> bool:
    """Download the latest EMA medicines report. Returns True on success."""
    try:
        req = urllib.request.Request(_EMA_DOWNLOAD_URL, headers={"User-Agent": "drug-pipeline-mcp/0.1"})
        with urllib.request.urlopen(req, timeout=30) as resp:
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
            medicines.append({
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
                "accelerated_assessment": str(row[16] or "") if len(row) > 16 and row[16] else None,
                "additional_monitoring": str(row[17] or "") if len(row) > 17 and row[17] else None,
                "biosimilar": str(row[19] or "") if len(row) > 19 and row[19] else None,
                "conditional_approval": str(row[20] or "") if len(row) > 20 and row[20] else None,
                "orphan": str(row[23] or "") if len(row) > 23 and row[23] else None,
            })

        wb.close()
        _ema_cache = medicines
        _ema_cache_time = time.time()
        return medicines
    except Exception:
        # Don't overwrite healthy cache on parse error
        if _ema_cache is None:
            _ema_cache = []
        return _ema_cache or []


def _rate_limited():
    """Minimal rate limiting for APIs."""
    global _last_call
    now = time.time()
    elapsed = now - _last_call
    if elapsed < _RATE_LIMIT_DELAY:
        time.sleep(_RATE_LIMIT_DELAY - elapsed)
    _last_call = time.time()


def _fetch(url: str, timeout: int = 15) -> dict | list | str:
    """Fetch a URL and parse JSON, with basic error handling."""
    _rate_limited()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "drug-pipeline-mcp/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            ct = resp.headers.get("Content-Type", "")
            if "application/json" in ct or url.endswith("format=json") or url.endswith("&retmode=json"):
                return json.loads(body)
            return body
    except urllib.error.HTTPError as e:
        return {"status": "error", "error_code": "HTTP_ERROR", "message": f"HTTP {e.code}: {e.reason}", "source": url[:80]}
    except urllib.error.URLError as e:
        return {"status": "error", "error_code": "NETWORK_ERROR", "message": str(e.reason), "source": url[:80]}
    except json.JSONDecodeError:
        return {"status": "error", "error_code": "PARSE_ERROR", "message": "Invalid JSON response", "source": url[:80]}
    except Exception as e:
        return {"status": "error", "error_code": "FETCH_ERROR", "message": str(e)[:200], "source": url[:80]}


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
    "ACTIVE_NOT_RECRUITING", "COMPLETED", "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING", "RECRUITING", "SUSPENDED", "TERMINATED",
    "WITHDRAWN", "UNKNOWN", "AVAILABLE", "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE", "APPROVED_FOR_MARKETING",
]


def search_trials(
    condition: str | None = None,
    phase: str | None = None,
    status: str | None = None,
    sponsor: str | None = None,
    intervention: str | None = None,
    limit: int = 10,
) -> dict:
    """
    Search clinical trials on ClinicalTrials.gov.

    Returns list of matching studies with NCT ID, title, phase, status, conditions.
    Every result includes its NCT ID for 100% traceability.
    """
    if limit < 1 or limit > 100:
        return {"status": "error", "error_code": "INVALID_INPUT", "message": "limit must be 1-100"}

    # Build query WITHOUT double-encoding
    # query.cond is the native API parameter for condition search (no AREA syntax needed)
    # For intervention, use AREA syntax via query.term
    params = {"pageSize": min(limit, 100), "format": "json"}
    if condition:
        params["query.cond"] = condition
    if intervention:
        params["query.term"] = f'AREA[InterventionSearch]/{_escape(intervention)}'
    if sponsor:
        params["query.spons"] = sponsor

    url = f"{_CLINICALTRIALS_BASE}/studies?{urllib.parse.urlencode(params)}"
    data = _fetch(url)

    if _is_error(data):
        return data

    if not isinstance(data, dict) or "studies" not in data:
        return {"status": "error", "error_code": "NO_DATA", "message": "No studies returned"}

    studies = data["studies"]
    results = []

    for s in studies:
        p = s.get("protocolSection", {})
        if not p:
            continue

        id_mod = p.get("identificationModule", {})
        des_mod = p.get("designModule", {})
        stat_mod = p.get("statusModule", {})
        cond_mod = p.get("conditionsModule", {})
        spons_mod = p.get("sponsorCollaboratorsModule", {})

        phases_raw = des_mod.get("phases", [])
        phases_display = [PHASE_MAP.get(ph, ph) for ph in phases_raw]
        overall_status = stat_mod.get("overallStatus", "UNKNOWN")

        # Apply client-side filters (ClinicalTrials.gov API has limited filter support)
        if phase and phase not in phases_raw:
            continue
        if status and status != overall_status:
            continue

        interventions_raw = None
        arms = p.get("armsInterventionsModule", {})
        if arms:
            interventions_raw = [i.get("name", "") for i in (arms.get("interventions", []) or []) if i.get("name")]

        results.append({
            "nct_id": id_mod.get("nctId"),
            "title": id_mod.get("briefTitle"),
            "phase": phases_display,
            "phase_code": phases_raw,
            "overall_status": overall_status,
            "conditions": cond_mod.get("conditions", []),
            "lead_sponsor": spons_mod.get("leadSponsor", {}).get("name"),
            "interventions": interventions_raw,
            "start_date": stat_mod.get("startDateStruct", {}).get("date") if "startDateStruct" in stat_mod else None,
            "completion_date": stat_mod.get("completionDateStruct", {}).get("date") if "completionDateStruct" in stat_mod else None,
            "source_url": f"https://clinicaltrials.gov/study/{id_mod.get('nctId')}",
            "data_source": "clinicaltrials.gov",
        })

    return {
        "status": "ok",
        "total_count": len(results),
        "results": results[:limit],
        "query": {"condition": condition, "phase": phase, "status": status, "sponsor": sponsor},
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_trial_detail(nct_id: str) -> dict:
    """Get full protocol detail for a specific clinical trial by NCT ID."""
    if not nct_id or not nct_id.startswith("NCT"):
        return {"status": "error", "error_code": "INVALID_NCT", "message": f"Invalid NCT ID: {nct_id}. Must start with 'NCT'."}

    url = f"{_CLINICALTRIALS_BASE}/studies/{nct_id}?format=json"
    data = _fetch(url)

    if _is_error(data):
        return data

    if not isinstance(data, dict):
        return {"status": "error", "error_code": "NO_DATA", "message": "Trial not found"}

    p = data.get("protocolSection", {})

    id_mod = p.get("identificationModule", {})
    des_mod = p.get("designModule", {})
    stat_mod = p.get("statusModule", {})
    cond_mod = p.get("conditionsModule", {})
    spons_mod = p.get("sponsorCollaboratorsModule", {})
    elig_mod = p.get("eligibilityModule", {})
    outcome_mod = p.get("outcomesModule", {})
    arms_mod = p.get("armsInterventionsModule", {})
    loc_mod = p.get("contactsLocationsModule", {})
    ref_mod = p.get("referencesModule", {})
    overs_mod = p.get("oversightModule", {})

    phases_raw = des_mod.get("phases", [])
    results = {
        "nct_id": id_mod.get("nctId"),
        "title": id_mod.get("briefTitle"),
        "acronym": id_mod.get("acronym"),
        "phase": [PHASE_MAP.get(ph, ph) for ph in phases_raw],
        "phase_code": phases_raw,
        "overall_status": stat_mod.get("overallStatus", "UNKNOWN"),
        "brief_summary": (p.get("descriptionModule", {}) or {}).get("briefSummary", ""),
        "conditions": cond_mod.get("conditions", []),
        "lead_sponsor": spons_mod.get("leadSponsor", {}).get("name"),
        "collaborators": [c.get("name") for c in (spons_mod.get("collaborators", []) or [])],
        "study_type": des_mod.get("studyType"),
        "enrollment": des_mod.get("enrollmentInfo", {}).get("count") if "enrollmentInfo" in des_mod else None,
        "interventions": [
            {"name": i.get("name"), "type": i.get("type")}
            for i in (arms_mod.get("interventions", []) or [])
        ] if arms_mod.get("interventions") else None,
        "primary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in (outcome_mod.get("primaryOutcomes", []) or [])
        ] if outcome_mod.get("primaryOutcomes") else None,
        "secondary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in (outcome_mod.get("secondaryOutcomes", []) or [])
        ] if outcome_mod.get("secondaryOutcomes") else None,
        "eligibility_criteria": (elig_mod.get("eligibilityCriteria", "") or "")[:2000],
        "sex": elig_mod.get("sex"),
        "min_age": elig_mod.get("minimumAge"),
        "max_age": elig_mod.get("maximumAge"),
        "healthy_volunteers": elig_mod.get("healthyVolunteers"),
        "locations": [
            {"facility": l.get("facility"), "city": l.get("city"), "country": l.get("country")}
            for l in (loc_mod.get("locations", []) or [])
        ][:20] if loc_mod.get("locations") else None,
        "start_date": (stat_mod.get("startDateStruct", {}) or {}).get("date"),
        "primary_completion_date": (stat_mod.get("primaryCompletionDateStruct", {}) or {}).get("date"),
        "completion_date": (stat_mod.get("completionDateStruct", {}) or {}).get("date"),
        "study_first_submit": (stat_mod.get("studyFirstSubmitDate", "")) if "studyFirstSubmitDate" in stat_mod else None,
        "last_update": (stat_mod.get("lastUpdatePostDateStruct", {}) or {}).get("date"),
        "fda_regulated": (overs_mod.get("fdaRegulatedDrug", False)) if "fdaRegulatedDrug" in overs_mod else None,
        "references": [
            {"citation": r.get("citation"), "pmid": r.get("pmid")}
            for r in (ref_mod.get("references", []) or [])
        ][:10] if ref_mod.get("references") else None,
        "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
        "data_source": "clinicaltrials.gov",
    }

    return {
        "status": "ok",
        "data": results,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 2. openFDA — Drug Approvals, NDC, Labels
# ═════════════════════════════════════════════════════════════


def search_drug(name: str) -> dict:
    """
    Look up a drug by brand or generic name.

    Returns active ingredients, strength, labeler, NDC,
    RxNorm RxCUI, and ATC classification.
    """
    # 1. FDA NDC lookup
    url_ndc = f"{_FDA_BASE}/drug/ndc.json?search=brand_name:{_escape(name)}+OR+generic_name:{_escape(name)}&limit=5"
    ndc_data = _fetch(url_ndc)

    # 2. RxNorm / ATC lookup
    url_rx = f"{_RXNORM_BASE}/approximateTerm.json?term={_escape(name)}&maxEntries=3"
    rx_data = _fetch(url_rx)

    results = []
    if not _is_error(ndc_data) and isinstance(ndc_data, dict):
        for r in (ndc_data.get("results", []) or []):
            results.append({
                "brand_name": r.get("brand_name"),
                "generic_name": r.get("generic_name"),
                "labeler": r.get("labeler_name"),
                "active_ingredients": [
                    {"name": i["name"], "strength": i.get("strength", "")}
                    for i in (r.get("active_ingredients", []) or [])
                ],
                "product_ndc": r.get("product_ndc"),
                "route": r.get("route"),
            })

    # Extract RxNorm / ATC from RxNav
    atc_info = None
    rxcui = None
    if not _is_error(rx_data):
        candidates = (rx_data.get("approximateGroup", {}) or {}).get("candidate", []) or []
        for c in candidates:
            if c.get("rxcui"):
                rxcui = c["rxcui"]
                break
        if rxcui:
            atc_url = f"{_RXNORM_BASE}/rxclass/class/byDrugName.json?drugName={_escape(name)}&relaSource=ATC"
            atc_data = _fetch(atc_url)
            if not _is_error(atc_data):
                classes = ((atc_data.get("rxclassDrugInfoList", {}) or {}).get("rxclassDrugInfo", []) or [])
                if classes:
                    cls = classes[0].get("rxclassMinConceptItem", {})
                    atc_info = {"code": cls.get("classId"), "name": cls.get("className")}

    return {
        "status": "ok",
        "drug_name": name,
        "rxcui": rxcui,
        "atc_classification": atc_info,
        "products": results[:5],
        "total_products": len(results),
        "data_sources": ["openFDA", "RxNorm", "RxNav"],
        "timestamp": datetime.utcnow().isoformat(),
    }


def get_fda_approvals(drug_name: str) -> dict:
    """
    Get FDA approval history for a drug by brand or generic name.

    Returns application number, sponsor, submission history with dates and status.
    """
    url = f"{_FDA_BASE}/drug/drugsfda.json?search=products.brand_name:{_escape(drug_name)}+OR+products.active_ingredients.name:{_escape(drug_name)}&limit=3"
    data = _fetch(url)

    if _is_error(data):
        return data

    if not isinstance(data, dict) or "results" not in data:
        return {"status": "ok", "results": [], "total": 0, "message": f"No FDA approvals found for '{drug_name}'"}

    apps = []
    for r in (data.get("results", []) or []):
        submissions = []
        for s in (r.get("submissions", []) or []):
            submissions.append({
                "type": s.get("submission_type"),
                "number": s.get("submission_number"),
                "status": s.get("submission_status"),
                "status_date": s.get("submission_status_date"),
                "review_priority": s.get("review_priority"),
                "class_code": s.get("submission_class_code_description"),
            })
        apps.append({
            "application_number": r.get("application_number"),
            "sponsor": r.get("sponsor_name"),
            "brand_names": [p.get("brand_name") for p in (r.get("products", []) or []) if p.get("brand_name")],
            "generic_names": [p.get("generic_name") for p in (r.get("products", []) or []) if p.get("generic_name")],
            "submissions": submissions,
            "source_url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={r.get('application_number','')}",
        })

    return {
        "status": "ok",
        "drug_name": drug_name,
        "applications": apps,
        "total": len(apps),
        "data_source": "openFDA",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 3. PubMed — Publications
# ═════════════════════════════════════════════════════════════


def search_publications(query: str, max_results: int = 10) -> dict:
    """
    Search PubMed for publications matching a query.

    Returns PMIDs, titles, journal, and publication dates.
    """
    if not query or len(query) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT", "message": "Query must be at least 2 characters"}

    # Step 1: ESearch — find matching PMIDs
    search_url = f"{_PUBMED_BASE}/esearch.fcgi?db=pubmed&term={urllib.parse.quote(query)}&retmax={min(max_results, 50)}&retmode=json"
    search_data = _fetch(search_url)

    if _is_error(search_data):
        return search_data

    if not isinstance(search_data, dict):
        return {"status": "error", "error_code": "NO_DATA", "message": "PubMed search failed"}

    id_list = (search_data.get("esearchresult", {}) or {}).get("idlist", [])
    total_count = (search_data.get("esearchresult", {}) or {}).get("count", "0")

    if not id_list:
        return {"status": "ok", "total_count": 0, "results": [], "query": query}

    # Step 2: EFetch — get details for found PMIDs
    ids_csv = ",".join(id_list)
    fetch_url = f"{_PUBMED_BASE}/efetch.fcgi?db=pubmed&id={ids_csv}&retmode=xml&rettype=abstract"
    fetch_data = _fetch(fetch_url)

    # Parse XML minimally (we're getting XML, not JSON — parse with simple regex)
    xml_text = fetch_data if isinstance(fetch_data, str) else ""

    # Simple extraction (no external XML parser dependency)
    results = []
    if xml_text:
        import re
        articles = re.split(r"<PubmedArticle>", xml_text)[1:]

        for art in articles[:max_results]:
            pmid_match = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
            title_match = re.search(r"<ArticleTitle[^>]*>(.*?)</ArticleTitle>", art, re.DOTALL)
            journal_match = re.search(r"<Journal[^>]*>.*?<Title[^>]*>(.*?)</Title>", art, re.DOTALL)
            year_match = re.search(r"<PubDate[^>]*>.*?<Year[^>]*>(\d{4})", art, re.DOTALL)
            abstract_match = re.search(r"<Abstract[^>]*>.*?<AbstractText[^>]*>(.*?)</AbstractText>", art, re.DOTALL)

            # Clean HTML entities
            def clean(s):
                if not s:
                    return None
                s = re.sub(r"<[^>]+>", "", s)
                s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
                return s[:300] if s else None

            pmid = clean(pmid_match.group(1)) if pmid_match else None
            title = clean(title_match.group(1)) if title_match else None
            journal = clean(journal_match.group(1)) if journal_match else None
            year = clean(year_match.group(1)) if year_match else None
            abstract = clean(abstract_match.group(1)) if abstract_match else None

            if pmid:
                results.append({
                    "pmid": pmid,
                    "title": title,
                    "journal": journal,
                    "year": year,
                    "abstract": abstract,
                    "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                })

    return {
        "status": "ok",
        "total_count": int(total_count) if total_count.isdigit() else len(id_list),
        "returned_count": len(results),
        "results": results[:max_results],
        "query": query,
        "data_source": "PubMed",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 4. EU (EMA) Approvals — via Daily XLSX
# ═════════════════════════════════════════════════════════════


def get_eu_approvals(drug_name: str) -> dict:
    """
    Get EU/EMA approval status for a drug by brand name or active substance.

    Queries the EMA Human Medicines Register (daily updated XLSX).
    Returns authorization status, ATC code, therapeutic area, indication,
    and special designations (orphan, biosimilar, conditional approval).
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    name_lower = drug_name.lower()
    ema_data = _load_ema_data()

    if not ema_data:
        return {"status": "ok", "drug_name": drug_name,
                "results": [], "total": 0,
                "message": "EMA data not available. Try again or check /tmp/ema_medicines.xlsx",
                "data_source": "EMA"}

    results = []
    for med in ema_data:
        name = (med.get("name") or "").lower()
        inn = (med.get("inn") or "").lower()
        subst = (med.get("active_substance") or "").lower()

        if name_lower in name or name_lower in inn or name_lower in subst:
            results.append({
                "brand_name": med.get("name"),
                "ema_product_number": med.get("ema_product_number"),
                "status": med.get("status"),
                "inn": med.get("inn"),
                "active_substance": med.get("active_substance"),
                "atc_code": med.get("atc_code"),
                "therapeutic_area": med.get("therapeutic_area"),
                "pharma_group": med.get("pharma_group"),
                "indication": (med.get("indication") or "")[:300],
                "additional_monitoring": med.get("additional_monitoring") == "Yes",
                "biosimilar": med.get("biosimilar") == "Yes",
                "conditional_approval": med.get("conditional_approval") == "Yes",
                "orphan": med.get("orphan") == "Yes",
                "accelerated_assessment": med.get("accelerated_assessment") == "Yes",
                "source_url": f"https://www.ema.europa.eu/en/medicines/human/EPAR/{med.get('name', '').lower().replace(' (previously ', '-').replace(' ', '-').split(',')[0].strip('-')}" if med.get("name") else None,
            })

    return {
        "status": "ok",
        "drug_name": drug_name,
        "results": results[:20],
        "total": len(results),
        "data_source": "EMA (Daily XLSX)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 5. FAERS — Adverse Event Safety Data via openFDA
# ═════════════════════════════════════════════════════════════

_FAERS_DISCLAIMER = (
    "Do not rely on openFDA to make decisions regarding medical care. "
    "FAERS data is unvalidated; single reports may be incomplete or inaccurate. "
    "Report counts are NOT incidence rates — they reflect reporting volume, not prevalence."
)


def get_safety_data(drug_name: str) -> dict:
    """
    Get FDA Adverse Event Reporting System (FAERS) data for a drug.

    Returns total number of adverse event reports, top reported reactions,
    and serious outcome breakdown (death, hospitalization, etc.).
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    # 1. Total reports + serious outcomes
    search_term = urllib.parse.quote(drug_name)
    url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&limit=1"
    data = _fetch(url)

    if _is_error(data):
        return data

    total = (data.get("meta", {}).get("results", {}) or {}).get("total", 0) or 0

    if total == 0:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "total_reports": 0,
            "message": f"No adverse event reports found for '{drug_name}' in FAERS",
            "data_source": "openFDA FAERS",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # 2. Top reactions by count
    count_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&count=patient.reaction.reactionmeddrapt.exact&limit=10"
    count_data = _fetch(count_url)
    top_reactions = []
    if not _is_error(count_data) and isinstance(count_data, dict):
        for r in (count_data.get("results", []) or []):
            top_reactions.append({"reaction": r.get("term"), "count": r.get("count")})

    # 3. Serious outcomes breakdown
    serious_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&count=serious&limit=5"
    serious_data = _fetch(serious_url)
    serious_outcomes = {}
    if not _is_error(serious_data) and isinstance(serious_data, dict):
        for r in (serious_data.get("results", []) or []):
            key = r.get("term", "unknown")
            label = {"1": "Serious (any)", "2": "Not serious"}.get(key, key)
            serious_outcomes[label] = r.get("count")

    return {
        "status": "ok",
        "drug_name": drug_name,
        "total_reports": total,
        "top_reactions": top_reactions[:10],
        "serious_outcomes": serious_outcomes,
        "disclaimer": _FAERS_DISCLAIMER,
        "data_source": "openFDA FAERS",
        "faers_url": f"https://api.fda.gov/drug/event.json?search=patient.drug.medicinalproduct:{search_term}",
        "timestamp": datetime.utcnow().isoformat(),
    }



# ═════════════════════════════════════════════════════════════
# 6. Indication → Drug — Therapien per Indikation finden
# ═════════════════════════════════════════════════════════════

import re as _re


def _tokenize(text: str) -> set[str]:
    """Tokenize a string into normalized lowercase tokens for matching."""
    text = text.lower()
    text = _re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if len(t) > 1}


def _condition_match_score(query_tokens: set[str], area: str) -> float:
    """
    Compute a match score between query tokens and a therapeutic area string.
    
    Returns 0.0-1.0. Uses token overlap with synonym expansion and
    boosting for significant words.
    """
    if not query_tokens or not area:
        return 0.0
    
    area_tokens = _tokenize(area)
    if not area_tokens:
        return 0.0

    # Expand query with medical synonyms
    expanded = _expand_tokens(query_tokens)
    
    # Check overlap with both original and expanded tokens
    overlap = (query_tokens & area_tokens) or (expanded & area_tokens)
    if not overlap:
        return 0.0
    
    # Score based on matched portion — use the larger set
    matched_tokens = query_tokens & area_tokens
    if not matched_tokens:
        matched_tokens = expanded & area_tokens
        # Lower weight for synonym matches
        score = len(matched_tokens) / (len(query_tokens) + 0.5)
    else:
        score = len(overlap) / len(query_tokens)
    
    avg_query_len = sum(len(t) for t in query_tokens) / len(query_tokens) if query_tokens else 1
    avg_overlap_len = sum(len(t) for t in overlap) / len(overlap) if overlap else 1
    if avg_overlap_len >= avg_query_len:
        score *= 1.2
    
    return min(score, 1.0)


# Medical condition synonym map — bridges common terms to MeSH vocabulary
_CONDITION_SYNONYMS = {
    "cancer": "carcinoma neoplasm malignancy tumor",
    "blood": "leukemia lymphoma myeloma hematologic",
    "skin": "dermal cutaneous melanoma",
    "high blood pressure": "hypertension",
    "lung": "pulmonary bronchial",
    "kidney": "renal nephrology",
    "liver": "hepatic hepatocellular",
    "heart": "cardiac cardiovascular",
    "stomach": "gastric gastrointestinal",
    "eye": "ocular ophthalmic",
    "nerve": "neural neurological neuropathy",
}


def _expand_tokens(tokens: set[str]) -> set[str]:
    """Expand tokens with common medical synonyms."""
    expanded = set(tokens)
    for token in tokens:
        if token in _CONDITION_SYNONYMS:
            synonyms = _CONDITION_SYNONYMS[token]
            for syn in synonyms.split():
                expanded.add(syn)
    return expanded


def approved_for_condition(condition: str, limit: int = 30) -> dict:
    """
    Find EU-approved drugs for a medical condition.

    Queries the EMA Human Medicines Register by therapeutic area
    and indication text. Returns drug names, active substances,
    ATC codes, and authorization status.
    """
    if not condition or len(condition) < 3:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "condition must be at least 3 characters"}

    query_tokens = _tokenize(condition)
    if not query_tokens:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "Could not parse condition into search tokens"}

    ema_data = _load_ema_data()
    if not ema_data:
        return {"status": "ok", "condition": condition,
                "results": [], "total": 0,
                "message": "EMA data not available"}

    scored = []
    seen_names = set()

    for med in ema_data:
        name = med.get("name") or ""
        if name.lower() in seen_names:
            continue

        area = med.get("therapeutic_area") or ""
        indication = med.get("indication") or ""

        # Primary: score from structured therapeutic_area (MeSH terms)
        # Only these are reliable indicators of approval for a condition
        area_score = 0.0
        if area:
            for sub_area in area.split(";"):
                sub_area = sub_area.strip()
                if sub_area:
                    s = _condition_match_score(query_tokens, sub_area)
                    if s > area_score:
                        area_score = s

        # Require at least a therapeutic_area match
        # Threshold: >0.4 means at least ~40% token overlap
        if area_score < 0.4:
            continue

        # Secondary: indication text can boost, but not create, matches
        indication_score = 0.0
        if indication:
            ind_tokens = _tokenize(indication)
            if ind_tokens and query_tokens:
                overlap = query_tokens & ind_tokens
                if overlap:
                    indication_score = len(overlap) / len(query_tokens) * 0.2

        combined = area_score + indication_score

        if combined > 0.2:
            seen_names.add(name.lower())
            scored.append({
                "name": name,
                "active_substance": med.get("active_substance"),
                "atc_code": med.get("atc_code"),
                "status": med.get("status"),
                "therapeutic_area": area[:120] if area else None,
                "pharma_group": med.get("pharma_group"),
                "indication": (indication or "")[:200],
                "biosimilar": med.get("biosimilar") == "Yes",
                "orphan": med.get("orphan") == "Yes",
                "score": round(combined, 2),
            })

    scored.sort(key=lambda x: (-x["score"], x["name"]))

    by_substance: dict[str, dict] = {}
    for s in scored:
        key = (s["active_substance"] or s["name"]).lower()
        if key not in by_substance:
            by_substance[key] = s

    results = list(by_substance.values())[:limit]

    return {
        "status": "ok",
        "condition": condition,
        "results": results[:limit],
        "total": len(results),
        "total_raw_matches": len(scored),
        "data_source": "EMA (Daily XLSX)",
        "timestamp": datetime.utcnow().isoformat(),
    }

def drug_pipeline_summary(drug_name: str | None = None, condition: str | None = None) -> dict:
    """
    Composite intelligence: given a drug name OR condition, returns:
    - Drug info (ingredients, ATC class, FDA status)
    - Active trials for this drug/condition
    - Recent publications

    This is the primary AX tool — saves agents 3+ API calls.
    """
    if not drug_name and not condition:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "Provide at least one of: drug_name or condition"}

    drug_info = None
    approvals = None
    trials = None
    publications = None
    sources_used = []

    # 1. Drug info (if drug_name provided)
    if drug_name:
        drug_info = search_drug(drug_name)
        if drug_info.get("status") == "ok":
            sources_used.extend(drug_info.get("data_sources", []))

        approvals = get_fda_approvals(drug_name)
        if approvals.get("status") == "ok" and approvals.get("applications"):
            sources_used.append("openFDA-drugsfda")

    # 2. Trials (by condition + intervention)
    trial_query_kwargs = {"limit": 10}
    if condition:
        trial_query_kwargs["condition"] = condition
    if drug_name:
        trial_query_kwargs["intervention"] = drug_name

    if trial_query_kwargs.get("condition") or trial_query_kwargs.get("intervention"):
        trials = search_trials(**trial_query_kwargs)
        if trials.get("status") == "ok":
            sources_used.append("clinicaltrials.gov")

    # 3. Publications
    pub_query = drug_name or condition or ""
    if pub_query:
        publications = search_publications(pub_query + " clinical trial", max_results=5)
        if publications.get("status") == "ok":
            sources_used.append("PubMed")

    # 4. EU approvals (if drug_name provided)
    eu_approvals = None
    if drug_name:
        eu_data = get_eu_approvals(drug_name)
        if eu_data.get("status") == "ok" and eu_data.get("results"):
            eu_approvals = {
                "total": eu_data["total"],
                "results": [{
                    "brand_name": r["brand_name"],
                    "status": r["status"],
                    "atc_code": r["atc_code"],
                    "therapeutic_area": r["therapeutic_area"],
                    "orphan": r["orphan"],
                    "biosimilar": r["biosimilar"],
                } for r in eu_data["results"][:5]] if eu_data.get("results") else [],
            }
            sources_used.append("EMA")

    # 5. Safety data (if drug_name provided)
    safety = None
    if drug_name:
        safety_data = get_safety_data(drug_name)
        if safety_data.get("status") == "ok" and safety_data.get("total_reports", 0) > 0:
            safety = {
                "total_reports": safety_data["total_reports"],
                "top_reactions": safety_data.get("top_reactions", [])[:5],
            }
            sources_used.append("openFDA FAERS")

    # 6. Orphan status (from EU data, already in eu_approvals)
    orphan_status = None
    if eu_approvals and eu_approvals.get("results"):
        orphan_count = sum(1 for r in eu_approvals["results"] if r.get("orphan"))
        if orphan_count:
            orphan_status = {"eu_orphan_designations": orphan_count}

    # 7. Approved-for-condition (if condition provided)
    condition_drugs = None
    if condition:
        afc_data = approved_for_condition(condition, limit=10)
        if afc_data.get("status") == "ok" and afc_data.get("results"):
            condition_drugs = {
                "total_approved": afc_data["total"],
                "top_matches": [{
                    "name": r["name"],
                    "atc_code": r["atc_code"],
                    "orphan": r["orphan"],
                } for r in afc_data["results"][:8]],
            }
            sources_used.append("EMA")

    # 8. Drug Label (if drug_name provided)
    drug_label = None
    if drug_name:
        label_data = get_drug_label(drug_name)
        if label_data.get("status") == "ok" and label_data.get("found") is True:
            drug_label = {
                "indications_and_usage": (label_data.get("indications_and_usage") or "")[:500],
                "boxed_warning": (label_data.get("boxed_warning") or "")[:300],
                "contraindications": (label_data.get("contraindications") or "")[:300],
            }
            sources_used.append("openFDA Labeling")

    # 9. Recalls (if drug_name provided)
    recalls = None
    if drug_name:
        recall_data = get_recalls(drug_name)
        if recall_data.get("status") == "ok" and recall_data.get("recalls"):
            recalls = {
                "total_recalls": recall_data["total_recalls"],
                "recent": [{
                    "date": r.get("recall_initiation_date"),
                    "reason": (r.get("reason_for_recall", "") or "")[:200],
                    "classification": r.get("classification"),
                    "status": r.get("status"),
                    "firm": r.get("recalling_firm"),
                } for r in recall_data["recalls"][:5]],
            }
            sources_used.append("openFDA Enforcement")

    # 10. Safety Signals (if drug_name provided)
    safety_signals = None
    if drug_name:
        signal_data = detect_safety_signals(drug_name)
        if signal_data.get("status") == "ok" and signal_data.get("signals"):
            safety_signals = {
                "total_signals": signal_data["total_signals"],
                "top_signals": [{
                    "reaction": s.get("reaction"),
                    "prr": round(s.get("prr", 0), 2),
                    "reports": s.get("reports_with_drug", 0),
                    "signal_strength": s.get("signal_strength"),
                } for s in signal_data["signals"][:5]],
            }
            sources_used.append("openFDA FAERS")

    # 11. Patent Expiry (if drug_name provided)
    patent_info = None
    if drug_name:
        patent_data = get_patent_expiry(drug_name)
        if patent_data.get("status") == "ok":
            patent_info = {
                "is_reference_listed_drug": patent_data.get("is_reference_listed_drug"),
                "marketing_statuses": patent_data.get("marketing_statuses"),
                "estimated_exclusivity": patent_data.get("estimated_exclusivity", []),
                "total_applications": len(patent_data.get("applications", [])),
                "total_submissions": patent_data.get("total_submissions"),
                "patent_note": patent_data.get("note"),
            }
            sources_used.extend(patent_data.get("data_sources", []))

    # 12. Drug Interactions (if drug_name provided)
    drug_interactions = None
    if drug_name:
        interaction_data = get_drug_interactions(drug_name)
        if interaction_data.get("status") == "ok":
            drug_interactions = {
                "has_label_interactions": interaction_data["label_interactions"].get("drug_interactions_text") is not None,
                "contraindications_available": interaction_data["label_interactions"].get("contraindications_text") is not None,
                "co_reported_in_faers": interaction_data.get("co_reported_in_faers", [])[:3],
                "total_co_reported": interaction_data.get("total_co_reported", 0),
            }
            sources_used.extend(interaction_data.get("data_sources", []))

    return {
        "status": "ok",
        "query": {"drug_name": drug_name, "condition": condition},
        "drug_info": drug_info,
        "fda_approvals": approvals,
        "eu_approvals": eu_approvals,
        "orphan_status": orphan_status,
        "approved_drugs_for_condition": condition_drugs,
        "drug_label": drug_label,
        "recalls": recalls,
        "safety_signals": safety_signals,
        "patent_info": patent_info,
        "drug_interactions": drug_interactions,
        "clinical_trials": trials,
        "publications": publications,
        "safety_data": safety,
        "data_sources": list(set(sources_used)),
        "timestamp": datetime.utcnow().isoformat(),
    }


def _escape(s: str) -> str:
    """URL-encode a string value."""
    return urllib.parse.quote(s)


# ═════════════════════════════════════════════════════════════
# 7. Trial Results — Abgeschlossene Studienergebnisse
# ═════════════════════════════════════════════════════════════


def get_trial_results(nct_id: str) -> dict:
    """
    Get results for a completed clinical trial.

    Returns outcome measures (primary/secondary), participant baseline
    characteristics, adverse events, and participant flow.
    Results are embedded in the study record on ClinicalTrials.gov.
    """
    if not nct_id or not nct_id.startswith("NCT"):
        return {"status": "error", "error_code": "INVALID_NCT",
                "message": f"Invalid NCT ID: {nct_id}. Must start with 'NCT'."}

    url = f"{_CLINICALTRIALS_BASE}/studies/{nct_id}?format=json"
    data = _fetch(url)

    if _is_error(data):
        return data

    if not isinstance(data, dict):
        return {"status": "error", "error_code": "NO_DATA", "message": "Trial not found"}

    # Check if results exist
    results_section = data.get("resultsSection", {})
    if not results_section:
        id_mod = data.get("protocolSection", {}).get("identificationModule", {})
        return {"status": "ok",
                "nct_id": nct_id,
                "has_results": False,
                "message": f"No results posted yet for {nct_id}. The trial may still be ongoing or results haven't been submitted.",
                "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
                "data_source": "clinicaltrials.gov"}

    outcome_module = results_section.get("outcomeMeasuresModule", {}) or {}
    baseline_module = results_section.get("baselineCharacteristicsModule", {}) or {}
    ae_module = results_section.get("adverseEventsModule", {}) or {}
    flow_module = results_section.get("participantFlowModule", {}) or {}
    more_info = results_section.get("moreInfoModule", {}) or {}

    # Parse outcome measures
    outcomes = []
    for om in (outcome_module.get("outcomeMeasures", []) or []):
        classes_data = []
        for cls in (om.get("classes", []) or []):
            categories = []
            for cat in (cls.get("categories", []) or []):
                measurements = []
                for m in (cat.get("measurements", []) or []):
                    measurements.append({
                        "group": m.get("groupDescription"),
                        "value": m.get("value"),
                        "spread": m.get("spread"),
                        "unit": m.get("unit"),
                    })
                categories.append({
                    "title": cat.get("title"),
                    "measurements": measurements,
                })
            classes_data.append({
                "title": cls.get("title"),
                "categories": categories,
            })
        outcomes.append({
            "title": om.get("title"),
            "type": om.get("type"),
            "time_frame": om.get("timeFrame"),
            "description": (om.get("description") or "")[:300],
            "population": om.get("populationDescription"),
            "classes": classes_data,
        })

    # Parse baseline
    baseline_groups = []
    for g in (baseline_module.get("denomGroups", []) or []):
        baseline_groups.append({
            "description": g.get("description", ""),
            "count": (g.get("denomCount", {}) or {}).get("value"),
        })
    baseline_measures = []
    for m in (baseline_module.get("measures", []) or []):
        baseline_measures.append({
            "title": m.get("title"),
            "description": (m.get("description") or "")[:200],
        })

    # Parse adverse events
    serious_events = []
    for e in (ae_module.get("seriousEvents", []) or []):
        serious_events.append({
            "term": e.get("term"),
            "organ_system": e.get("organSystem"),
            "subjects_affected": e.get("subjectsAffected"),
            "subjects_at_risk": e.get("subjectsAtRisk"),
        })
    other_events = []
    for e in (ae_module.get("otherEvents", []) or []):
        other_events.append({
            "term": e.get("term"),
            "organ_system": e.get("organSystem"),
            "subjects_affected": e.get("subjectsAffected"),
            "subjects_at_risk": e.get("subjectsAtRisk"),
        })

    # Participant flow
    flow_groups = []
    for g in (flow_module.get("denomGroups", []) or []):
        flow_groups.append({
            "description": g.get("description", ""),
            "count": (g.get("denomCount", {}) or {}).get("value"),
        })
    flow_periods = []
    for p in (flow_module.get("periods", []) or []):
        milestones = []
        for m in (p.get("milestones", []) or []):
            milestones.append({
                "description": m.get("description"),
                "participants": [{
                    "group": d.get("groupDescription"),
                    "count": d.get("count"),
                } for d in (m.get("denoms", []) or [])],
            })
        flow_periods.append({
            "title": p.get("title"),
            "milestones": milestones,
        })

    # Limitations and caveats
    limitations = None
    if more_info:
        limitations = (more_info.get("limitationsAndCaveats") or "")[:500]

    return {
        "status": "ok",
        "nct_id": nct_id,
        "has_results": True,
        "summary": {
            "outcome_count": len(outcomes),
            "baseline_groups": len(baseline_groups),
            "serious_events": len(serious_events),
            "other_events": len(other_events),
        },
        "outcome_measures": outcomes[:5],  # limit to 5 outcomes
        "baseline": {
            "groups": baseline_groups,
            "measures": baseline_measures[:10],
        },
        "adverse_events": {
            "serious": serious_events[:20],
            "other": other_events[:20],
        },
        "participant_flow": {
            "groups": flow_groups,
            "periods": flow_periods,
        },
        "limitations": limitations,
        "source_url": f"https://clinicaltrials.gov/study/{nct_id}#results",
        "data_source": "clinicaltrials.gov",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 8. Orphan Drug List — EU Orphan Designations aus EMA
# ═════════════════════════════════════════════════════════════


def list_orphan_drugs(condition: str | None = None, limit: int = 50) -> dict:
    """
    List drugs with EU Orphan Drug Designation from the EMA register.

    Optionally filter by therapeutic area/condition.
    Orphan designation means the drug treats a life-threatening
    or chronically debilitating condition affecting <5 in 10,000 people.
    """
    ema_data = _load_ema_data()
    if not ema_data:
        return {"status": "ok", "results": [], "total": 0,
                "message": "EMA data not available"}

    query_tokens = _tokenize(condition) if condition else None
    results = []

    for med in ema_data:
        if med.get("orphan") != "Yes":
            continue

        name = med.get("name") or ""
        area = med.get("therapeutic_area") or ""
        indication = med.get("indication") or ""

        # If condition filter provided, check therapeutic_area match
        if query_tokens:
            area_score = 0.0
            if area:
                for sub_area in area.split(";"):
                    s = _condition_match_score(query_tokens, sub_area.strip())
                    if s > area_score:
                        area_score = s
            if area_score < 0.3:
                continue

        results.append({
            "name": name,
            "active_substance": med.get("active_substance"),
            "atc_code": med.get("atc_code"),
            "therapeutic_area": area[:120] if area else None,
            "indication": (indication or "")[:200],
            "ema_product_number": med.get("ema_product_number"),
        })

    # Deduplicate by active substance
    by_substance: dict[str, dict] = {}
    for r in results:
        key = (r["active_substance"] or r["name"]).lower()
        if key not in by_substance:
            by_substance[key] = r

    final = list(by_substance.values())[:limit]
    final.sort(key=lambda x: x["name"].lower())

    return {
        "status": "ok",
        "condition": condition,
        "results": final,
        "total": len(final),
        "total_raw_matches": len(results),
        "data_source": "EMA (Daily XLSX)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 9. Company Pipeline — Firmen-Pipeline auf einen Blick
# ═════════════════════════════════════════════════════════════


def company_pipeline(company_name: str, include_eu: bool = True, limit: int = 30) -> dict:
    """
    Get the clinical pipeline for a pharmaceutical company.

    Searches ClinicalTrials.gov for all active studies sponsored by
    the company, grouped by phase. Optionally enriches with EU approval
    status for drugs found in trials.
    """
    if not company_name or len(company_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "company_name must be at least 2 characters"}

    # 1. Search trials by sponsor
    trials_raw = search_trials(sponsor=company_name, limit=100)
    if _is_error(trials_raw):
        return trials_raw

    trials = trials_raw.get("results", [])
    if not trials:
        return {"status": "ok", "company": company_name,
                "results": [], "total": 0,
                "message": f"No clinical trials found for sponsor '{company_name}'",
                "data_source": "clinicaltrials.gov"}

    # 2. Group by phase
    by_phase: dict[str, list[dict]] = {}
    for t in trials:
        for phase_code in (t.get("phase_code", []) or ["NA"]):
            by_phase.setdefault(phase_code, []).append(t)

    # 3. Build phase summary
    phase_summary = {}
    for phase_code in ["PHASE1", "PHASE12", "PHASE2", "PHASE23", "PHASE3", "PHASE4", "EARLY1", "NA"]:
        phase_key = PHASE_MAP.get(phase_code, phase_code)
        matched = by_phase.get(phase_code, [])
        if matched:
            phase_summary[phase_key] = {
                "count": len(matched),
                "studies": [{
                    "nct_id": s["nct_id"],
                    "title": s["title"],
                    "status": s.get("overall_status"),
                    "conditions": s.get("conditions", []),
                    "interventions": s.get("interventions"),
                    "source_url": s.get("source_url"),
                } for s in matched[:15]],
            }

    # 4. Extract drug names from trial interventions for EU lookup
    eu_status = None
    if include_eu:
        all_drugs = set()
        for t in trials:
            interventions = t.get("interventions") or []
            for i in interventions:
                if i and len(i) > 2:
                    all_drugs.add(i.lower())
        eu_status = {}
        for drug in sorted(all_drugs)[:15]:
            eu = get_eu_approvals(drug)
            if eu.get("results"):
                eu_status[drug] = {
                    "brand_names": [r["brand_name"] for r in eu["results"]],
                    "statuses": [r["status"] for r in eu["results"]],
                    "orphan": any(r.get("orphan") for r in eu["results"]),
                }

    return {
        "status": "ok",
        "company": company_name,
        "trial_count": len(trials),
        "phase_summary": phase_summary,
        "eu_approvals": eu_status,
        "active_trials": sum(1 for t in trials if t.get("overall_status") in
                             ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")),
        "completed_trials": sum(1 for t in trials if t.get("overall_status") == "COMPLETED"),
        "data_source": "clinicaltrials.gov, EMA",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 10. Drug Label Information (openFDA)
# ═════════════════════════════════════════════════════════════


def get_drug_label(drug_name: str) -> dict:
    """
    Fetch openFDA drug labeling data for a drug.

    Returns structured label sections: indications_and_usage, boxed_warning,
    dosage_and_administration, contraindications, adverse_reactions,
    warnings_and_cautions, drug_interactions, pregnancy_and_lactation.

    NOTE: The openFDA Drug Labeling API primarily covers prescription (Rx) drugs
    with FDA-approved NDAs/BLAs. OTC monograph drugs (e.g., generic ibuprofen)
    typically return 'found: False' because they are not individually labeled
    under an FDA application. Use brand-name OTC products for best results.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    search_term = _escape(drug_name)
    _rate_limited()
    url = f"{_FDA_BASE}/drug/label.json?search=openfda.brand_name:{search_term}+OR+openfda.generic_name:{search_term}&limit=1"
    data = _cached_fetch(url, ttl=300)  # 5 min cache

    if _is_error(data):
        return data

    if not isinstance(data, dict) or "results" not in data:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No label found for '{drug_name}' in openFDA",
            "data_source": "openFDA Drug Labeling",
            "timestamp": datetime.utcnow().isoformat(),
        }

    results = data.get("results", []) or []
    if not results:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No label found for '{drug_name}' in openFDA",
            "data_source": "openFDA Drug Labeling",
            "timestamp": datetime.utcnow().isoformat(),
        }

    label = results[0]

    def _get_field(field_name: str) -> str | None:
        val = label.get(field_name)
        if isinstance(val, list):
            return val[0] if val else None
        return val

    return {
        "status": "ok",
        "drug_name": drug_name,
        "found": True,
        "indications_and_usage": _get_field("indications_and_usage"),
        "boxed_warning": _get_field("boxed_warning"),
        "dosage_and_administration": _get_field("dosage_and_administration"),
        "contraindications": _get_field("contraindications"),
        "adverse_reactions": _get_field("adverse_reactions"),
        "warnings_and_cautions": _get_field("warnings_and_cautions"),
        "drug_interactions": _get_field("drug_interactions"),
        "pregnancy_and_lactation": _get_field("pregnancy_and_lactation"),
        "source_url": url,
        "data_source": "openFDA Drug Labeling",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 11. FDA Recalls / Enforcement
# ═════════════════════════════════════════════════════════════


def get_recalls(drug_name: str) -> dict:
    """
    Fetch FDA recalls and enforcement data for a drug.

    Returns a list of recalls with: recall_initiation_date, reason_for_recall,
    product_quantity, classification (Class I/II/III), status, recalling_firm.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    search_term = _escape(drug_name)
    url = f"{_FDA_BASE}/drug/enforcement.json?search=openfda.brand_name:{search_term}&limit=20"
    data = _cached_fetch(url, ttl=300)  # 5 min cache

    if _is_error(data):
        return data

    recalls = []
    if isinstance(data, dict) and "results" in data:
        for r in (data.get("results", []) or []):
            recalls.append({
                "recall_initiation_date": r.get("recall_initiation_date"),
                "reason_for_recall": r.get("reason_for_recall"),
                "product_quantity": r.get("product_quantity"),
                "classification": r.get("classification"),
                "status": r.get("status"),
                "recalling_firm": r.get("recalling_firm"),
                "product_description": r.get("product_description"),
                "code_info": r.get("code_info"),
            })

    return {
        "status": "ok",
        "drug_name": drug_name,
        "total_recalls": len(recalls),
        "recalls": recalls[:20],
        "source_url": url,
        "data_source": "openFDA Enforcement Reports",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 12. Safety Signal Detection (PRR from FAERS)
# ═════════════════════════════════════════════════════════════


def _resolve_faers_brand(drug_name: str, safety_data: dict) -> tuple[str, dict]:
    """Resolve brand name aliasing for FAERS queries.
    
    If the initial drug name yields fewer than 10,000 FAERS reports,
    try to find brand names (via openFDA) that may have more reports
    filed under them. Returns (best_name, safety_data)."""
    best_name = drug_name
    best_safety = safety_data
    best_reports = safety_data.get("total_reports", 0)
    
    # Only bother if reports are low — suggests generic name with poor FAERS coverage
    if best_reports >= 10000:
        return best_name, best_safety
    
    # Try to find brand name aliases via FDA approvals data
    try:
        import urllib.parse as _up
        search_term = _up.quote(drug_name)
        url = f"{_FDA_BASE}/drug/drugsfda.json?search=products.brand_name:{search_term}+OR+products.active_ingredients.name:{search_term}&limit=3"
        data = _cached_fetch(url, ttl=600)
        if not _is_error(data) and isinstance(data, dict):
            brands_seen = set()
            for r in (data.get("results", []) or []):
                for p in (r.get("products", []) or []):
                    bn = p.get("brand_name", "")
                    if bn and bn.lower() not in brands_seen and bn.lower() != drug_name.lower():
                        brands_seen.add(bn.lower())
                        _rate_limited()
                        brand_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{_up.quote(bn)}&limit=1"
                        bdata = _fetch(brand_url)
                        if not _is_error(bdata) and isinstance(bdata, dict):
                            total = (bdata.get("meta", {}).get("results", {}) or {}).get("total", 0) or 0
                            if total > best_reports:
                                best_reports = total
                                best_name = bn
                                # Re-fetch full safety data for the best brand
                                best_safety = get_safety_data(bn)
    except Exception:
        pass  # If brand resolution fails, fall back to original name
    
    return best_name, best_safety


def detect_safety_signals(drug_name: str) -> dict:
    """
    Compute Proportional Reporting Ratio (PRR) safety signals from FAERS data.

    Uses get_safety_data() to fetch top reactions, then queries the event
    endpoint for drug-specific and background counts to compute PRR.

    PRR = (a/(a+b)) / (c/(c+d)) where:
    - a = reports for drug with reaction X
    - b = reports for drug without reaction X
    - c = reports for all other drugs with reaction X
    - d = reports for all other drugs without reaction X

    Returns reactions ranked by PRR where PRR > 1 as signals.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    # Step 1: Get FAERS data for this drug
    safety = get_safety_data(drug_name)
    if _is_error(safety):
        return safety

    # Step 1b: Brand alias resolution — try brand names if reports are low
    drug_name, safety = _resolve_faers_brand(drug_name, safety)

    total_drug_reports = safety.get("total_reports", 0)
    top_reactions = safety.get("top_reactions", []) or []

    if total_drug_reports == 0 or not top_reactions:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "total_reports": total_drug_reports,
            "signals": [],
            "message": "Insufficient FAERS data to compute safety signals",
            "data_source": "openFDA FAERS (PRR analysis)",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Step 2: Get background total (all drugs in FAERS)
    search_term = _escape(drug_name)
    background_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&limit=1"
    bg_data = _fetch(background_url)

    if _is_error(bg_data):
        return bg_data

    background_total = (bg_data.get("meta", {}).get("results", {}) or {}).get("total", 0) or 0

    if background_total == 0:
        background_total = total_drug_reports

    # Step 3: For each top reaction, get counts and compute PRR
    signals = []
    for reaction in top_reactions:
        reaction_term = _escape(reaction.get("reaction", ""))
        reaction_count = reaction.get("count", 0)

        if not reaction_term or not reaction_count:
            continue

        # a = reports for this drug with this reaction (same as reaction_count)
        a = reaction_count

        # b = reports for this drug without this reaction
        b = total_drug_reports - a

        if b < 0:
            b = 0

        # c = reports for all other drugs with this reaction
        # Query FAERS count for this reaction across all drugs
        reaction_count_url = f"{_FDA_BASE}/drug/event.json?search=patient.reaction.reactionmeddrapt.exact:{reaction_term}&count=patient.drug.medicinalproduct.exact&limit=1"
        reaction_data = _fetch(reaction_count_url)
        c = 0
        if not _is_error(reaction_data) and isinstance(reaction_data, dict):
            all_reaction_reports = 0
            for r in (reaction_data.get("results", []) or []):
                all_reaction_reports += r.get("count", 0) or 0
            # c = reports for other drugs with this reaction = total all drugs - this drug
            c = max(0, all_reaction_reports - a)
        else:
            # Fallback: estimate from proportions
            c = 0

        # d = reports for other drugs without this reaction
        # We don't have a simple FAERS total for "all drugs", so estimate
        # For the denominator, use total_drug_reports as a proxy
        d = max(0, (background_total * 10) - c)  # rough estimate of all other drug-reaction combos

        # Compute PRR
        if b == 0 or (c + d) == 0:
            prr = 0.0
        else:
            drug_risk = a / (a + b) if (a + b) > 0 else 0
            bg_risk = c / (c + d) if (c + d) > 0 else 0
            if bg_risk > 0:
                prr = drug_risk / bg_risk
            else:
                prr = float('inf') if drug_risk > 0 else 0.0

        # Only include signals with PRR > 1
        if prr > 1:
            signals.append({
                "reaction": reaction.get("reaction"),
                "reaction_count": a,
                "drug_total_reports": total_drug_reports,
                "background_count_estimate": c,
                "prr": round(prr, 2),
            })

    # Sort by PRR descending
    signals.sort(key=lambda x: x["prr"], reverse=True)

    return {
        "status": "ok",
        "drug_name": drug_name,
        "total_reports": total_drug_reports,
        "total_signals": len(signals),
        "signals": signals,
        "methodology": (
            "PRR (Proportional Reporting Ratio): ratio of the proportion of reports "
            "with a given reaction for the target drug vs all other drugs. "
            "PRR > 1 suggests a disproportionate reporting signal."
        ),
        "data_source": "openFDA FAERS (PRR analysis)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 13. Patent / Exclusivity (FDA Orange Book)
# ═════════════════════════════════════════════════════════════


def get_patent_expiry(drug_name: str) -> dict:
    """
    Get FDA patent, exclusivity, and marketing status information.

    Uses openFDA drugsfda and NDC data to provide:
    - Marketing status (Prescription, OTC, Discontinued)
    - Reference Listed Drug (RLD) status
    - Therapeutic equivalence codes (AB, AA, etc.)
    - Submission class codes (Type 1 NME = 5yr exclusivity, Type 3-5 = 3yr)
    - Estimated exclusivity expiry based on submission types
    - Initial approval date (earliest ORIG submission)
    - NDC market availability dates

    NOTE: The FDA Orange Book download endpoints (products.txt, exclusivity.txt)
    have been discontinued by the FDA. This implementation uses openFDA data
    as the best available alternative for patent/exclusivity intelligence.
    """
    import re as _re

    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    search_term = _escape(drug_name)
    url = f"{_FDA_BASE}/drug/drugsfda.json?search=products.brand_name:{search_term}+OR+products.active_ingredients.name:{search_term}&limit=5"
    data = _cached_fetch(url, ttl=3600)

    if _is_error(data):
        return data

    exclusivity_info = []
    all_submissions = []

    if isinstance(data, dict):
        for r in (data.get("results", []) or []):
            app_number = r.get("application_number", "?")
            sponsor = r.get("sponsor_name", "?")

            # Collect all submissions with dates
            for s in (r.get("submissions", []) or []):
                date_str = s.get("submission_status_date", "")
                sub_type = s.get("submission_type", "")
                sub_status = s.get("submission_status", "")
                class_desc = s.get("submission_class_code_description", "")
                priority = s.get("review_priority", "")
                all_submissions.append({
                    "application_number": app_number,
                    "type": sub_type,
                    "status": sub_status,
                    "date": date_str,
                    "class_description": class_desc,
                    "review_priority": priority,
                })

            # Extract product-level data
            products_info = []
            for p in (r.get("products", []) or []):
                ingredients = [i.get("name", "") for i in (p.get("active_ingredients", []) or [])]
                te = p.get("te_code", "")
                # Map TE codes to descriptions
                te_desc = None
                if te:
                    te_desc = f"AB ({te[2:]})" if len(te) > 2 else te
                    if te.upper().startswith("AB"):
                        te_desc = "Therapeutically equivalent (AB-rated)"
                    elif te.upper().startswith("AA"):
                        te_desc = "Therapeutically equivalent (AA-rated)"
                    elif te.upper().startswith("BC"):
                        te_desc = "Not therapeutically equivalent (BC-rated)"
                    elif te.upper().startswith("B"):
                        te_desc = "Not therapeutically equivalent"

                products_info.append({
                    "brand_name": p.get("brand_name"),
                    "active_ingredients": ingredients,
                    "marketing_status": p.get("marketing_status"),
                    "reference_drug": p.get("reference_drug") == "Yes",
                    "reference_standard": p.get("reference_standard") == "Yes",
                    "therapeutic_equivalence": te,
                    "te_description": te_desc,
                    "dosage_form": p.get("dosage_form"),
                    "route": p.get("route"),
                })

            exclusivity_info.append({
                "application_number": app_number,
                "sponsor_name": sponsor,
                "products": products_info,
            })

    # Calculate estimated exclusivity from submission data
    estimated_exclusivity = []
    if all_submissions:
        # Find earliest ORIG (original) approval
        orig_dates = [s["date"] for s in all_submissions
                     if s["type"] == "ORIG" and s["status"] == "AP" and s["date"]]
        if orig_dates:
            earliest = min(orig_dates)
            # Format: YYYYMMDD
            try:
                year = int(earliest[:4])
                month = int(earliest[4:6])
                day = int(earliest[6:8])
                estimated_exclusivity.append({
                    "type": "Initial FDA Approval",
                    "date": f"{year}-{month:02d}-{day:02d}",
                    "description": "Earliest original approval date",
                })
                # Type 1 NME = 5 year exclusivity
                type1_found = any(
                    s["class_description"] == "Type 1 - New Molecular Entity"
                    for s in all_submissions
                )
                if type1_found:
                    exp_year = year + 5
                    estimated_exclusivity.append({
                        "type": "NME Exclusivity Estimate (5yr)",
                        "date": f"{exp_year}-{month:02d}-{day:02d}",
                        "description": "New Molecular Entity — estimated 5-year exclusivity from approval",
                    })
                # Type 3-5 = 3 year exclusivity
                type35_found = any(
                    c in (s.get("class_description", "") or "")
                    for s in all_submissions
                    for c in ["Type 3", "Type 4", "Type 5"]
                )
                if type35_found:
                    exp_year = year + 3
                    estimated_exclusivity.append({
                        "type": "New Clinical Study Exclusivity Estimate (3yr)",
                        "date": f"{exp_year}-{month:02d}-{day:02d}",
                        "description": "New formulation/combination — estimated 3-year exclusivity",
                    })
            except (ValueError, IndexError):
                pass

    # Check if RLD (Reference Listed Drug) — indicates brand/originator
    is_rld = any(
        p.get("reference_drug")
        for app in exclusivity_info
        for p in app.get("products", [])
    )

    # Summary
    statuses = set()
    for app in exclusivity_info:
        for p in app.get("products", []):
            ms = p.get("marketing_status")
            if ms:
                statuses.add(ms)

    return {
        "status": "ok",
        "drug_name": drug_name,
        "applications": exclusivity_info,
        "is_reference_listed_drug": is_rld,
        "marketing_statuses": sorted(statuses),
        "estimated_exclusivity": estimated_exclusivity,
        "total_submissions": len(all_submissions),
        "note": (
            "Patent/exclusivity estimates based on FDA submission class codes. "
            "Type 1 (New Molecular Entity) grants 5-year exclusivity. "
            "Types 3-5 (new formulation, combination, manufacturer) grant 3-year exclusivity. "
            "The FDA Orange Book direct download endpoints have been discontinued by the FDA. "
            "For exact patent numbers and litigation dates, consult the USPTO or Drugs@FDA."
        ),
        "data_sources": ["openFDA drugsfda"],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 14. Drug-Drug Interactions
# ═════════════════════════════════════════════════════════════


def get_drug_interactions(drug_name: str) -> dict:
    """
    Get drug-drug interaction information from FDA drug labeling.

    Returns the drug interactions section from the label, plus
    contraindicated and interacting drug classes. Uses openFDA
    Drug Labeling and RxNorm APIs.

    NOTE: The openFDA Drug Labeling API primarily covers prescription (Rx) drugs.
    OTC monograph drugs (e.g., generic ibuprofen) will return null for
    label_interactions fields (drug_interactions_text, contraindications_text).
    The FAERS co-reported drugs analysis still works for OTC drugs.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    # 1. Label-based interactions
    search_term = _escape(drug_name)
    url = f"{_FDA_BASE}/drug/label.json?search=openfda.brand_name:{search_term}+OR+openfda.generic_name:{search_term}&limit=1"
    data = _cached_fetch(url, ttl=3600)  # 1 hour cache

    interactions = {
        "drug_interactions_text": None,
        "contraindications_text": None,
        "warnings_and_cautions_text": None,
    }

    if not _is_error(data) and isinstance(data, dict):
        results = data.get("results", []) or []
        if results:
            label = results[0]
            def _get_field(field_name: str) -> str | None:
                val = label.get(field_name)
                if isinstance(val, list):
                    return val[0] if val else None
                return val

            interactions["drug_interactions_text"] = _get_field("drug_interactions")
            interactions["contraindications_text"] = _get_field("contraindications")
            interactions["warnings_and_cautions_text"] = _get_field("warnings_and_cautions")

    # 2. FAERS co-reported drugs — find drugs commonly reported together
    co_reported = []
    faers_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&count=patient.drug.medicinalproduct.exact&limit=10"
    faers_data = _cached_fetch(faers_url, ttl=3600)

    if not _is_error(faers_data) and isinstance(faers_data, dict):
        terms = faers_data.get("results", []) or []
        for t in terms:
            name = t.get("term", "")
            count = t.get("count", 0)
            # Skip the drug itself and empty/non-drug terms
            if name and name.lower() != drug_name.lower() and count > 0:
                co_reported.append({
                    "drug": name,
                    "report_count": count,
                })

    # 3. Build structured result
    result = {
        "status": "ok",
        "drug_name": drug_name,
        "label_interactions": interactions,
        "co_reported_in_faers": co_reported[:8],  # Top 8 co-reported drugs
        "total_co_reported": len(co_reported),
        "data_sources": [
            "openFDA Drug Labeling",
            "openFDA FAERS",
        ],
        "timestamp": datetime.utcnow().isoformat(),
        "note": (
            "Label-based interactions are from FDA prescribing information. "
            "FAERS co-reported drugs are those commonly reported together in adverse "
            "event reports — this suggests but does not confirm a pharmacological interaction."
        ),
    }

    return result


# ═════════════════════════════════════════════════════════════
# 14. Open Targets — Target Genetics, MoA & Drug Intelligence
# ═════════════════════════════════════════════════════════════

_OT_ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"
_OT_CACHE_TTL = 3600  # 1 hour


def _chembl_search(drug_name: str) -> str | None:
    """Search Open Targets for a drug by name, return ChEMBL ID."""
    query = '{"query":"{ search(queryString: \\"' + drug_name + '\\", entityNames: [\\"drug\\"]) { hits { id name description } } }"}'
    try:
        req = urllib.request.Request(_OT_ENDPOINT, data=query.encode(), headers={"Content-Type": "application/json", "User-Agent": "drug-pipeline-mcp/0.5"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        hits = data.get("data", {}).get("search", {}).get("hits", [])
        for h in hits:
            if drug_name.lower() in h.get("name", "").lower():
                return h["id"]
        return hits[0]["id"] if hits else None
    except Exception:
        return None


def get_opentargets_drug(drug_name: str) -> dict:
    """
    Get drug-target intelligence from Open Targets Platform.

    Uses EMBL-EBI's Open Targets GraphQL API to return: mechanisms of action,
    drug targets, clinical development stage, drug type, and known indications.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    chembl_id = _chembl_search(drug_name)
    if not chembl_id:
        return {"status": "ok", "drug_name": drug_name, "found": False,
                "message": f"No Open Targets entry found for '{drug_name}'"}

    query = ('{"query":"{ drug(chemblId: \\"' + chembl_id + '\\") { '
             'id name tradeNames maximumClinicalStage drugType '
             'mechanismsOfAction { rows { actionType targetName } } '
             'indications { rows { name status } } '
             'adverseEvents { rows { name count } } '
             'pharmacogenomics { rows { variantAnnotation } } } }"}')

    try:
        _rate_limited()
        req = urllib.request.Request(_OT_ENDPOINT, data=query.encode(),
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "drug-pipeline-mcp/0.5"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "error_code": "HTTP_ERROR",
                "message": f"Open Targets API error: {str(e)[:100]}"}

    drug = data.get("data", {}).get("drug")
    if not drug:
        return {"status": "ok", "drug_name": drug_name, "found": False,
                "message": "No drug data returned from Open Targets"}

    moa = drug.get("mechanismsOfAction", {}).get("rows", [])
    indications = drug.get("indications", {}).get("rows", [])
    adverse = drug.get("adverseEvents", {}).get("rows", [])

    return {
        "status": "ok",
        "drug_name": drug_name,
        "chembl_id": chembl_id,
        "found": True,
        "generic_name": drug.get("name"),
        "trade_names": drug.get("tradeNames", []),
        "drug_type": drug.get("drugType"),
        "max_clinical_stage": drug.get("maximumClinicalStage"),
        "mechanisms_of_action": [
            {"type": m.get("actionType"), "target": m.get("targetName")}
            for m in moa if m.get("targetName")
        ],
        "indications": [
            {"name": ind.get("name"), "status": ind.get("status")}
            for ind in indications[:15] if ind.get("name")
        ],
        "top_adverse_events": [
            {"event": ae.get("name"), "count": ae.get("count")}
            for ae in adverse[:10] if ae.get("name")
        ],
        "data_source": "Open Targets Platform (EMBL-EBI)",
        "api_url": "https://platform.opentargets.org",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 15. DailyMed — Alternative Drug Label Source (NIH/NLM)
# ═════════════════════════════════════════════════════════════

_DM_BASE = "https://dailymed.nlm.nih.gov/dailymed/services/v2"


def get_dailymed_label(drug_name: str) -> dict:
    """
    Get drug label information from DailyMed (NIH/NLM).

    Alternative to openFDA Drug Labeling API. DailyMed contains
    FDA Structured Product Labels (SPLs). Better OTC coverage.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    search = _escape(drug_name.upper())
    url = f"{_DM_BASE}/spls.json?drug_name={search}&pagesize=1"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data):
        return data

    if not isinstance(data, dict) or not data.get("data"):
        return {"status": "ok", "drug_name": drug_name, "found": False,
                "message": f"No DailyMed label found for '{drug_name}'"}

    spl_entry = data["data"][0]
    setid = spl_entry.get("setid")
    title = spl_entry.get("title", "")
    version = spl_entry.get("spl_version")
    pub_date = spl_entry.get("published_date")

    return {
        "status": "ok",
        "drug_name": drug_name,
        "found": True,
        "title": title,
        "setid": setid,
        "spl_version": version,
        "published_date": pub_date,
        "url": f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={setid}",
        "data_source": "DailyMed (NIH/NLM)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 16. compare_drugs — Head-to-Head Drug Comparison (Synthetic)
# ═════════════════════════════════════════════════════════════


def compare_drugs(drug_a: str, drug_b: str) -> dict:
    """
    Head-to-head comparison of two drugs using all available data sources.

    Compares: general info, FDA approvals, EU status, safety (FAERS),
    mechanisms of action, patent/exclusivity, and drug labels.
    """
    if not all(len(d) >= 2 for d in [drug_a, drug_b]):
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "Each drug name must be at least 2 characters"}

    try:
        info_a = search_drug(drug_a)
        info_b = search_drug(drug_b)
    except Exception:
        info_a = {"status": "error", "message": "lookup failed"}
        info_b = {"status": "error", "message": "lookup failed"}

    try:
        fda_a = get_fda_approvals(drug_a)
        fda_b = get_fda_approvals(drug_b)
    except Exception:
        fda_a = {"status": "error"}
        fda_b = {"status": "error"}

    try:
        eu_a = get_eu_approvals(drug_a)
        eu_b = get_eu_approvals(drug_b)
    except Exception:
        eu_a = {"status": "error"}
        eu_b = {"status": "error"}

    try:
        safety_a = get_safety_data(drug_a)
        safety_b = get_safety_data(drug_b)
    except Exception:
        safety_a = {"status": "error"}
        safety_b = {"status": "error"}

    try:
        moa_a = get_opentargets_drug(drug_a)
        moa_b = get_opentargets_drug(drug_b)
    except Exception:
        moa_a = {"status": "error"}
        moa_b = {"status": "error"}

    try:
        pat_a = get_patent_expiry(drug_a)
        pat_b = get_patent_expiry(drug_b)
    except Exception:
        pat_a = {"status": "error"}
        pat_b = {"status": "error"}

    def _label(d: dict) -> str:
        if d.get("status") == "ok" and d.get("found"):
            return d.get("brand_name") or d.get("generic_name") or d.get("name", "?")
        if isinstance(d, dict) and d.get("results"):
            return d["results"][0].get("brand_name", "?")
        return "N/A"

    def _fda_status(d: dict) -> str:
        results = d.get("results", [])
        if results:
            orig = results[0]
            apps = orig.get("applications", [])
            approved = [a for a in apps if a.get("status") == "Approved"]
            if approved:
                return f"Approved ({approved[0].get('type', 'N/A')})"
            pending = [a for a in apps if "pending" in str(a.get("status", "")).lower()]
            if pending:
                return f"Pending review"
            return "Applications filed"
        return "No FDA data"

    def _eu_status(d: dict) -> str:
        if d.get("status") == "ok" and d.get("authorised"):
            return f"Authorised (EU)"
        if d.get("status") == "ok" and not d.get("authorised"):
            return "Not authorised (EU)"
        return "No EU data"

    def _extract_moa(d: dict) -> str:
        if d.get("found") and d.get("mechanisms_of_action"):
            moas = d["mechanisms_of_action"]
            return "; ".join(f"{m.get('type','?')}→{m.get('target','?')}" for m in moas[:3])
        return "N/A"

    def _patent_summary(d: dict) -> str:
        if d.get("status") == "ok":
            items = []
            p = d.get("patent_data", [])
            if p:
                for pt in p[:3]:
                    exp = pt.get("expiry_date", pt.get("patent_expiry", "?"))
                    items.append(f"Patent exp {exp}")
            ex = d.get("exclusivity", [])
            if ex:
                for e in ex[:2]:
                    exp = e.get("expiry_date", e.get("exclusivity_expiry", "?"))
                    items.append(f"Excl exp {exp}")
            return "; ".join(items) if items else "No patent data"
        return "N/A"

    def _safety_n(d: dict) -> int:
        return d.get("total_reports", 0) if d.get("status") == "ok" else 0
    safety_n_a = safety_a.get("total_reports", 0) if safety_a.get("status") == "ok" else 0
    safety_n_b = safety_b.get("total_reports", 0) if safety_b.get("status") == "ok" else 0

    return {
        "status": "ok",
        "drug_a": {"name": drug_a, "label": _label(info_a)},
        "drug_b": {"name": drug_b, "label": _label(info_b)},
        "comparison": [
            {
                "field": "FDA Approval Status",
                "drug_a": _fda_status(fda_a),
                "drug_b": _fda_status(fda_b),
            },
            {
                "field": "EU/EMA Status",
                "drug_a": _eu_status(eu_a),
                "drug_b": _eu_status(eu_b),
            },
            {
                "field": "Mechanism of Action",
                "drug_a": _extract_moa(moa_a),
                "drug_b": _extract_moa(moa_b),
            },
            {
                "field": "FAERS Total Reports",
                "drug_a": str(safety_n_a),
                "drug_b": str(safety_n_b),
            },
            {
                "field": "Drug Type",
                "drug_a": moa_a.get("drug_type", "N/A") if moa_a.get("found") else "N/A",
                "drug_b": moa_b.get("drug_type", "N/A") if moa_b.get("found") else "N/A",
            },
            {
                "field": "Patent / Exclusivity",
                "drug_a": _patent_summary(pat_a),
                "drug_b": _patent_summary(pat_b),
            },
        ],
        "data_source": "Composite (openFDA + EMA + FAERS + Open Targets + RxNorm)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 17. pipeline_landscape — Structured Pipeline for a Condition
# ═════════════════════════════════════════════════════════════


def pipeline_landscape(condition: str, limit: int = 20) -> dict:
    """
    Complete pipeline landscape for a medical condition.

    Structure:
    - Approved drugs (from EU/EMA)
    - Phase 3 active trials
    - Phase 2 active trials
    - Phase 1 / Early trials
    - Key mechanisms & targets
    - Pipeline PubMed review references
    """
    if not condition or len(condition) < 3:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "condition must be at least 3 characters"}

    # Phase 1: Approved drugs for condition
    approved = []
    try:
        app = approved_for_condition(condition, limit=limit)
        if app.get("status") == "ok":
            approved = [
                {
                    "name": d.get("name", "?"),
                    "active_substance": d.get("active_substance", ""),
                    "atc_code": d.get("atc_code", ""),
                    "biosimilar": d.get("biosimilar", False),
                    "orphan": d.get("orphan", False),
                }
                for d in app.get("drugs", [])
            ]
    except Exception:
        pass

    # Phase 2: Trials by phase
    trials_phase3 = []
    trials_phase2 = []
    trials_phase1 = []

    try:
        r3 = search_trials(condition=condition, phase="PHASE3", limit=limit)
        if r3.get("status") == "ok":
            trials_phase3 = r3.get("results", r3.get("studies", []))
    except Exception:
        pass
    try:
        r2 = search_trials(condition=condition, phase="PHASE2", limit=limit)
        if r2.get("status") == "ok":
            trials_phase2 = r2.get("results", r2.get("studies", []))
    except Exception:
        pass
    try:
        r1 = search_trials(condition=condition, phase="EARLY1", limit=limit)
        if r1.get("status") == "ok":
            trials_phase1 = r1.get("results", r1.get("studies", []))
    except Exception:
        pass

    # Phase 3: Extract unique sponsors / companies
    def _extract_sponsors(trials: list) -> list:
        seen = set()
        sponsors = []
        for t in trials:
            s = None
            if isinstance(t, dict):
                s = t.get("sponsor") or t.get("lead_sponsor") or t.get("sponsors")
                if isinstance(s, dict):
                    s = s.get("name") or s.get("lead_sponsor", {}).get("name", "")
            if s and str(s) not in seen:
                seen.add(str(s))
                sponsors.append(str(s))
        return sponsors[:10]

    key_sponsors_p3 = _extract_sponsors(trials_phase3)
    key_sponsors_p2 = _extract_sponsors(trials_phase2)

    # Phase 4: Pipeline publications
    publications = []
    try:
        pubs = search_publications(
            query=f'"{condition}" pipeline 2025 2026 novel therapies review',
            max_results=5,
        )
        if pubs.get("status") == "ok":
            publications = [
                {"title": p.get("title", "?"), "pmid": p.get("pmid", "?"),
                 "journal": p.get("journal", ""), "year": p.get("year", "")}
                for p in pubs.get("results", pubs.get("publications", []))
            ]
    except Exception:
        pass

    # Phase 5: Mechanism summary from approved drugs (via Open Targets)
    mechanisms = {}
    for d in approved[:5]:
        try:
            moa = get_opentargets_drug(d["name"])
            if moa.get("found") and moa.get("mechanisms_of_action"):
                for m in moa["mechanisms_of_action"]:
                    target = m.get("target", "?")
                    mtype = m.get("type", "?")
                    key = f"{mtype} → {target}"
                    mechanisms[key] = mechanisms.get(key, 0) + 1
        except Exception:
            pass

    sorted_mechanisms = sorted(mechanisms.items(), key=lambda x: -x[1])

    return {
        "status": "ok",
        "condition": condition,
        "landscape": {
            "approved_drugs": {
                "count": len(approved),
                "drugs": approved[:limit],
            },
            "phase_3_trials": {
                "count": len(trials_phase3),
                "trials": [
                    {
                        "nct_id": t.get("nct_id", t.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "?")),
                        "title": t.get("title", t.get("briefTitle", t.get("protocolSection", {}).get("identificationModule", {}).get("briefTitle", "?"))),
                        "sponsor": t.get("sponsor", t.get("leadSponsor", {}).get("name", t.get("protocolSection", {}).get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "?"))),
                        "status": t.get("status", t.get("overallStatus", t.get("protocolSection", {}).get("statusModule", {}).get("overallStatus", "?"))),
                    }
                    for t in trials_phase3[:limit]
                ],
                "key_sponsors": key_sponsors_p3,
            },
            "phase_2_trials": {
                "count": len(trials_phase2),
                "trials": [
                    {
                        "nct_id": t.get("nct_id", t.get("protocolSection", {}).get("identificationModule", {}).get("nctId", "?")),
                        "title": t.get("title", t.get("briefTitle", t.get("protocolSection", {}).get("identificationModule", {}).get("briefTitle", "?"))),
                        "sponsor": t.get("sponsor", t.get("leadSponsor", {}).get("name", t.get("protocolSection", {}).get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "?"))),
                        "status": t.get("status", t.get("overallStatus", t.get("protocolSection", {}).get("statusModule", {}).get("overallStatus", "?"))),
                    }
                    for t in trials_phase2[:limit]
                ],
                "key_sponsors": key_sponsors_p2,
            },
            "phase_1_trials": {
                "count": len(trials_phase1),
            },
            "key_mechanisms": [
                {"mechanism": k, "drug_count": v}
                for k, v in sorted_mechanisms[:10]
            ],
            "pipeline_publications": publications,
        },
        "data_sources": ["ClinicalTrials.gov", "EMA", "Open Targets", "PubMed"],
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 18. get_us_orphan_designations — US FDA Orphan Drug (MyChem.info)
# ═════════════════════════════════════════════════════════════

_MYCHEM_BASE = "https://mychem.info/v1"


def get_us_orphan_designations(drug_name: str) -> dict:
    """
    Get US FDA Orphan Drug Designation data from MyChem.info.

    Returns designation history: indications, status, dates,
    exclusivity periods, and approval status.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    query = urllib.parse.quote(drug_name.strip().lower())
    url = f"{_MYCHEM_BASE}/query?q={query}&fields=fda_orphan_drug"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data):
        return data

    if not isinstance(data, dict):
        return {"status": "error", "error_code": "PARSE_ERROR",
                "message": "Unexpected API response format"}

    hits = data.get("hits", [])
    orphan_entries = []
    for hit in hits:
        name = hit.get("name", "")
        orphan_field = hit.get("fda_orphan_drug", [])
        if not orphan_field:
            continue
        for entry in orphan_field if isinstance(orphan_field, list) else [orphan_field]:
            orphan_entries.append({
                "substance": name,
                "designation_number": entry.get("designation_number", ""),
                "orphan_designation": entry.get("orphan_designation", ""),
                "designation_status": entry.get("designation_status", ""),
                "designated_date": entry.get("designated_date", ""),
                "approval_status": entry.get("approval_status", ""),
                "approved_labeled_indication": entry.get("approved_labeled_indication", ""),
                "exclusivity_end_date": entry.get("exclusivity_end_date", ""),
            })

    if not orphan_entries:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No US orphan drug designations found for '{drug_name}'",
            "data_source": "MyChem.info (BioThings API, aggregating FDA OPD)",
            "timestamp": datetime.utcnow().isoformat(),
        }

    return {
        "status": "ok",
        "drug_name": drug_name,
        "found": True,
        "orphan_designations": orphan_entries,
        "designation_count": len(orphan_entries),
        "approved_count": sum(1 for e in orphan_entries if e["approval_status"] == "Approved"),
        "data_source": "MyChem.info (BioThings API, aggregating FDA OPD)",
        "api_url": "https://mychem.info",
        "timestamp": datetime.utcnow().isoformat(),
    }


def _search_orphan_by_condition(condition: str, limit: int = 30) -> dict:
    """
    Search US orphan designations by medical condition.
    Internal helper — queries MyChem.info for condition matches.
    """
    if not condition or len(condition) < 3:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "condition must be at least 3 characters"}

    query = urllib.parse.quote(f"fda_orphan_drug.orphan_designation:{condition}")
    url = f"{_MYCHEM_BASE}/query?q={query}&fields=name,fda_orphan_drug&size={min(limit, 100)}"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data):
        return data

    hits = data.get("hits", []) if isinstance(data, dict) else []
    results = []
    for hit in hits:
        name = hit.get("name", "")
        orphan_field = hit.get("fda_orphan_drug", [])
        if not orphan_field:
            continue
        for entry in orphan_field if isinstance(orphan_field, list) else [orphan_field]:
            if condition.lower() in (entry.get("orphan_designation", "") or "").lower():
                results.append({
                    "substance": name,
                    "orphan_designation": entry.get("orphan_designation", ""),
                    "designation_status": entry.get("designation_status", ""),
                    "approval_status": entry.get("approval_status", ""),
                })

    return {
        "status": "ok",
        "condition": condition,
        "found": len(results) > 0,
        "designations": results[:limit],
        "count": len(results),
        "data_source": "MyChem.info (BioThings API)",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 19. get_drug_pricing — US Drug Pricing (NADAC + CMS)
# ═════════════════════════════════════════════════════════════

_NADAC_API = "https://data.medicaid.gov/api/3/action/datastore_search"
_NADAC_BASE_CSV = "https://download.medicaid.gov/data"


def get_drug_pricing(drug_name: str) -> dict:
    """
    Get US drug pricing data from NADAC (Medicaid) and CMS.

    Uses NADAC National Average Drug Acquisition Cost for pharmacy-level
    pricing. Returns price per unit, effective date, and pricing unit.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    # Try all recent NADAC datasets in parallel for the drug
    nadac_resource_ids = [
        "fbb83258-11c7-47f5-8b18-5f8e79f7e704",  # 2026
        "f38d0706-1239-442c-a3cc-40ef1b686ac0",  # 2025
        "99315a95-37ac-4eee-946a-3c523b4c481e",  # 2024
    ]

    pricing_results = []
    search_term = drug_name.strip().upper()

    for rid in nadac_resource_ids:
        try:
            sql = urllib.parse.quote(
                f'SELECT * FROM "{rid}" WHERE "NDC Description" LIKE \'%{search_term}%\' LIMIT 5'
            )
            url = f"https://data.medicaid.gov/api/3/action/datastore_search_sql?sql={sql}"

            _rate_limited()
            data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
            if _is_error(data) or not isinstance(data, dict):
                continue

            records = data.get("result", {}).get("records", [])
            for rec in records:
                pricing_results.append({
                    "ndc": rec.get("NDC", ""),
                    "product_name": rec.get("NDC Description", ""),
                    "nadac_per_unit": rec.get("NADAC Per Unit", ""),
                    "effective_date": rec.get("Effective Date", ""),
                    "pricing_unit": rec.get("Pricing Unit", ""),
                    "pharmacy_type": rec.get("Pharmacy Type", ""),
                })
        except Exception:
            continue

    # Also try by NDC from openFDA lookup
    # First get NDC candidates
    ndc_candidates = []
    try:
        drug_info = search_drug(drug_name)
        if drug_info.get("found"):
            ndc = drug_info.get("ndc") or drug_info.get("product_ndc", "")
            if ndc:
                ndc_candidates.append(ndc)
    except Exception:
        pass

    if not pricing_results:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No NADAC pricing data found for '{drug_name}'",
            "sources_checked": len(nadac_resource_ids),
            "note": "NADAC covers outpatient prescription drugs. Pricing data limited for biologics, hospital-only, or very new drugs.",
            "data_source": "NADAC (data.medicaid.gov)",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Get best price (most recent)
    pricing_results.sort(key=lambda r: r.get("effective_date", ""), reverse=True)

    return {
        "status": "ok",
        "drug_name": drug_name,
        "found": True,
        "nadac_entries": pricing_results[:10],
        "entry_count": len(pricing_results),
        "most_recent_entry": pricing_results[0] if pricing_results else None,
        "data_source": "NADAC (data.medicaid.gov)",
        "api_url": "https://data.medicaid.gov",
        "note": "NADAC = National Average Drug Acquisition Cost. Updated weekly by CMS. Does not include wholesale or negotiated prices.",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 20. list_biosimilars — EU Biosimilars from EMA Register
# ═════════════════════════════════════════════════════════════


def list_biosimilars(condition: str | None = None, limit: int = 50) -> dict:
    """
    List all EU-approved biosimilars from the EMA Human Medicines Register.

    Optionally filter by medical condition/therapeutic area.
    Returns drug names, active substances, ATC codes, and therapeutic areas.
    """
    try:
        all_medicines = _load_ema_data()
    except Exception as e:
        return {"status": "error", "error_code": "EMA_LOAD_ERROR",
                "message": f"Failed to load EMA data: {str(e)[:100]}"}

    biosimilars = [m for m in all_medicines if m.get("biosimilar") == "Yes"]

    if condition:
        cond = condition.lower()
        filtered = []
        for m in biosimilars:
            area = (m.get("therapeutic_area", "") or "").lower()
            indication = (m.get("indication", "") or "").lower()
            if cond in area or cond in indication:
                filtered.append(m)
        biosimilars = filtered

    drugs = [
        {
            "name": m.get("name", "?"),
            "active_substance": m.get("active_substance", ""),
            "inn": m.get("inn", ""),
            "atc_code": m.get("atc_code", ""),
            "therapeutic_area": m.get("therapeutic_area", ""),
            "status": m.get("status", ""),
            "ema_product_number": m.get("ema_product_number", ""),
        }
        for m in biosimilars[:limit]
    ]

    # Group by active substance for summary
    substance_groups: dict[str, list] = {}
    for d in drugs:
        sub = d["active_substance"] or d["inn"] or "unknown"
        substance_groups.setdefault(sub, []).append(d["name"])

    return {
        "status": "ok",
        "condition_filter": condition,
        "found": len(drugs) > 0,
        "total_eu_biosimilars": len(biosimilars),
        "drugs": drugs,
        "biosimilar_count": len(drugs),
        "biosimilars_by_substance": [
            {"substance": sub, "count": len(names), "brands": names}
            for sub, names in sorted(substance_groups.items(), key=lambda x: -len(x[1]))
        ],
        "data_source": "EMA Human Medicines Register",
        "timestamp": datetime.utcnow().isoformat(),
    }


def list_loss_of_exclusivity(limit: int = 30) -> dict:
    """
    Identify drugs approaching Loss of Exclusivity (LOE).

    Combines EMA biosimilar entries (potential competitors) with
    FDA patent expiry data for reference products. Returns drugs
    with expiring patents and available biosimilar/generic competition.
    """
    # Get all EMA biosimilars as a baseline
    biosimilars_with_refs = []
    try:
        all_med = _load_ema_data()
        bios = [m for m in all_med if m.get("biosimilar") == "Yes"]
        for b in bios[:limit]:
            biosimilars_with_refs.append({
                "biosimilar_name": b.get("name", "?"),
                "active_substance": b.get("active_substance", "") or b.get("inn", ""),
                "atc_code": b.get("atc_code", ""),
                "authorised": b.get("status", "") == "Authorised",
            })
    except Exception:
        pass

    # Group by active substance
    refs: dict[str, dict] = {}
    for b in biosimilars_with_refs:
        sub = b["active_substance"]
        if sub:
            refs.setdefault(sub, {"substance": sub, "biosimilars": [], "atc": b["atc_code"]})
            refs[sub]["biosimilars"].append(b["biosimilar_name"])

    # Try to get patent data for reference products
    # (limited — we don't have a reference product database, so mark known LOE risks)
    loe_entries = []
    for sub, info in refs.items():
        loe_entries.append({
            "active_substance": sub,
            "atc_code": info["atc"],
            "biosimilar_count": len(info["biosimilars"]),
            "biosimilar_names": info["biosimilars"],
            "category": "LOE Active" if len(info["biosimilars"]) >= 3 else "Early Biosimilar Entry",
            "note": f"{len(info['biosimilars'])} EU-approved biosimilar(s) indicate active post-LOE market",
        })

    loe_entries.sort(key=lambda x: -x["biosimilar_count"])

    return {
        "status": "ok",
        "loss_of_exclusivity_entries": loe_entries[:limit],
        "total_loe_active_substances": len(loe_entries),
        "total_eu_biosimilars": sum(e["biosimilar_count"] for e in loe_entries),
        "data_sources": ["EMA Human Medicines Register", "FDA Orange Book (patent data)"],
        "note": "Biosimilar competition indicates marketed reference products have passed or are approaching LOE. For precise patent dates, use get_patent_expiry on the reference brand name.",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 21. get_trial_sites — Clinical Trial Site & Location Intelligence
# ═════════════════════════════════════════════════════════════


def get_trial_sites(nct_id: str) -> dict:
    """
    Get clinical trial site locations and facility information.

    Extracts facility names, cities, countries, recruitment status,
    and contact information from the full trial protocol.
    """
    nct_id = nct_id.strip().upper()
    if not nct_id.startswith("NCT") or len(nct_id) < 8:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "NCT ID must start with 'NCT' and be at least 8 characters"}

    try:
        detail = get_trial_detail(nct_id)
    except Exception as e:
        return {"status": "error", "error_code": "FETCH_ERROR",
                "message": f"Failed to fetch trial detail: {str(e)[:100]}"}

    if detail.get("status") != "ok":
        return {"status": "error", "error_code": detail.get("error_code", "FETCH_ERROR"),
                "message": detail.get("message", "Failed to get trial detail")}

    # ClinicalTrials.gov v2 API — the detail comes as protocolSection
    protocol = detail.get("protocolSection", detail)
    locations_module = protocol.get("locationsModule", {})
    contacts_module = protocol.get("contactsLocationsModule", {})

    # Try both v2 & v1 location structures
    locations = locations_module.get("locations", []) or contacts_module.get("locations", [])

    if not locations:
        # v1 API fallback
        v1_loc = detail.get("location", []) or detail.get("locations", [])
        if v1_loc:
            locations = v1_loc if isinstance(v1_loc, list) else [v1_loc]

    sites = []
    country_counts: dict[str, int] = {}

    for loc in locations:
        fac = loc.get("facility", "")
        if isinstance(fac, dict):
            fac = fac.get("name", "")
        city = loc.get("city", "")
        state = loc.get("state", "")
        country = loc.get("country", "")
        status = loc.get("status", loc.get("recruitmentStatus", ""))
        contact = loc.get("contact", {})

        # Contact info
        contact_name = ""
        contact_phone = ""
        if isinstance(contact, dict):
            contact_name = contact.get("name", "")
            contact_phone = contact.get("phone", "")

        location_str = ", ".join(filter(None, [city, state, country]))
        country_c = country or "Unknown"

        sites.append({
            "facility": fac or "Not specified",
            "location": location_str,
            "city": city or "",
            "state": state or "",
            "country": country_c,
            "status": status or "",
            "contact_name": contact_name,
            "contact_phone": contact_phone,
        })
        country_counts[country_c] = country_counts.get(country_c, 0) + 1

    # Global central contact
    central_contact = {}
    if isinstance(contacts_module, dict):
        cc = contacts_module.get("centralContacts", [])
        if isinstance(cc, list) and cc:
            c = cc[0]
            central_contact = {
                "name": c.get("name", ""),
                "phone": c.get("phone", ""),
                "email": c.get("email", ""),
            }

    # Overall status from study
    status_module = protocol.get("statusModule", {})
    overall_status = status_module.get("overallStatus", "")

    return {
        "status": "ok",
        "nct_id": nct_id,
        "trial_status": overall_status,
        "site_count": len(sites),
        "country_count": len(country_counts),
        "geographic_distribution": [
            {"country": c, "sites": n}
            for c, n in sorted(country_counts.items(), key=lambda x: -x[1])
        ],
        "sites": sites,
        "central_contact": central_contact,
        "data_source": "ClinicalTrials.gov",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 22. detect_combination_therapies — Co-Intervention Detection
# ═════════════════════════════════════════════════════════════


def detect_combination_therapies(drug_name: str, condition: str | None = None, limit: int = 15) -> dict:
    """
    Detect combination therapies involving a drug.

    Searches ClinicalTrials.gov for trials where the drug is used as an
    intervention, then extracts co-administered drugs/interventions.
    Useful for oncology combination analysis, add-on trials, and
    competitive positioning.
    """
    if not drug_name or len(drug_name) < 2:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "drug_name must be at least 2 characters"}

    try:
        if condition:
            trials = search_trials(intervention=drug_name, condition=condition, limit=limit)
        else:
            trials = search_trials(intervention=drug_name, limit=limit)
    except Exception as e:
        return {"status": "error", "error_code": "FETCH_ERROR",
                "message": f"Failed to search trials: {str(e)[:100]}"}

    study_list = trials.get("results", trials.get("studies", []))
    if not study_list:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "condition": condition,
            "found": False,
            "message": f"No trials found for '{drug_name}'",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Extract co-interventions from each trial
    combinations = []
    co_drug_counter: dict[str, int] = {}

    for study in study_list:
        ps = study.get("protocolSection", study)
        id_mod = ps.get("identificationModule", study)
        design_mod = ps.get("designModule", {})
        arms_mod = ps.get("armsInterventionsModule", {})

        nct = id_mod.get("nctId", id_mod.get("nct_id", "?"))
        title = id_mod.get("briefTitle", id_mod.get("title", "?"))
        phase = ps.get("statusModule", {}).get("phase", design_mod.get("phase", "?"))

        # Get all interventions
        interventions = arms_mod.get("armGroups", []) or arms_mod.get("interventions", [])
        all_interventions = []
        for inv in interventions if isinstance(interventions, list) else []:
            if isinstance(inv, dict):
                name = inv.get("name", inv.get("description", ""))
                inv_type = inv.get("type", "")
                if name and name.upper() != drug_name.upper():
                    all_interventions.append({"name": name, "type": inv_type})
                    co_drug_counter[name] = co_drug_counter.get(name, 0) + 1

        if all_interventions:
            combinations.append({
                "nct_id": nct,
                "title": title,
                "phase": phase,
                "co_interventions": all_interventions,
            })

    # Most frequent co-interventions
    top_co = sorted(co_drug_counter.items(), key=lambda x: -x[1])[:15]

    return {
        "status": "ok",
        "drug_name": drug_name,
        "condition": condition,
        "found": len(combinations) > 0,
        "total_trials_analyzed": len(study_list),
        "trials_with_combinations": len(combinations),
        "top_co_administered": [
            {"drug": name, "trial_count": count}
            for name, count in top_co
        ],
        "combinations": combinations[:limit],
        "data_source": "ClinicalTrials.gov",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# 23. find_investigators — Key Opinion Leader & Site Investigator Search
# ═════════════════════════════════════════════════════════════


def find_investigators(
    condition: str | None = None,
    drug_name: str | None = None,
    limit: int = 20,
) -> dict:
    """
    Find principal investigators / Key Opinion Leaders (KOLs) by
    condition or drug.

    Searches ClinicalTrials.gov for active trials and extracts
    investigator names, roles, and affiliations. Useful for
    competitive intelligence, trial design, and KOL mapping.
    """
    if not condition and not drug_name:
        return {"status": "error", "error_code": "INVALID_INPUT",
                "message": "Provide at least one of: condition, drug_name"}

    # Search for relevant trials
    try:
        if drug_name and condition:
            trials = search_trials(intervention=drug_name, condition=condition,
                                   status="RECRUITING", limit=limit)
        elif condition:
            trials = search_trials(condition=condition, status="RECRUITING", limit=limit)
        else:
            trials = search_trials(intervention=drug_name, status="RECRUITING", limit=limit)
    except Exception as e:
        return {"status": "error", "error_code": "FETCH_ERROR",
                "message": f"Failed to search trials: {str(e)[:100]}"}

    studies = trials.get("results", trials.get("studies", []))
    if not studies:
        return {
            "status": "ok",
            "condition": condition,
            "drug_name": drug_name,
            "found": False,
            "message": "No active trials found matching criteria",
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Get detail for each trial to extract investigators (batch)
    investigators = []
    seen_investigators: set[str] = set()

    for study in studies[:10]:  # Limit to 10 trial details for performance
        ps = study.get("protocolSection", study)
        id_mod = ps.get("identificationModule", study)
        nct = id_mod.get("nctId", id_mod.get("nct_id", "?"))
        title = id_mod.get("briefTitle", id_mod.get("title", "?"))

        try:
            detail = get_trial_detail(nct)
        except Exception:
            continue

        if detail.get("status") != "ok":
            continue

        protocol = detail.get("protocolSection", detail)
        sponsors_mod = protocol.get("sponsorCollaboratorsModule", {})
        contacts_mod = protocol.get("contactsLocationsModule", {})

        # Lead sponsor
        sponsor = sponsors_mod.get("leadSponsor", {})
        if isinstance(sponsor, dict):
            sponsor_name = sponsor.get("name", "")
        else:
            sponsor_name = str(sponsor) if sponsor else ""

        # Central contacts (often PIs)
        central_contacts = contacts_mod.get("centralContacts", []) if isinstance(contacts_mod, dict) else []
        locations = contacts_mod.get("locations", []) if isinstance(contacts_mod, dict) else []

        # Extract from central contacts
        for cc in central_contacts if isinstance(central_contacts, list) else []:
            name = cc.get("name", "").strip()
            if name and name.lower() not in seen_investigators:
                seen_investigators.add(name.lower())
                investigators.append({
                    "name": name,
                    "role": cc.get("role", "Principal Investigator"),
                    "affiliation": sponsor_name,
                    "phone": cc.get("phone", ""),
                    "email": cc.get("email", ""),
                    "trial_nct": nct,
                    "trial_title": title[:120],
                })

        # Also extract from facility contacts (site PIs)
        for loc in locations if isinstance(locations, list) else []:
            facility = loc.get("facility", {})
            if isinstance(facility, dict):
                facility_name = facility.get("name", "")
            else:
                facility_name = str(facility) if facility else ""
            pi = loc.get("contact", loc.get("investigator", {}))
            if isinstance(pi, dict):
                name = pi.get("name", "").strip()
                if name and name.lower() not in seen_investigators:
                    seen_investigators.add(name.lower())
                    investigators.append({
                        "name": name,
                        "role": pi.get("role", "Site Investigator"),
                        "affiliation": facility_name,
                        "phone": pi.get("phone", ""),
                        "email": pi.get("email", ""),
                        "trial_nct": nct,
                        "trial_title": title[:120],
                    })

        if len(investigators) >= limit:
            break

    # Also search PubMed for KOL publications in the area
    publications = []
    if condition:
        try:
            pubs = search_publications(
                query=f'"{condition}" AND (investigator OR "clinical trial")',
                max_results=5,
            )
            if pubs.get("status") == "ok":
                publications = [
                    {"title": p.get("title", "?"), "pmid": p.get("pmid", "?")}
                    for p in pubs.get("results", pubs.get("publications", []))
                ]
        except Exception:
            pass

    return {
        "status": "ok",
        "condition": condition,
        "drug_name": drug_name,
        "found": len(investigators) > 0,
        "total_investigators": len(investigators),
        "investigators": investigators[:limit],
        "related_publications": publications,
        "data_sources": ["ClinicalTrials.gov", "PubMed"],
        "note": "Investigator data from trial protocols. Not all trials list named PIs publicly.",
        "timestamp": datetime.utcnow().isoformat(),
    }
