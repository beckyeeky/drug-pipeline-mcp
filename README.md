# 💊 drug-pipeline-mcp

[![CI](https://github.com/beckyeeky/drug-pipeline-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/beckyeeky/drug-pipeline-mcp/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-61_✔️-brightgreen)](https://github.com/beckyeeky/drug-pipeline-mcp/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Pharmaceutical R&D Pipeline Intelligence for AI Agents** — a lightweight MCP server that aggregates clinical trial data, FDA/EMA approvals, safety surveillance (FAERS), drug labels, patents, drug interactions, recalls, and publications through a unified API. Every output includes a verifiable source identifier (NCT ID, FDA Application Number, or PMID).

> 🍴 **This is a fork** of [DasClown/drug-pipeline-mcp](https://github.com/DasClown/drug-pipeline-mcp). Original author: [@DasClown](https://github.com/DasClown).

---

## 🍴 Fork Changes (vs Upstream)

| Change | Detail |
|--------|--------|
| **Cross-platform EMA path** | Changed from hardcoded `/tmp/ema_medicines.xlsx` to project-local `drug_pipeline/ema_medicines.xlsx` — works on Windows, Linux, and macOS without manual setup |
| **Auto-download EMA data** | EMA medicines register auto-downloads on first use (no manual download needed) |
| **License metadata fix** | PEP 621-compliant `license = {text = "MIT"}` format, removed deprecated classifier |
| **PyPI / Git URLs** | All repository references updated to this fork |

---

## Quick Start

### From Source (Windows / Linux / macOS)

```bash
# 1. Clone
git clone https://github.com/beckyeeky/drug-pipeline-mcp.git
cd drug-pipeline-mcp

# 2. Install in editable mode
pip install -e .

# 3. Start MCP server (stdio)
drug-pipeline

# Or HTTP mode for remote access
pip install drug-pipeline-mcp[http]
drug-pipeline --http --port 8081
```

### Windows-Specific Notes

```powershell
# PowerShell terminal — use these commands:
git clone https://github.com/beckyeeky/drug-pipeline-mcp.git
cd drug-pipeline-mcp
pip install -e .

# EMA data is auto-downloaded to drug_pipeline/ema_medicines.xlsx on first use
# No /tmp directory needed

# Start server
drug-pipeline
```

### Linux / macOS

```bash
git clone https://github.com/beckyeeky/drug-pipeline-mcp.git
cd drug-pipeline-mcp
pip install -e .
drug-pipeline
```

**All dependencies**: The EMA XLSX parser (`openpyxl`) is included as a required dependency. No extra steps needed.

---

## Tools (28)

| Tool | What it does | Data Source |
|------|-------------|-------------|
| `search_trials` | Search clinical trials by condition, phase, status, sponsor | ClinicalTrials.gov |
| `get_trial_detail` | Full protocol for a specific NCT (eligibility, outcomes, locations) | ClinicalTrials.gov |
| `get_trial_results` | Trial outcomes — endpoints, adverse events, participant flow | ClinicalTrials.gov |
| `get_trial_sites` | Trial site locations — facilities, countries, geo distribution | ClinicalTrials.gov |
| `lookup_drug` | Drug info: active ingredients, strength, ATC classification, NDC | openFDA + RxNorm |
| `get_approvals` | FDA approval history with submission dates and status | openFDA Drugs@FDA |
| `get_eu_approvals` | EU/EMA authorization — brand names, ATC, status, orphan/biosimilar flags | EMA Daily XLSX |
| `get_safety_data` | FAERS adverse event reports — top reactions, serious outcomes, total count | openFDA FAERS |
| `detect_safety_signals` | Disproportionality screening (exploratory) — AE reporting ratios | openFDA FAERS |
| `get_drug_label` | FDA prescribing info — indications, boxed warnings, contraindications, dosing | openFDA Drug Labeling |
| `get_dailymed_label` | NIH drug label (OTC + Rx) — SPL set ID, version, DailyMed URL | DailyMed (NIH/NLM) |
| `get_recalls` | FDA drug recalls — Class I/II/III, reasons, dates, firms | openFDA Enforcement |
| `get_patent_expiry` | Patent & exclusivity — approval dates, market exclusivity estimates | openFDA |
| `get_drug_interactions` | Drug-drug interactions — FDA label + FAERS co-reported drugs | openFDA Labeling + FAERS |
| `get_drug_pricing` | US drug product ID — NDC codes, manufacturers, strength, form | openFDA NDC Directory |
| `get_opentargets_drug` | Drug-target MOA — mechanisms, targets, clinical stage, drug type | Open Targets (EMBL-EBI) |
| `get_us_orphan_designations` | US FDA Orphan Drug Designations — indication, status, exclusivity | MyChem.info |
| `approved_for_condition` | Find drugs by indication — which are EU-approved for a condition | EMA Daily XLSX |
| `list_orphan_drugs` | EU orphan drug designations — filter by therapeutic area | EMA Daily XLSX |
| `list_biosimilars` | EU biosimilars — filter by condition / therapeutic area | EMA Daily XLSX |
| `list_loss_of_exclusivity` | LOE timing — biosimilar competition by active substance | EMA + FDA |
| `company_pipeline` | Company R&D — trials grouped by phase + EU approval enrichment | ClinicalTrials.gov + EMA |
| `search_publications` | PubMed search for drug/trial publications | PubMed / NCBI |
| `find_investigators` | KOL / PI search — investigators by condition or drug | ClinicalTrials.gov + PubMed |
| `detect_combination_therapies` | Combination therapy detection — co-administered drugs in trials | ClinicalTrials.gov |
| `compare_drugs` | Head-to-head — FDA, EU, MOA, safety, patent across 2 drugs | Composite |
| `drug_pipeline` | **Composite** — drug info + FDA + EU + safety + label + signals + recalls + interactions + trials + pubs + patent | All sources |
| `pipeline_landscape` | **Full pipeline for a condition** — approved + Phase 3/2/1 + mechanisms + sponsors + pubs | Composite |

> ⚠️ **`detect_safety_signals`**: Exploratory disproportionality screening — uses an approximate denominator, not a validated PRR. Not for regulatory or clinical use.

---

## Architecture

```
drug-pipeline-mcp/
├── drug_pipeline/
│   ├── __init__.py        # Version
│   ├── server.py          # MCP server (28 tools)
│   └── sources.py         # Data source fetchers (API aggregation layer)
├── drug_pipeline_cli.py   # CLI entry point
├── tests/                 # 61 unit tests (pytest)
├── pyproject.toml
└── README.md
```

**Design philosophy:** Lightweight API aggregation. No caching layer. No ML models. No predictions. Each tool makes real-time requests to a public API and returns structured data with source identifiers.

**Limitations by design:**
- Rate limits apply per source (openFDA: 10 req/sec, ClinicalTrials.gov: generous)
- EMA data sourced from a daily-updated XLSX register — auto-downloaded on first use
- FAERS data is spontaneous reporting, not incidence rates
- The server does not interpret, predict, or synthesize beyond what the sources provide

---

## Data Sources

| Source | Data | Access |
|--------|------|--------|
| ClinicalTrials.gov | 500K+ studies, phases, status, eligibility, results, site locations | ✅ Always free |
| openFDA NDC Directory | Drug product ID, NDC codes, manufacturers | ✅ Always free |
| openFDA FAERS | Adverse event reports, reactions, serious outcomes | ✅ Always free |
| openFDA Drug Labeling | Prescribing info, interactions, contraindications | ✅ Always free |
| openFDA Drugs@FDA | Approval history, submissions, orphan designations | ✅ Always free |
| openFDA Enforcement | Recalls, market withdrawals, safety alerts | ✅ Always free |
| RxNorm / RxNav | Drug identifiers, RxCUI, ATC classification | ✅ Always free |
| PubMed / NCBI | Scientific publications, abstracts, PMIDs | ✅ Always free |
| EMA Medicines Register | EU authorization status, ATC, orphan/biosimilar flags | ✅ Always free |
| Open Targets (EMBL-EBI) | Drug-target mechanisms of action, clinical development stage | ✅ Always free |
| DailyMed (NIH/NLM) | Drug labels (OTC + Rx), structured product labeling | ✅ Always free |
| MyChem.info | US FDA Orphan Drug Designations | ✅ Always free |

**All sources are publicly funded and freely accessible.** No API keys, subscriptions, or licensing required.

---

## Verifiable Outputs

Every data point includes a direct link to its primary source:

| Output Field | Example Source URL |
|-------------|-------------------|
| NCT ID | `https://clinicaltrials.gov/study/NCT03178617` |
| FDA Application Number | `https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm?event=overview.process&ApplNo=NDA125456` |
| PMID | `https://pubmed.ncbi.nlm.nih.gov/37272535/` |
| FDA Product NDC | `https://www.accessdata.fda.gov/scripts/cder/ndc/` |
| DailyMed SPL Set ID | `https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=xxx` |

---

## Client Integration

### Claude Desktop

```json
{
  "mcpServers": {
    "drug-pipeline": {
      "command": "python3",
      "args": ["-m", "drug_pipeline.server"]
    }
  }
}
```

On Windows, use `python` instead of `python3`:

```json
{
  "mcpServers": {
    "drug-pipeline": {
      "command": "python",
      "args": ["-m", "drug_pipeline.server"]
    }
  }
}
```

### Cursor / VS Code

```json
{
  "mcpServers": {
    "drug-pipeline": {
      "command": "uvx",
      "args": ["drug-pipeline-mcp"]
    }
  }
}
```

### ChatWise / Other Clients

```json
{
  "mcpServers": {
    "drug-pipeline": {
      "command": "python",
      "args": ["-m", "drug_pipeline.server"]
    }
  }
}
```

If your client supports environment variables, these settings help avoid long hangs on slower Windows networks by returning a timeout error or partial result sooner:

```json
{
  "mcpServers": {
    "drug-pipeline": {
      "command": "python",
      "args": ["-m", "drug_pipeline.server"],
      "env": {
        "DRUG_PIPELINE_TOOL_TIMEOUT": "20",
        "DRUG_PIPELINE_REQUEST_TIMEOUT": "8"
      }
    }
  }
}
```

### HTTP / SSE (Remote)

```bash
pip install drug-pipeline-mcp[http]
drug-pipeline --http --port 8081
```

Connect at `http://your-server:8081/sse`.

---

## Example Agent Queries

> *"What's in the pipeline for GLP-1 agonists?"*
→ `drug_pipeline(drug_name="semaglutide")` → ATC class, FDA status, clinical trials, publications

> *"Which companies have Phase 3 trials for non-small cell lung cancer?"*
→ `search_trials(condition="non-small cell lung cancer", phase="PHASE3", status="RECRUITING")`

> *"Is pembrolizumab approved in the EU vs US?"*
→ `get_approvals(drug_name="Keytruda")` + `get_eu_approvals(drug_name="Keytruda")`

> *"What are the safety signals for semaglutide?"*
→ `get_safety_data(drug_name="semaglutide")` + `detect_safety_signals(drug_name="semaglutide")`

---

## 🍴 Syncing with Upstream

This fork tracks [DasClown/drug-pipeline-mcp](https://github.com/DasClown/drug-pipeline-mcp) as upstream.

```bash
# One-time setup
git remote add upstream https://github.com/DasClown/drug-pipeline-mcp.git

# Sync latest changes
git fetch upstream
git merge upstream/main
git push origin main
```

---

## 🤝 Getting Help & Contributing

| Channel | Purpose |
|---------|---------|
| **[🐛 GitHub Issues](https://github.com/beckyeeky/drug-pipeline-mcp/issues)** | Bug reports, feature requests |
| **[📖 CONTRIBUTING.md](CONTRIBUTING.md)** | Development setup, code style, testing |
| **[⬆️ Original Upstream](https://github.com/DasClown/drug-pipeline-mcp)** | Original project by @DasClown |

---

## License

MIT — see [LICENSE](LICENSE). Original work by [@DasClown](https://github.com/DasClown).
