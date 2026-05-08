#!/usr/bin/env python3
"""
drug-pipeline — Pipeline Data Product Generator

Generates structured JSON/YAML data from the shared wiki concept pages.
Can be consumed by other agents (crop-mcp, general, etc.) or used as API.

Usage:
  python3 pipeline-data-product.py                    → JSON to stdout
  python3 pipeline-data-product.py --format yaml       → YAML to stdout
  python3 pipeline-data-product.py --format json --output /tmp/pipeline.json

Schema:
  {
    "meta": { "generated": "ISO timestamp", "source": "drug-pipeline Wiki" },
    "pipelines": [
      {
        "indication": "COPD",
        "wikipage": "copd-pipeline-2026",
        "standard_of_care": [...],
        "failed": [...] {"drug", "reason", "phase"},
        "approved": [...] {"drug", "sponsor", "fda", "ema", "date"},
        "phase3": [...] {"drug", "target", "sponsor", "status", "data_expected"},
        "phase2": [...] {"drug", "target", "sponsor", "status"},
        "key_companies": {...}
      }
    ],
    "cross_indication": {
      "overlapping_targets": {...},
      "overlapping_companies": {...},
      "strategic_insights": [...]
    }
  }
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

WIKI_DIR = "/root/.hermes/shared-wiki/concepts"

def extract_yaml_field(content, field):
    """Extract a field from YAML frontmatter."""
    match = re.search(rf'^{field}:\s*(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip().strip('"').strip("'")
    return None

def extract_tags(content):
    """Extract tags list from YAML frontmatter."""
    match = re.search(r'tags:\s*\[(.*?)\]', content, re.MULTILINE)
    if match:
        return [t.strip().strip('"').strip("'") for t in match.group(1).split(',')]
    return []

def extract_sections(content):
    """Extract markdown sections by heading level."""
    sections = {}
    current_section = "preamble"
    current_lines = []
    
    for line in content.split('\n'):
        if line.startswith('## '):
            sections[current_section] = '\n'.join(current_lines)
            current_section = line.strip('# ').strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections[current_section] = '\n'.join(current_lines)
    return sections

def extract_pipeline_data(filepath):
    """Extract structured data from a pipeline concept page."""
    content = filepath.read_text()
    name = filepath.stem
    
    # Extract disease name from the page
    title = extract_yaml_field(content, 'title') or name
    # Clean up
    disease = title.replace('Global ', '').replace(' Pipeline 2026', '').replace(' Analyse 2026', '').strip()
    
    tags = extract_tags(content)
    sections = extract_sections(content)
    
    pipeline = {
        "indication": disease,
        "wikipage": name,
        "tags": tags,
        "standard_of_care": [],
        "failed": [],
        "approved": [],
        "phase3": [],
        "phase2": [],
        "key_companies": {}
    }
    
    # Extract companies from page
    common_companies = [
        'AstraZeneca', 'GSK', 'Sanofi', 'Novo Nordisk', 'Eli Lilly',
        'Amgen', 'Pfizer', 'Boehringer', 'Novartis', 'Roche', 'Merck',
        'BMS', 'Eisai', 'Biogen', 'Madrigal', 'Akero', 'Intercept',
        'Chiesi', 'Verona', 'Zealand', 'Viking', 'Altimmune',
        'CSPC', 'Chia Tai', 'Jiangsu Hengrui'
    ]
    companies_found = []
    for c in common_companies:
        if c.lower() in content.lower():
            companies_found.append(c)
    pipeline["company_count"] = len(companies_found)
    
    # Extract failed drugs
    failed_section = sections.get("❌ Gescheitert", sections.get("Gescheitert", ""))
    if failed_section:
        failed_drugs = re.findall(r'\*\*(.+?)\*\*', failed_section)
        pipeline["failed"] = [d for d in failed_drugs if len(d) > 2 and len(d) < 100]
    
    # Extract approved drugs  
    approved_section = sections.get("✅ Neu Zugelassen", sections.get("Neu Zugelassen", ""))
    if not approved_section:
        approved_section = sections.get("✅ Neu Zugelassen (2024–2026)", "")
    if approved_section:
        approved_drugs = re.findall(r'\*\*(.+?)\*\*', approved_section)
        pipeline["approved"] = [d for d in approved_drugs if len(d) > 2 and len(d) < 100]
    
    # Determine pipeline maturity
    phase3_count = len(re.findall(r'Phase\s*[3Ⅲ]', content))
    phase2_count = len(re.findall(r'Phase\s*[2Ⅱ]', content))
    
    if len(pipeline["approved"]) > 3 and phase3_count > 3:
        pipeline["maturity"] = "very_active"
    elif len(pipeline["approved"]) > 0:
        pipeline["maturity"] = "established"
    elif phase3_count > 2:
        pipeline["maturity"] = "building"
    else:
        pipeline["maturity"] = "early"
    
    return pipeline


def main():
    # Parse args
    fmt = "json"
    output = None
    
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--format" and i + 2 < len(sys.argv):
            fmt = sys.argv[i + 2]
        elif arg == "--output" and i + 2 < len(sys.argv):
            output = sys.argv[i + 2]
        elif arg == "-o" and i + 2 < len(sys.argv):
            output = sys.argv[i + 2]
    
    # Collect all pipeline files
    wiki_dir = Path(WIKI_DIR)
    pipeline_files = sorted(wiki_dir.glob("*pipeline*2026*.md"))
    
    pipelines = []
    for f in pipeline_files:
        try:
            data = extract_pipeline_data(f)
            pipelines.append(data)
        except Exception as e:
            print(f"⚠️ Could not parse {f.name}: {e}", file=sys.stderr)
    
    # Cross-indication analysis
    all_companies = {}
    all_failed = []
    all_approved = []
    
    for p in pipelines:
        for drug in p.get("failed", []):
            all_failed.append({"drug": drug, "indication": p["indication"]})
        for drug in p.get("approved", []):
            all_approved.append({"drug": drug, "indication": p["indication"]})
    
    # Build the data product
    data_product = {
        "meta": {
            "generated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "version": "1.0.0",
            "source": "drug-pipeline Wiki + ClinicalTrials.gov + openFDA + EMA + PubMed",
            "pipeline_count": len(pipelines),
            "indications": [p["indication"] for p in pipelines]
        },
        "pipelines": pipelines,
        "cross_indication": {
            "total_pipelines": len(pipelines),
            "all_failed_drugs": all_failed[:20],
            "all_approved_drugs": all_approved[:20],
            "analysis_url": "https://github.com/DasClown/drug-pipeline-mcp"
        }
    }
    
    # Output
    if fmt == "yaml":
        try:
            import yaml
            result = yaml.dump(data_product, default_flow_style=False, allow_unicode=True)
        except ImportError:
            print("⚠️ PyYAML not installed, falling back to JSON", file=sys.stderr)
            result = json.dumps(data_product, indent=2, ensure_ascii=False)
    else:
        result = json.dumps(data_product, indent=2, ensure_ascii=False)
    
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(result)
        print(f"✅ Data product saved to {output}")
        print(f"   {len(pipelines)} pipelines, {len(all_failed)} failed drugs, {len(all_approved)} approved drugs")
    else:
        print(result)


if __name__ == "__main__":
    main()
