# Changelog — drug-pipeline-mcp

## 2026-05-04

### Added
- **TTL-Caching-Layer** (`_cached_fetch`) — API-Responses werden 5 Minuten (Standard) zwischengespeichert, reduziert Latenz bei Wiederholungsanfragen drastisch
- **EMA-Cache Auto-Refresh** bei Modul-Import — EMA-Medikamentenliste wird beim Start im Hintergrund aktualisiert
- **get_drug_label** und **get_recalls** nutzen jetzt `_cached_fetch` (5 Min TTL)

### Changed
- **get_patent_expiry** grundlegend überarbeitet 🔬
  - Liefert jetzt `marketing_status` (Prescription/OTC/Discontinued)
  - `reference_listed_drug` (RLD) Flag — ist es das Original-Präparat?
  - `therapeutic_equivalence` Codes (AB, AA, BC) mit Beschreibung
  - `estimated_exclusivity` basierend auf Submission-Typen:
    - Type 1 (New Molecular Entity) → 5-Jahres-Exklusivität
    - Type 3-5 (neue Formulierung/Kombination) → 3-Jahres-Exklusivität
  - `total_submissions` Count
  - Nutzt `_cached_fetch` mit 1h TTL
  - Hinweis: FDA Orange Book Downloads wurden eingestellt (alle URLs 404)
  - `get_drug_label` — FDA-Arzneimittelkennzeichnung (Indikationen, Boxed Warnings, Kontraindikationen, Dosierung) via openFDA Drug Labeling API
  - `get_recalls` — FDA-Rückrufaktionen (Class I/II/III, Gründe, Daten, Firmen) via openFDA Enforcement API
  - `detect_safety_signals` — PRR (Proportional Reporting Ratio) Signalerkennung aus FAERS-Daten, erweiterte Pharmakovigilanz
  - `get_patent_expiry` — FDA-Patent- und Exklusivitätsinformationen (Zulassungsdaten, Marktexklusivität)
- **drug_pipeline Composite** um 4 neue Datenbereiche erweitert: drug_label, recalls, safety_signals, patent_info
- **Optimierungs-Cron** (wöchentlich montags) — Markt- & Wettbewerbsrecherche
- **Monats-Update-Cron** (1. des Monats) — automatischer Git-Pull, EMA-Update, Build & Push

### Fixed
- **pyproject.toml:** build-backend auf `setuptools.build_meta` aktualisiert (Kompatibilität mit setuptools 82+)
- **get_recalls:** Feldname in drug_pipeline_summary korrigiert

### Changed
- Version auf v0.5.0 angehoben
- README aktualisiert: 16 Tools, neue Beispielqueries
- Server-Card & Root-Endpoint auf 16 Tools aktualisiert

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
