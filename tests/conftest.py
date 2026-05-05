"""Shared fixtures for drug-pipeline-mcp tests."""

import pytest
from drug_pipeline.sources import _CACHE, _ema_cache, _ema_cache_time


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear all caches before each test for isolation."""
    _CACHE.clear()
    yield


@pytest.fixture(autouse=True)
def reset_ema_cache():
    """Reset EMA cache to avoid cross-test interference."""
    global _ema_cache, _ema_cache_time
    _ema_cache = None
    _ema_cache_time = 0.0
    yield


@pytest.fixture
def sample_trial_data():
    """Minimal ClinicalTrials.gov API response structure."""
    return {
        "studies": [
            {
                "protocolSection": {
                    "identificationModule": {
                        "nctId": "NCT00000000",
                        "briefTitle": "Test Trial"
                    },
                    "designModule": {
                        "phases": ["PHASE3"]
                    },
                    "statusModule": {
                        "overallStatus": "RECRUITING",
                        "startDateStruct": {"date": "2024-01"},
                        "completionDateStruct": {"date": "2026-12"}
                    },
                    "conditionsModule": {
                        "conditions": ["Test Condition"]
                    },
                    "sponsorCollaboratorsModule": {
                        "leadSponsor": {"name": "Test Sponsor"}
                    },
                    "armsInterventionsModule": {
                        "interventions": [{"name": "Test Drug", "type": "DRUG"}]
                    }
                }
            }
        ],
        "nextPageToken": None
    }


@pytest.fixture
def sample_drug_result():
    """Minimal openFDA NDC result."""
    return {
        "results": [
            {
                "brand_name": "TestDrug",
                "generic_name": "testdrug",
                "labeler_name": "Test Pharma",
                "active_ingredients": [{"name": "testdrug", "strength": "10 mg"}],
                "product_ndc": "00000-0000",
                "route": "ORAL"
            }
        ]
    }
