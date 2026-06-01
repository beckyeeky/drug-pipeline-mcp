# Fact-Check Protocol: Heidelberg Pharma ADC Report

> Systematische Prüfung aller verifizierbaren Datenpunkte gegen Primärquellen.
> Ausgeführt: 2026-05-26 02:32 UTC

## ✅ Company Financials (VERIFIED via Yahoo Finance API)

| Datenpunkt | Alter Wert | Korrigierter Wert | Quelle |
|---|---|---|---|
| Market Cap | €113M (geschätzt) | **€127,721,184** | Yahoo Finance |
| Aktienkurs | — | **€2.73** | Yahoo Finance |
| Shares Outstanding | — | **46,784,317** | Yahoo Finance |
| Enterprise Value | — | **€120,503,104** | Yahoo Finance |
| Float | — | **10,119,836** | Yahoo Finance |

## ✅ HDP-101 Clinical Trial (VERIFIED via ClinicalTrials.gov)

| Datenpunkt | Alter Wert | Korrigierter Wert | Quelle |
|---|---|---|---|
| NCT | NCT04879043 | ✅ **NCT04879043** | ClinicalTrials.gov |
| Phase | Phase 1/2 | ✅ **Phase 1/2** | ClinicalTrials.gov |
| Status | RECRUITING | ✅ **RECRUITING** | ClinicalTrials.gov |
| Enrollment | ~54 (geschätzt) | **78** | ClinicalTrials.gov |
| Start | Feb 2022 | ✅ **2022-02-07** | ClinicalTrials.gov |
| Primary Completion | — | **2025-08** | ClinicalTrials.gov |
| Completion | May 2026 | ✅ **2026-05** | ClinicalTrials.gov |
| Study Type | — | **Interventional** | ClinicalTrials.gov |
| Sex | — | **All** | ClinicalTrials.gov |
| Min Age | — | **18 Years** | ClinicalTrials.gov |
| Lead Sponsor | Heidelberg Pharma | ✅ **Heidelberg Pharma AG** | ClinicalTrials.gov |

**Kritische Detail-Korrektur:** Phase 2a schließt Patienten mit vorheriger BCMA-Therapie aus. Dies ist ein strategisch relevanter Unterschied zu Blenrep und Tecvayli.

## ✅ HDP-101 China Trial (VERIFIED via ClinicalTrials.gov)

| Datenpunkt | Alter Wert | Korrigierter Wert | Quelle |
|---|---|---|---|
| NCT | NCT07529782 | ✅ **NCT07529782** | ClinicalTrials.gov |
| Phase | Phase 1 | ✅ **Phase 1** | ClinicalTrials.gov |
| Status | RECRUITING | ✅ **RECRUITING** | ClinicalTrials.gov |
| Enrollment | — | **15** | ClinicalTrials.gov |
| Start | March 2026 | ✅ **2026-03-17** | ClinicalTrials.gov |
| Primary Completion | — | **2026-06-30** | ClinicalTrials.gov |
| Completion | Dec 2026 | ✅ **2026-12-31** | ClinicalTrials.gov |
| Sponsor | Huadong | ✅ **Hangzhou Zhongmei Huadong Pharmaceutical** | ClinicalTrials.gov |

## ✅ EU Drug Approvals (VERIFIED via EMA Register)

| Drug | ATC | EU Status | Prior Lines | Notes |
|---|---|---|---|---|
| **Blenrep** (belantamab) | L01FX15 | ✅ Authorised (combo) | 1L+ | Monotherapy authorization EXPIRED |
| **Darzalex** (daratumumab) | L01FC01 | ✅ Authorised | 1L+ | Orphan |
| **Tecvayli** (teclistamab) | L01F | ✅ Conditional | 3L+ | Bispecific BCMAxCD3 |
| **Talvey** (talquetamab) | L01FX29 | ✅ Conditional | 3L+ | Bispecific GPRC5DxCD3 |
| **Elrexfio** (elranatamab) | — | ✅ Conditional | 3L+ | Bispecific BCMAxCD3 |
| **Lynozyfic** (linvoseltamab) | L01FX | ✅ Conditional | 3L+ | Bispecific BCMAxCD3 |
| **Abecma** (ide-cel) | L01 | ✅ Authorised | **2L+** | CAR-T |
| **Carvykti** (cilta-cel) | L01XL05 | ✅ Authorised | **1L+** (len-refr) | CAR-T |
| **Sarclisa** (isatuximab) | L01XC38 | ✅ Authorised | **2L+** | CD38 mAb |
| **Kyprolis** (carfilzomib) | L01XX45 | ✅ Authorised | **1L+** | PI |
| **Nexpovio** (selinexor) | L01XX66 | ✅ Authorised | 1L+ (combo) / 4L+ (mono) | XPO1 inhibitor |

**Korrektur:** Abecma ist 2L+ (nicht 3L+), Carvykti ist 1L+ (nicht 2L+). Dies sind wichtige strategische Unterschiede für die Positionierung von HDP-101.

## ✅ Blenrep Safety (VERIFIED via openFDA FAERS)

| Datenpunkt | Alter Wert | Korrigierter Wert | Quelle |
|---|---|---|---|
| Total Reports | **2,809** ❌ | **290** | openFDA FAERS |
| Top Reaction | — | DEATH (44) | openFDA FAERS |
| Ocular Toxicity | Keratopathy dominant | KERATOPATHY (22) | openFDA FAERS |
| Serious Outcomes | — | 243 serious + 43 non-serious | openFDA FAERS |

**⚠️ KRITISCHER FEHLER:** Blenrep FAERS Reports waren 10x überhöht (2.809 statt 290). Dies ist der schwerwiegendste gefundene Datenfehler.

## Anmerkungen zu Marktschätzungen

Alle Marktgrößen (180.000 MM Fälle/Jahr, CAR-T $5B, Bispecifics $3-4B, ADC $2-4B) sind **Autorenschätzungen** und nicht aus Primärquellen verifiziert. Im Bericht müssen sie explizit als Schätzungen gekennzeichnet werden.

## Summary: Fehler-Triage

| Schweregrad | Anzahl | Beispiele |
|---|---|---|
| **Critical** | 2 | MCap falsch (€113M→€127.7M), Blenrep FAERS 10x überhöht |
| **Major** | 3 | HDP-101 Enrollment, Abecma/Carvykti Prior Lines, Blenrep Monotherapie-Status |
| **Minor** | 2 | Fehlende BCMA-Exclusion in Phase 2a, vereinfachte Blenrep-Indikation |
