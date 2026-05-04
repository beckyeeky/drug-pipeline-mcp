# Changelog — drug-pipeline-mcp

## 2026-05-04

### Changed
- Monthly auto-update: EMA-Medikamentenliste aktualisiert (2.688 Einträge)
- pyproject.toml: build-backend auf setuptools.build_meta aktualisiert

## 2026-05-03

### Added
- Erstes Release: drug-pipeline-mcp v0.4.0
- 12 MCP Tools: search_trials, get_trial_detail, lookup_drug, get_approvals, get_eu_approvals, get_safety_data, approved_for_condition, get_trial_results, list_orphan_drugs, company_pipeline, search_publications, drug_pipeline
- 6 freie Datenquellen: ClinicalTrials.gov, openFDA, EMA, RxNorm, PubMed, FAERS
- GitHub: https://github.com/DasClown/drug-pipeline-mcp
- Automatischer Health-Check Cron-Job (alle 2 Tage)
- Optimierungs-Cron (wöchentlich)
- Telegram Bot Integration (/home/j/bots/telegram_bot.py)
- CHANGELOG.md

### Fixed
- search_trials: double-encoding bug behoben (AREA[ConditionSearch]/ → native query.cond)
- get_fda_approvals: API-Feld korrigiert (products.generic_name → products.active_ingredients.name)
