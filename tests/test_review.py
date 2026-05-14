"""Tests for independent quality review.

CCA-F Task 4.6: separate instance review without extraction context.
"""

from unittest.mock import MagicMock

from anthropic.types import ToolUseBlock

from src.structured_extraction.extraction import TokenUsage
from src.structured_extraction.review import (
    REVIEW_SYSTEM_PROMPT,
    REVIEW_TOOL,
    QualityReviewResult,
    ReviewFinding,
    review_extraction,
)
from src.structured_extraction.schemas import (
    CoverageCategory,
    DocumentType,
    ExclusionItem,
    ExtractionResult,
    InsuredItem,
    IPIDExtraction,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extraction() -> ExtractionResult:
    return ExtractionResult(
        document_type=DocumentType.IPID,
        source_file="test.pdf",
        ipid=IPIDExtraction(
            product_name="API Santé Équilibre",
            insurer_name="APICIL Mutuelle",
            insurance_type="Complémentaire santé",
            covered_items=[
                InsuredItem(description="Soins courants", category=CoverageCategory.ROUTINE_CARE),
            ],
            not_covered_items=["Chirurgie esthétique"],
            exclusions=[
                ExclusionItem(description="Participation forfaitaire", exclusion_type="regulatory"),
            ],
        ),
    )


def _make_review_response(is_approved: bool, findings: list | None = None) -> MagicMock:
    tool_block = ToolUseBlock(
        id="toolu_review",
        type="tool_use",
        name="submit_review",
        input={
            "is_approved": is_approved,
            "findings": findings or [],
            "reviewer_notes": "Review complete.",
        },
    )
    message = MagicMock()
    message.content = [tool_block]
    message.stop_reason = "tool_use"
    message.usage = MagicMock()
    message.usage.input_tokens = 2000
    message.usage.output_tokens = 500
    return message


# ---------------------------------------------------------------------------
# Review tool definition tests
# ---------------------------------------------------------------------------


class TestReviewToolDefinition:
    def test_review_tool_has_required_fields(self):
        assert "name" in REVIEW_TOOL
        assert "description" in REVIEW_TOOL
        assert "input_schema" in REVIEW_TOOL

    def test_review_tool_schema_has_findings(self):
        schema = REVIEW_TOOL["input_schema"]
        assert "findings" in schema["properties"]
        assert "is_approved" in schema["properties"]

    def test_review_system_prompt_mentions_hallucination(self):
        assert "hallucination" in REVIEW_SYSTEM_PROMPT.lower()

    def test_review_system_prompt_mentions_independence(self):
        """CCA-F Task 4.6: reviewer should NOT have extraction context."""
        assert "did NOT perform" in REVIEW_SYSTEM_PROMPT or "someone else" in REVIEW_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Review result tests
# ---------------------------------------------------------------------------


class TestQualityReviewResult:
    def test_approved_result(self):
        result = QualityReviewResult(
            source_file="test.pdf",
            is_approved=True,
        )
        assert result.is_approved is True
        assert result.finding_count == 0
        assert result.has_hallucinations is False

    def test_result_with_hallucination(self):
        result = QualityReviewResult(
            source_file="test.pdf",
            is_approved=False,
            findings=[
                ReviewFinding(
                    field_path="madelin_eligible",
                    issue_type="hallucination",
                    description="Document doesn't mention Madelin",
                ),
            ],
        )
        assert result.has_hallucinations is True
        assert result.finding_count == 1

    def test_result_with_missed_info(self):
        result = QualityReviewResult(
            source_file="test.pdf",
            is_approved=False,
            findings=[
                ReviewFinding(
                    field_path="covered_items",
                    issue_type="missed_info",
                    description="Missing dental coverage",
                ),
            ],
        )
        assert result.has_missed_info is True

    def test_summary_format(self):
        result = QualityReviewResult(source_file="test.pdf", is_approved=True)
        summary = result.summary()
        assert "APPROVED" in summary
        assert "test.pdf" in summary


# ---------------------------------------------------------------------------
# Integration tests (mocked API)
# ---------------------------------------------------------------------------


class TestReviewExtraction:
    def test_review_approved(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_review_response(
            is_approved=True,
        )

        result = review_extraction(
            document_text="Document content...",
            extraction_result=_make_extraction(),
            client=mock_client,
        )

        assert result.is_approved is True
        assert result.finding_count == 0

    def test_review_with_findings(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_review_response(
            is_approved=False,
            findings=[
                {
                    "field_path": "madelin_eligible",
                    "issue_type": "hallucination",
                    "description": "Not mentioned in document",
                    "suggested_correction": "Set to null",
                }
            ],
        )

        result = review_extraction(
            document_text="Document content...",
            extraction_result=_make_extraction(),
            client=mock_client,
        )

        assert result.is_approved is False
        assert result.finding_count == 1
        assert result.findings[0].issue_type == "hallucination"

    def test_review_uses_forced_tool_selection(self):
        """Review should force the submit_review tool."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_review_response(is_approved=True)

        review_extraction(
            document_text="doc",
            extraction_result=_make_extraction(),
            client=mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args
        assert call_kwargs.kwargs["tool_choice"] == {"type": "tool", "name": "submit_review"}

    def test_review_uses_separate_system_prompt(self):
        """CCA-F Task 4.6: review instance has its own system prompt."""
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_review_response(is_approved=True)

        review_extraction(
            document_text="doc",
            extraction_result=_make_extraction(),
            client=mock_client,
        )

        call_kwargs = mock_client.messages.create.call_args
        system_prompt = call_kwargs.kwargs["system"]
        assert "independent" in system_prompt.lower() or "reviewer" in system_prompt.lower()

    def test_review_tracks_tokens(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = _make_review_response(is_approved=True)

        token_usage = TokenUsage()
        review_extraction(
            document_text="doc",
            extraction_result=_make_extraction(),
            client=mock_client,
            token_usage=token_usage,
        )

        assert token_usage.total_calls == 1
        assert token_usage.call_details[0]["call_type"] == "quality_review"

    def test_review_api_failure(self):
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = Exception("API error")

        result = review_extraction(
            document_text="doc",
            extraction_result=_make_extraction(),
            client=mock_client,
        )

        assert result.is_approved is False
        assert "API call failed" in result.findings[0].description

    def test_review_empty_extraction(self):
        result = review_extraction(
            document_text="doc",
            extraction_result=ExtractionResult(
                document_type=DocumentType.IPID,
                source_file="empty.pdf",
            ),
            client=MagicMock(),
        )

        assert result.is_approved is False
        assert result.findings[0].issue_type == "missed_info"
