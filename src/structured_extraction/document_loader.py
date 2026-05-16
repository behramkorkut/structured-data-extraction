"""
Document loader for insurance PDF documents.

Extracts text content from PDF files for downstream structured extraction.
Uses pdfplumber for text extraction from structured/tabular PDFs.
"""

from dataclasses import dataclass, field
from pathlib import Path

# --- Document type detection based on filename patterns ---

DOCUMENT_TYPE_PATTERNS: dict[str, list[str]] = {
    "ipid": ["ipid"],
    "guarantee_table": ["barème", "bareme", "bg "],
    "product_sheet": ["fiche produit"],
    "pricing": ["cotisation", "tarif"],
    "reimbursement_example": ["rbst", "remboursement"],
    "information_notice": ["notice", " ni "],
    "commercial_brochure": ["plaquette"],
}


# Types with a full extraction schema (tool_use + Pydantic model + validation)
SUPPORTED_EXTRACTION_TYPES: set[str] = {"ipid", "guarantee_table"}

# Types we recognise but cannot extract yet (no schema defined)
RECOGNISED_UNSUPPORTED_TYPES: set[str] = {
    "product_sheet",
    "pricing",
    "reimbursement_example",
    "information_notice",
    "commercial_brochure",
}


def is_extraction_supported(document_type: str) -> bool:
    """Check whether a document type has a full extraction schema.

    Args:
        document_type: The detected document type string.

    Returns:
        True if the pipeline can extract structured data from this type.
    """
    return document_type in SUPPORTED_EXTRACTION_TYPES


def get_unsupported_reason(document_type: str) -> str:
    """Return a human-readable explanation for why extraction is not supported.

    Args:
        document_type: The detected document type string.

    Returns:
        Explanation string with suggested next steps.
    """
    type_descriptions = {
        "product_sheet": (
            "Product sheets contain marketing and summary information. "
            "A dedicated schema with fields like target_audience, "
            "key_selling_points, and eligibility_criteria would be needed."
        ),
        "pricing": (
            "Pricing documents contain tariff tables by age/region. "
            "A dedicated schema with fields like age_brackets, "
            "monthly_premiums, and regional_multipliers would be needed."
        ),
        "reimbursement_example": (
            "Reimbursement examples show concrete cost scenarios. "
            "A dedicated schema with fields like scenario_description, "
            "total_cost, ss_reimbursement, and insurer_reimbursement would be needed."
        ),
        "information_notice": (
            "Information notices contain legal and regulatory text. "
            "A dedicated schema with fields like articles, "
            "effective_date, and regulatory_references would be needed."
        ),
        "commercial_brochure": (
            "Commercial brochures contain marketing material. "
            "A dedicated schema with product highlights and "
            "comparison tables would be needed."
        ),
    }
    if document_type in type_descriptions:
        return type_descriptions[document_type]
    return (
        f"Document type '{document_type}' is not recognised. "
        "Check the filename or add a new detection pattern."
    )


@dataclass
class InsuranceDocument:
    """Represents a loaded insurance document with metadata.

    Attributes:
        file_path: Original file path.
        file_name: File name without extension.
        text_content: Extracted text from the PDF.
        document_type: Detected document type based on filename patterns.
        product_line: Detected product line (e.g., "API Santé Equilibre").
        page_count: Number of pages in the source document.
        metadata: Additional metadata extracted during loading.
    """

    file_path: Path
    file_name: str
    text_content: str
    document_type: str
    product_line: str | None = None
    page_count: int = 0
    metadata: dict = field(default_factory=dict)


def detect_document_type(filename: str) -> str:
    """Detect the document type from the filename using pattern matching.

    Args:
        filename: The filename (without path) to analyze.

    Returns:
        The detected document type string, or "unknown" if no pattern matches.
    """
    filename_lower = filename.lower()
    for doc_type, patterns in DOCUMENT_TYPE_PATTERNS.items():
        for pattern in patterns:
            if pattern in filename_lower:
                return doc_type
    return "unknown"


PRODUCT_LINE_PATTERNS: dict[str, list[str]] = {
    "API Santé Equilibre": ["api santé - equilibre", "api santé equilibre", "api sante equilibre"],
    "API Santé Sérénité": [
        "api santé-sérénité",
        "api santé sérénité",
        "api santé - sérénité",
        "api sante serenite",
    ],
    "APICIL Essentio": ["essentio"],
    "APICIL Accident": ["apicil accident"],
    "APICIL Protection Décès": ["protection décès", "protection deces"],
    "APICIL Tandem": ["tandem"],
    "Garantie Hospitalisation": ["garantie hospitalisation"],
}


def detect_product_line(filename: str) -> str | None:
    """Detect the product line from the filename.

    Args:
        filename: The filename to analyze.

    Returns:
        The detected product line name, or None if not detected.
    """
    filename_lower = filename.lower()
    for product_line, patterns in PRODUCT_LINE_PATTERNS.items():
        for pattern in patterns:
            if pattern in filename_lower:
                return product_line
    return None


def load_text_from_file(file_path: Path) -> tuple[str, int]:
    """Load text content from a file.

    For PDF files, uses pdfplumber to extract text.
    For .txt files, reads directly.

    Args:
        file_path: Path to the file.

    Returns:
        Tuple of (extracted_text, page_count).

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file format is not supported.
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        return _load_pdf(file_path)
    elif suffix == ".txt":
        text = file_path.read_text(encoding="utf-8")
        page_count = text.count("\f") + 1  # Form feed = page break
        return text, page_count
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Supported: .pdf, .txt")


def _load_pdf(file_path: Path) -> tuple[str, int]:
    """Extract text from a PDF file using pdfplumber.

    Args:
        file_path: Path to the PDF file.

    Returns:
        Tuple of (extracted_text, page_count).
    """
    try:
        import pdfplumber
    except ImportError as err:
        raise ImportError(
            "pdfplumber is required for PDF extraction. Install it with: uv add pdfplumber"
        ) from err

    pages_text = []
    with pdfplumber.open(file_path) as pdf:
        page_count = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages_text.append(f"--- Page {i + 1} ---\n{text}")

    return "\n\n".join(pages_text), page_count


def load_document(file_path: Path) -> InsuranceDocument:
    """Load an insurance document from a file path.

    Extracts text, detects document type and product line from filename.

    Args:
        file_path: Path to the document file.

    Returns:
        An InsuranceDocument with extracted text and metadata.
    """
    file_path = Path(file_path)
    file_name = file_path.stem

    text_content, page_count = load_text_from_file(file_path)
    document_type = detect_document_type(file_path.name)
    product_line = detect_product_line(file_path.name)

    return InsuranceDocument(
        file_path=file_path,
        file_name=file_name,
        text_content=text_content,
        document_type=document_type,
        product_line=product_line,
        page_count=page_count,
        metadata={
            "source_extension": file_path.suffix,
            "text_length": len(text_content),
        },
    )


def load_documents_from_directory(
    directory: Path,
    extensions: list[str] | None = None,
) -> list[InsuranceDocument]:
    """Load all documents from a directory (recursive).

    Args:
        directory: Root directory to scan.
        extensions: File extensions to include. Defaults to [".pdf", ".txt"].

    Returns:
        List of loaded InsuranceDocument objects.
    """
    if extensions is None:
        extensions = [".pdf", ".txt"]

    directory = Path(directory)
    if not directory.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")

    documents = []
    for ext in extensions:
        for file_path in sorted(directory.rglob(f"*{ext}")):
            try:
                doc = load_document(file_path)
                documents.append(doc)
            except Exception as e:
                # Log but don't fail on individual document errors
                print(f"Warning: Failed to load {file_path}: {e}")

    return documents
