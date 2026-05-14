"""
Pipeline metrics and reporting.

Aggregates metrics across all pipeline stages:
extraction, validation, retry, confidence routing, review, and batch.
"""

from dataclasses import dataclass, field


@dataclass
class PipelineMetrics:
    """Aggregate metrics for a pipeline run.

    Tracks the full journey of documents through the extraction pipeline
    for reporting and optimization.
    """

    # Run metadata
    run_id: str = ""
    started_at: str = ""
    completed_at: str = ""

    # Document counts
    total_documents: int = 0
    successfully_extracted: int = 0
    failed_extraction: int = 0

    # Validation
    valid_on_first_try: int = 0
    valid_after_retry: int = 0
    invalid_after_all_retries: int = 0

    # Retry stats
    total_retries: int = 0
    retries_skipped_not_retryable: int = 0

    # Review routing
    auto_accepted: int = 0
    sent_to_human_review: int = 0
    rejected: int = 0

    # Quality review (independent instance)
    reviews_performed: int = 0
    reviews_approved: int = 0
    hallucinations_detected: int = 0
    missed_info_detected: int = 0

    # Token usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Per-document-type breakdown
    by_document_type: dict[str, dict] = field(default_factory=dict)

    @property
    def success_rate(self) -> float | None:
        if self.total_documents == 0:
            return None
        return (self.successfully_extracted / self.total_documents) * 100

    @property
    def first_try_rate(self) -> float | None:
        if self.successfully_extracted == 0:
            return None
        return (self.valid_on_first_try / self.successfully_extracted) * 100

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "PIPELINE METRICS REPORT",
            "=" * 60,
            f"Run ID: {self.run_id}",
            f"Started: {self.started_at}",
            f"Completed: {self.completed_at}",
            "",
            "--- Document Processing ---",
            f"Total documents:          {self.total_documents}",
            f"Successfully extracted:    {self.successfully_extracted}",
            f"Failed:                   {self.failed_extraction}",
            f"Success rate:             {self.success_rate:.1f}%"
            if self.success_rate
            else "Success rate: N/A",
            "",
            "--- Validation & Retry ---",
            f"Valid on first try:       {self.valid_on_first_try}",
            f"Valid after retry:        {self.valid_after_retry}",
            f"Invalid (all retries):    {self.invalid_after_all_retries}",
            f"Total retries:            {self.total_retries}",
            f"First-try rate:           {self.first_try_rate:.1f}%"
            if self.first_try_rate
            else "First-try rate: N/A",
            "",
            "--- Review Routing ---",
            f"Auto-accepted:            {self.auto_accepted}",
            f"Sent to human review:     {self.sent_to_human_review}",
            f"Rejected:                 {self.rejected}",
            "",
            "--- Quality Review ---",
            f"Reviews performed:        {self.reviews_performed}",
            f"Approved:                 {self.reviews_approved}",
            f"Hallucinations found:     {self.hallucinations_detected}",
            f"Missed info found:        {self.missed_info_detected}",
            "",
            "--- Cost ---",
            f"Input tokens:             {self.total_input_tokens:,}",
            f"Output tokens:            {self.total_output_tokens:,}",
            f"Estimated cost:           ${self.estimated_cost_usd:.4f}",
            "=" * 60,
        ]
        return "\n".join(lines)
