# Changelog — drug-pipeline-mcp

## 2026-05-13 (v0.6.0)

#### Added (Regulatory Intelligence)
- **📄 `docs/local-regulation-2026.md`** — Comprehensive multi-jurisdiction regulatory reference covering all 7 major pharma markets (US IRA, DE AMNOG, FR HAS/CEPS, IT AIFA, UK MHRA/NICE, JP PMDA/NHI, CN NMPA/NRDL)
- **Pipeline Risk Matrix** — Small molecule vs. biologic vs. orphan risk assessment across jurisdictions
- **IRA 2026 timeline** — First Medicare price negotiation takes effect Sep 1, 2026 (10 drugs, ~$50.2B spend)
- **AMNOG Reform 2026** — Fixed effect-size thresholds (<15% RRR = no added benefit), stricter combo rules
- **China NRDL analysis** — Annual –61% average price cuts, PD-1 price war (–70%)
- **NICE key appraisals** — Wegovy, Mounjaro, Alzheimer drugs status

### Changed
- **README** — Added `docs/` reference and regulatory intelligence use cases
- **pyproject.toml** — v0.5.3 → v0.6.0

---

#### Fixed
- **🐛 Health Check PubMed-Endpunkt** — `echo`-Endpoint war veraltet (HTTP 400), auf `einfo.fcgi` umgestellt. Alle 9 Checks passen jetzt.
- **Health Check Script** nach `/root/.hermes/profiles/drug-pipeline/scripts/` kopiert für Cron-Job-Zugriff.

## 2026-05-05 (v0.5.4)

#### Added
- **get_drug_interactions Tool (#17)** — FDA Label Interactions + FAERS Co-Reported Drugs
- **README Badges**: CI passing, Docker ghcr.io, PyPI version
- **Smithery-Konfiguration**: get_drug_interactions registriert

### Changed
- **drug_pipeline Composite** — enthält jetzt drug_interactions-Sektion
- **README**: 17 Tools dokumentiert
- **Server Card**: auf 17 Tools aktualisiert

## 2026-05-05 (v0.5.3)

#### Fixed
- **🐛 openpyxl fehlte in Dependencies** — EMA-Funktionen (`get_eu_approvals`, `approved_for_condition`, `list_orphan_drugs`) gaben stumm leere Results zurück, weil `openpyxl` nicht installiert war. Jetzt als Pflichtdependency in `pyproject.toml`.
- **EMA-Fehlerbehandlung** — Wenn `openpyxl` doch fehlt, wird ein logging-Warning ausgegeben statt silent fail.

## 2026-05-05 (v0.5.2)

#### Added
- **Tests** (`tests/`) — 31 Unit-Tests: Cache-Logik, Input-Validierung, Tool-Registrierung, Fehlerbehandlung
- **CI/CD Multi-Python Matrix** (`.github/workflows/ci.yml`) — pytest auf Python 3.10, 3.11, 3.12 parallel
- **PyPI Publish Workflow** (`.github/workflows/publish.yml`) — OIDC-basierter PyPI-Upload bei Releases
- **Docker Multi-Arch Build** (`.github/workflows/docker.yml`) — ghcr.io: linux/amd64 + linux/arm64, Buildx-Caching, Semver-Tags
- **smithery.json** — optimierte Smithery-Deployment-Konfiguration mit allen 16 Tools

### Changed
- **Dockerfile** — auf python:3.12-slim aktualisiert, tini für Signal-Handling, Labels, bessere HEALTHCHECK

#### Added
- **GitHub Actions CI** (`.github/workflows/ci.yml`) — ruff lint + smoke test bei jedem Push/PR
- **Dockerfile** + **docker-compose.yml** — Container-Betrieb mit Healthcheck
- **LICENSE** — MIT-Lizenz als separate Datei
- **PyPI-Readiness** — URLs, dev dependencies, ruff-Konfig, License-Deprecation gefixt
- **Issue Templates** (`.github/ISSUE_TEMPLATE/`) — Bug Report, Feature Request, Config
- **CONTRIBUTING.md** — vollständiger Leitfaden für Contributionen
- **Version-Sync** — pyproject.toml auf v0.5.0 aktualisiert
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
