"""Additional registry and enrichment providers for drug-pipeline-mcp."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

from .sources import _FDA_BASE, _cached_fetch, _escape, _fetch, _is_error, _rate_limited, datetime

# ═════════════════════════════════════════════════════════════
# 14. Open Targets — Target Genetics, MoA & Drug Intelligence
# ═════════════════════════════════════════════════════════════

_OT_ENDPOINT = "https://api.platform.opentargets.org/api/v4/graphql"
_OT_CACHE_TTL = 3600  # 1 hour


def _chembl_search(drug_name: str) -> str | None:
    """Search Open Targets for a drug by name, return ChEMBL ID."""
    query = (
        '{"query":"{ search(queryString: \\"'
        + drug_name
        + '\\", entityNames: [\\"drug\\"]) { hits { id name description } } }"}'
    )
    try:
        timeout = _resolve_timeout(10)
        req = urllib.request.Request(
            _OT_ENDPOINT,
            data=query.encode(),
            headers={"Content-Type": "application/json", "User-Agent": "drug-pipeline-mcp/0.5"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    chembl_id = _chembl_search(drug_name)
    if not chembl_id:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No Open Targets entry found for '{drug_name}'",
        }

    query = (
        '{"query":"{ drug(chemblId: \\"' + chembl_id + '\\") { '
        "id name tradeNames maximumClinicalStage drugType "
        "mechanismsOfAction { rows { actionType targetName } } "
        "indications { rows { name status } } "
        "adverseEvents { rows { name count } } "
        'pharmacogenomics { rows { variantAnnotation } } } }"}'
    )

    try:
        timeout = _resolve_timeout(10)
        req = urllib.request.Request(
            _OT_ENDPOINT,
            data=query.encode(),
            headers={"Content-Type": "application/json", "User-Agent": "drug-pipeline-mcp/0.5"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {
            "status": "error",
            "error_code": "HTTP_ERROR",
            "message": f"Open Targets API error: {str(e)[:100]}",
        }

    drug = data.get("data", {}).get("drug")
    if not drug:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": "No drug data returned from Open Targets",
        }

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
            for m in moa
            if m.get("targetName")
        ],
        "indications": [
            {"name": ind.get("name"), "status": ind.get("status")}
            for ind in indications[:15]
            if ind.get("name")
        ],
        "top_adverse_events": [
            {"event": ae.get("name"), "count": ae.get("count")}
            for ae in adverse[:10]
            if ae.get("name")
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    search = _escape(drug_name.upper())
    url = f"{_DM_BASE}/spls.json?drug_name={search}&pagesize=1"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data):
        return data

    if not isinstance(data, dict) or not data.get("data"):
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No DailyMed label found for '{drug_name}'",
        }

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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    query = urllib.parse.quote(drug_name.strip().lower())
    url = f"{_MYCHEM_BASE}/query?q={query}&fields=fda_orphan_drug"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data):
        return data

    if not isinstance(data, dict):
        return {
            "status": "error",
            "error_code": "PARSE_ERROR",
            "message": "Unexpected API response format",
        }

    hits = data.get("hits", [])
    orphan_entries = []
    for hit in hits:
        orphan_field = hit.get("fda_orphan_drug", [])
        if not orphan_field:
            continue
        for entry in orphan_field if isinstance(orphan_field, list) else [orphan_field]:
            # Get substance name from entry.generic_name or hit.name or hit._id
            substance = entry.get("generic_name", "") or hit.get("name", "") or hit.get("_id", "")
            # orphan_designation can be a string, a dict with original_text/parsed_text, or missing
            od = entry.get("orphan_designation", "")
            if isinstance(od, dict):
                orphan_designation_str = od.get("parsed_text", od.get("original_text", ""))
            else:
                orphan_designation_str = str(od) if od else ""
            # approval_status vs designation_status
            desig_status = entry.get("designation_status", "")
            approval = entry.get("approval_status", "")
            # Some entries embed approval in designation_status like "Designated/Approved"
            if not approval and "/" in desig_status:
                parts = desig_status.split("/")
                approval = parts[-1] if len(parts) > 1 else ""
            orphan_entries.append(
                {
                    "substance": substance,
                    "orphan_designation": orphan_designation_str,
                    "designation_status": desig_status,
                    "designated_date": entry.get("designated_date", ""),
                    "approval_status": approval,
                    "marketing_approval_date": entry.get("marketing_approval_date", ""),
                    "approved_labeled_indication": entry.get("approved_labeled_indication", ""),
                    "exclusivity_end_date": entry.get("exclusivity_end_date", ""),
                }
            )

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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "condition must be at least 3 characters",
        }

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
                results.append(
                    {
                        "substance": name,
                        "orphan_designation": entry.get("orphan_designation", ""),
                        "designation_status": entry.get("designation_status", ""),
                        "approval_status": entry.get("approval_status", ""),
                    }
                )

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
    Get US drug product and pricing reference information.

    Primary: openFDA NDC Directory (drug product identification, NDC codes,
    manufacturer, brand/generic names, strength, dosage form).

    Note: Real-time NADAC acquisition costs are available via CMS/Medicaid
    but their API has inconsistent uptime. For live pricing, use:
    - NADAC weekly CSV: https://data.medicaid.gov (search "NADAC")
    - CMS Part B/D spending: https://data.cms.gov (free API key)
    - GoodRx / Drugs@FDA for reference pricing online
    """
    if not drug_name or len(drug_name) < 2:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    search_term = drug_name.strip().upper()

    # OpenFDA NDC directory — reliable drug product identification
    fda_search = urllib.parse.quote(f"brand_name:{search_term}")
    url = f"{_FDA_BASE}/drug/ndc.json?search={fda_search}&limit=15"

    _rate_limited()
    data = _cached_fetch(url, ttl=_OT_CACHE_TTL)
    if _is_error(data) or not isinstance(data, dict):
        return {
            "status": "error",
            "error_code": "HTTP_ERROR",
            "message": "Failed to query NDC directory",
        }

    results = data.get("results", [])
    if not results:
        # Try generic name search
        fda_search2 = urllib.parse.quote(f"generic_name:{search_term}")
        url2 = f"{_FDA_BASE}/drug/ndc.json?search={fda_search2}&limit=15"
        _rate_limited()
        data2 = _cached_fetch(url2, ttl=_OT_CACHE_TTL)
        if isinstance(data2, dict):
            results = data2.get("results", [])

    if not results:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "found": False,
            "message": f"No NDC product data found for '{drug_name}'",
            "data_source": "openFDA NDC Directory",
            "alternative_sources": [
                "NADAC weekly CSV: https://data.medicaid.gov (search 'NADAC')",
                "CMS Part B/D spending: https://data.cms.gov (free API key required)",
                "GoodRx: https://goodrx.com",
            ],
            "note": "openFDA NDC contains drug product identification. Live US pricing requires CMS/NADAC data.",
            "timestamp": datetime.utcnow().isoformat(),
        }

    products = []
    for r in results[:10]:
        active_ing = r.get("active_ingredients", [{}])
        ing_name = active_ing[0].get("name", "") if active_ing else ""
        ing_strength = active_ing[0].get("strength", "") if active_ing else ""

        products.append(
            {
                "brand_name": r.get("brand_name", ""),
                "generic_name": r.get("generic_name", ""),
                "active_ingredient": ing_name,
                "strength": ing_strength,
                "dosage_form": r.get("dosage_form", ""),
                "route": r.get("route", ""),
                "labeler_name": r.get("labeler_name", ""),
                "product_ndc": r.get("product_ndc", ""),
                "is_otc": bool("OTC" in r.get("marketing_status", "").upper()),
            }
        )

    return {
        "status": "ok",
        "drug_name": drug_name,
        "found": True,
        "product_count": len(products),
        "products": products,
        "data_source": "openFDA NDC Directory",
        "pricing_note": (
            "NDC directory contains product identification only (no prices). "
            "For US acquisition costs: use NADAC (https://data.medicaid.gov, search 'NADAC') "
            "or CMS Part B/D spending (https://data.cms.gov, free API key). "
            "NADAC is updated weekly, covers outpatient prescription drugs."
        ),
        "api_url": "https://api.fda.gov/drug/ndc.json",
        "timestamp": datetime.utcnow().isoformat(),
    }


