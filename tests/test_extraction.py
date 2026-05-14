"""Tests for extraction module.

All tests use mocked Anthropic API responses — zero API cost.
Tests validate:
- Tool choice strategy (forced vs "any")
- Response parsing from tool_use blocks
- Pydantic validation of extracted data
- Error handling for API failures and malformed responses
"""

from unittest.mock import MagicMock

import pytest

from src.structured_extraction.extraction import (
    ALL_EXTRACTION_TOOLS,
    GUARANTEE_TABLE_TOOL,
    IPID_TOOL,
    TokenUsage,
    _build_extraction_result,
    extract_document,
    get_tool_choice,
    parse_tool_response,
)
from src.structured_extraction.schemas import DocumentType, FieldConfidence

# ---------------------------------------------------------------------------
# Tool choice strategy tests
# ---------------------------------------------------------------------------


class TestGetToolChoice:
    """Test tool_choice selection based on document type.

    CCA-F Task 4.3: forced selection when type is known, "any" when unknown.
    """

    def test_ipid_uses_forced_selection(self):
        """Known IPID → force extract_ipid tool."""
        choice = get_tool_choice("ipid")
        assert choice == {"type": "tool", "name": "extract_ipid"}

    def test_guarantee_table_uses_forced_selection(self):
        """Known guarantee table → force extract_guarantee_table tool."""
        choice = get_tool_choice("guarantee_table")
        assert choice == {"type": "tool", "name": "extract_guarantee_table"}

    def test_unknown_type_uses_any(self):
        """Unknown type → 'any' forces a tool call but lets Claude choose."""
        choice = get_tool_choice("unknown")
        assert choice == {"type": "any"}

    def test_product_sheet_uses_any(self):
        """Unsupported types fall through to 'any'."""
        choice = get_tool_choice("product_sheet")
        assert choice == {"type": "any"}

    def test_auto_never_used(self):
        """We never use 'auto' — risk of Claude returning prose instead of structured data."""
        for doc_type in ["ipid", "guarantee_table", "unknown", "pricing", "product_sheet"]:
            choice = get_tool_choice(doc_type)
            assert choice != "auto", f"'auto' should never be used (got it for {doc_type})"


# ---------------------------------------------------------------------------
# Tool definition tests
# ---------------------------------------------------------------------------


class TestToolDefinitions:
    """Test that tool definitions are well-structured for Claude."""

    def test_ipid_tool_has_required_fields(self):
        assert "name" in IPID_TOOL
        assert "description" in IPID_TOOL
        assert "input_schema" in IPID_TOOL

    def test_guarantee_table_tool_has_required_fields(self):
        assert "name" in GUARANTEE_TABLE_TOOL
        assert "description" in GUARANTEE_TABLE_TOOL
        assert "input_schema" in GUARANTEE_TABLE_TOOL

    def test_tool_descriptions_differentiate_tools(self):
        """CCA-F Task 2.1: descriptions must clearly differentiate tools."""
        ipid_desc = IPID_TOOL["description"].lower()
        bg_desc = GUARANTEE_TABLE_TOOL["description"].lower()

        # IPID description mentions IPID-specific sections
        assert "qu'est-ce qui est assuré" in ipid_desc
        # BG description mentions tabular/benefit structure
        assert "tabular" in bg_desc or "reimbursement" in bg_desc

    def test_tool_descriptions_include_negative_guidance(self):
        """CCA-F Task 2.1: descriptions should say when NOT to use the tool."""
        ipid_desc = IPID_TOOL["description"]
        bg_desc = GUARANTEE_TABLE_TOOL["description"]

        assert "Do NOT use" in ipid_desc
        assert "Do NOT use" in bg_desc

    def test_tool_descriptions_handle_missing_data(self):
        """Tools should instruct Claude on handling missing fields."""
        ipid_desc = IPID_TOOL["description"]
        bg_desc = GUARANTEE_TABLE_TOOL["description"]

        assert "null" in ipid_desc.lower() or "null" in bg_desc.lower()

    def test_all_tools_list(self):
        assert len(ALL_EXTRACTION_TOOLS) == 2


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------


class TestParseToolResponse:
    """Test parsing Claude's tool_use response."""

    def _make_tool_use_message(self, tool_name: str, tool_input: dict) -> MagicMock:
        """Helper to create a mock Claude message with a ToolUseBlock."""
        block = MagicMock()
        block.__class__ = type("ToolUseBlock", (), {})
        # We need isinstance check to work, so we use a real ToolUseBlock-like object
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        tool_block = RealToolUseBlock(
            id="toolu_test123",
            type="tool_use",
            name=tool_name,
            input=tool_input,
        )
        message = MagicMock()
        message.content = [tool_block]
        message.stop_reason = "tool_use"
        return message

    def test_parse_ipid_tool_response(self):
        message = self._make_tool_use_message(
            "extract_ipid",
            {
                "product_name": "API Santé Équilibre",
                "insurer_name": "APICIL Mutuelle",
                "insurance_type": "Complémentaire santé",
                "covered_items": [],
                "not_covered_items": [],
                "exclusions": [],
            },
        )
        tool_name, data = parse_tool_response(message)
        assert tool_name == "extract_ipid"
        assert data["product_name"] == "API Santé Équilibre"

    def test_parse_guarantee_table_response(self):
        message = self._make_tool_use_message(
            "extract_guarantee_table",
            {
                "product_name": "API Santé - Gamme Équilibre",
                "guarantee_level": "Equilibre 1",
                "has_comfort_pack": True,
                "benefits": [],
            },
        )
        tool_name, data = parse_tool_response(message)
        assert tool_name == "extract_guarantee_table"
        assert data["guarantee_level"] == "Equilibre 1"

    def test_parse_no_tool_use_raises(self):
        """If Claude responds with text instead of tool_use, raise an error."""
        text_block = MagicMock()
        text_block.__class__ = type("TextBlock", (), {})
        message = MagicMock()
        message.content = [text_block]
        message.stop_reason = "end_turn"
        with pytest.raises(ValueError, match="No tool_use block found"):
            parse_tool_response(message)


# ---------------------------------------------------------------------------
# Build extraction result tests
# ---------------------------------------------------------------------------


class TestBuildExtractionResult:
    """Test building validated ExtractionResult from raw tool output."""

    def test_build_ipid_result_success(self):
        data = {
            "product_name": "API Santé Équilibre",
            "insurer_name": "APICIL Mutuelle",
            "insurance_type": "Complémentaire santé",
            "covered_items": [{"description": "Soins courants", "category": "routine_care"}],
            "not_covered_items": ["Chirurgie esthétique"],
            "exclusions": [
                {"description": "Participation forfaitaire", "exclusion_type": "regulatory"}
            ],
        }
        result = _build_extraction_result("extract_ipid", data, "test.pdf")
        assert result.document_type == DocumentType.IPID
        assert result.ipid is not None
        assert result.ipid.product_name == "API Santé Équilibre"
        assert result.extraction_errors is None

    def test_build_guarantee_table_result_success(self):
        data = {
            "product_name": "API Santé",
            "guarantee_level": "Equilibre 1",
            "has_comfort_pack": False,
            "benefits": [
                {
                    "benefit_name": "Analyses",
                    "category": "routine_care",
                    "reimbursement": {
                        "raw_value": "100 % BR - SS",
                        "reimbursement_type": "percentage_br_minus_ss",
                        "percentage": 100.0,
                    },
                }
            ],
        }
        result = _build_extraction_result("extract_guarantee_table", data, "bg.pdf")
        assert result.document_type == DocumentType.GUARANTEE_TABLE
        assert result.guarantee_table is not None
        assert len(result.guarantee_table.benefits) == 1

    def test_build_result_validation_failure(self):
        """Semantic validation error: missing required fields."""
        data = {"product_name": "Test"}  # Missing required fields
        result = _build_extraction_result("extract_ipid", data, "bad.pdf")
        assert result.extraction_errors is not None
        assert len(result.extraction_errors) > 0

    def test_build_result_unknown_tool(self):
        result = _build_extraction_result("unknown_tool", {}, "test.pdf")
        assert result.document_type == DocumentType.UNKNOWN
        assert "Unknown tool" in result.extraction_errors[0]

    def test_build_ipid_with_nullable_fields(self):
        """CCA-F Task 4.3: nullable fields should pass through as None."""
        data = {
            "product_name": "Test",
            "insurer_name": "Test Co",
            "insurance_type": "Santé",
            "covered_items": [],
            "not_covered_items": [],
            "exclusions": [],
            # All optional fields deliberately omitted
        }
        result = _build_extraction_result("extract_ipid", data, "test.pdf")
        assert result.ipid is not None
        assert result.ipid.insurer_registration is None
        assert result.ipid.eligible_population is None
        assert result.ipid.madelin_eligible is None
        assert result.ipid.geographic_coverage is None

    def test_build_ipid_with_confidence_scores(self):
        """CCA-F Task 5.5: field-level confidence for human review routing."""
        data = {
            "product_name": "API Santé",
            "insurer_name": "APICIL",
            "insurance_type": "Complémentaire santé",
            "covered_items": [],
            "not_covered_items": [],
            "exclusions": [],
            "field_confidences": {
                "insurer_registration": "medium",
                "eligible_population": "low",
            },
        }
        result = _build_extraction_result("extract_ipid", data, "test.pdf")
        assert result.ipid.field_confidences["insurer_registration"] == FieldConfidence.MEDIUM
        assert result.ipid.field_confidences["eligible_population"] == FieldConfidence.LOW


# ---------------------------------------------------------------------------
# Token tracking tests
# ---------------------------------------------------------------------------


class TestTokenUsage:
    """Test token usage tracking for cost monitoring."""

    def test_initial_state(self):
        usage = TokenUsage()
        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.total_calls == 0

    def test_add_usage(self):
        usage = TokenUsage()
        usage.add_usage(1000, 500, "extraction_ipid")
        assert usage.input_tokens == 1000
        assert usage.output_tokens == 500
        assert usage.total_calls == 1

    def test_cumulative_usage(self):
        usage = TokenUsage()
        usage.add_usage(1000, 500, "call_1")
        usage.add_usage(2000, 800, "call_2")
        assert usage.input_tokens == 3000
        assert usage.output_tokens == 1300
        assert usage.total_calls == 2

    def test_estimated_cost(self):
        usage = TokenUsage()
        usage.add_usage(1_000_000, 100_000, "test")
        # Cost: (1M / 1M * $1) + (100K / 1M * $5) = $1.00 + $0.50 = $1.50
        assert abs(usage.estimated_cost_usd - 1.50) < 0.01

    def test_summary_format(self):
        usage = TokenUsage()
        usage.add_usage(1500, 300, "test")
        summary = usage.summary()
        assert "1,500" in summary
        assert "300" in summary
        assert "$" in summary

    def test_call_details_tracking(self):
        usage = TokenUsage()
        usage.add_usage(100, 50, "extraction_ipid")
        usage.add_usage(200, 80, "extraction_bg")
        assert len(usage.call_details) == 2
        assert usage.call_details[0]["call_type"] == "extraction_ipid"
        assert usage.call_details[1]["call_number"] == 2


# ---------------------------------------------------------------------------
# Full extraction integration tests (mocked API)
# ---------------------------------------------------------------------------


class TestExtractDocument:
    """Integration tests for extract_document with mocked API."""

    def _mock_tool_response(self, tool_name: str, tool_input: dict) -> MagicMock:
        """Create a mock API response with tool_use."""
        from anthropic.types import ToolUseBlock as RealToolUseBlock

        tool_block = RealToolUseBlock(
            id="toolu_mock",
            type="tool_use",
            name=tool_name,
            input=tool_input,
        )
        message = MagicMock()
        message.content = [tool_block]
        message.stop_reason = "tool_use"
        message.usage = MagicMock()
        message.usage.input_tokens = 1500
        message.usage.output_tokens = 800
        return message

    def test_extract_ipid_success(self):
        """Full extraction pipeline for an IPID document."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_tool_response(
            "extract_ipid",
            {
                "product_name": "API Santé Équilibre",
                "insurer_name": "APICIL Mutuelle",
                "insurance_type": "Complémentaire santé",
                "covered_items": [{"description": "Soins courants", "category": "routine_care"}],
                "not_covered_items": ["Chirurgie esthétique"],
                "exclusions": [
                    {"description": "Participation forfaitaire", "exclusion_type": "regulatory"}
                ],
            },
        )

        token_usage = TokenUsage()
        result = extract_document(
            text_content="Document IPID content...",
            document_type="ipid",
            source_file="IPID_test.pdf",
            client=mock_client,
            token_usage=token_usage,
        )

        assert result.document_type == DocumentType.IPID
        assert result.ipid is not None
        assert result.ipid.product_name == "API Santé Équilibre"
        assert result.extraction_errors is None
        assert token_usage.total_calls == 1
        assert token_usage.input_tokens == 1500

    def test_extract_guarantee_table_success(self):
        """Full extraction pipeline for a guarantee table."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_tool_response(
            "extract_guarantee_table",
            {
                "product_name": "API Santé - Gamme Équilibre",
                "guarantee_level": "Equilibre 1",
                "has_comfort_pack": True,
                "comfort_pack_type": "Jeunes et Familles",
                "benefits": [
                    {
                        "benefit_name": "Analyses et examens de biologie médicale",
                        "category": "routine_care",
                        "reimbursement": {
                            "raw_value": "100 % BR - SS",
                            "reimbursement_type": "percentage_br_minus_ss",
                            "percentage": 100.0,
                        },
                    }
                ],
                "comfort_pack_options": [
                    {
                        "benefit_name": "Ostéopathe",
                        "formula_levels": {"PC1": "30€", "PC2": "40€", "PC3": "50€"},
                    }
                ],
            },
        )

        result = extract_document(
            text_content="Barème de garanties content...",
            document_type="guarantee_table",
            source_file="BG_Equilibre_1.pdf",
            client=mock_client,
        )

        assert result.document_type == DocumentType.GUARANTEE_TABLE
        assert result.guarantee_table is not None
        assert result.guarantee_table.guarantee_level == "Equilibre 1"
        assert result.guarantee_table.has_comfort_pack is True
        assert len(result.guarantee_table.comfort_pack_options) == 1

    def test_extract_api_failure(self):
        """API call failure should return ExtractionResult with errors."""
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API timeout")

        result = extract_document(
            text_content="content",
            document_type="ipid",
            source_file="test.pdf",
            client=mock_client,
        )

        assert result.extraction_errors is not None
        assert "API call failed" in result.extraction_errors[0]

    def test_extract_unknown_type_uses_any(self):
        """Unknown document type should use tool_choice 'any'."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_tool_response(
            "extract_ipid",
            {
                "product_name": "Test",
                "insurer_name": "Test",
                "insurance_type": "Test",
                "covered_items": [],
                "not_covered_items": [],
                "exclusions": [],
            },
        )

        extract_document(
            text_content="content",
            document_type="unknown",
            source_file="test.pdf",
            client=mock_client,
        )

        # Verify the API was called with tool_choice "any"
        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["tool_choice"] == {"type": "any"}

    def test_extract_ipid_uses_forced_selection(self):
        """Known IPID should use forced tool selection."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = self._mock_tool_response(
            "extract_ipid",
            {
                "product_name": "Test",
                "insurer_name": "Test",
                "insurance_type": "Test",
                "covered_items": [],
                "not_covered_items": [],
                "exclusions": [],
            },
        )

        extract_document(
            text_content="content",
            document_type="ipid",
            source_file="test.pdf",
            client=mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["tool_choice"] == {"type": "tool", "name": "extract_ipid"}
