"""Unit tests for server.py — tool registration, version, input models."""

from drug_pipeline import __version__
from drug_pipeline.server import TOOLS, server


class TestVersion:
    """Package version consistency."""

    def test_version_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        for p in parts:
            assert p.isdigit()

    def test_version_non_empty(self):
        assert len(__version__) > 0


class TestToolRegistration:
    """All tools are registered correctly."""

    def test_tools_count(self):
        assert len(TOOLS) >= 17, f"Expected 17+ tools, got {len(TOOLS)}"

    def test_core_tools_present(self):
        core = [
            "search_trials",
            "get_trial_detail",
            "lookup_drug",
            "get_approvals",
            "get_eu_approvals",
            "get_safety_data",
            "search_publications",
            "drug_pipeline",
        ]
        for name in core:
            assert name in TOOLS, f"Missing tool: {name}"

    def test_new_tools_present(self):
        new_tools = [
            "get_drug_label",
            "get_recalls",
            "detect_safety_signals",
            "get_patent_expiry",
            "get_drug_interactions",
            "approved_for_condition",
            "get_trial_results",
            "list_orphan_drugs",
            "company_pipeline",
        ]
        for name in new_tools:
            assert name in TOOLS, f"Missing tool: {name}"

    def test_tools_have_descriptions(self):
        for name, meta in TOOLS.items():
            assert meta.get("description"), f"Tool '{name}' has no description"
            assert len(meta["description"]) > 10, f"Tool '{name}' description too short"

    def test_tools_have_input_schema(self):
        for name, meta in TOOLS.items():
            assert meta.get("input_schema"), f"Tool '{name}' has no input_schema"

    def test_tools_have_handler(self):
        for name, meta in TOOLS.items():
            assert meta.get("handler"), f"Tool '{name}' has no handler"

    def test_all_schema_have_title(self):
        for name, meta in TOOLS.items():
            schema = meta.get("input_schema", {})
            assert "title" in schema, f"Tool '{name}' input_schema missing title"
            assert "properties" in schema, f"Tool '{name}' input_schema missing properties"
            assert "type" in schema, f"Tool '{name}' input_schema missing type"


class TestServerIdentity:
    """Server info and metadata."""

    def test_server_name(self):
        assert server.name == "drug-pipeline"

    def test_too_long_tool_names(self):
        """Ensure no tool name exceeds common MCP limits."""
        for name in TOOLS:
            assert len(name) <= 40, f"Tool '{name}' is {len(name)} chars (max 40)"


class TestHandlerErrors:
    """Error handling in tool dispatch."""

    def test_unknown_tool_returns_error(self):
        """Simulate the call_tool handler for an unknown tool."""
        import asyncio

        from drug_pipeline.server import handle_call_tool

        result = asyncio.run(handle_call_tool("nonexistent_tool", {}))
        assert len(result) == 1
        import json

        data = json.loads(result[0].text)
        assert data["status"] == "error"
        assert data["error_code"] == "UNKNOWN_TOOL"

    def test_drug_interactions_tool_has_handler(self):
        """get_drug_interactions must have a callable handler."""
        assert callable(TOOLS["get_drug_interactions"]["handler"])

    def test_all_handlers_callable(self):
        for name, meta in TOOLS.items():
            assert callable(meta["handler"]), f"Handler for '{name}' is not callable"
