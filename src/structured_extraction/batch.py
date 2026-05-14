"""
Batch processing using the Message Batches API.

CCA-F Scenario 6, Task 4.5:
- Message Batches API: 50% cost savings, up to 24-hour processing window
- Appropriate for non-blocking, latency-tolerant workloads
- Does NOT support multi-turn tool calling within a single request
- custom_id fields for correlating batch request/response pairs
- Failure handling: resubmit only failed documents by custom_id

Design decision: we build batch requests as Message API calls with tool_use,
then submit them through the Batches API. Each document is independent
(no multi-turn needed), making batch processing a perfect fit.
"""

from dataclasses import dataclass, field

from src.structured_extraction.extraction import (
    ALL_EXTRACTION_TOOLS,
    EXTRACTION_SYSTEM_PROMPT,
    _build_extraction_result,
    get_tool_choice,
)
from src.structured_extraction.schemas import (
    DocumentType,
    ExtractionResult,
)

# ---------------------------------------------------------------------------
# Batch request builder
# ---------------------------------------------------------------------------


@dataclass
class BatchDocumentRequest:
    """A single document prepared for batch submission.

    custom_id is used to correlate request/response pairs
    when batch results come back (CCA-F Task 4.5).
    """

    custom_id: str
    document_type: str
    source_file: str
    text_content: str


@dataclass
class BatchSubmission:
    """A prepared batch ready for submission."""

    requests: list[BatchDocumentRequest]
    model: str = "claude-haiku-4-5"

    @property
    def total_documents(self) -> int:
        return len(self.requests)


def prepare_batch_requests(
    documents: list[dict],
    model: str = "claude-haiku-4-5",
) -> BatchSubmission:
    """Prepare a batch of documents for submission to the Batches API.

    Each document becomes an independent extraction request with a custom_id
    for result correlation.

    Args:
        documents: List of dicts with keys: custom_id, document_type,
                   source_file, text_content.
        model: Claude model to use.

    Returns:
        BatchSubmission ready for submit_batch().
    """
    requests = []
    for doc in documents:
        requests.append(
            BatchDocumentRequest(
                custom_id=doc["custom_id"],
                document_type=doc["document_type"],
                source_file=doc["source_file"],
                text_content=doc["text_content"],
            )
        )

    return BatchSubmission(requests=requests, model=model)


def build_batch_api_requests(submission: BatchSubmission) -> list[dict]:
    """Convert a BatchSubmission into Anthropic Batches API format.

    Each request is a standalone Messages API call with tool_use,
    packaged for the batch endpoint.

    Args:
        submission: The prepared batch submission.

    Returns:
        List of request dicts in the Batches API format.
    """
    api_requests = []
    for req in submission.requests:
        tool_choice = get_tool_choice(req.document_type)

        api_request = {
            "custom_id": req.custom_id,
            "params": {
                "model": submission.model,
                "max_tokens": 4096,
                "system": EXTRACTION_SYSTEM_PROMPT,
                "tools": ALL_EXTRACTION_TOOLS,
                "tool_choice": tool_choice,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Extract structured data from this insurance document.\n"
                            f"Document type: {req.document_type}\n"
                            f"Source file: {req.source_file}\n\n"
                            f"--- DOCUMENT CONTENT ---\n{req.text_content}\n--- END DOCUMENT ---"
                        ),
                    }
                ],
            },
        }
        api_requests.append(api_request)

    return api_requests


# ---------------------------------------------------------------------------
# Batch result processing
# ---------------------------------------------------------------------------


@dataclass
class BatchResultItem:
    """A single result from batch processing."""

    custom_id: str
    extraction_result: ExtractionResult | None = None
    error: str | None = None
    is_success: bool = False


@dataclass
class BatchResults:
    """Complete results from a batch processing run."""

    items: list[BatchResultItem] = field(default_factory=list)
    total_submitted: int = 0
    processing_time_seconds: float | None = None

    @property
    def success_count(self) -> int:
        return sum(1 for item in self.items if item.is_success)

    @property
    def failure_count(self) -> int:
        return sum(1 for item in self.items if not item.is_success)

    @property
    def failed_custom_ids(self) -> list[str]:
        """Get custom_ids of failed items for resubmission.

        CCA-F Task 4.5: resubmitting only failed documents
        identified by custom_id.
        """
        return [item.custom_id for item in self.items if not item.is_success]

    def summary(self) -> str:
        return (
            f"Batch: {self.success_count}/{self.total_submitted} succeeded | "
            f"Failed: {self.failure_count} | "
            f"Time: {self.processing_time_seconds or 'N/A'}s"
        )


def parse_batch_results(
    raw_results: list[dict],
    submission: BatchSubmission,
) -> BatchResults:
    """Parse raw batch API results into structured ExtractionResults.

    Args:
        raw_results: Raw results from the Batches API.
        submission: The original submission (for source_file mapping).

    Returns:
        BatchResults with parsed extractions and error tracking.
    """
    # Build lookup for source files by custom_id
    source_lookup = {
        req.custom_id: (req.source_file, req.document_type) for req in submission.requests
    }

    items = []
    for raw in raw_results:
        custom_id = raw.get("custom_id", "unknown")
        source_file, doc_type = source_lookup.get(custom_id, ("unknown", "unknown"))

        result_data = raw.get("result", {})

        if result_data.get("type") == "succeeded":
            message_data = result_data.get("message", {})
            # Find tool_use block in response content
            extraction = _extract_from_batch_message(message_data, source_file)
            items.append(
                BatchResultItem(
                    custom_id=custom_id,
                    extraction_result=extraction,
                    is_success=extraction.extraction_errors is None,
                )
            )
        else:
            error_msg = result_data.get("error", {}).get("message", "Unknown batch error")
            items.append(
                BatchResultItem(
                    custom_id=custom_id,
                    error=error_msg,
                    is_success=False,
                )
            )

    return BatchResults(
        items=items,
        total_submitted=len(submission.requests),
    )


def _extract_from_batch_message(
    message_data: dict,
    source_file: str,
) -> ExtractionResult:
    """Extract structured data from a batch response message."""
    content = message_data.get("content", [])

    for block in content:
        if block.get("type") == "tool_use":
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            return _build_extraction_result(tool_name, tool_input, source_file)

    return ExtractionResult(
        document_type=DocumentType.UNKNOWN,
        source_file=source_file,
        extraction_errors=["No tool_use block in batch response"],
    )


# ---------------------------------------------------------------------------
# SLA calculation
# ---------------------------------------------------------------------------


def calculate_batch_schedule(
    total_documents: int,
    batch_size: int = 1000,
    max_batch_processing_hours: int = 24,
    sla_hours: int = 30,
) -> dict:
    """Calculate batch submission schedule based on SLA constraints.

    CCA-F Task 4.5: calculating batch submission frequency based on
    SLA constraints (e.g., 4-hour windows to guarantee 30-hour SLA
    with 24-hour batch processing).

    Args:
        total_documents: Total number of documents to process.
        batch_size: Maximum documents per batch.
        max_batch_processing_hours: Maximum batch processing time (24h for Anthropic).
        sla_hours: Required SLA in hours.

    Returns:
        Dict with schedule details.
    """
    num_batches = (total_documents + batch_size - 1) // batch_size  # ceil division
    buffer_hours = sla_hours - max_batch_processing_hours

    return {
        "total_documents": total_documents,
        "num_batches": num_batches,
        "batch_size": batch_size,
        "max_processing_hours": max_batch_processing_hours,
        "sla_hours": sla_hours,
        "buffer_hours": buffer_hours,
        "submit_before_hours": buffer_hours,
        "cost_savings_percent": 50,
        "recommendation": (
            f"Submit {num_batches} batch(es) of up to {batch_size} documents. "
            f"Must submit at least {buffer_hours}h before SLA deadline "
            f"to guarantee delivery within {sla_hours}h SLA. "
            f"Saves 50% compared to synchronous API calls."
        ),
    }
