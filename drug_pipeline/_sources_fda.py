"""FDA, FAERS, RxNorm, and DailyMed helpers for drug-pipeline-mcp."""

from __future__ import annotations

import urllib.parse

from .sources import _FDA_BASE, _RXNORM_BASE, _cached_fetch, _escape, _fetch, _is_error, _rate_limited, datetime

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
        for r in ndc_data.get("results", []) or []:
            results.append(
                {
                    "brand_name": r.get("brand_name"),
                    "generic_name": r.get("generic_name"),
                    "labeler": r.get("labeler_name"),
                    "active_ingredients": [
                        {"name": i["name"], "strength": i.get("strength", "")}
                        for i in (r.get("active_ingredients", []) or [])
                    ],
                    "product_ndc": r.get("product_ndc"),
                    "route": r.get("route"),
                }
            )

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
                classes = (atc_data.get("rxclassDrugInfoList", {}) or {}).get(
                    "rxclassDrugInfo", []
                ) or []
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
        return {
            "status": "ok",
            "results": [],
            "total": 0,
            "message": f"No FDA approvals found for '{drug_name}'",
        }

    apps = []
    for r in data.get("results", []) or []:
        submissions = []
        for s in r.get("submissions", []) or []:
            submissions.append(
                {
                    "type": s.get("submission_type"),
                    "number": s.get("submission_number"),
                    "status": s.get("submission_status"),
                    "status_date": s.get("submission_status_date"),
                    "review_priority": s.get("review_priority"),
                    "class_code": s.get("submission_class_code_description"),
                }
            )
        apps.append(
            {
                "application_number": r.get("application_number"),
                "sponsor": r.get("sponsor_name"),
                "brand_names": [
                    p.get("brand_name")
                    for p in (r.get("products", []) or [])
                    if p.get("brand_name")
                ],
                "generic_names": [
                    p.get("generic_name")
                    for p in (r.get("products", []) or [])
                    if p.get("generic_name")
                ],
                "submissions": submissions,
                "source_url": f"https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo={r.get('application_number', '')}",
            }
        )

    return {
        "status": "ok",
        "drug_name": drug_name,
        "applications": apps,
        "total": len(apps),
        "data_source": "openFDA",
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

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
        for r in count_data.get("results", []) or []:
            top_reactions.append({"reaction": r.get("term"), "count": r.get("count")})

    # 3. Serious outcomes breakdown
    serious_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&count=serious&limit=5"
    serious_data = _fetch(serious_url)
    serious_outcomes = {}
    if not _is_error(serious_data) and isinstance(serious_data, dict):
        for r in serious_data.get("results", []) or []:
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    search_term = _escape(drug_name)
    url = f"{_FDA_BASE}/drug/enforcement.json?search=openfda.brand_name:{search_term}&limit=20"
    data = _cached_fetch(url, ttl=300)  # 5 min cache

    if _is_error(data):
        return data

    recalls = []
    if isinstance(data, dict) and "results" in data:
        for r in data.get("results", []) or []:
            recalls.append(
                {
                    "recall_initiation_date": r.get("recall_initiation_date"),
                    "reason_for_recall": r.get("reason_for_recall"),
                    "product_quantity": r.get("product_quantity"),
                    "classification": r.get("classification"),
                    "status": r.get("status"),
                    "recalling_firm": r.get("recalling_firm"),
                    "product_description": r.get("product_description"),
                    "code_info": r.get("code_info"),
                }
            )

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
            for r in data.get("results", []) or []:
                for p in r.get("products", []) or []:
                    bn = p.get("brand_name", "")
                    if bn and bn.lower() not in brands_seen and bn.lower() != drug_name.lower():
                        brands_seen.add(bn.lower())
                        _rate_limited()
                        brand_url = f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{_up.quote(bn)}&limit=1"
                        bdata = _fetch(brand_url)
                        if not _is_error(bdata) and isinstance(bdata, dict):
                            total = (bdata.get("meta", {}).get("results", {}) or {}).get(
                                "total", 0
                            ) or 0
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

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
    background_url = (
        f"{_FDA_BASE}/drug/event.json?search=patient.drug.medicinalproduct:{search_term}&limit=1"
    )
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
            for r in reaction_data.get("results", []) or []:
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
            prr = drug_risk / bg_risk if bg_risk > 0 else (float("inf") if drug_risk > 0 else 0.0)

        # Only include signals with PRR > 1
        if prr > 1:
            signals.append(
                {
                    "reaction": reaction.get("reaction"),
                    "reaction_count": a,
                    "drug_total_reports": total_drug_reports,
                    "background_count_estimate": c,
                    "prr": round(prr, 2),
                }
            )

    # Sort by PRR descending
    signals.sort(key=lambda x: x["prr"], reverse=True)

    return {
        "status": "ok",
        "drug_name": drug_name,
        "total_reports": total_drug_reports,
        "total_signals": len(signals),
        "signals": signals,
        "methodology": (
            "Exploratory disproportionality screening (not a validated PRR). "
            "Denominator uses an arbitrary scaling factor (background_total * 10) "
            "as an approximation, not a true pharmacovigilance denominator. "
            "No stratification, no Chi-squared calculation, no signal evaluation. "
            "Do NOT use for regulatory reporting, signal evaluation, "
            "or clinical decision-making. Directional hypothesis generation only."
        ),
        "data_source": "openFDA FAERS (exploratory screening — not validated PRR)",
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

    if not drug_name or len(drug_name) < 2:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    search_term = _escape(drug_name)
    url = f"{_FDA_BASE}/drug/drugsfda.json?search=products.brand_name:{search_term}+OR+products.active_ingredients.name:{search_term}&limit=5"
    data = _cached_fetch(url, ttl=3600)

    if _is_error(data):
        return data

    exclusivity_info = []
    all_submissions = []

    if isinstance(data, dict):
        for r in data.get("results", []) or []:
            app_number = r.get("application_number", "?")
            sponsor = r.get("sponsor_name", "?")

            # Collect all submissions with dates
            for s in r.get("submissions", []) or []:
                date_str = s.get("submission_status_date", "")
                sub_type = s.get("submission_type", "")
                sub_status = s.get("submission_status", "")
                class_desc = s.get("submission_class_code_description", "")
                priority = s.get("review_priority", "")
                all_submissions.append(
                    {
                        "application_number": app_number,
                        "type": sub_type,
                        "status": sub_status,
                        "date": date_str,
                        "class_description": class_desc,
                        "review_priority": priority,
                    }
                )

            # Extract product-level data
            products_info = []
            for p in r.get("products", []) or []:
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

                products_info.append(
                    {
                        "brand_name": p.get("brand_name"),
                        "active_ingredients": ingredients,
                        "marketing_status": p.get("marketing_status"),
                        "reference_drug": p.get("reference_drug") == "Yes",
                        "reference_standard": p.get("reference_standard") == "Yes",
                        "therapeutic_equivalence": te,
                        "te_description": te_desc,
                        "dosage_form": p.get("dosage_form"),
                        "route": p.get("route"),
                    }
                )

            exclusivity_info.append(
                {
                    "application_number": app_number,
                    "sponsor_name": sponsor,
                    "products": products_info,
                }
            )

    # Calculate estimated exclusivity from submission data
    estimated_exclusivity = []
    if all_submissions:
        # Find earliest ORIG (original) approval
        orig_dates = [
            s["date"]
            for s in all_submissions
            if s["type"] == "ORIG" and s["status"] == "AP" and s["date"]
        ]
        if orig_dates:
            earliest = min(orig_dates)
            # Format: YYYYMMDD
            try:
                year = int(earliest[:4])
                month = int(earliest[4:6])
                day = int(earliest[6:8])
                estimated_exclusivity.append(
                    {
                        "type": "Initial FDA Approval",
                        "date": f"{year}-{month:02d}-{day:02d}",
                        "description": "Earliest original approval date",
                    }
                )
                # Type 1 NME = 5 year exclusivity
                type1_found = any(
                    s["class_description"] == "Type 1 - New Molecular Entity"
                    for s in all_submissions
                )
                if type1_found:
                    exp_year = year + 5
                    estimated_exclusivity.append(
                        {
                            "type": "NME Exclusivity Estimate (5yr)",
                            "date": f"{exp_year}-{month:02d}-{day:02d}",
                            "description": "New Molecular Entity — estimated 5-year exclusivity from approval",
                        }
                    )
                # Type 3-5 = 3 year exclusivity
                type35_found = any(
                    c in (s.get("class_description", "") or "")
                    for s in all_submissions
                    for c in ["Type 3", "Type 4", "Type 5"]
                )
                if type35_found:
                    exp_year = year + 3
                    estimated_exclusivity.append(
                        {
                            "type": "New Clinical Study Exclusivity Estimate (3yr)",
                            "date": f"{exp_year}-{month:02d}-{day:02d}",
                            "description": "New formulation/combination — estimated 3-year exclusivity",
                        }
                    )
            except (ValueError, IndexError):
                pass

    # Check if RLD (Reference Listed Drug) — indicates brand/originator
    is_rld = any(
        p.get("reference_drug") for app in exclusivity_info for p in app.get("products", [])
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

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
                co_reported.append(
                    {
                        "drug": name,
                        "report_count": count,
                    }
                )

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


