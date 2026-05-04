# Contributing — drug-pipeline-mcp

🎉 Danke, dass du zu **drug-pipeline-mcp** beitragen willst!  
Pharma R&D Intelligence für AI Agents — jedes Issue, jeder PR und jedes Feedback hilft.

## 📋 Inhaltsverzeichnis

- [Verhaltenskodex](#verhaltenskodex)
- [Wie kann ich beitragen?](#wie-kann-ich-beitragen)
- [Issues](#issues)
  - [Bug Reports](#bug-reports)
  - [Feature Requests](#feature-requests)
- [Pull Requests](#pull-requests)
  - [Vorbereitung](#vorbereitung)
  - [Branch-Naming](#branch-naming)
  - [Commit-Naming](#commit-naming)
  - [Code-Style](#code-style)
  - [Tests](#tests)
  - [CHANGELOG](#changelog)
- [Entwicklungsumgebung](#entwicklungsumgebung)
- [Release-Prozess](#release-prozess)
- [Datenquellen & Limits](#datenquellen--limits)

---

## Verhaltenskodex

Sei respektvoll, konstruktiv und sachlich. Dieses Projekt lebt von offener Zusammenarbeit.

## Wie kann ich beitragen?

- **🐛 Bugs melden** → Issue aufmachen (Template nutzen)
- **💡 Feature vorschlagen** → Issue aufmachen (Template nutzen)
- **🔧 Code beitragen** → PR stellen (siehe unten)
- **📖 Dokumentation verbessern** → README / Wiki PR
- **⭐ Star geben** — hilft bei Sichtbarkeit!

## Issues

### Bug Reports

Nutze das **Bug Report Template**. Wichtig:

- **Reproduktionsschritte** — so genau wie möglich
- **MCP Client & Version** — Claude Desktop, Cursor, custom?
- **Tool + Parameter** — welches Tool mit welchen Parametern?
- **Logs / Fehlermeldungen** — stdout/stderr, Traceback

### Feature Requests

Nutze das **Feature Request Template**. Wichtig:

- **Problem & Lösung** — nicht nur die Lösung, auch das Problem dahinter
- **Use Case** — in welchem Szenario brauchst du das?
- **Datenquelle** — falls bekannt: ClinicalTrials.gov, openFDA, EMA, PubMed, FAERS

## Pull Requests

### Vorbereitung

1. Forke das Repository
2. Erstelle einen Feature-Branch
3. Implementiere deine Änderung
4. Füge Tests hinzu (wenn möglich)
5. Stelle den PR gegen `main`

### Branch-Naming

```
fix/fehler-kurzbeschreibung
feat/feature-name
docs/was-wurde-geaendert
chore/aufgabe
```

### Commit-Naming

Conventional Commits:

```
feat: neue Funktion XYZ
fix: search_trials double-encoding behoben
docs: README erweitert
refactor: caching layer extrahiert
chore: CI Pipeline aktualisiert
test: Tests für get_fda_approvals
```

### Code-Style

- **Python 3.10+** Typannotationen (Type Hints) — Pflicht
- **Pydantic v2** für Datenmodelle
- **Docstrings** — Google Style oder NumPy Style
- **Max 100 Zeichen pro Zeile**
- Lint mit `ruff` vor dem Commit:
  ```bash
  ruff check .
  ruff format --check .
  ```

### Tests

- Tests liegen in `tests/`
- pytest mit:
  ```bash
  pytest -v
  ```
- Tests sind API-abhängig — fake/mock erwünscht, wo sinnvoll
- Jeder neue Tool-Endpoint braucht mindestens einen Happy-Path-Test

### CHANGELOG

Jeder PR muss einen Eintrag in `CHANGELOG.md` haben:

```markdown
## YYYY-MM-DD

### Added
- ...

### Changed
- ...

### Fixed
- ...
```

## Entwicklungsumgebung

```bash
# Clone
git clone https://github.com/DasClown/drug-pipeline-mcp.git
cd drug-pipeline-mcp

# Venv (optional)
python -m venv venv
source venv/bin/activate

# Dev install
pip install -e ".[http]"

# Test
pytest -v
```

Kein API-Key nötig — alle Datenquellen sind öffentlich und kostenlos.

## Release-Prozess

1. `CHANGELOG.md` finalisieren
2. Version in `pyproject.toml` aktualisieren
3. Taggen: `git tag v0.X.0 && git push origin v0.X.0`
4. GitHub Release mit Release Notes erstellen

## Datenquellen & Limits

| Quelle | Rate Limit | Kosten |
|--------|-----------|--------|
| ClinicalTrials.gov | ~100 req/10s | 💰 Frei |
| openFDA | ~240 req/min | 💰 Frei |
| EMA | ~10 req/min (empfohlen) | 💰 Frei |
| RxNorm (UTS) | keine harten Limits | 💰 Frei (Login nötig) |
| PubMed E-utilities | 10 req/s + 3 req/s ohne API-Key | 💰 Frei |
| FAERS (openFDA) | ~240 req/min | 💰 Frei |

---

**Noch Fragen?** Schreib ein Issue oder ping @DasClown auf GitHub! 🚀
