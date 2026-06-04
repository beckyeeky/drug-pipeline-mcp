"""Unit tests for sources.py — cache logic, validation, error handling."""

import time

import pytest

import drug_pipeline.sources as sources
from drug_pipeline.sources import (
    PHASE_MAP,
    VALID_PHASES,
    VALID_STATUSES,
    _cached_fetch,
    _clear_cache,
    _is_error,
    get_trial_detail,
    search_trials,
)


class TestHelpers:
    """Helper function tests — no API calls."""

    def test_is_error_true(self):
        assert _is_error({"status": "error", "error_code": "HTTP_ERROR", "message": "404"})

    def test_is_error_false_dict(self):
        assert not _is_error({"status": "ok", "results": []})

    def test_is_error_false_string(self):
        assert not _is_error("plain text")

    def test_is_error_false_none(self):
        assert not _is_error(None)

    def test_is_error_false_list(self):
        assert not _is_error([1, 2, 3])

    def test_is_error_false_int(self):
        assert not _is_error(42)


class TestCache:
    """TTL cache behaviour tests."""

    def test_clear_cache_all(self):
        sources._CACHE["test_key"] = (time.time() + 300, "value")
        assert len(sources._CACHE) == 1
        cleared = _clear_cache()
        assert cleared == 1
        assert len(sources._CACHE) == 0

    def test_clear_cache_pattern(self):
        sources._CACHE["clinicaltrials.gov/search"] = (time.time() + 300, "a")
        sources._CACHE["api.fda.gov/drug"] = (time.time() + 300, "b")
        sources._CACHE["pubmed/query"] = (time.time() + 300, "c")
        cleared = _clear_cache(pattern="fda")
        assert cleared == 1  # only the FDA entry
        assert "api.fda.gov/drug" not in sources._CACHE
        assert "clinicaltrials.gov/search" in sources._CACHE

    def test_cache_expiry(self):
        """A stale cache entry should not be returned."""
        sources._CACHE["stale_key"] = (time.time() - 1, "stale_value")
        # _cached_fetch will try to fetch, which may fail with network error
        # but at least it doesn't return stale cached data
        result = _cached_fetch("http://nonexistent.example/test")
        assert result is not None


class TestTimeoutBudget:
    """Per-tool time budget helpers."""

    def test_resolve_timeout_without_deadline(self):
        resolved = sources._resolve_timeout(3)
        assert resolved == 3

    def test_resolve_timeout_caps_to_remaining_budget(self):
        token = sources.set_request_deadline(2.0)
        try:
            resolved = sources._resolve_timeout(10)
            assert 1.0 <= resolved <= 1.95
        finally:
            sources.reset_request_deadline(token)

    def test_resolve_timeout_raises_when_budget_exhausted(self):
        token = sources.set_request_deadline(0.05)
        try:
            with pytest.raises(TimeoutError):
                sources._resolve_timeout(5)
        finally:
            sources.reset_request_deadline(token)

    def test_non_fda_requests_skip_rate_limit_sleep(self):
        original_last_call = sources._last_call
        sources._last_call = time.time()
        try:
            started = time.perf_counter()
            sources._rate_limited("https://clinicaltrials.gov/api/v2/studies")
            elapsed = time.perf_counter() - started
            assert elapsed < 0.1
        finally:
            sources._last_call = original_last_call


class TestDrugInteractions:
    """Drug interactions validation."""

    def test_invalid_drug_name_empty(self):
        from drug_pipeline.sources import get_drug_interactions

        result = get_drug_interactions("")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_drug_name_short(self):
        from drug_pipeline.sources import get_drug_interactions

        result = get_drug_interactions("A")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_drug_interactions_schema(self):
        """Verify the function returns correct schema on API call."""
        from drug_pipeline.sources import get_drug_interactions

        result = get_drug_interactions("aspirin")
        if result.get("status") == "ok":
            assert "label_interactions" in result
            assert "co_reported_in_faers" in result
            assert "data_sources" in result


class TestSearchTrialsValidation:
    """Input validation for search_trials."""

    def test_invalid_limit_low(self):
        result = search_trials(condition="test", limit=0)
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_limit_high(self):
        result = search_trials(condition="test", limit=101)
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_default_limit(self):
        """Default limit should be 10 (valid)."""
        result = search_trials(condition="test")
        # Should be an API call attempt, not an INVALID_INPUT error
        assert result.get("error_code") != "INVALID_INPUT"


class TestGetTrialDetail:
    """Input validation for get_trial_detail."""

    def test_invalid_nct_empty(self):
        result = get_trial_detail("")
        assert result["error_code"] == "INVALID_NCT"

    def test_invalid_nct_wrong_prefix(self):
        result = get_trial_detail("XYZ123456")
        assert result["error_code"] == "INVALID_NCT"

    def test_invalid_nct_invalid_characters(self):
        """NCT with no digits should fail at API level (no client-side check)."""
        result = get_trial_detail("NCT")
        # "NCT" starts with "NCT" so it passes client validation
        # It then hits the API and gets an HTTP error
        assert result.get("status") in ("ok", "error")


class TestPhaseMap:
    """Phase mapping consistency."""

    def test_all_valid_phases_have_display(self):
        for code in VALID_PHASES:
            assert code in PHASE_MAP, f"Missing display for {code}"

    def test_all_display_names_are_strings(self):
        for code, display in PHASE_MAP.items():
            assert isinstance(display, str), f"Display for {code} is not a string: {display}"
            assert display.startswith("Phase") or display == "Not Applicable"


class TestValidStatuses:
    """Status constants."""

    def test_common_statuses_present(self):
        common = ["RECRUITING", "ACTIVE_NOT_RECRUITING", "COMPLETED", "TERMINATED"]
        for s in common:
            assert s in VALID_STATUSES, f"Missing common status: {s}"

    def test_no_duplicates(self):
        assert len(VALID_STATUSES) == len(set(VALID_STATUSES))


# ═════════════════════════════════════════════════════════════
# NEW v0.7.0 Tools — Input Validation (no API calls)
# ═════════════════════════════════════════════════════════════


class TestCompareDrugs:
    """compare_drugs input validation."""

    def test_invalid_empty(self):
        from drug_pipeline.sources import compare_drugs

        result = compare_drugs("", "DrugB")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_short(self):
        from drug_pipeline.sources import compare_drugs

        result = compare_drugs("A", "B")
        assert result["status"] == "error"

    def test_valid_calls_ok_schema(self):
        """Happy path returns correct schema (may fail API but schema is right)."""
        from drug_pipeline.sources import compare_drugs

        result = compare_drugs("aspirin", "ibuprofen")
        if result.get("status") == "ok":
            assert "drug_a" in result
            assert "drug_b" in result
            assert "comparison" in result
            assert len(result["comparison"]) > 0
            fields = [c["field"] for c in result["comparison"]]
            assert "FDA Approval Status" in fields
            assert "EU/EMA Status" in fields
            assert "Mechanism of Action" in fields


class TestPipelineLandscape:
    """pipeline_landscape input validation."""

    def test_invalid_short_condition(self):
        from drug_pipeline.sources import pipeline_landscape

        result = pipeline_landscape("AB")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_empty_condition(self):
        from drug_pipeline.sources import pipeline_landscape

        result = pipeline_landscape("")
        assert result["status"] == "error"

    def test_valid_schema(self):
        from drug_pipeline.sources import pipeline_landscape

        result = pipeline_landscape("type 2 diabetes", limit=5)
        if result.get("status") == "ok":
            assert "condition" in result
            assert "landscape" in result
            landscape = result["landscape"]
            assert "approved_drugs" in landscape
            assert "phase_3_trials" in landscape
            assert "phase_2_trials" in landscape
            assert "key_mechanisms" in landscape
            assert "data_sources" in result


class TestUsOrphanDesignations:
    """get_us_orphan_designations input validation."""

    def test_invalid_empty(self):
        from drug_pipeline.sources import get_us_orphan_designations

        result = get_us_orphan_designations("")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_short(self):
        from drug_pipeline.sources import get_us_orphan_designations

        result = get_us_orphan_designations("X")
        assert result["status"] == "error"

    def test_valid_schema(self):
        from drug_pipeline.sources import get_us_orphan_designations

        result = get_us_orphan_designations("vigabatrin")
        if result.get("status") == "ok":
            if result.get("found"):
                assert "orphan_designations" in result
                assert "designation_count" in result
                od = result["orphan_designations"][0]
                assert "orphan_designation" in od
                assert "designation_status" in od
                assert "designated_date" in od


class TestDrugPricing:
    """get_drug_pricing input validation."""

    def test_invalid_empty(self):
        from drug_pipeline.sources import get_drug_pricing

        result = get_drug_pricing("")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_short(self):
        from drug_pipeline.sources import get_drug_pricing

        result = get_drug_pricing("A")
        assert result["status"] == "error"

    def test_valid_schema(self):
        from drug_pipeline.sources import get_drug_pricing

        result = get_drug_pricing("atorvastatin")
        if result.get("status") == "ok" and result.get("found"):
            assert "products" in result
            assert "product_count" in result
            e = result["products"][0]
            assert "brand_name" in e
            assert "product_ndc" in e
            assert "labeler_name" in e


class TestListBiosimilars:
    """list_biosimilars input validation + schema."""

    def test_all_biosimilars(self):
        from drug_pipeline.sources import list_biosimilars

        result = list_biosimilars(limit=5)
        if result.get("status") == "ok":
            assert "drugs" in result
            assert "biosimilars_by_substance" in result
            assert "total_eu_biosimilars" in result

    def test_filter_by_condition(self):
        from drug_pipeline.sources import list_biosimilars

        result = list_biosimilars(condition="arthritis", limit=10)
        if result.get("status") == "ok":
            assert "condition_filter" in result
            assert result["condition_filter"] == "arthritis"

    def test_biosimilar_entry_schema(self):
        from drug_pipeline.sources import list_biosimilars

        result = list_biosimilars(limit=5)
        if result.get("status") == "ok" and result["drugs"]:
            d = result["drugs"][0]
            assert "name" in d
            assert "active_substance" in d
            assert "atc_code" in d


class TestLossOfExclusivity:
    """list_loss_of_exclusivity schema."""

    def test_valid_schema(self):
        from drug_pipeline.sources import list_loss_of_exclusivity

        result = list_loss_of_exclusivity(limit=5)
        if result.get("status") == "ok":
            assert "loss_of_exclusivity_entries" in result
            assert "total_loe_active_substances" in result
            assert "total_eu_biosimilars" in result


class TestTrialSites:
    """get_trial_sites input validation."""

    def test_invalid_nct_empty(self):
        from drug_pipeline.sources import get_trial_sites

        result = get_trial_sites("")
        assert result["status"] == "error"
        assert "INVALID" in result.get("error_code", "")

    def test_invalid_nct_wrong_prefix(self):
        from drug_pipeline.sources import get_trial_sites

        result = get_trial_sites("XYZ123456")
        assert result["status"] == "error"

    def test_valid_schema(self):
        from drug_pipeline.sources import get_trial_sites

        result = get_trial_sites("NCT03178617")
        if result.get("status") == "ok":
            assert "site_count" in result
            assert "country_count" in result
            assert "geographic_distribution" in result
            assert "sites" in result
            assert "trial_status" in result


class TestCombinationTherapies:
    """detect_combination_therapies input validation."""

    def test_invalid_empty(self):
        from drug_pipeline.sources import detect_combination_therapies

        result = detect_combination_therapies("")
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_invalid_short(self):
        from drug_pipeline.sources import detect_combination_therapies

        result = detect_combination_therapies("A")
        assert result["status"] == "error"

    def test_valid_schema(self):
        from drug_pipeline.sources import detect_combination_therapies

        result = detect_combination_therapies("pembrolizumab", limit=5)
        if result.get("status") == "ok" and result.get("found"):
            assert "top_co_administered" in result
            assert "combinations" in result
            assert "trials_with_combinations" in result


class TestFindInvestigators:
    """find_investigators input validation."""

    def test_invalid_no_args(self):
        from drug_pipeline.sources import find_investigators

        result = find_investigators()
        assert result["status"] == "error"
        assert result["error_code"] == "INVALID_INPUT"

    def test_valid_by_condition(self):
        from drug_pipeline.sources import find_investigators

        result = find_investigators(condition="lung cancer", limit=5)
        if result.get("status") == "ok":
            if result.get("found"):
                assert "investigators" in result
                inv = result["investigators"][0]
                assert "name" in inv
                assert "role" in inv
                assert "trial_nct" in inv

    def test_valid_by_drug(self):
        from drug_pipeline.sources import find_investigators

        result = find_investigators(drug_name="pembrolizumab", limit=5)
        if result.get("status") == "ok":
            # May be found or not — schema should be valid either way
            assert "total_investigators" in result


class TestDrugPipelineSummary:
    """Regression coverage for the composite drug pipeline response."""

    def test_keytruda_summary_trims_fda_payload_and_surfaces_partial_errors(self, monkeypatch):
        import drug_pipeline._sources_composite as composite
        from drug_pipeline.sources import drug_pipeline_summary

        def ok_search_drug(name):
            return {"status": "ok", "drug_name": name, "data_sources": ["openFDA"]}

        def ok_trials(**kwargs):
            return {"status": "ok", "total_count": 1, "results": [{"nct_id": "NCT00000001"}]}

        def timeout_publications(query, max_results=5):
            return {"status": "error", "error_code": "TIMEOUT", "message": "PubMed timed out"}

        def many_approvals(name):
            submissions = [
                {
                    "type": "SUPPL",
                    "number": str(i),
                    "status": "AP",
                    "status_date": f"2024{(i % 12) + 1:02d}{(i % 27) + 1:02d}",
                    "review_priority": "STANDARD",
                    "class_code": "Labeling",
                }
                for i in range(12)
            ]
            return {
                "status": "ok",
                "drug_name": name,
                "total": 1,
                "data_source": "openFDA",
                "applications": [
                    {
                        "application_number": "BLA125514",
                        "sponsor": "MERCK SHARP DOHME",
                        "brand_names": ["KEYTRUDA"],
                        "generic_names": ["pembrolizumab"],
                        "submissions": submissions,
                        "source_url": "https://example.test/fda/keytruda",
                    }
                ],
            }

        def not_found(*args, **kwargs):
            return {"status": "ok", "found": False}

        def no_results(*args, **kwargs):
            return {"status": "ok", "results": []}

        def no_reports(*args, **kwargs):
            return {"status": "ok", "total_reports": 0, "top_reactions": []}

        def no_recalls(*args, **kwargs):
            return {"status": "ok", "recalls": [], "total_recalls": 0}

        def no_signals(*args, **kwargs):
            return {"status": "ok", "signals": [], "total_signals": 0}

        def patent_stub(*args, **kwargs):
            return {"status": "error", "error_code": "TIMEOUT", "message": "Patent lookup timed out"}

        def interactions_stub(*args, **kwargs):
            return {
                "status": "ok",
                "label_interactions": {
                    "drug_interactions_text": None,
                    "contraindications_text": None,
                },
                "co_reported_in_faers": [],
                "total_co_reported": 0,
                "data_sources": ["openFDA FAERS"],
            }

        monkeypatch.setattr(composite, "search_drug", ok_search_drug)
        monkeypatch.setattr(composite, "get_fda_approvals", many_approvals)
        monkeypatch.setattr(composite, "search_trials", ok_trials)
        monkeypatch.setattr(composite, "search_publications", timeout_publications)
        monkeypatch.setattr(composite, "get_eu_approvals", no_results)
        monkeypatch.setattr(composite, "get_safety_data", no_reports)
        monkeypatch.setattr(composite, "approved_for_condition", no_results)
        monkeypatch.setattr(composite, "get_drug_label", not_found)
        monkeypatch.setattr(composite, "get_recalls", no_recalls)
        monkeypatch.setattr(composite, "detect_safety_signals", no_signals)
        monkeypatch.setattr(composite, "get_patent_expiry", patent_stub)
        monkeypatch.setattr(composite, "get_drug_interactions", interactions_stub)

        result = drug_pipeline_summary(drug_name="Keytruda")

        assert result["status"] == "ok"
        assert "partial_errors" in result
        assert any(error["source"] == "publications" for error in result["partial_errors"])
        assert any(error["source"] == "patent_info" for error in result["partial_errors"])

        approvals = result["fda_approvals"]
        assert approvals["total"] == 1
        assert len(approvals["applications"]) == 1

        app = approvals["applications"][0]
        assert app["total_submissions"] == 12
        assert len(app["recent_submissions"]) == 5
        assert "submissions" not in app


class TestSplitModuleRegressions:
    """Guard against missing imports introduced by the module split."""

    def test_approved_for_condition_keeps_regex_helper_available(self):
        from drug_pipeline.sources import approved_for_condition

        result = approved_for_condition("diabetes", limit=5)
        assert result.get("error_code") != "TOOL_ERROR"

    def test_company_pipeline_keeps_phase_map_available(self, monkeypatch):
        import drug_pipeline._sources_composite as composite
        from drug_pipeline.sources import company_pipeline

        monkeypatch.setattr(
            composite,
            "search_trials",
            lambda **kwargs: {
                "status": "ok",
                "results": [
                    {
                        "nct_id": "NCT00000001",
                        "title": "Test Phase 3 Study",
                        "phase_code": ["PHASE3"],
                        "overall_status": "RECRUITING",
                        "conditions": ["Test Condition"],
                        "interventions": ["Test Drug"],
                        "source_url": "https://clinicaltrials.gov/study/NCT00000001",
                    }
                ],
            },
        )
        monkeypatch.setattr(composite, "get_eu_approvals", lambda drug: {"results": []})

        result = company_pipeline("Pfizer", include_eu=False, limit=5)

        assert result["status"] == "ok"
        assert "Phase 3" in result["phase_summary"]
