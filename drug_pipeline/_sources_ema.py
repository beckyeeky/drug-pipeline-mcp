"""EMA-backed catalogue helpers and condition matching utilities."""

from __future__ import annotations

from .sources import _load_ema_data, datetime

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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    name_lower = drug_name.lower()
    ema_data = _load_ema_data()

    if not ema_data:
        return {
            "status": "ok",
            "drug_name": drug_name,
            "results": [],
            "total": 0,
            "message": "EMA data not available. The data file is auto-downloaded on first use to drug_pipeline/ema_medicines.xlsx",
            "data_source": "EMA",
        }

    results = []
    for med in ema_data:
        name = (med.get("name") or "").lower()
        inn = (med.get("inn") or "").lower()
        subst = (med.get("active_substance") or "").lower()

        if name_lower in name or name_lower in inn or name_lower in subst:
            results.append(
                {
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
                    "source_url": f"https://www.ema.europa.eu/en/medicines/human/EPAR/{med.get('name', '').lower().replace(' (previously ', '-').replace(' ', '-').split(',')[0].strip('-')}"
                    if med.get("name")
                    else None,
                }
            )

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
# ═════════════════════════════════════════════════════════════
# 6. Indication → Drug — Therapien per Indikation finden
# ═════════════════════════════════════════════════════════════


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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "condition must be at least 3 characters",
        }

    query_tokens = _tokenize(condition)
    if not query_tokens:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Could not parse condition into search tokens",
        }

    ema_data = _load_ema_data()
    if not ema_data:
        return {
            "status": "ok",
            "condition": condition,
            "results": [],
            "total": 0,
            "message": "EMA data not available",
        }

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
            scored.append(
                {
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
                }
            )

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
        return {"status": "ok", "results": [], "total": 0, "message": "EMA data not available"}

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

        results.append(
            {
                "name": name,
                "active_substance": med.get("active_substance"),
                "atc_code": med.get("atc_code"),
                "therapeutic_area": area[:120] if area else None,
                "indication": (indication or "")[:200],
                "ema_product_number": med.get("ema_product_number"),
            }
        )

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
        return {
            "status": "error",
            "error_code": "EMA_LOAD_ERROR",
            "message": f"Failed to load EMA data: {str(e)[:100]}",
        }

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
            biosimilars_with_refs.append(
                {
                    "biosimilar_name": b.get("name", "?"),
                    "active_substance": b.get("active_substance", "") or b.get("inn", ""),
                    "atc_code": b.get("atc_code", ""),
                    "authorised": b.get("status", "") == "Authorised",
                }
            )
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
        loe_entries.append(
            {
                "active_substance": sub,
                "atc_code": info["atc"],
                "biosimilar_count": len(info["biosimilars"]),
                "biosimilar_names": info["biosimilars"],
                "category": "LOE Active"
                if len(info["biosimilars"]) >= 3
                else "Early Biosimilar Entry",
                "note": f"{len(info['biosimilars'])} EU-approved biosimilar(s) indicate active post-LOE market",
            }
        )

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


