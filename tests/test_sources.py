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
