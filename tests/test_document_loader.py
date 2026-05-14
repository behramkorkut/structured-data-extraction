"""Tests for document_loader module."""

from pathlib import Path

import pytest

from src.structured_extraction.document_loader import (
    InsuranceDocument,
    detect_document_type,
    detect_product_line,
    load_document,
    load_text_from_file,
)

# --- Document type detection ---


class TestDetectDocumentType:
    """Tests for detect_document_type function."""

    @pytest.mark.parametrize(
        "filename, expected_type",
        [
            ("SP24FCR0103 IPID API Santé Equilibre - MAJ- 052024.pdf", "ipid"),
            ("IPID APICIL Accident_AM_SP18FCR0560_2024.pdf", "ipid"),
            ("BG API Santé - Equilibre 1 avec PC MAJ 12.2025.pdf", "guarantee_table"),
            (
                "Barème de garanties API Santé - Equilibre MAJ 12.2025 paysage.pdf",
                "guarantee_table",
            ),
            ("Essentio_ Barème Garanties APICIL_20251021.pdf", "guarantee_table"),
            ("SP23-FCR0100 Fiche produit API Santé Equilibre 202403.pdf", "product_sheet"),
            ("Fiche produit POG_APICIL M_APICIL Accident_V052021_V3 - 2024.pdf", "product_sheet"),
            ("APICIL ACCIDENT - Cotisations 2025.pdf", "pricing"),
            ("APICIL GARANTIE HOSPITALISATION - Cotisations 2025.pdf", "pricing"),
            (
                "API SANTE EQUILIBRE Niveaux 1 à 6_Rbst 2026 UNOCAM_RG.pdf",
                "reimbursement_example",
            ),
            ("M 047-01 NI Api Santé (01-25).pdf", "information_notice"),
            ("Plaquette API Santé Particulier.pdf", "commercial_brochure"),
            ("random_document.pdf", "unknown"),
        ],
    )
    def test_detect_document_type(self, filename: str, expected_type: str):
        assert detect_document_type(filename) == expected_type

    def test_detect_document_type_case_insensitive(self):
        assert detect_document_type("IPID_test.pdf") == "ipid"
        assert detect_document_type("ipid_test.pdf") == "ipid"

    def test_detect_document_type_unknown_returns_unknown(self):
        assert detect_document_type("something_else.pdf") == "unknown"


# --- Product line detection ---


class TestDetectProductLine:
    """Tests for detect_product_line function."""

    @pytest.mark.parametrize(
        "filename, expected_line",
        [
            ("BG API Santé - Equilibre 1 avec PC MAJ 12.2025.pdf", "API Santé Equilibre"),
            ("BG API Santé-Sérénité 1 avec PC MAJ 12.2025.pdf", "API Santé Sérénité"),
            ("Essentio_ Barème Garanties APICIL_20251021.pdf", "APICIL Essentio"),
            ("APICIL ACCIDENT - Cotisations 2025.pdf", "APICIL Accident"),
            (
                "SP25FCR0325 - IPID APICIL Protection Décès.pdf",
                "APICIL Protection Décès",
            ),
            ("M 044-04 Tandem (07-25).pdf", "APICIL Tandem"),
            (
                "APICIL GARANTIE HOSPITALISATION - Cotisations 2025.pdf",
                "Garantie Hospitalisation",
            ),
        ],
    )
    def test_detect_product_line(self, filename: str, expected_line: str):
        assert detect_product_line(filename) == expected_line

    def test_detect_product_line_unknown_returns_none(self):
        assert detect_product_line("random_document.pdf") is None


# --- Text loading ---


class TestLoadTextFromFile:
    """Tests for load_text_from_file function."""

    def test_load_txt_file(self, tmp_path: Path):
        """Test loading a plain text file."""
        txt_file = tmp_path / "test_doc.txt"
        txt_file.write_text("Line 1\nLine 2\nLine 3", encoding="utf-8")

        text, page_count = load_text_from_file(txt_file)
        assert "Line 1" in text
        assert page_count == 1  # No form feeds = 1 page

    def test_load_txt_file_with_page_breaks(self, tmp_path: Path):
        """Test that form feeds are counted as page breaks."""
        txt_file = tmp_path / "multi_page.txt"
        txt_file.write_text("Page 1\fPage 2\fPage 3", encoding="utf-8")

        text, page_count = load_text_from_file(txt_file)
        assert page_count == 3

    def test_load_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_text_from_file(Path("/nonexistent/file.txt"))

    def test_load_unsupported_format_raises(self, tmp_path: Path):
        docx_file = tmp_path / "test.docx"
        docx_file.write_text("test", encoding="utf-8")

        with pytest.raises(ValueError, match="Unsupported file format"):
            load_text_from_file(docx_file)


# --- Full document loading ---


class TestLoadDocument:
    """Tests for load_document function."""

    def test_load_document_txt(self, tmp_path: Path):
        """Test loading a full document from a .txt file."""
        txt_file = tmp_path / "IPID API Santé Equilibre test.txt"
        txt_file.write_text("Assurance complémentaire santé\nGaranties optique", encoding="utf-8")

        doc = load_document(txt_file)

        assert isinstance(doc, InsuranceDocument)
        assert doc.document_type == "ipid"
        assert doc.product_line == "API Santé Equilibre"
        assert "Assurance complémentaire santé" in doc.text_content
        assert doc.metadata["source_extension"] == ".txt"
        assert doc.metadata["text_length"] > 0

    def test_load_document_preserves_path(self, tmp_path: Path):
        """Test that the original file path is preserved."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("content", encoding="utf-8")

        doc = load_document(txt_file)
        assert doc.file_path == txt_file
        assert doc.file_name == "test"
