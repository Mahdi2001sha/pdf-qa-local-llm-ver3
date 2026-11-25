"""Step 2 - Read the text of a PDF, page by page.

Typed pages are read directly. Pages that are only a picture (scanned pages)
are sent to ocr_reader.py when OCR support is installed.
"""
import logging
import re
from pathlib import Path

import pymupdf  # PyMuPDF

import ocr_reader
from config import OCR_MIN_TEXT_CHARS

log = logging.getLogger(__name__)


class PDFReadError(Exception):
    """Raised when text cannot be extracted."""


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_pdf(path: Path) -> list[dict]:
    """Return [{'page': 1, 'text': '...', 'ocr': False}, ...] (empty pages are skipped)."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise PDFReadError("Could not open the PDF. The file may be damaged.") from exc

    try:
        if doc.needs_pass:
            raise PDFReadError("The PDF is password protected.")

        texts: dict[int, str] = {}
        ocr_done: set[int] = set()
        needs_ocr: list[int] = []

        for number, page in enumerate(doc, start=1):
            text = _clean(page.get_text("text"))
            if text:
                texts[number] = text
            # almost no text + big picture on the page = scanned page
            if len(text) < OCR_MIN_TEXT_CHARS and ocr_reader.page_looks_scanned(page):
                needs_ocr.append(number)

        if needs_ocr:
            try:
                for item in ocr_reader.ocr_pages(doc, needs_ocr):
                    ocr_text = _clean(item["text"])
                    if ocr_text:
                        page_no = item["page"]
                        texts[page_no] = (texts.get(page_no, "") + "\n" + ocr_text).strip()
                        ocr_done.add(page_no)
            except ocr_reader.OCRError as exc:
                if not texts:  # nothing readable at all -> tell the user why
                    raise PDFReadError(str(exc)) from exc
                # typed PDF with a few picture pages: keep the text we have
                log.warning("OCR skipped: %s", exc)
    finally:
        doc.close()

    if not texts:
        raise PDFReadError("No readable text was found in this PDF.")

    return [{"page": n, "text": texts[n], "ocr": n in ocr_done} for n in sorted(texts)]
