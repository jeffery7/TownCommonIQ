"""Extracts text from PDF documents using OCR when direct extraction fails.

pypdf can extract text from PDFs that were created digitally (Word exports,
web-generated documents).  Older government records are often scanned images
saved as PDF, so pypdf returns empty strings for them.  This module converts
those pages to images via pdf2image (which calls pdftoppm from poppler-utils)
and runs them through Tesseract to recover the text.

Extracted text is cached in a sidecar .txt file alongside the PDF so repeated
calls do not re-OCR the same document.
"""
import io
import logging
from pathlib import Path

from pdf2image import convert_from_bytes
from pypdf import PdfReader
import pytesseract

_logger = logging.getLogger(__name__)

_SIDECAR_SUFFIX = '_text.txt'
_MAX_OCR_PAGES = 5
_DPI = 200  # lower DPI is faster; sufficient for typical government documents


def _sidecar_path(pdf_path: Path) -> Path:
    """Return the path where extracted text is cached alongside the PDF."""
    return pdf_path.parent / (pdf_path.stem + _SIDECAR_SUFFIX)


def _read_pdf_pages(pdf_bytes: bytes) -> str:
    """Extract text from each page using pypdf and join the results."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    parts = []
    for page in reader.pages[:_MAX_OCR_PAGES]:
        parts.append(page.extract_text() or '')
    return '\n'.join(parts).strip()


def _extract_with_pypdf(pdf_bytes: bytes, pdf_path: Path) -> str:
    """Try to pull text directly from a digital PDF; return '' for scanned ones."""
    try:
        return _read_pdf_pages(pdf_bytes)
    except Exception:
        _logger.warning('pypdf text extraction failed for %s', pdf_path, exc_info=True)
        return ''


def _rasterise_pdf(pdf_bytes: bytes) -> str:
    """Convert pages to images and run Tesseract on each."""
    images = convert_from_bytes(
        pdf_bytes,
        dpi=_DPI,
        first_page=1,
        last_page=_MAX_OCR_PAGES,
    )
    parts = [pytesseract.image_to_string(img) for img in images]
    return '\n'.join(parts).strip()


def _ocr_pages(pdf_bytes: bytes, pdf_path: Path) -> str:
    """Rasterise the first few PDF pages and run Tesseract on them."""
    try:
        return _rasterise_pdf(pdf_bytes)
    except Exception:
        _logger.warning(
            'OCR failed for %s — check that Tesseract and Poppler are installed and on PATH',
            pdf_path, exc_info=True,
        )
        return ''


def extract_text(pdf_path: Path, use_cache: bool = True) -> str:
    """Return the text content of a PDF, using OCR if direct extraction fails.

    Saves the result to a sidecar .txt file on first extraction so subsequent
    calls return immediately without re-running Tesseract.  Pass
    use_cache=False to force re-extraction (e.g. after a Tesseract upgrade).
    """
    sidecar = _sidecar_path(pdf_path)
    if use_cache and sidecar.exists():
        return sidecar.read_text()

    pdf_bytes = pdf_path.read_bytes()
    text = _extract_with_pypdf(pdf_bytes, pdf_path)
    if not text:
        text = _ocr_pages(pdf_bytes, pdf_path)

    if text:
        sidecar.write_text(text)
    return text
