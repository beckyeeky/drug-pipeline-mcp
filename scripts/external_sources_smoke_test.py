#!/usr/bin/env python3
"""Smoke-test external data sources and the project's source parsers.

Run from the repository root:

    python scripts/external_sources_smoke_test.py
    python scripts/external_sources_smoke_test.py --repeat 3 --parallelism 4

The script makes small, read-only requests. It does not write project data or
populate the application's cache.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Callable


USER_AGENT = "drug-pipeline-mcp-external-smoke-test/1.0"


@dataclass
class Result:
    name: str
    layer: str
    status: str
    elapsed: float
    detail: str

    def line(self) -> str:
        return f"{self.layer:8} {self.name:22} {self.status:12} {self.elapsed:6.2f}s  {self.detail}"


def fetch_json(name: str, request_spec: tuple[str, str, bytes | None], timeout: float) -> Result:
    started = time.perf_counter()
    method, url, body = request_spec
    try:
        headers = {"Accept": "application/json", "User-Agent": USER_AGENT}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url,
            data=body,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read()
            response_status = response.status
            content_type = response.headers.get("Content-Type", "")
        if "spreadsheet" in content_type or name == "EMA XLSX":
            return Result(name, "network", f"HTTP {response_status}", time.perf_counter() - started, f"{content_type}; {len(body)} bytes")
        payload = json.loads(body.decode("utf-8"))
        keys = ",".join(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        return Result(name, "network", f"HTTP {response_status}", time.perf_counter() - started, f"{content_type}; {keys[:100]}")
    except urllib.error.HTTPError as exc:
        message = exc.read(300).decode("utf-8", errors="replace").replace("\n", " ")
        return Result(name, "network", f"HTTP {exc.code}", time.perf_counter() - started, message[:180])
    except Exception as exc:
        return Result(name, "network", type(exc).__name__, time.perf_counter() - started, str(exc)[:180])


def run_project_function(name: str, function: Callable[[], dict[str, Any]]) -> Result:
    started = time.perf_counter()
    try:
        result = function()
        status = result.get("status", "missing-status") if isinstance(result, dict) else "bad-type"
        detail = {key: result.get(key) for key in ("error_code", "found", "total", "total_count") if isinstance(result, dict) and key in result}
        if isinstance(result, dict):
            detail["keys"] = list(result.keys())[:8]
        return Result(name, "project", status, time.perf_counter() - started, json.dumps(detail, ensure_ascii=False))
    except Exception as exc:
        return Result(name, "project", type(exc).__name__, time.perf_counter() - started, str(exc)[:180])


def network_checks() -> dict[str, tuple[str, str, bytes | None]]:
    return {
        "ClinicalTrials.gov": ("GET", "https://clinicaltrials.gov/api/v2/studies?query.cond=non-small%20cell%20lung%20cancer&pageSize=1&format=json", None),
        "openFDA NDC": ("GET", "https://api.fda.gov/drug/ndc.json?search=generic_name:aspirin&limit=1", None),
        "openFDA DrugsFDA": ("GET", "https://api.fda.gov/drug/drugsfda.json?search=products.brand_name:Keytruda&limit=1", None),
        "RxNorm": ("GET", "https://rxnav.nlm.nih.gov/REST/approximateTerm.json?term=aspirin&maxEntries=1", None),
        "PubMed": ("GET", "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=aspirin&retmax=1&retmode=json", None),
        "EMA XLSX": ("GET", "https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx", None),
        "Open Targets": ("POST", "https://api.platform.opentargets.org/api/v4/graphql", json.dumps({"query": '{ search(queryString: "aspirin", entityNames: ["drug"]) { hits { id name } } }'}).encode()),
        "DailyMed": ("GET", "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name=aspirin&pagesize=1", None),
        "MyChem.info": ("GET", "https://mychem.info/v1/query?q=vigabatrin&size=1", None),
    }


def project_checks() -> dict[str, Callable[[], dict[str, Any]]]:
    from drug_pipeline.sources import (
        get_dailymed_label,
        get_eu_approvals,
        get_fda_approvals,
        get_opentargets_drug,
        get_us_orphan_designations,
        search_drug,
        search_publications,
        search_trials,
    )

    return {
        "ClinicalTrials.gov": lambda: search_trials(condition="non-small cell lung cancer", limit=1),
        "openFDA/RxNorm": lambda: search_drug("aspirin"),
        "openFDA DrugsFDA": lambda: get_fda_approvals("Keytruda"),
        "EMA": lambda: get_eu_approvals("Keytruda"),
        "PubMed": lambda: search_publications("aspirin", max_results=1),
        "Open Targets": lambda: get_opentargets_drug("aspirin"),
        "DailyMed": lambda: get_dailymed_label("aspirin"),
        "MyChem.info": lambda: get_us_orphan_designations("vigabatrin"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15, help="Timeout per network request (seconds)")
    parser.add_argument("--parallelism", type=int, default=4, help="Maximum simultaneous checks")
    parser.add_argument("--repeat", type=int, default=1, help="Repeat network checks this many times")
    parser.add_argument("--network-only", action="store_true", help="Skip importing and calling project functions")
    args = parser.parse_args()

    if args.parallelism < 1 or args.repeat < 1:
        parser.error("--parallelism and --repeat must be positive")

    print(f"Python: {sys.version.split()[0]}")
    print(f"Timeout: {args.timeout}s; parallelism: {args.parallelism}; repeats: {args.repeat}")
    print("\nNetwork layer")
    all_results: list[Result] = []
    checks = network_checks()
    for repeat in range(1, args.repeat + 1):
        with ThreadPoolExecutor(max_workers=args.parallelism) as pool:
            futures = [pool.submit(fetch_json, name, url, args.timeout) for name, url in checks.items()]
            results = [future.result() for future in as_completed(futures)]
        if args.repeat > 1:
            print(f"\nRound {repeat}")
        for result in sorted(results, key=lambda item: item.name):
            print(result.line())
        all_results.extend(results)

    if not args.network_only:
        print("\nProject parser layer")
        try:
            checks = project_checks()
        except Exception as exc:
            print(f"project  import                  FAILED       {type(exc).__name__}: {exc}")
        else:
            with ThreadPoolExecutor(max_workers=min(args.parallelism, len(checks))) as pool:
                futures = [pool.submit(run_project_function, name, function) for name, function in checks.items()]
                results = [future.result() for future in as_completed(futures)]
            for result in sorted(results, key=lambda item: item.name):
                print(result.line())
            all_results.extend(results)

    network_failures = [result for result in all_results if result.layer == "network" and not result.status.startswith("HTTP 2")]
    project_failures = [result for result in all_results if result.layer == "project" and result.status not in {"ok"}]
    print(f"\nSummary: {len(network_failures)} network failures; {len(project_failures)} project-parser non-ok results")
    print("Note: HTTP 200 does not guarantee a usable payload; inspect the project-parser layer and source-specific errors.")
    return 1 if network_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
