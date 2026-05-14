"""
Core extraction engine using Claude API tool_use.

Implements structured data extraction from insurance documents using
Claude's tool_use feature with JSON schemas for guaranteed schema compliance.

CCA-F Scenario 6 concepts:
- tool_use with JSON schemas eliminates syntax errors (Task 4.3)
- tool_choice forced selection when document type is known (Task 4.3)
- tool_choice "any" when document type is unknown (Task 4.3)
- Semantic errors still possible — handled by validation layer (Task 4.4)
"""

from dataclasses import dataclass, field

from anthropic import Anthropic
from anthropic.types import Message, ToolUseBlock

from src.structured_extraction.schemas import (
    DocumentType,
    ExtractionResult,
    GuaranteeTableExtraction,
    IPIDExtraction,
    get_guarantee_table_tool_schema,
    get_ipid_tool_schema,
)

# ---------------------------------------------------------------------------
# Tool definitions for Claude API
# ---------------------------------------------------------------------------

# These tool definitions are sent to Claude in each API call.
# Claude sees the name, description, and input_schema — these are
# the PRIMARY mechanism for tool selection (CCA-F Task 2.1).

IPID_TOOL = {
    "name": "extract_ipid",
    "description": (
        "Extract structured data from an IPID (Insurance Product Information Document). "
        "Use this tool ONLY for IPID documents — standardized EU documents that contain "
        "sections like 'Qu'est-ce qui est assuré?', 'Qu'est-ce qui n'est pas assuré?', "
        "'Y-a-t-il des exclusions?', and 'Où suis-je couvert(e)?'. "
        "IPIDs are typically 2 pages and follow the IDD directive format. "
        "Do NOT use for guarantee tables, pricing documents, or product sheets. "
        "When a field's information is not present in the document, return null for that field."
    ),
    "input_schema": get_ipid_tool_schema(),
}

GUARANTEE_TABLE_TOOL = {
    "name": "extract_guarantee_table",
    "description": (
        "Extract structured data from a Guarantee Table (Barème de Garanties). "
        "Use this tool ONLY for documents that contain tabular benefit-by-benefit "
        "reimbursement rates organized by coverage category (Soins courants, "
        "Hospitalisation, Optique, Dentaire, Aides auditives). "
        "These documents list specific benefits with their reimbursement levels "
        "(e.g., '100% BR - SS', '30€/séance'). "
        "Do NOT use for IPIDs, pricing documents, or product sheets. "
        "When a reimbursement level is blank or absent for a benefit, "
        "set the raw_value to 'Non précisé' and reimbursement_type to 'other'."
    ),
    "input_schema": get_guarantee_table_tool_schema(),
}

ALL_EXTRACTION_TOOLS = [IPID_TOOL, GUARANTEE_TABLE_TOOL]


# ---------------------------------------------------------------------------
# System prompt for extraction
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """You are a specialized insurance document data extractor.
Your role is to extract structured data from French insurance documents (APICIL products).

CRITICAL RULES:
1. Extract ONLY information explicitly stated in the document.
2. If a field's information is not present in the document, return null — NEVER fabricate values.
3. Preserve the exact wording from the document in raw_value fields.
4. For reimbursement levels, capture BOTH the raw text and the parsed components.
5. For confidence scoring: mark a field as "high" when clearly stated, "medium" when
   inferred from context, "low" when ambiguous or partially legible.
6. Only include fields in field_confidences that have non-HIGH confidence.

FORMAT NORMALIZATION:
- Percentages: extract as float (e.g., "100 % BR - SS" → percentage: 100.0)
- Amounts: extract as float in euros (e.g., "30 € / séance" → fixed_amount_euros: 30.0)
- Dates: preserve original format from document (e.g., "05/2024", "12/2025")
"""


# ---------------------------------------------------------------------------
# Token tracking
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Track token usage for cost monitoring."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_calls: int = 0
    call_details: list[dict] = field(default_factory=list)

    def add_usage(self, input_t: int, output_t: int, call_type: str = "") -> None:
        self.input_tokens += input_t
        self.output_tokens += output_t
        self.total_calls += 1
        self.call_details.append(
            {
                "call_number": self.total_calls,
                "call_type": call_type,
                "input_tokens": input_t,
                "output_tokens": output_t,
            }
        )

    @property
    def estimated_cost_usd(self) -> float:
        """Estimate cost using claude-haiku-4-5 pricing ($1/M input, $5/M output)."""
        return (self.input_tokens / 1_000_000) + (self.output_tokens * 5 / 1_000_000)

    def summary(self) -> str:
        return (
            f"API Calls: {self.total_calls} | "
            f"Input: {self.input_tokens:,} tokens | "
            f"Output: {self.output_tokens:,} tokens | "
            f"Est. cost: ${self.estimated_cost_usd:.4f}"
        )


# ---------------------------------------------------------------------------
# Tool choice strategy
# ---------------------------------------------------------------------------


def get_tool_choice(document_type: str) -> dict | str:
    """Determine the tool_choice strategy based on document type.

    CCA-F Task 4.3 — three tool_choice modes:
    - Forced selection: when we know the document type → guarantee correct tool
    - "any": when document type is unknown → Claude must call a tool but chooses which
    - "auto": not used here — risk of Claude returning text instead of structured data

    Args:
        document_type: The detected document type string.

    Returns:
        tool_choice parameter for the Claude API call.
    """
    if document_type == "ipid":
        # Forced selection — we know it's an IPID, force the correct tool
        return {"type": "tool", "name": "extract_ipid"}
    elif document_type == "guarantee_table":
        # Forced selection — we know it's a guarantee table
        return {"type": "tool", "name": "extract_guarantee_table"}
    else:
        # Unknown document type — Claude must call a tool but chooses which
        # "any" guarantees structured output (no prose fallback)
        return {"type": "any"}


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def parse_tool_response(message: Message) -> tuple[str, dict]:
    """Extract the tool name and input from Claude's response.

    When tool_choice forces a specific tool (or "any"), Claude's response
    contains a ToolUseBlock with the structured extraction data.

    Args:
        message: The Claude API response message.

    Returns:
        Tuple of (tool_name, extracted_data_dict).

    Raises:
        ValueError: If no tool use block is found in the response.
    """
    for block in message.content:
        if isinstance(block, ToolUseBlock):
            return block.name, block.input

    raise ValueError(
        f"No tool_use block found in response. stop_reason={message.stop_reason}. "
        "This may indicate tool_choice was set to 'auto' and Claude responded with text."
    )


# ---------------------------------------------------------------------------
# Core extraction function
# ---------------------------------------------------------------------------


def extract_document(
    text_content: str,
    document_type: str,
    source_file: str,
    client: Anthropic | None = None,
    model: str = "claude-haiku-4-5",
    token_usage: TokenUsage | None = None,
) -> ExtractionResult:
    """Extract structured data from an insurance document.

    This is the core extraction function. It:
    1. Selects the appropriate tool_choice based on document type
    2. Sends the document text to Claude with extraction tools
    3. Parses the tool_use response into a validated Pydantic model
    4. Returns an ExtractionResult with the typed extraction

    Args:
        text_content: The text content of the document to extract from.
        document_type: Detected document type (e.g., "ipid", "guarantee_table").
        source_file: Original filename for tracking.
        client: Anthropic client instance. Created from env if None.
        model: Claude model to use.
        token_usage: Optional token tracker for cost monitoring.

    Returns:
        ExtractionResult with the structured extraction or errors.
    """
    if client is None:
        client = Anthropic()

    tool_choice = get_tool_choice(document_type)

    # Select which tools to send based on document type
    # When type is known, we still send both tools (Claude needs the schema)
    # but force selection via tool_choice
    tools = ALL_EXTRACTION_TOOLS

    try:
        message = client.messages.create(
            model=model,
            max_tokens=4096,
            system=EXTRACTION_SYSTEM_PROMPT,
            tools=tools,
            tool_choice=tool_choice,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract structured data from this insurance document.\n"
                        f"Document type: {document_type}\n"
                        f"Source file: {source_file}\n\n"
                        f"--- DOCUMENT CONTENT ---\n{text_content}\n--- END DOCUMENT ---"
                    ),
                }
            ],
        )
    except Exception as e:
        return ExtractionResult(
            document_type=DocumentType(document_type)
            if document_type in DocumentType.__members__.values()
            else DocumentType.UNKNOWN,
            source_file=source_file,
            extraction_errors=[f"API call failed: {e!s}"],
        )

    # Track token usage
    if token_usage is not None:
        token_usage.add_usage(
            input_t=message.usage.input_tokens,
            output_t=message.usage.output_tokens,
            call_type=f"extraction_{document_type}",
        )

    # Parse tool response
    try:
        tool_name, extracted_data = parse_tool_response(message)
    except ValueError as e:
        return ExtractionResult(
            document_type=_safe_document_type(document_type),
            source_file=source_file,
            extraction_errors=[str(e)],
        )

    # Validate with Pydantic models
    return _build_extraction_result(tool_name, extracted_data, source_file)


def _safe_document_type(document_type: str) -> DocumentType:
    """Convert a string to DocumentType safely."""
    try:
        return DocumentType(document_type)
    except ValueError:
        return DocumentType.UNKNOWN


def _build_extraction_result(
    tool_name: str,
    extracted_data: dict,
    source_file: str,
) -> ExtractionResult:
    """Build a validated ExtractionResult from raw tool output.

    This is where Pydantic validation catches semantic issues:
    - Missing required fields that Claude should have extracted
    - Invalid enum values
    - Type mismatches (string where float expected)

    Schema syntax errors (malformed JSON) are already eliminated by tool_use.
    What we catch here are semantic validation errors (Task 4.4).
    """
    errors = []

    if tool_name == "extract_ipid":
        try:
            ipid = IPIDExtraction.model_validate(extracted_data)
            return ExtractionResult(
                document_type=DocumentType.IPID,
                source_file=source_file,
                ipid=ipid,
            )
        except Exception as e:
            errors.append(f"IPID validation failed: {e!s}")
            return ExtractionResult(
                document_type=DocumentType.IPID,
                source_file=source_file,
                extraction_errors=errors,
            )

    elif tool_name == "extract_guarantee_table":
        try:
            bg = GuaranteeTableExtraction.model_validate(extracted_data)
            return ExtractionResult(
                document_type=DocumentType.GUARANTEE_TABLE,
                source_file=source_file,
                guarantee_table=bg,
            )
        except Exception as e:
            errors.append(f"Guarantee table validation failed: {e!s}")
            return ExtractionResult(
                document_type=DocumentType.GUARANTEE_TABLE,
                source_file=source_file,
                extraction_errors=errors,
            )

    else:
        return ExtractionResult(
            document_type=DocumentType.UNKNOWN,
            source_file=source_file,
            extraction_errors=[f"Unknown tool called: {tool_name}"],
        )
