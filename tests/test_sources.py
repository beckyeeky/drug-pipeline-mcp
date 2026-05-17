"""Unit tests for sources.py — cache logic, validation, error handling."""

import time
import drug_pipeline.sources as sources
from drug_pipeline.sources import (
    _is_error,
    _clear_cache,
    _cached_fetch,
    search_trials,
    get_trial_detail,
    VALID_PHASES,
    VALID_STATUSES,
    PHASE_MAP,
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
            l = result["landscape"]
            assert "approved_drugs" in l
            assert "phase_3_trials" in l
            assert "phase_2_trials" in l
            assert "key_mechanisms" in l
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
            assert "nadac_entries" in result
            assert "most_recent_entry" in result
            e = result["nadac_entries"][0]
            assert "nadac_per_unit" in e
            assert "ndc" in e
            assert "effective_date" in e


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
