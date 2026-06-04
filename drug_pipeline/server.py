#!/usr/bin/env python3
"""
Drug Pipeline MCP Server — Pharmaceutical R&D Intelligence for AI Agents.

Tools:
  search_trials        — Search clinical trials by condition, phase, status
  get_trial_detail     — Full protocol for a specific NCT
  lookup_drug          — Drug info, ingredients, ATC classification
  get_approvals        — FDA approval history for a drug
  get_eu_approvals     — EU/EMA authorization status
  get_safety_data      — FAERS adverse event reports, reactions, outcomes
  approved_for_condition — Find EU-approved drugs for a condition
  get_trial_results    — Trial outcome measures, adverse events, baseline
  list_orphan_drugs    — EU Orphan Drug Designations
  company_pipeline     — Company R&D pipeline by phase
  search_publications  — PubMed publications for a drug/trial
  drug_pipeline        -- **Composite**: drug info + FDA + EU + safety + trials + pubs
  get_drug_label       — FDA drug label (prescribing information)
  get_recalls          — FDA recall/enforcement history
  detect_safety_signals — PRR-based pharmacovigilance signal detection
  get_patent_expiry    — FDA patent & exclusivity information
  get_drug_interactions — Drug-drug interactions (FDA label + FAERS)
  get_opentargets_drug — Drug-target MOA from Open Targets (EMBL-EBI)
  get_dailymed_label   — Drug label from DailyMed (NIH, OTC-friendly)
  compare_drugs        — **Head-to-head drug comparison** (synthetic)
  pipeline_landscape   — **Complete pipeline landscape for a condition**
  get_us_orphan_designations — US FDA Orphan Drug Designations
  get_drug_pricing     — US drug pricing (NADAC/CMS)
  list_biosimilars     — EU biosimilars from EMA register
  list_loss_of_exclusivity — LOE timing & biosimilar competition
  get_trial_sites      — Clinical trial site locations & geographic distribution
  detect_combination_therapies — Co-administered drug detection
  find_investigators   — Principal investigator / KOL search
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from pydantic import BaseModel, Field

from . import __version__
from .sources import (
    approved_for_condition as _approved_for_condition,
)
from .sources import (
    company_pipeline as _company_pipeline,
)
from .sources import (
    compare_drugs as _compare_drugs,
)
from .sources import (
    detect_combination_therapies as _detect_combination_therapies,
)
from .sources import (
    detect_safety_signals as _detect_safety_signals,
)
from .sources import (
    drug_pipeline_summary,
)
from .sources import (
    find_investigators as _find_investigators,
)
from .sources import (
    get_dailymed_label as _get_dailymed_label,
)
from .sources import (
    get_drug_interactions as _get_drug_interactions,
)
from .sources import (
    get_drug_label as _get_drug_label,
)
from .sources import (
    get_drug_pricing as _get_drug_pricing,
)
from .sources import (
    get_eu_approvals as _get_eu_approvals,
)
from .sources import (
    get_fda_approvals as _get_fda_approvals,
)
from .sources import (
    get_opentargets_drug as _get_opentargets_drug,
)
from .sources import (
    get_patent_expiry as _get_patent_expiry,
)
from .sources import (
    get_recalls as _get_recalls,
)
from .sources import (
    get_safety_data as _get_safety_data,
)
from .sources import (
    get_trial_detail as _get_trial_detail,
)
from .sources import (
    get_trial_results as _get_trial_results,
)
from .sources import (
    get_trial_sites as _get_trial_sites,
)
from .sources import (
    get_us_orphan_designations as _get_us_orphan_designations,
)
from .sources import (
    list_biosimilars as _list_biosimilars,
)
from .sources import (
    list_loss_of_exclusivity as _list_loss_of_exclusivity,
)
from .sources import (
    list_orphan_drugs as _list_orphan_drugs,
)
from .sources import (
    pipeline_landscape as _pipeline_landscape,
)
from .sources import (
    search_drug as _search_drug,
)
from .sources import (
    search_publications as _search_publications,
)
from .sources import (
    search_trials as _search_trials,
)
from .sources import reset_request_deadline, set_request_deadline

_start_time = time.time()
_PRETTY_JSON = os.getenv("DRUG_PIPELINE_PRETTY_JSON", "").lower() in {"1", "true", "yes", "on"}
_TOOL_TIMEOUT_SECONDS = float(os.getenv("DRUG_PIPELINE_TOOL_TIMEOUT", "20"))

# ─────────────────────────────────────────────────────────────
# Pydantic Input Models
# ─────────────────────────────────────────────────────────────


class SearchTrialsInput(BaseModel):
    """Search for clinical trials by condition, phase, status, or sponsor."""

    condition: str | None = Field(
        default=None,
        description="Medical condition or disease (e.g., 'type 2 diabetes', 'non-small cell lung cancer')",
    )
    phase: str | None = Field(
        default=None,
        pattern=r"^(EARLY1|PHASE1|PHASE12|PHASE2|PHASE23|PHASE3|PHASE4|NA)$",
        description="Trial phase filter. One of: EARLY1, PHASE1, PHASE12, PHASE2, PHASE23, PHASE3, PHASE4, NA",
    )
    status: str | None = Field(
        default=None,
        description="Recruitment status filter. Common: RECRUITING, ACTIVE_NOT_RECRUITING, COMPLETED, TERMINATED",
    )
    sponsor: str | None = Field(
        default=None,
        description="Lead sponsor name (e.g., 'Novo Nordisk', 'Pfizer')",
    )
    intervention: str | None = Field(
        default=None,
        description="Drug or intervention name (e.g., 'semaglutide', 'pembrolizumab')",
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum results to return (1-50)",
    )


class GetTrialDetailInput(BaseModel):
    """Get full protocol details for a specific clinical trial by NCT ID."""

    nct_id: str = Field(
        ...,
        min_length=8,
        max_length=16,
        description="NCT identifier from ClinicalTrials.gov (e.g., 'NCT03178617')",
    )


class LookupDrugInput(BaseModel):
    """Look up a drug by brand or generic name."""

    name: str = Field(
        ...,
        min_length=2,
        description="Brand or generic drug name (e.g., 'Ozempic', 'semaglutide')",
    )


class GetApprovalsInput(BaseModel):
    """Get FDA approval history for a drug."""

    drug_name: str = Field(
        ...,
        min_length=2,
        description="Brand or generic drug name (e.g., 'Ozempic', 'semaglutide')",
    )


class SearchPublicationsInput(BaseModel):
    """Search PubMed for publications related to a drug, condition, or trial."""

    query: str = Field(
        ...,
        min_length=2,
        description="Search query (e.g., 'semaglutide diabetes phase 3', 'NCT03178617')",
    )
    max_results: int = Field(
        default=10,
        ge=1,
        le=30,
        description="Maximum publications to return (1-30)",
    )


class DrugPipelineInput(BaseModel):
    """Composite intelligence: drug info + trials + FDA + publications in one call."""

    drug_name: str | None = Field(
        default=None,
        description="Brand or generic drug name (optional if condition is provided)",
    )
    condition: str | None = Field(
        default=None,
        description="Medical condition (optional if drug_name is provided)",
    )


class GetEuApprovalsInput(BaseModel):
    """Get EU/EMA approval status for a drug."""

    drug_name: str = Field(
        ...,
        min_length=2,
        description="Brand or generic drug name (e.g., 'Ozempic', 'semaglutide')",
    )


class GetSafetyDataInput(BaseModel):
    """Get FDA Adverse Event Reporting System (FAERS) data."""

    drug_name: str = Field(
        ...,
        min_length=2,
        description="Brand or generic drug name (e.g., 'Ozempic', 'semaglutide')",
    )


class ApprovedForConditionInput(BaseModel):
    """Find EU-approved drugs for a medical condition."""

    condition: str = Field(
        ...,
        min_length=3,
        description="Medical condition (e.g., 'non-small cell lung cancer', 'type 2 diabetes', 'melanoma')",
    )
    limit: int = Field(
        default=30,
        ge=5,
        le=100,
        description="Maximum number of unique drugs to return (5-100, default 30)",
    )


class GetTrialResultsInput(BaseModel):
    """Get results for a completed clinical trial."""

    nct_id: str = Field(
        ...,
        min_length=8,
        max_length=16,
        description="NCT identifier (e.g., 'NCT02918162')",
    )


class ListOrphanDrugsInput(BaseModel):
    """List drugs with EU Orphan Drug Designation."""

    condition: str | None = Field(
        default=None,
        description="Optional medical condition filter (e.g., 'lung cancer', 'leukemia')",
    )
    limit: int = Field(
        default=50,
        ge=5,
        le=200,
        description="Maximum number of drugs to return (5-200, default 50)",
    )


class CompanyPipelineInput(BaseModel):
    """Get the clinical pipeline for a pharmaceutical company."""

    company_name: str = Field(
        ...,
        min_length=2,
        description="Company name (e.g., 'Novo Nordisk', 'Pfizer', 'Moderna')",
    )
    include_eu: bool = Field(
        default=True,
        description="Also look up EU approval status for drugs found in trials",
    )
    limit: int = Field(
        default=30,
        ge=5,
        le=100,
        description="Maximum results (5-100, default 30)",
    )


class DrugNameInput(BaseModel):
    """Drug name input for label, recalls, signals, and patent tools."""

    drug_name: str = Field(
        ...,
        min_length=2,
        description="Brand or generic drug name (e.g., 'Ozempic', 'semaglutide', 'Keytruda')",
    )


class CompareDrugsInput(BaseModel):
    """Head-to-head comparison of two drugs."""

    drug_a: str = Field(..., min_length=2, description="First drug name (brand or generic)")
    drug_b: str = Field(..., min_length=2, description="Second drug name (brand or generic)")


class PipelineLandscapeInput(BaseModel):
    """Complete pipeline landscape for a medical condition."""

    condition: str = Field(
        ...,
        min_length=3,
        description="Medical condition (e.g., 'non-small cell lung cancer', 'COPD', 'type 2 diabetes')",
    )
    limit: int = Field(
        default=20, ge=5, le=50, description="Maximum results per phase (5-50, default 20)"
    )


class ListBiosimilarsInput(BaseModel):
    """List EU-approved biosimilars, optionally by condition."""

    condition: str | None = Field(
        default=None, description="Optional medical condition / therapeutic area filter"
    )
    limit: int = Field(default=50, ge=5, le=200, description="Maximum results (5-200, default 50)")


class LossOfExclusivityInput(BaseModel):
    """Identify drugs approaching Loss of Exclusivity."""

    limit: int = Field(default=30, ge=5, le=100, description="Maximum results (5-100, default 30)")


class DetectCombinationTherapiesInput(BaseModel):
    """Detect combination therapies involving a drug."""

    drug_name: str = Field(..., min_length=2, description="Drug name to analyze for combinations")
    condition: str | None = Field(default=None, description="Optional medical condition filter")
    limit: int = Field(default=15, ge=5, le=30, description="Maximum trials to analyze (5-30)")


class FindInvestigatorsInput(BaseModel):
    """Find principal investigators / KOLs by condition or drug."""

    condition: str | None = Field(
        default=None, description="Medical condition to search for investigators"
    )
    drug_name: str | None = Field(default=None, description="Drug name to find investigators for")
    limit: int = Field(
        default=20, ge=5, le=50, description="Maximum investigators to return (5-50)"
    )


# ─────────────────────────────────────────────────────────────
# Tool Metadata & Dispatch
# ─────────────────────────────────────────────────────────────


# Tool Handlers
# ─────────────────────────────────────────────────────────────


def _handle_search_trials(**kwargs: Any) -> list[types.TextContent]:
    validated = SearchTrialsInput(**kwargs)
    result = _search_trials(
        condition=validated.condition,
        phase=validated.phase,
        status=validated.status,
        sponsor=validated.sponsor,
        intervention=validated.intervention,
        limit=validated.limit,
    )
    return _response(result)


def _handle_get_trial_detail(**kwargs: Any) -> list[types.TextContent]:
    validated = GetTrialDetailInput(**kwargs)
    result = _get_trial_detail(validated.nct_id.strip().upper())
    return _response(result)


def _handle_lookup_drug(**kwargs: Any) -> list[types.TextContent]:
    validated = LookupDrugInput(**kwargs)
    result = _search_drug(validated.name.strip())
    return _response(result)


def _handle_get_approvals(**kwargs: Any) -> list[types.TextContent]:
    validated = GetApprovalsInput(**kwargs)
    result = _get_fda_approvals(validated.drug_name.strip())
    return _response(result)


def _handle_search_publications(**kwargs: Any) -> list[types.TextContent]:
    validated = SearchPublicationsInput(**kwargs)
    result = _search_publications(validated.query.strip(), max_results=validated.max_results)
    return _response(result)


def _handle_drug_pipeline(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugPipelineInput(**kwargs)
    result = drug_pipeline_summary(
        drug_name=validated.drug_name.strip() if validated.drug_name else None,
        condition=validated.condition.strip() if validated.condition else None,
    )
    return _response(result)


def _handle_get_eu_approvals(**kwargs: Any) -> list[types.TextContent]:
    validated = GetEuApprovalsInput(**kwargs)
    result = _get_eu_approvals(validated.drug_name.strip())
    return _response(result)


def _handle_get_safety_data(**kwargs: Any) -> list[types.TextContent]:
    validated = GetSafetyDataInput(**kwargs)
    result = _get_safety_data(validated.drug_name.strip())
    return _response(result)


def _handle_approved_for_condition(**kwargs: Any) -> list[types.TextContent]:
    validated = ApprovedForConditionInput(**kwargs)
    result = _approved_for_condition(
        condition=validated.condition.strip(),
        limit=validated.limit,
    )
    return _response(result)


def _handle_get_trial_results(**kwargs: Any) -> list[types.TextContent]:
    validated = GetTrialResultsInput(**kwargs)
    result = _get_trial_results(validated.nct_id.strip().upper())
    return _response(result)


def _handle_list_orphan_drugs(**kwargs: Any) -> list[types.TextContent]:
    validated = ListOrphanDrugsInput(**kwargs)
    result = _list_orphan_drugs(
        condition=validated.condition.strip() if validated.condition else None,
        limit=validated.limit,
    )
    return _response(result)


def _handle_company_pipeline(**kwargs: Any) -> list[types.TextContent]:
    validated = CompanyPipelineInput(**kwargs)
    result = _company_pipeline(
        company_name=validated.company_name.strip(),
        include_eu=validated.include_eu,
        limit=validated.limit,
    )
    return _response(result)


def _handle_get_drug_label(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_drug_label(validated.drug_name.strip())
    return _response(result)


def _handle_get_recalls(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_recalls(validated.drug_name.strip())
    return _response(result)


def _handle_detect_safety_signals(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _detect_safety_signals(validated.drug_name.strip())
    return _response(result)


def _handle_get_patent_expiry(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_patent_expiry(validated.drug_name.strip())
    return _response(result)


def _handle_get_drug_interactions(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_drug_interactions(validated.drug_name.strip())
    return _response(result)


def _handle_get_opentargets_drug(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_opentargets_drug(validated.drug_name.strip())
    return _response(result)


def _handle_get_dailymed_label(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_dailymed_label(validated.drug_name.strip())
    return _response(result)


def _handle_compare_drugs(**kwargs: Any) -> list[types.TextContent]:
    validated = CompareDrugsInput(**kwargs)
    result = _compare_drugs(validated.drug_a.strip(), validated.drug_b.strip())
    return _response(result)


def _handle_pipeline_landscape(**kwargs: Any) -> list[types.TextContent]:
    validated = PipelineLandscapeInput(**kwargs)
    result = _pipeline_landscape(validated.condition.strip(), limit=validated.limit)
    return _response(result)


def _handle_get_us_orphan_designations(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_us_orphan_designations(validated.drug_name.strip())
    return _response(result)


def _handle_get_drug_pricing(**kwargs: Any) -> list[types.TextContent]:
    validated = DrugNameInput(**kwargs)
    result = _get_drug_pricing(validated.drug_name.strip())
    return _response(result)


def _handle_list_biosimilars(**kwargs: Any) -> list[types.TextContent]:
    validated = ListBiosimilarsInput(**kwargs)
    result = _list_biosimilars(
        condition=validated.condition.strip() if validated.condition else None,
        limit=validated.limit,
    )
    return _response(result)


def _handle_list_loss_of_exclusivity(**kwargs: Any) -> list[types.TextContent]:
    validated = LossOfExclusivityInput(**kwargs)
    result = _list_loss_of_exclusivity(limit=validated.limit)
    return _response(result)


def _handle_get_trial_sites(**kwargs: Any) -> list[types.TextContent]:
    validated = GetTrialDetailInput(**kwargs)
    result = _get_trial_sites(validated.nct_id.strip().upper())
    return _response(result)


def _handle_detect_combination_therapies(**kwargs: Any) -> list[types.TextContent]:
    validated = DetectCombinationTherapiesInput(**kwargs)
    result = _detect_combination_therapies(
        validated.drug_name.strip(),
        condition=validated.condition.strip() if validated.condition else None,
        limit=validated.limit,
    )
    return _response(result)


def _handle_find_investigators(**kwargs: Any) -> list[types.TextContent]:
    validated = FindInvestigatorsInput(**kwargs)
    result = _find_investigators(
        condition=validated.condition.strip() if validated.condition else None,
        drug_name=validated.drug_name.strip() if validated.drug_name else None,
        limit=validated.limit,
    )
    return _response(result)


def _response(data: dict) -> list[types.TextContent]:
    """Wrap a result dict in MCP TextContent."""
    return [types.TextContent(type="text", text=_dump_json(data))]


def _dump_json(data: Any) -> str:
    """Serialize JSON compactly by default to reduce stdio payload size."""
    kwargs: dict[str, Any] = {"ensure_ascii": False}
    if _PRETTY_JSON:
        kwargs["indent"] = 2
    else:
        kwargs["separators"] = (",", ":")
    return json.dumps(data, **kwargs)


TOOLS = {
    "search_trials": {
        "description": (
            "Search ClinicalTrials.gov for clinical trials by medical condition, "
            "phase, status, sponsor, or intervention. Returns NCT IDs, titles, "
            "phases, and statuses. Every result links to its source NCT page. "
            "Use this to find active trials for a drug or disease."
        ),
        "input_schema": SearchTrialsInput.model_json_schema(),
        "handler": _handle_search_trials,
    },
    "get_trial_detail": {
        "description": (
            "Get the complete protocol for a specific clinical trial by NCT ID. "
            "Includes eligibility criteria, primary/secondary outcomes, locations, "
            "sponsor information, and references. Always use this after search_trials "
            "to get full details for a promising candidate."
        ),
        "input_schema": GetTrialDetailInput.model_json_schema(),
        "handler": _handle_get_trial_detail,
    },
    "lookup_drug": {
        "description": (
            "Look up a drug by brand or generic name. Returns active ingredients, "
            "strength, labeler/manufacturer, NDC number, RxNorm RxCUI, and ATC "
            "classification (anatomical therapeutic chemical code). Use this to "
            "identify what a drug is, who makes it, and how it's classified."
        ),
        "input_schema": LookupDrugInput.model_json_schema(),
        "handler": _handle_lookup_drug,
    },
    "get_approvals": {
        "description": (
            "Get the FDA approval history for a drug. Returns application numbers, "
            "sponsor name, and all submissions with status (approved, pending, etc.) "
            "and dates. Links to FDA's Drugs@FDA for official source. "
            "Use this to check regulatory status and approval timeline."
        ),
        "input_schema": GetApprovalsInput.model_json_schema(),
        "handler": _handle_get_approvals,
    },
    "search_publications": {
        "description": (
            "Search PubMed for scientific publications related to a drug, condition, "
            "or clinical trial. Returns PMIDs, titles, journals, publication years, "
            "and abstracts. Use this to find published evidence for a drug or trial."
        ),
        "input_schema": SearchPublicationsInput.model_json_schema(),
        "handler": _handle_search_publications,
    },
    "drug_pipeline": {
        "description": (
            "**Composite intelligence tool** — Combines drug lookup, FDA approval "
            "status, EU/EMA approval status, adverse event safety data, active "
            "clinical trials, drug labeling, safety signals, recalls, patent info, "
            "and recent publications into a single response. "
            "Given a drug name or medical condition, returns: drug info "
            "(ingredients, ATC code, labeler), FDA approval history, EU authorization "
            "status, FAERS safety data, drug label, safety signals, recalls, patent "
            "expiry, matching clinical trials, and recent PubMed "
            "publications. "
            "This is the primary tool for pipeline intelligence — use instead of "
            "calling separate tools individually."
        ),
        "input_schema": DrugPipelineInput.model_json_schema(),
        "handler": _handle_drug_pipeline,
    },
    "get_eu_approvals": {
        "description": (
            "Get EU/EMA approval status for a drug by brand name or active "
            "substance. Queries the EMA Human Medicines Register (daily updated). "
            "Returns authorization status, ATC code, therapeutic area, "
            "indication, and special designations (orphan drug, biosimilar, "
            "conditional approval). Use this to check if a drug is approved "
            "in the European Union."
        ),
        "input_schema": GetEuApprovalsInput.model_json_schema(),
        "handler": _handle_get_eu_approvals,
    },
    "get_safety_data": {
        "description": (
            "Get FDA Adverse Event Reporting System (FAERS) data for a drug. "
            "Returns total number of adverse event reports, the most commonly "
            "reported reactions (e.g., nausea, vomiting, fatigue), and serious "
            "outcome breakdown. "
            "Use this for safety due diligence and to understand the real-world "
            "side effect profile of a drug. "
            "WARNING: These are spontaneous reports, NOT incidence rates -- "
            "reporting volume reflects many factors including market exposure."
        ),
        "input_schema": GetSafetyDataInput.model_json_schema(),
        "handler": _handle_get_safety_data,
    },
    "approved_for_condition": {
        "description": (
            "Find EU-approved drugs for a medical condition. "
            "Queries the EMA Human Medicines Register to return drugs authorized "
            "for a specific indication. Returns drug names, active substances, "
            "ATC codes (anatomic therapeutic chemical classification), "
            "therapeutic area, and special designations (orphan drug, biosimilar). "
            "Use this to answer: 'What drugs are approved for condition X?' "
            "Examples: 'non-small cell lung cancer', 'type 2 diabetes', 'breast cancer', "
            "'hypertension', 'rheumatoid arthritis'."
        ),
        "input_schema": ApprovedForConditionInput.model_json_schema(),
        "handler": _handle_approved_for_condition,
    },
    "get_trial_results": {
        "description": (
            "Get results for a completed clinical trial by NCT ID. "
            "Returns outcome measures (primary and secondary endpoints with "
            "numerical values), participant baseline characteristics, "
            "adverse events (serious and other), and participant flow. "
            "Use this to answer: 'Did the trial meet its endpoint?' "
            "or 'What were the safety outcomes?' "
            "NOTE: Only trials that have been completed and have submitted "
            "results will have data here."
        ),
        "input_schema": GetTrialResultsInput.model_json_schema(),
        "handler": _handle_get_trial_results,
    },
    "list_orphan_drugs": {
        "description": (
            "List drugs with EU Orphan Drug Designation from the EMA "
            "register. Orphan designation means the drug treats a "
            "life-threatening or chronically debilitating condition "
            "affecting fewer than 5 in 10,000 people in the EU. "
            "Optionally filter by medical condition/therapeutic area. "
            "Returns drug names, active substances, ATC codes, "
            "and therapeutic areas."
        ),
        "input_schema": ListOrphanDrugsInput.model_json_schema(),
        "handler": _handle_list_orphan_drugs,
    },
    "company_pipeline": {
        "description": (
            "Get the complete clinical pipeline for a pharmaceutical "
            "company. Searches ClinicalTrials.gov for all studies "
            "sponsored by the company, grouped by phase (Phase 1, 2, 3). "
            "Returns the number of active and completed trials per phase, "
            "study details with NCT IDs, and optionally enriches with "
            "EU approval status for drugs found in the trials. "
            "Use this for competitive intelligence or to monitor "
            "a company's R&D pipeline."
        ),
        "input_schema": CompanyPipelineInput.model_json_schema(),
        "handler": _handle_company_pipeline,
    },
    "get_drug_label": {
        "description": (
            "Get the FDA-approved drug label (prescribing information) "
            "for a drug by brand or generic name. Returns key sections: "
            "indications and usage, boxed warnings, dosage and administration, "
            "contraindications, adverse reactions, warnings and precautions, "
            "drug interactions, and pregnancy/lactation information. "
            "Use this for clinical decision support and safety review."
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_drug_label,
    },
    "get_recalls": {
        "description": (
            "Get FDA drug recall and enforcement information for a drug "
            "by brand or generic name. Returns recall initiation dates, "
            "reasons for recall, product quantities, recall classification "
            "(Class I = dangerous, Class II = temporary, Class III = unlikely), "
            "status (ongoing/terminated), and the recalling firm. "
            "Use this for pharmacovigilance and supply chain monitoring."
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_recalls,
    },
    "detect_safety_signals": {
        "description": (
            "**Advanced pharmacovigilance** — Detect disproportionate "
            "adverse event signals for a drug using PRR (Proportional "
            "Reporting Ratio) analytics from FAERS data. "
            "Returns a ranked list of adverse reactions with PRR > 1, "
            "indicating potential safety signals that warrant further "
            "investigation. "
            "Use this for signal detection, not just raw reaction counting. "
            "NOTE: PRR > 2 with chi-squared > 4 is a typical regulatory threshold."
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_detect_safety_signals,
    },
    "get_patent_expiry": {
        "description": (
            "Get FDA patent and exclusivity information for a drug. "
            "Returns approval dates, Orange Book patent information, "
            "and estimated market exclusivity periods. "
            "Use this to answer: 'When does the patent expire?' "
            "or 'When can generics enter the market?' "
            "NOTE: Full Orange Book patent data requires downloading "
            "the FDA products.txt — results are based on FDA approval "
            "data when patent details are unavailable."
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_patent_expiry,
    },
    "get_drug_interactions": {
        "description": (
            "Get drug-drug interaction information for a drug using FDA "
            "labeling data and FAERS adverse event reports. Returns the "
            "official drug interactions section from the FDA label, "
            "contraindications, and warnings. Also lists drugs commonly "
            "co-reported in adverse event reports (FAERS) as a signal "
            "for potential interactions. "
            "Use this to answer: 'Does this drug interact with other "
            "medications?' or 'What should I avoid when taking this drug?'"
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_drug_interactions,
    },
    "get_opentargets_drug": {
        "description": (
            "Get drug-target intelligence from EMBL-EBI's Open Targets Platform. "
            "Returns mechanisms of action, drug targets, clinical development stage, "
            "drug type (e.g. Antibody, Small molecule), trade names, and known indications. "
            "Uses the free Open Targets GraphQL API (no auth required). "
            "Use this to answer: 'What is the mechanism of action?' or "
            "'What targets does this drug bind?' or 'What clinical stage has it reached?'"
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_opentargets_drug,
    },
    "get_dailymed_label": {
        "description": (
            "Get drug label information from DailyMed (NIH/NLM). "
            "Alternative to the openFDA Drug Labeling API. "
            "DailyMed contains FDA Structured Product Labels (SPLs) with better "
            "coverage of OTC and generic drugs than openFDA Labeling. "
            "Returns the SPL set ID, version, published date, and a direct URL to the label. "
            "Use this as a fallback when get_drug_label returns 'not found'."
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_dailymed_label,
    },
    "compare_drugs": {
        "description": (
            "**Head-to-head drug comparison** — Compares two drugs across FDA approvals, "
            "EU/EMA status, mechanisms of action, safety (FAERS total reports), drug type, "
            "and patent/exclusivity. Uses all available data sources internally. "
            "Use this to answer: 'Which drug is more effective?' or "
            "'How does Drug A compare to Drug B in safety and development stage?'"
        ),
        "input_schema": CompareDrugsInput.model_json_schema(),
        "handler": _handle_compare_drugs,
    },
    "pipeline_landscape": {
        "description": (
            "**Complete pipeline landscape for a medical condition** — Returns a structured "
            "view of approved drugs (EMA), Phase 3 active trials, Phase 2 trials, Phase 1 "
            "trials, key mechanisms and targets, key sponsor/companies, and recent pipeline "
            "publications. Use this instead of calling search_trials + approved_for_condition "
            "+ search_publications separately. "
            "Use this to answer: 'Give me the full pipeline for [disease]'"
        ),
        "input_schema": PipelineLandscapeInput.model_json_schema(),
        "handler": _handle_pipeline_landscape,
    },
    "get_us_orphan_designations": {
        "description": (
            "Get US FDA Orphan Drug Designation data from MyChem.info (aggregated from "
            "the FDA Orphan Drug Product Designation database). Returns designation "
            "history including indication, designation status, dates, and exclusivity "
            "end dates. Use this to complement list_orphan_drugs (EU-only). "
            "Use this to answer: 'Does this drug have US orphan designation?'"
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_us_orphan_designations,
    },
    "get_drug_pricing": {
        "description": (
            "Get US drug pricing data from the NADAC (National Average Drug Acquisition "
            "Cost) database by CMS/Medicaid. Returns pharmacy-level acquisition prices, "
            "NDC, effective date, and pricing unit. Updated weekly. "
            "Note: Covers outpatient prescription drugs; limited for biologics and hospital-only drugs. "
            "Use this to answer: 'How much does this drug cost in the US?'"
        ),
        "input_schema": DrugNameInput.model_json_schema(),
        "handler": _handle_get_drug_pricing,
    },
    "list_biosimilars": {
        "description": (
            "List all EU-approved biosimilars from the EMA Human Medicines Register. "
            "Optionally filter by medical condition or therapeutic area. "
            "Returns drug names, active substances, ATC codes, and groups by active "
            "substance for competitive landscape analysis. "
            "Use this to answer: 'What biosimilars are approved in the EU?'"
        ),
        "input_schema": ListBiosimilarsInput.model_json_schema(),
        "handler": _handle_list_biosimilars,
    },
    "list_loss_of_exclusivity": {
        "description": (
            "Identify drugs approaching or at Loss of Exclusivity (LOE) based on "
            "EU biosimilar competition. Combines EMA biosimilar data to detect active "
            "substances with multiple biosimilar entrants, indicating post-LOE markets. "
            "For precise patent dates, combine with get_patent_expiry. "
            "Use this to answer: 'Which drugs are facing biosimilar competition?'"
        ),
        "input_schema": LossOfExclusivityInput.model_json_schema(),
        "handler": _handle_list_loss_of_exclusivity,
    },
    "get_trial_sites": {
        "description": (
            "Get clinical trial site locations and geographic intelligence for a specific "
            "trial by NCT ID. Returns facility names, cities, states, countries, "
            "recruitment status, contact information, and geographic distribution. "
            "Use this after get_trial_detail to understand where a trial is being conducted. "
            "Use this to answer: 'Where is this clinical trial being conducted?'"
        ),
        "input_schema": GetTrialDetailInput.model_json_schema(),
        "handler": _handle_get_trial_sites,
    },
    "detect_combination_therapies": {
        "description": (
            "Detect combination therapies and co-administered drugs involving a specific "
            "drug. Searches ClinicalTrials.gov for trials where the drug is an intervention, "
            "then extracts all co-interventions. Returns the most frequently co-administered "
            "drugs and detailed trial-level breakdowns. Especially useful for oncology "
            "combination analysis and competitive positioning. "
            "Use this to answer: 'What drugs are combined with Drug X in clinical trials?'"
        ),
        "input_schema": DetectCombinationTherapiesInput.model_json_schema(),
        "handler": _handle_detect_combination_therapies,
    },
    "find_investigators": {
        "description": (
            "Find principal investigators and Key Opinion Leaders (KOLs) by medical "
            "condition or drug name. Searches active ClinicalTrials.gov trials and "
            "extracts investigator names, roles, affiliations, and contact details. "
            "Also searches PubMed for recent publications by KOLs in the field. "
            "Use this for competitive intelligence, trial design, and KOL mapping. "
            "Use this to answer: 'Who are the key investigators in [disease] research?'"
        ),
        "input_schema": FindInvestigatorsInput.model_json_schema(),
        "handler": _handle_find_investigators,
    },
}


# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# MCP Server
# ─────────────────────────────────────────────────────────────

server = Server("drug-pipeline")


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=meta["description"],
            inputSchema=meta["input_schema"],
        )
        for name, meta in TOOLS.items()
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any] | None) -> list[types.TextContent]:
    meta = TOOLS.get(name)
    if not meta:
        return [
            types.TextContent(
                type="text",
                text=_dump_json(
                    {
                        "status": "error",
                        "error_code": "UNKNOWN_TOOL",
                        "message": f"Tool '{name}' not found. Available: {list(TOOLS.keys())}",
                    }
                ),
            )
        ]
    deadline_token = set_request_deadline(_TOOL_TIMEOUT_SECONDS)
    try:
        return await asyncio.to_thread(meta["handler"], **(arguments or {}))
    except KeyError as e:
        return [
            types.TextContent(
                type="text",
                text=_dump_json(
                    {
                        "status": "error",
                        "error_code": "VALIDATION_ERROR",
                        "message": f"Missing required field: {e}",
                    }
                ),
            )
        ]
    except ValueError as e:
        return [
            types.TextContent(
                type="text",
                text=_dump_json(
                    {
                        "status": "error",
                        "error_code": "VALIDATION_ERROR",
                        "message": str(e),
                    }
                ),
            )
        ]
    except Exception as e:
        import traceback

        tb = traceback.format_exc()
        return [
            types.TextContent(
                type="text",
                text=_dump_json(
                    {
                        "status": "error",
                        "error_code": "TOOL_ERROR",
                        "message": str(e)[:200],
                        "traceback": tb.split("\n")[-6:]
                        if "--debug" in sys.argv
                        else "Use --debug for traceback",
                    }
                ),
            )
        ]
    finally:
        reset_request_deadline(deadline_token)


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="drug-pipeline",
                server_version=__version__,
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run_stdio():
    """Start the MCP server in stdio mode (default)."""
    import asyncio

    asyncio.run(main())


async def run_http(host: str = "0.0.0.0", port: int = 8080):
    """Start the MCP server in HTTP/SSE mode."""
    try:
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route
    except ImportError:
        print("HTTP mode requires: pip install mcp[httpx] uvicorn")
        sys.exit(1)

    sse = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            read_stream, write_stream = streams
            await server.run(read_stream, write_stream, server.create_initialization_options())

    async def handle_root(request):
        return JSONResponse(
            {
                "server": "drug-pipeline",
                "version": __version__,
                "description": "Pharmaceutical R&D Intelligence MCP Server — Clinical trials, FDA/EMA approvals, safety data, drug labels, recalls, patents, pricing, site intelligence, and company pipelines. 28 tools, 8 data sources.",
                "tools": list(TOOLS.keys()),
                "docs": "https://github.com/beckyeeky/drug-pipeline-mcp",
                "endpoints": {
                    "sse": "/sse",
                    "server_card": "/.well-known/mcp/server-card.json",
                    "config_schema": "/.well-known/mcp/config-schema.json",
                },
            }
        )

    async def handle_server_card(request):
        tools_list = []
        for name, meta in TOOLS.items():
            tools_list.append(
                {
                    "name": name,
                    "description": meta["description"],
                    "inputSchema": meta["input_schema"],
                }
            )
        return JSONResponse(
            {
                "serverInfo": {"name": "drug-pipeline", "version": __version__},
                "description": "Pharmaceutical R&D Intelligence MCP Server. Kombiniert ClinicalTrials.gov, openFDA, EMA, RxNorm, PubMed, und FAERS zu einer umfassenden Pharma-Intelligenz für KI-Agenten.",
                "homepage": "https://github.com/beckyeeky/drug-pipeline-mcp",
                "license": "MIT",
                "author": {
                    "name": "DrugPipelineMCP",
                    "url": "https://github.com/beckyeeky",
                },
                "iconUrl": "https://raw.githubusercontent.com/DasClown/CropProphEU/main/static/icon.svg",
                "capabilities": {
                    "tools": {"total": len(tools_list), "list": [t["name"] for t in tools_list]},
                    "resources": {"total": 1, "list": ["ema://medicines"]},
                    "prompts": {
                        "total": 3,
                        "list": ["drug-pipeline", "trial-search", "safety-review"],
                    },
                },
                "dataSources": [
                    {
                        "name": "ClinicalTrials.gov",
                        "type": "trials",
                        "url": "https://clinicaltrials.gov/",
                    },
                    {"name": "openFDA", "type": "approvals", "url": "https://open.fda.gov/"},
                    {"name": "EMA", "type": "approvals", "url": "https://www.ema.europa.eu/"},
                    {"name": "RxNorm", "type": "rx", "url": "https://rxnav.nlm.nih.gov/"},
                    {
                        "name": "PubMed",
                        "type": "research",
                        "url": "https://pubmed.ncbi.nlm.nih.gov/",
                    },
                    {
                        "name": "FAERS",
                        "type": "safety",
                        "url": "https://www.fda.gov/drugs/drug-approvals-and-databases/fda-adverse-event-reporting-system-faers",
                    },
                    {"name": "MyChem.info", "type": "orphan-drugs", "url": "https://mychem.info/"},
                    {"name": "NADAC/CMS", "type": "pricing", "url": "https://data.medicaid.gov/"},
                    {
                        "name": "Open Targets",
                        "type": "targets",
                        "url": "https://platform.opentargets.org/",
                    },
                    {
                        "name": "DailyMed (NIH/NLM)",
                        "type": "labels",
                        "url": "https://dailymed.nlm.nih.gov/",
                    },
                ],
                "tools": tools_list,
                "resources": [
                    {
                        "name": "EMA Medicines",
                        "uri": "ema://medicines",
                        "description": "EU Medicines database: aktuelle EMA-Zulassungen, Indikationen, Wirkstoffe",
                        "mimeType": "application/json",
                    },
                ],
                "prompts": [
                    {
                        "name": "drug-pipeline",
                        "description": "Full pipeline for a drug: FDA approvals + EU status + safety + trials + publications",
                        "arguments": [
                            {
                                "name": "drug_name",
                                "description": "Drug name (brand or generic)",
                                "required": True,
                            },
                        ],
                    },
                    {
                        "name": "trial-search",
                        "description": "Find clinical trials for a condition with phase/status filters",
                        "arguments": [
                            {
                                "name": "condition",
                                "description": "Medical condition to search",
                                "required": True,
                            },
                            {
                                "name": "phase",
                                "description": "Optional phase filter (PHASE1, PHASE2, PHASE3)",
                                "required": False,
                            },
                        ],
                    },
                    {
                        "name": "safety-review",
                        "description": "Safety profile for a drug: adverse events, reactions, outcomes",
                        "arguments": [
                            {
                                "name": "drug_name",
                                "description": "Drug name to analyze",
                                "required": True,
                            },
                        ],
                    },
                ],
            }
        )

    async def handle_config_schema(request):
        return JSONResponse(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {
                    "default_drug": {
                        "type": "string",
                        "title": "Standard-Wirkstoff",
                        "default": "",
                        "description": "Standard-Wirkstoff für Schnellabfragen",
                        "examples": ["KEYTRUDA", "Ozempic"],
                    },
                    "language": {
                        "type": "string",
                        "title": "Sprache",
                        "default": "en",
                        "enum": ["en", "de"],
                        "description": "Ausgabesprache",
                    },
                    "max_trials": {
                        "type": "integer",
                        "title": "Max Studien",
                        "default": 10,
                        "minimum": 1,
                        "maximum": 100,
                        "description": "Maximale Anzahl klinischer Studien pro Suche",
                    },
                },
                "required": [],
            }
        )

    app = Starlette(
        routes=[
            Route("/", endpoint=handle_root),
            Route("/.well-known/mcp/server-card.json", endpoint=handle_server_card),
            Route("/.well-known/mcp/config-schema.json", endpoint=handle_config_schema),
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )
    import uvicorn

    config = uvicorn.Config(app, host=host, port=port)
    srv = uvicorn.Server(config)
    print(f"💊 drug-pipeline HTTP server on http://{host}:{port}/sse")
    await srv.serve()


# ─────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--test" in sys.argv:
        import asyncio

        asyncio.run(main())
    elif "--http" in sys.argv:
        import asyncio

        asyncio.run(run_http(host="0.0.0.0", port=8081))
    else:
        run_stdio()
