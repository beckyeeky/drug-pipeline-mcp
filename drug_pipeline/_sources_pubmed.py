"""PubMed query helpers for drug-pipeline-mcp."""

from __future__ import annotations

import urllib.parse

from .sources import _PUBMED_BASE, _fetch, _is_error, datetime

# ═════════════════════════════════════════════════════════════
# 3. PubMed — Publications
# ═════════════════════════════════════════════════════════════


def search_publications(query: str, max_results: int = 10) -> dict:
    """
    Search PubMed for publications matching a query.

    Returns PMIDs, titles, journal, and publication dates.
    """
    if not query or len(query) < 2:
        return {
            "status": "error",
            "error_code": "INVALID_INPUT",
            "message": "Query must be at least 2 characters",
        }

    # Step 1: ESearch — find matching PMIDs
    search_url = f"{_PUBMED_BASE}/esearch.fcgi?db=pubmed&term={urllib.parse.quote(query)}&retmax={min(max_results, 50)}&retmode=json"
    search_data = _fetch(search_url)

    if _is_error(search_data):
        return search_data

    if not isinstance(search_data, dict):
        return {"status": "error", "error_code": "NO_DATA", "message": "PubMed search failed"}

    id_list = (search_data.get("esearchresult", {}) or {}).get("idlist", [])
    total_count = (search_data.get("esearchresult", {}) or {}).get("count", "0")

    if not id_list:
        return {"status": "ok", "total_count": 0, "results": [], "query": query}

    # Step 2: EFetch — get details for found PMIDs
    ids_csv = ",".join(id_list)
    fetch_url = f"{_PUBMED_BASE}/efetch.fcgi?db=pubmed&id={ids_csv}&retmode=xml&rettype=abstract"
    fetch_data = _fetch(fetch_url)

    # Parse XML minimally (we're getting XML, not JSON — parse with simple regex)
    xml_text = fetch_data if isinstance(fetch_data, str) else ""

    # Simple extraction (no external XML parser dependency)
    results = []
    if xml_text:
        import re

        articles = re.split(r"<PubmedArticle>", xml_text)[1:]

        for art in articles[:max_results]:
            pmid_match = re.search(r"<PMID[^>]*>(\d+)</PMID>", art)
            title_match = re.search(r"<ArticleTitle[^>]*>(.*?)</ArticleTitle>", art, re.DOTALL)
            journal_match = re.search(r"<Journal[^>]*>.*?<Title[^>]*>(.*?)</Title>", art, re.DOTALL)
            year_match = re.search(r"<PubDate[^>]*>.*?<Year[^>]*>(\d{4})", art, re.DOTALL)
            abstract_match = re.search(
                r"<Abstract[^>]*>.*?<AbstractText[^>]*>(.*?)</AbstractText>", art, re.DOTALL
            )

            # Clean HTML entities
            def clean(s):
                if not s:
                    return None
                s = re.sub(r"<[^>]+>", "", s)
                s = (
                    s.replace("&amp;", "&")
                    .replace("&lt;", "<")
                    .replace("&gt;", ">")
                    .replace("&quot;", '"')
                )
                return s[:300] if s else None

            pmid = clean(pmid_match.group(1)) if pmid_match else None
            title = clean(title_match.group(1)) if title_match else None
            journal = clean(journal_match.group(1)) if journal_match else None
            year = clean(year_match.group(1)) if year_match else None
            abstract = clean(abstract_match.group(1)) if abstract_match else None

            if pmid:
                results.append(
                    {
                        "pmid": pmid,
                        "title": title,
                        "journal": journal,
                        "year": year,
                        "abstract": abstract,
                        "source_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    }
                )

    return {
        "status": "ok",
        "total_count": int(total_count) if total_count.isdigit() else len(id_list),
        "returned_count": len(results),
        "results": results[:max_results],
        "query": query,
        "data_source": "PubMed",
        "timestamp": datetime.utcnow().isoformat(),
    }


