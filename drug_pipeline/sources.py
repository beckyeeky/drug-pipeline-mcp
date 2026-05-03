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

    # Build query
    query_parts = []
    if condition:
        query_parts.append(f"AREA[ConditionSearch]/{_escape(condition)}")
    if intervention:
        query_parts.append(f"AREA[InterventionSearch]/{_escape(intervention)}")
    query = " AND ".join(query_parts) if query_parts else ""

    params = {"pageSize": min(limit, 100), "format": "json"}
    if query:
        params["query.term"] = query
    if condition and not query:
        params["query.cond"] = condition
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
    url = f"{_FDA_BASE}/drug/drugsfda.json?search=products.brand_name:{_escape(drug_name)}+OR+products.generic_name:{_escape(drug_name)}&limit=3"
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

    return {
        "status": "ok",
        "query": {"drug_name": drug_name, "condition": condition},
        "drug_info": drug_info,
        "fda_approvals": approvals,
        "eu_approvals": eu_approvals,
        "orphan_status": orphan_status,
        "approved_drugs_for_condition": condition_drugs,
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
