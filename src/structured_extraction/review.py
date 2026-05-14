"""
Independent quality review using a separate Claude instance.

CCA-F Scenario 6, Task 4.6:
- Self-review is unreliable: the model retains reasoning context from generation
- An independent review instance (without prior reasoning) is more effective
- The reviewer sees the document + extraction, but NOT the extraction prompt/reasoning

This module implements a "second pair of eyes" pattern: a separate Claude call
that verifies the extraction against the source document, checking for
hallucination, misclassification, and missed information.
"""

from dataclasses import dataclass, field

from anthropic import Anthropic
from anthropic.types import ToolUseBlock

from src.structured_extraction.extraction import TokenUsage
from src.structured_extraction.schemas import (
    ExtractionResult,
)

# ---------------------------------------------------------------------------
# Review finding model
# ---------------------------------------------------------------------------


@dataclass
class ReviewFinding:
    """A single issue found during quality review."""

    field_path: str
    issue_type: str  # "hallucination", "misclassification", "missed_info", "inaccuracy"
    description: str
    suggested_correction: str | None = None
    confidence: str = "high"  # reviewer's confidence in the finding


@dataclass
class QualityReviewResult:
    """Result of an independent quality review."""

    source_file: str
    is_approved: bool
    findings: list[ReviewFinding] = field(default_factory=list)
    reviewer_notes: str | None = None

    @property
    def finding_count(self) -> int:
        return len(self.findings)

    @property
    def has_hallucinations(self) -> bool:
        return any(f.issue_type == "hallucination" for f in self.findings)

    @property
    def has_missed_info(self) -> bool:
        return any(f.issue_type == "missed_info" for f in self.findings)

    def summary(self) -> str:
        status = "APPROVED" if self.is_approved else "REJECTED"
        return (
            f"Review [{self.source_file}]: {status} | "
            f"Findings: {self.finding_count} | "
            f"Hallucinations: {self.has_hallucinations} | "
            f"Missed info: {self.has_missed_info}"
        )


# ---------------------------------------------------------------------------
# Review tool definition
# ---------------------------------------------------------------------------

REVIEW_TOOL = {
    "name": "submit_review",
    "description": (
        "Submit the quality review findings for an extraction. "
        "Compare the extraction against the source document and report: "
        "1) Any hallucinated values (present in extraction but NOT in document), "
        "2) Any misclassified categories or types, "
        "3) Any information present in the document but missing from extraction, "
        "4) Any inaccurate values (present in both but different). "
        "If the extraction is accurate and complete, approve it with no findings."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "is_approved": {
                "type": "boolean",
                "description": (
                    "True if extraction is accurate and complete, False if issues found."
                ),
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field_path": {
                            "type": "string",
                            "description": (
                                "Path to the problematic field (e.g., 'covered_items[2].category')."
                            ),
                        },
                        "issue_type": {
                            "type": "string",
                            "enum": [
                                "hallucination",
                                "misclassification",
                                "missed_info",
                                "inaccuracy",
                            ],
                            "description": "Type of issue found.",
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of the issue.",
                        },
                        "suggested_correction": {
                            "type": ["string", "null"],
                            "description": "Suggested fix, or null if unclear.",
                        },
                    },
                    "required": ["field_path", "issue_type", "description"],
                },
                "description": "List of issues found. Empty array if approved.",
            },
            "reviewer_notes": {
                "type": ["string", "null"],
                "description": "Overall assessment notes from the reviewer.",
            },
        },
        "required": ["is_approved", "findings"],
    },
}


# ---------------------------------------------------------------------------
# Review system prompt
# ---------------------------------------------------------------------------

REVIEW_SYSTEM_PROMPT = """\
You are an independent quality reviewer for insurance document extractions.

Your role is to verify that structured data extracted from French insurance documents
is accurate, complete, and free of hallucination.

CRITICAL: You are reviewing someone else's work. You did NOT perform the extraction.
Be objective and thorough.

CHECK FOR:
1. HALLUCINATION: Values in the extraction that do NOT appear in the source document.
   This is the most critical issue. If a field has a value but the document doesn't
   mention it, flag it as hallucination.

2. MISCLASSIFICATION: Values assigned to wrong categories.
   Example: a dental benefit classified as "optical", or an absolute exclusion
   marked as "regulatory".

3. MISSED INFORMATION: Information clearly present in the document that was NOT extracted.
   Example: a coverage category mentioned in the document but absent from covered_items.

4. INACCURACY: Values that appear in both but differ.
   Example: document says "150% BR" but extraction has percentage=100.

IMPORTANT:
- If a field is null in the extraction AND the information is not in the document,
  that is CORRECT (not an issue).
- Focus on factual accuracy, not style or formatting preferences.
- Only flag clear, unambiguous issues — not borderline interpretation differences.
"""


# ---------------------------------------------------------------------------
# Core review function
# ---------------------------------------------------------------------------


def review_extraction(
    document_text: str,
    extraction_result: ExtractionResult,
    client: Anthropic | None = None,
    model: str = "claude-haiku-4-5",
    token_usage: TokenUsage | None = None,
) -> QualityReviewResult:
    """Run an independent quality review on an extraction.

    CCA-F Task 4.6: uses a SEPARATE Claude instance (no shared context
    with the extraction call) to verify accuracy.

    Args:
        document_text: Original document text (source of truth).
        extraction_result: The extraction to review.
        client: Anthropic client. Created from env if None.
        model: Claude model to use for review.
        token_usage: Optional token tracker.

    Returns:
        QualityReviewResult with findings.
    """
    if client is None:
        client = Anthropic()

    # Serialize extraction for review
    if extraction_result.ipid is not None:
        extraction_json = extraction_result.ipid.model_dump_json(indent=2)
        doc_type_label = "IPID"
    elif extraction_result.guarantee_table is not None:
        extraction_json = extraction_result.guarantee_table.model_dump_json(indent=2)
        doc_type_label = "Guarantee Table"
    else:
        return QualityReviewResult(
            source_file=extraction_result.source_file,
            is_approved=False,
            findings=[
                ReviewFinding(
                    field_path="extraction",
                    issue_type="missed_info",
                    description="No extraction data to review.",
                )
            ],
        )

    try:
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            system=REVIEW_SYSTEM_PROMPT,
            tools=[REVIEW_TOOL],
            tool_choice={"type": "tool", "name": "submit_review"},
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Review this {doc_type_label} extraction for accuracy.\n\n"
                        f"--- SOURCE DOCUMENT ---\n{document_text}\n--- END DOCUMENT ---\n\n"
                        f"--- EXTRACTION TO REVIEW ---\n"
                        f"{extraction_json}\n--- END EXTRACTION ---\n\n"
                        f"Compare the extraction against the source document. "
                        f"Flag any hallucinations, misclassifications, missed information, "
                        f"or inaccuracies. Approve if the extraction is accurate and complete."
                    ),
                }
            ],
        )
    except Exception as e:
        return QualityReviewResult(
            source_file=extraction_result.source_file,
            is_approved=False,
            findings=[
                ReviewFinding(
                    field_path="review",
                    issue_type="inaccuracy",
                    description=f"Review API call failed: {e!s}",
                )
            ],
        )

    # Track tokens
    if token_usage is not None:
        token_usage.add_usage(
            input_t=message.usage.input_tokens,
            output_t=message.usage.output_tokens,
            call_type="quality_review",
        )

    # Parse review response
    return _parse_review_response(message, extraction_result.source_file)


def _parse_review_response(message, source_file: str) -> QualityReviewResult:
    """Parse the review tool response into a QualityReviewResult."""
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            data = block.input
            findings = [
                ReviewFinding(
                    field_path=f.get("field_path", "unknown"),
                    issue_type=f.get("issue_type", "inaccuracy"),
                    description=f.get("description", ""),
                    suggested_correction=f.get("suggested_correction"),
                )
                for f in data.get("findings", [])
            ]
            return QualityReviewResult(
                source_file=source_file,
                is_approved=data.get("is_approved", False),
                findings=findings,
                reviewer_notes=data.get("reviewer_notes"),
            )

    return QualityReviewResult(
        source_file=source_file,
        is_approved=False,
        findings=[
            ReviewFinding(
                field_path="review",
                issue_type="inaccuracy",
                description="No tool_use block in review response.",
            )
        ],
    )
