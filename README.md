# 💊 drug-pipeline-mcp

**Pharmaceutical R&D Pipeline Intelligence for AI Agents** — Clinical trials, FDA approvals, drug information & publications in one MCP server.

No hallucination. Every output traces to a source NCT ID, FDA application number, or PMID.

## Quick Start

```bash
pip install git+https://github.com/DasClown/drug-pipeline-mcp.git

# Start MCP server (stdio)
drug-pipeline

# Or HTTP mode for remote access
pip install drug-pipeline-mcp[http]
drug-pipeline --http --port 8081
```

## Tools (6)

| Tool | What it does | Data Source |
|------|-------------|-------------|
| `search_trials` | Search clinical trials by condition, phase, status, sponsor | ClinicalTrials.gov |
| `get_trial_detail` | Full protocol for a specific NCT (eligibility, outcomes, locations) | ClinicalTrials.gov |
| `lookup_drug` | Drug info: active ingredients, strength, ATC classification, NDC | openFDA + RxNorm |
| `get_approvals` | FDA approval history with submission dates and status | openFDA |
| `get_eu_approvals` | **EU/EMA authorization status** — brand names, ATC, status, orphan/biosimilar flags | EMA Daily XLSX |
| `get_safety_data` | **FAERS adverse event reports** — top reactions, serious outcomes, total count | openFDA FAERS |
| `approved_for_condition` | **Find drugs by indication** — which drugs are EU-approved for a condition | EMA Daily XLSX |
| `get_trial_results` | **Trial results** — outcome measures, adverse events, baseline, participant flow | ClinicalTrials.gov |
| `list_orphan_drugs` | **EU orphan drug designations** — filter by therapeutic area | EMA Daily XLSX |
| `company_pipeline` | **Company R&D pipeline** — all trials grouped by phase + EU approval status | ClinicalTrials.gov + EMA |
| `search_publications` | PubMed search for drug/trial publications | PubMed / NCBI |
| `drug_pipeline` | **Composite** — drug info + FDA + EU + safety + trials + pubs + orphan | All sources |

## Example Agent Queries

> *"What's in the pipeline for GLP-1 agonists?"*
→ `drug_pipeline(drug_name="semaglutide")` → ATC class, FDA status, 10+ trials, publications

> *"Which companies have Phase 3 trials for non-small cell lung cancer?"*
→ `search_trials(condition="non-small cell lung cancer", phase="PHASE3", status="RECRUITING")`

> *"Is pembrolizumab approved in the EU vs US?"*
→ `get_approvals(drug_name="Keytruda")` → FDA submission history with dates
→ `get_eu_approvals(drug_name="Keytruda")` → EU authorization status

> *"What are the safety signals for semaglutide?"*
→ `get_safety_data(drug_name="semaglutide")` → 6,027 FAERS reports, top reactions: Nausea (862), Vomiting (750)

> *"What drugs are approved for non-small cell lung cancer?"*
→ `approved_for_condition(condition="non-small cell lung cancer")` → 82 drugs (Keytruda, Tagrisso, Opdivo, Tecentriq, ...)

> *"What are the eligibility criteria for NCT03178617?"*
→ `get_trial_detail(nct_id="NCT03178617")`

## Example Output (drug_pipeline)

```json
{
  "status": "ok",
  "query": {"drug_name": "semaglutide"},
  "drug_info": {
    "atc_classification": {"code": "A10BJ", "name": "GLP-1 analogues"},
    "rxcui": "1991302",
    "products": [{"brand_name": "Ozempic", "generic_name": "semaglutide", "labeler": "Novo Nordisk"}]
  },
  "clinical_trials": { "results": [ ... ] },
  "publications": { "total_count": 846, "returned_count": 5 },
  "data_sources": ["openFDA", "RxNorm", "PubMed", "clinicaltrials.gov"]
}
```

## Architecture

```
drug-pipeline-mcp/
├── drug_pipeline/
│   ├── __init__.py        # Version
│   ├── server.py          # MCP server (6 tools)
│   └── sources.py         # Data source fetchers
├── drug_pipeline_cli.py   # CLI entry point
├── pyproject.toml
└── README.md
```

No machine learning. No predictions. Only structured synthesis of verified primary sources.

## Data Sources

| Source | Data | Free |
|--------|------|------|
| ClinicalTrials.gov | 500K+ studies, phases, status, eligibility, **results** | ✅ Always free |
| openFDA Drug Approvals | FDA approvals, NDC directory, submissions | ✅ Always free |
| openFDA FAERS | Adverse event reports, reactions, outcomes | ✅ Always free |
| RxNorm / RxNav | Drug identifiers, ATC classification | ✅ Always free |
| PubMed / NCBI | Scientific publications | ✅ Always free |
| EMA Medicines Register | EU authorization status, ATC, orphan/biosimilar flags, **therapeutic areas** | ✅ Always free |

## Anti-Hallucination

Every result includes:
- **NCT ID** → `https://clinicaltrials.gov/study/NCT...`
- **FDA Application Number** → `https://www.accessdata.fda.gov/...`
- **PMID** → `https://pubmed.ncbi.nlm.nih.gov/PMID...`

No calculated fields, no predictions, no "ungefähre" estimates.

## License

MIT
