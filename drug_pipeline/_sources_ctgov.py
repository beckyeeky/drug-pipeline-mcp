"""ClinicalTrials.gov query helpers for drug-pipeline-mcp."""

from __future__ import annotations

import urllib.parse

from .sources import (
    _CLINICALTRIALS_BASE,
    _cached_fetch,
    _escape,
    _fetch,
    _is_error,
    _rate_limited,
    datetime,
    PHASE_MAP,
)

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
        params["query.term"] = f"AREA[InterventionSearch]/{_escape(intervention)}"
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
            interventions_raw = [
                i.get("name", "") for i in (arms.get("interventions", []) or []) if i.get("name")
            ]

        results.append(
            {
                "nct_id": id_mod.get("nctId"),
                "title": id_mod.get("briefTitle"),
                "phase": phases_display,
                "phase_code": phases_raw,
                "overall_status": overall_status,
                "conditions": cond_mod.get("conditions", []),
                "lead_sponsor": spons_mod.get("leadSponsor", {}).get("name"),
                "interventions": interventions_raw,
                "start_date": stat_mod.get("startDateStruct", {}).get("date")
                if "startDateStruct" in stat_mod
                else None,
                "completion_date": stat_mod.get("completionDateStruct", {}).get("date")
                if "completionDateStruct" in stat_mod
                else None,
                "source_url": f"https://clinicaltrials.gov/study/{id_mod.get('nctId')}",
                "data_source": "clinicaltrials.gov",
            }
        )

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
        return {
            "status": "error",
            "error_code": "INVALID_NCT",
            "message": f"Invalid NCT ID: {nct_id}. Must start with 'NCT'.",
        }

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
        "enrollment": des_mod.get("enrollmentInfo", {}).get("count")
        if "enrollmentInfo" in des_mod
        else None,
        "interventions": [
            {"name": i.get("name"), "type": i.get("type")}
            for i in (arms_mod.get("interventions", []) or [])
        ]
        if arms_mod.get("interventions")
        else None,
        "primary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in (outcome_mod.get("primaryOutcomes", []) or [])
        ]
        if outcome_mod.get("primaryOutcomes")
        else None,
        "secondary_outcomes": [
            {"measure": o.get("measure"), "time_frame": o.get("timeFrame")}
            for o in (outcome_mod.get("secondaryOutcomes", []) or [])
        ]
        if outcome_mod.get("secondaryOutcomes")
        else None,
        "eligibility_criteria": (elig_mod.get("eligibilityCriteria", "") or "")[:2000],
        "sex": elig_mod.get("sex"),
        "min_age": elig_mod.get("minimumAge"),
        "max_age": elig_mod.get("maximumAge"),
        "healthy_volunteers": elig_mod.get("healthyVolunteers"),
        "locations": [
            {
                "facility": loc.get("facility"),
                "city": loc.get("city"),
                "country": loc.get("country"),
            }
            for loc in (loc_mod.get("locations", []) or [])
        ][:20]
        if loc_mod.get("locations")
        else None,
        "start_date": (stat_mod.get("startDateStruct", {}) or {}).get("date"),
        "primary_completion_date": (stat_mod.get("primaryCompletionDateStruct", {}) or {}).get(
            "date"
        ),
        "completion_date": (stat_mod.get("completionDateStruct", {}) or {}).get("date"),
        "study_first_submit": (stat_mod.get("studyFirstSubmitDate", ""))
        if "studyFirstSubmitDate" in stat_mod
        else None,
        "last_update": (stat_mod.get("lastUpdatePostDateStruct", {}) or {}).get("date"),
        "fda_regulated": (overs_mod.get("fdaRegulatedDrug", False))
        if "fdaRegulatedDrug" in overs_mod
        else None,
        "references": [
            {"citation": r.get("citation"), "pmid": r.get("pmid")}
            for r in (ref_mod.get("references", []) or [])
        ][:10]
        if ref_mod.get("references")
        else None,
        "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
        "data_source": "clinicaltrials.gov",
    }

    return {
        "status": "ok",
        "data": results,
        "timestamp": datetime.utcnow().isoformat(),
    }



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
        return {
            "status": "error",
            "error_code": "INVALID_NCT",
            "message": f"Invalid NCT ID: {nct_id}. Must start with 'NCT'.",
        }

    url = f"{_CLINICALTRIALS_BASE}/studies/{nct_id}?format=json"
    data = _fetch(url)

    if _is_error(data):
        return data

    if not isinstance(data, dict):
        return {"status": "error", "error_code": "NO_DATA", "message": "Trial not found"}

    # Check if results exist
    results_section = data.get("resultsSection", {})
    if not results_section:
        return {
            "status": "ok",
            "nct_id": nct_id,
            "has_results": False,
            "message": f"No results posted yet for {nct_id}. The trial may still be ongoing or results haven't been submitted.",
            "source_url": f"https://clinicaltrials.gov/study/{nct_id}",
            "data_source": "clinicaltrials.gov",
        }

    outcome_module = results_section.get("outcomeMeasuresModule", {}) or {}
    baseline_module = results_section.get("baselineCharacteristicsModule", {}) or {}
    ae_module = results_section.get("adverseEventsModule", {}) or {}
    flow_module = results_section.get("participantFlowModule", {}) or {}
    more_info = results_section.get("moreInfoModule", {}) or {}

    # Parse outcome measures
    outcomes = []
    for om in outcome_module.get("outcomeMeasures", []) or []:
        classes_data = []
        for cls in om.get("classes", []) or []:
            categories = []
            for cat in cls.get("categories", []) or []:
                measurements = []
                for m in cat.get("measurements", []) or []:
                    measurements.append(
                        {
                            "group": m.get("groupDescription"),
                            "value": m.get("value"),
                            "spread": m.get("spread"),
                            "unit": m.get("unit"),
                        }
                    )
                categories.append(
                    {
                        "title": cat.get("title"),
                        "measurements": measurements,
                    }
                )
            classes_data.append(
                {
                    "title": cls.get("title"),
                    "categories": categories,
                }
            )
        outcomes.append(
            {
                "title": om.get("title"),
                "type": om.get("type"),
                "time_frame": om.get("timeFrame"),
                "description": (om.get("description") or "")[:300],
                "population": om.get("populationDescription"),
                "classes": classes_data,
            }
        )

    # Parse baseline
    baseline_groups = []
    for g in baseline_module.get("denomGroups", []) or []:
        baseline_groups.append(
            {
                "description": g.get("description", ""),
                "count": (g.get("denomCount", {}) or {}).get("value"),
            }
        )
    baseline_measures = []
    for m in baseline_module.get("measures", []) or []:
        baseline_measures.append(
            {
                "title": m.get("title"),
                "description": (m.get("description") or "")[:200],
            }
        )

    # Parse adverse events
    serious_events = []
    for e in ae_module.get("seriousEvents", []) or []:
        serious_events.append(
            {
                "term": e.get("term"),
                "organ_system": e.get("organSystem"),
                "subjects_affected": e.get("subjectsAffected"),
                "subjects_at_risk": e.get("subjectsAtRisk"),
            }
        )
    other_events = []
    for e in ae_module.get("otherEvents", []) or []:
        other_events.append(
            {
                "term": e.get("term"),
                "organ_system": e.get("organSystem"),
                "subjects_affected": e.get("subjectsAffected"),
                "subjects_at_risk": e.get("subjectsAtRisk"),
            }
        )

    # Participant flow
    flow_groups = []
    for g in flow_module.get("denomGroups", []) or []:
        flow_groups.append(
            {
                "description": g.get("description", ""),
                "count": (g.get("denomCount", {}) or {}).get("value"),
            }
        )
    flow_periods = []
    for p in flow_module.get("periods", []) or []:
        milestones = []
        for m in p.get("milestones", []) or []:
            milestones.append(
                {
                    "description": m.get("description"),
                    "participants": [
                        {
                            "group": d.get("groupDescription"),
                            "count": d.get("count"),
                        }
                        for d in (m.get("denoms", []) or [])
                    ],
                }
            )
        flow_periods.append(
            {
                "title": p.get("title"),
                "milestones": milestones,
            }
        )

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
# 21. get_trial_sites — Clinical Trial Site & Location Intelligence
# ═════════════════════════════════════════════════════════════


def get_trial_sites(nct_id: str) -> dict:
    """
    Get clinical trial site locations and facility information.

    Extracts facility names, cities, countries, recruitment status,
    and contact information from the full trial protocol.
    Calls ClinicalTrials.gov v2 API directly.
    """
    nct_id = nct_id.strip().upper()
    if not nct_id.startswith("NCT") or len(nct_id) < 8:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "NCT ID must start with 'NCT' and be at least 8 characters",
        }

    # Fetch direct from ClinicalTrials.gov v2 API (not via get_trial_detail wrapper)
    url = f"{_CLINICALTRIALS_BASE}/studies/{nct_id}"
    _rate_limited()
    raw = _cached_fetch(url, ttl=300)
    if _is_error(raw):
        return {
            "status": "error",
            "error_code": "FETCH_ERROR",
            "message": f"Failed to fetch trial data for {nct_id}",
        }

    if not isinstance(raw, dict):
        return {
            "status": "error",
            "error_code": "PARSE_ERROR",
            "message": "Unexpected API response format",
        }

    protocol = raw.get("protocolSection", {})
    contacts_mod = protocol.get("contactsLocationsModule", {})

    # Locations array from contactsLocationsModule (v2 API)
    locations = []
    if isinstance(contacts_mod, dict):
        locations = contacts_mod.get("locations", [])

    if not locations:
        return {
            "status": "ok",
            "nct_id": nct_id,
            "found": False,
            "site_count": 0,
            "message": "No location data available for this trial",
            "data_source": "ClinicalTrials.gov v2 API",
            "timestamp": datetime.utcnow().isoformat(),
        }

    sites = []
    country_counts: dict[str, int] = {}

    for loc in locations:
        if not isinstance(loc, dict):
            continue

        fac = loc.get("facility", "")
        if isinstance(fac, dict):
            fac = fac.get("name", "")

        city = loc.get("city", "")
        state = loc.get("state", "")
        zip_code = loc.get("zip", "")
        country = loc.get("country", "")
        status = loc.get("status", loc.get("recruitmentStatus", ""))
        contact = loc.get("contact", {}) or {}

        location_str = ", ".join(filter(None, [city, state, country]))
        country_c = country or "Unknown"

        sites.append(
            {
                "facility": fac or "Not specified",
                "location": location_str,
                "city": city or "",
                "state": state or "",
                "zip": zip_code or "",
                "country": country_c,
                "status": status or "",
                "contact_name": contact.get("name", "") if isinstance(contact, dict) else "",
                "contact_phone": contact.get("phone", "") if isinstance(contact, dict) else "",
            }
        )
        country_counts[country_c] = country_counts.get(country_c, 0) + 1

    # Overall officials (investigators / central contacts)
    officials = []
    if isinstance(contacts_mod, dict):
        for off in contacts_mod.get("overallOfficials", []):
            if isinstance(off, dict):
                officials.append(
                    {
                        "name": off.get("name", ""),
                        "role": off.get("role", ""),
                        "affiliation": off.get("affiliation", ""),
                    }
                )

    # Trial overview
    status_module = protocol.get("statusModule", {})
    id_module = protocol.get("identificationModule", {})

    return {
        "status": "ok",
        "nct_id": nct_id,
        "found": True,
        "trial_title": id_module.get("briefTitle", ""),
        "trial_status": status_module.get("overallStatus", ""),
        "site_count": len(sites),
        "country_count": len(country_counts),
        "geographic_distribution": [
            {"country": c, "sites": n}
            for c, n in sorted(country_counts.items(), key=lambda x: -x[1])
        ],
        "sites": sites,
        "overall_officials": officials,
        "data_source": "ClinicalTrials.gov v2 API",
        "timestamp": datetime.utcnow().isoformat(),
    }


