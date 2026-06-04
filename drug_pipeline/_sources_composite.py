"""Composite pipeline views built on top of the lower-level source helpers."""

from __future__ import annotations

from .sources import PHASE_MAP, _is_error, datetime
from ._sources_ctgov import get_trial_detail, search_trials
from ._sources_ema import approved_for_condition, get_eu_approvals
from ._sources_fda import (
    detect_safety_signals,
    get_drug_interactions,
    get_drug_label,
    get_fda_approvals,
    get_patent_expiry,
    get_recalls,
    get_safety_data,
    search_drug,
)
from ._sources_pubmed import search_publications
from ._sources_registry import get_opentargets_drug


def _record_partial_error(partial_errors: list[dict], source_name: str, result: dict | None) -> None:
    """Capture downstream fetch failures without failing the whole composite call."""
    if not _is_error(result):
        return

    partial_errors.append(
        {
            "source": source_name,
            "error_code": result.get("error_code", "UNKNOWN_ERROR"),
            "message": result.get("message", "Unknown downstream error"),
        }
    )


def _summarize_fda_approvals(approvals: dict) -> dict:
    """Trim verbose approval histories so brand-name drugs do not overwhelm the payload."""
    summarized_apps = []
    for app in approvals.get("applications", []) or []:
        submissions = sorted(
            app.get("submissions", []) or [],
            key=lambda item: item.get("status_date", "") or "",
            reverse=True,
        )
        summarized_apps.append(
            {
                "application_number": app.get("application_number"),
                "sponsor": app.get("sponsor"),
                "brand_names": app.get("brand_names", []),
                "generic_names": app.get("generic_names", []),
                "total_submissions": len(submissions),
                "recent_submissions": submissions[:5],
                "source_url": app.get("source_url"),
            }
        )

    return {
        "status": approvals.get("status", "ok"),
        "drug_name": approvals.get("drug_name"),
        "total": approvals.get("total", len(summarized_apps)),
        "applications": summarized_apps,
        "data_source": approvals.get("data_source"),
        "timestamp": approvals.get("timestamp"),
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Provide at least one of: drug_name or condition",
        }

    drug_info = None
    approvals = None
    trials = None
    publications = None
    partial_errors: list[dict] = []
    sources_used = []

    # 1. Drug info (if drug_name provided)
    if drug_name:
        drug_info = search_drug(drug_name)
        if drug_info.get("status") == "ok":
            sources_used.extend(drug_info.get("data_sources", []))
        else:
            _record_partial_error(partial_errors, "drug_info", drug_info)

        approvals = get_fda_approvals(drug_name)
        if approvals.get("status") == "ok" and approvals.get("applications"):
            sources_used.append("openFDA-drugsfda")
            approvals = _summarize_fda_approvals(approvals)
        else:
            _record_partial_error(partial_errors, "fda_approvals", approvals)

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
        else:
            _record_partial_error(partial_errors, "clinical_trials", trials)

    # 3. Publications
    pub_query = drug_name or condition or ""
    if pub_query:
        publications = search_publications(pub_query + " clinical trial", max_results=5)
        if publications.get("status") == "ok":
            sources_used.append("PubMed")
        else:
            _record_partial_error(partial_errors, "publications", publications)

    # 4. EU approvals (if drug_name provided)
    eu_approvals = None
    if drug_name:
        eu_data = get_eu_approvals(drug_name)
        if eu_data.get("status") == "ok" and eu_data.get("results"):
            eu_approvals = {
                "total": eu_data["total"],
                "results": [
                    {
                        "brand_name": r["brand_name"],
                        "status": r["status"],
                        "atc_code": r["atc_code"],
                        "therapeutic_area": r["therapeutic_area"],
                        "orphan": r["orphan"],
                        "biosimilar": r["biosimilar"],
                    }
                    for r in eu_data["results"][:5]
                ]
                if eu_data.get("results")
                else [],
            }
            sources_used.append("EMA")
        else:
            _record_partial_error(partial_errors, "eu_approvals", eu_data)

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
        else:
            _record_partial_error(partial_errors, "safety_data", safety_data)

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
                "top_matches": [
                    {
                        "name": r["name"],
                        "atc_code": r["atc_code"],
                        "orphan": r["orphan"],
                    }
                    for r in afc_data["results"][:8]
                ],
            }
            sources_used.append("EMA")
        else:
            _record_partial_error(partial_errors, "approved_drugs_for_condition", afc_data)

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
        else:
            _record_partial_error(partial_errors, "drug_label", label_data)

    # 9. Recalls (if drug_name provided)
    recalls = None
    if drug_name:
        recall_data = get_recalls(drug_name)
        if recall_data.get("status") == "ok" and recall_data.get("recalls"):
            recalls = {
                "total_recalls": recall_data["total_recalls"],
                "recent": [
                    {
                        "date": r.get("recall_initiation_date"),
                        "reason": (r.get("reason_for_recall", "") or "")[:200],
                        "classification": r.get("classification"),
                        "status": r.get("status"),
                        "firm": r.get("recalling_firm"),
                    }
                    for r in recall_data["recalls"][:5]
                ],
            }
            sources_used.append("openFDA Enforcement")
        else:
            _record_partial_error(partial_errors, "recalls", recall_data)

    # 10. Safety Signals (if drug_name provided)
    safety_signals = None
    if drug_name:
        signal_data = detect_safety_signals(drug_name)
        if signal_data.get("status") == "ok" and signal_data.get("signals"):
            safety_signals = {
                "total_signals": signal_data["total_signals"],
                "top_signals": [
                    {
                        "reaction": s.get("reaction"),
                        "prr": round(s.get("prr", 0), 2),
                        "reports": s.get("reports_with_drug", 0),
                        "signal_strength": s.get("signal_strength"),
                    }
                    for s in signal_data["signals"][:5]
                ],
            }
            sources_used.append("openFDA FAERS")
        else:
            _record_partial_error(partial_errors, "safety_signals", signal_data)

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
        else:
            _record_partial_error(partial_errors, "patent_info", patent_data)

    # 12. Drug Interactions (if drug_name provided)
    drug_interactions = None
    if drug_name:
        interaction_data = get_drug_interactions(drug_name)
        if interaction_data.get("status") == "ok":
            drug_interactions = {
                "has_label_interactions": interaction_data["label_interactions"].get(
                    "drug_interactions_text"
                )
                is not None,
                "contraindications_available": interaction_data["label_interactions"].get(
                    "contraindications_text"
                )
                is not None,
                "co_reported_in_faers": interaction_data.get("co_reported_in_faers", [])[:3],
                "total_co_reported": interaction_data.get("total_co_reported", 0),
            }
            sources_used.extend(interaction_data.get("data_sources", []))
        else:
            _record_partial_error(partial_errors, "drug_interactions", interaction_data)

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
        "partial_errors": partial_errors,
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "company_name must be at least 2 characters",
        }

    # 1. Search trials by sponsor
    trials_raw = search_trials(sponsor=company_name, limit=100)
    if _is_error(trials_raw):
        return trials_raw

    trials = trials_raw.get("results", [])
    if not trials:
        return {
            "status": "ok",
            "company": company_name,
            "results": [],
            "total": 0,
            "message": f"No clinical trials found for sponsor '{company_name}'",
            "data_source": "clinicaltrials.gov",
        }

    # 2. Group by phase
    by_phase: dict[str, list[dict]] = {}
    for t in trials:
        for phase_code in t.get("phase_code", []) or ["NA"]:
            by_phase.setdefault(phase_code, []).append(t)

    # 3. Build phase summary
    phase_summary = {}
    for phase_code in [
        "PHASE1",
        "PHASE12",
        "PHASE2",
        "PHASE23",
        "PHASE3",
        "PHASE4",
        "EARLY1",
        "NA",
    ]:
        phase_key = PHASE_MAP.get(phase_code, phase_code)
        matched = by_phase.get(phase_code, [])
        if matched:
            phase_summary[phase_key] = {
                "count": len(matched),
                "studies": [
                    {
                        "nct_id": s["nct_id"],
                        "title": s["title"],
                        "status": s.get("overall_status"),
                        "conditions": s.get("conditions", []),
                        "interventions": s.get("interventions"),
                        "source_url": s.get("source_url"),
                    }
                    for s in matched[:15]
                ],
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
        "active_trials": sum(
            1
            for t in trials
            if t.get("overall_status")
            in ("RECRUITING", "ACTIVE_NOT_RECRUITING", "ENROLLING_BY_INVITATION")
        ),
        "completed_trials": sum(1 for t in trials if t.get("overall_status") == "COMPLETED"),
        "data_source": "clinicaltrials.gov, EMA",
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Each drug name must be at least 2 characters",
        }

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
                return "Pending review"
            return "Applications filed"
        return "No FDA data"

    def _eu_status(d: dict) -> str:
        if d.get("status") == "ok" and d.get("authorised"):
            return "Authorised (EU)"
        if d.get("status") == "ok" and not d.get("authorised"):
            return "Not authorised (EU)"
        return "No EU data"

    def _extract_moa(d: dict) -> str:
        if d.get("found") and d.get("mechanisms_of_action"):
            moas = d["mechanisms_of_action"]
            return "; ".join(f"{m.get('type', '?')}→{m.get('target', '?')}" for m in moas[:3])
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "condition must be at least 3 characters",
        }

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
                {
                    "title": p.get("title", "?"),
                    "pmid": p.get("pmid", "?"),
                    "journal": p.get("journal", ""),
                    "year": p.get("year", ""),
                }
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
                        "nct_id": t.get(
                            "nct_id",
                            t.get("protocolSection", {})
                            .get("identificationModule", {})
                            .get("nctId", "?"),
                        ),
                        "title": t.get(
                            "title",
                            t.get(
                                "briefTitle",
                                t.get("protocolSection", {})
                                .get("identificationModule", {})
                                .get("briefTitle", "?"),
                            ),
                        ),
                        "sponsor": t.get(
                            "sponsor",
                            t.get("leadSponsor", {}).get(
                                "name",
                                t.get("protocolSection", {})
                                .get("sponsorCollaboratorsModule", {})
                                .get("leadSponsor", {})
                                .get("name", "?"),
                            ),
                        ),
                        "status": t.get(
                            "status",
                            t.get(
                                "overallStatus",
                                t.get("protocolSection", {})
                                .get("statusModule", {})
                                .get("overallStatus", "?"),
                            ),
                        ),
                    }
                    for t in trials_phase3[:limit]
                ],
                "key_sponsors": key_sponsors_p3,
            },
            "phase_2_trials": {
                "count": len(trials_phase2),
                "trials": [
                    {
                        "nct_id": t.get(
                            "nct_id",
                            t.get("protocolSection", {})
                            .get("identificationModule", {})
                            .get("nctId", "?"),
                        ),
                        "title": t.get(
                            "title",
                            t.get(
                                "briefTitle",
                                t.get("protocolSection", {})
                                .get("identificationModule", {})
                                .get("briefTitle", "?"),
                            ),
                        ),
                        "sponsor": t.get(
                            "sponsor",
                            t.get("leadSponsor", {}).get(
                                "name",
                                t.get("protocolSection", {})
                                .get("sponsorCollaboratorsModule", {})
                                .get("leadSponsor", {})
                                .get("name", "?"),
                            ),
                        ),
                        "status": t.get(
                            "status",
                            t.get(
                                "overallStatus",
                                t.get("protocolSection", {})
                                .get("statusModule", {})
                                .get("overallStatus", "?"),
                            ),
                        ),
                    }
                    for t in trials_phase2[:limit]
                ],
                "key_sponsors": key_sponsors_p2,
            },
            "phase_1_trials": {
                "count": len(trials_phase1),
            },
            "key_mechanisms": [
                {"mechanism": k, "drug_count": v} for k, v in sorted_mechanisms[:10]
            ],
            "pipeline_publications": publications,
        },
        "data_sources": ["ClinicalTrials.gov", "EMA", "Open Targets", "PubMed"],
        "timestamp": datetime.utcnow().isoformat(),
    }



# ═════════════════════════════════════════════════════════════
# 22. detect_combination_therapies — Co-Intervention Detection
# ═════════════════════════════════════════════════════════════


def detect_combination_therapies(
    drug_name: str, condition: str | None = None, limit: int = 15
) -> dict:
    """
    Detect combination therapies involving a drug.

    Searches ClinicalTrials.gov for trials where the drug is used as an
    intervention, then extracts co-administered drugs/interventions.
    Useful for oncology combination analysis, add-on trials, and
    competitive positioning.
    """
    if not drug_name or len(drug_name) < 2:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "drug_name must be at least 2 characters",
        }

    try:
        if condition:
            trials = search_trials(intervention=drug_name, condition=condition, limit=limit)
        else:
            trials = search_trials(intervention=drug_name, limit=limit)
    except Exception as e:
        return {
            "status": "error",
            "error_code": "FETCH_ERROR",
            "message": f"Failed to search trials: {str(e)[:100]}",
        }

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
            combinations.append(
                {
                    "nct_id": nct,
                    "title": title,
                    "phase": phase,
                    "co_interventions": all_interventions,
                }
            )

    # Most frequent co-interventions
    top_co = sorted(co_drug_counter.items(), key=lambda x: -x[1])[:15]

    return {
        "status": "ok",
        "drug_name": drug_name,
        "condition": condition,
        "found": len(combinations) > 0,
        "total_trials_analyzed": len(study_list),
        "trials_with_combinations": len(combinations),
        "top_co_administered": [{"drug": name, "trial_count": count} for name, count in top_co],
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
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Provide at least one of: condition, drug_name",
        }

    # Search for relevant trials
    try:
        if drug_name and condition:
            trials = search_trials(
                intervention=drug_name, condition=condition, status="RECRUITING", limit=limit
            )
        elif condition:
            trials = search_trials(condition=condition, status="RECRUITING", limit=limit)
        else:
            trials = search_trials(intervention=drug_name, status="RECRUITING", limit=limit)
    except Exception as e:
        return {
            "status": "error",
            "error_code": "FETCH_ERROR",
            "message": f"Failed to search trials: {str(e)[:100]}",
        }

    studies = trials.get("results", trials.get("studies", []))
    if not studies:
        return {
            "status": "ok",
            "condition": condition,
            "drug_name": drug_name,
            "found": False,
            "total_investigators": 0,
            "investigators": [],
            "related_publications": [],
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
        central_contacts = (
            contacts_mod.get("centralContacts", []) if isinstance(contacts_mod, dict) else []
        )
        locations = contacts_mod.get("locations", []) if isinstance(contacts_mod, dict) else []

        # Extract from central contacts
        for cc in central_contacts if isinstance(central_contacts, list) else []:
            name = cc.get("name", "").strip()
            if name and name.lower() not in seen_investigators:
                seen_investigators.add(name.lower())
                investigators.append(
                    {
                        "name": name,
                        "role": cc.get("role", "Principal Investigator"),
                        "affiliation": sponsor_name,
                        "phone": cc.get("phone", ""),
                        "email": cc.get("email", ""),
                        "trial_nct": nct,
                        "trial_title": title[:120],
                    }
                )

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
                    investigators.append(
                        {
                            "name": name,
                            "role": pi.get("role", "Site Investigator"),
                            "affiliation": facility_name,
                            "phone": pi.get("phone", ""),
                            "email": pi.get("email", ""),
                            "trial_nct": nct,
                            "trial_title": title[:120],
                        }
                    )

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
