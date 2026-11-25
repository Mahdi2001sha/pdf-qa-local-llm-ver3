"""Optional step - OCR for pages that are pictures (scanned PDFs).

Based on the Persian_OCR_Simple notebook: Tesseract (Persian + English) with the
same image clean-up (grayscale, contrast, sharpness), "--psm 3 --oem 3", and
parallel workers. Pages are rendered with PyMuPDF, so poppler / pdf2image are
not needed.

pytesseract and Pillow are imported only when a page really needs OCR, so typed
PDFs never load them. Tesseract itself is a separate program (see _INSTALL_HELP).
"""
import logging
import os
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pymupdf

from config import (MODELS_DIR, OCR_BATCH_SIZE, OCR_CONTRAST, OCR_DPI, OCR_LANGUAGES,
                    OCR_MAX_PAGES, OCR_MIN_IMAGE_COVERAGE, OCR_PAGE_TIMEOUT,
                    OCR_SHARPNESS, OCR_TESSERACT_CMD, OCR_TESSERACT_CONFIG, OCR_WORKERS)

log = logging.getLogger(__name__)

_INSTALL_HELP = (
    "Install Tesseract for Windows from https://github.com/UB-Mannheim/tesseract/wiki "
    "(tick Persian under Additional language data), or copy tesseract.exe into models/tesseract/."
)


class OCRError(Exception):
    """Raised when OCR is not installed, not usable, or the PDF is too long to OCR."""


_lang = None                      # e.g. "fas+eng" once Tesseract has been checked
_lang_lock = threading.Lock()


def page_looks_scanned(page) -> bool:
    """True when pictures cover a big part of the page (a scan, not a logo)."""
    try:
        page_area = page.rect.width * page.rect.height
        if page_area <= 0:
            return False
        covered = 0.0
        for info in page.get_image_info():
            part = pymupdf.Rect(info["bbox"]) & page.rect
            if not part.is_empty:
                covered += part.width * part.height
        return covered / page_area >= OCR_MIN_IMAGE_COVERAGE
    except Exception:
        return False


def _find_tesseract():
    """Look for tesseract: env var, config, models/tesseract, PATH, default Windows folders."""
    exe = "tesseract.exe" if os.name == "nt" else "tesseract"
    for candidate in (os.getenv("TESSERACT_CMD", ""), OCR_TESSERACT_CMD,
                      str(MODELS_DIR / "tesseract" / exe)):
        if candidate and Path(candidate).is_file():
            return candidate
    on_path = shutil.which("tesseract")
    if on_path:
        return on_path
    if os.name == "nt":
        bases = [os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"),
                 os.path.join(os.getenv("LOCALAPPDATA", ""), "Programs")]
        for base in bases:
            if base:
                path = Path(base) / "Tesseract-OCR" / "tesseract.exe"
                if path.is_file():
                    return str(path)
    return None


def _prepare_engine() -> str:
    """Find Tesseract and return the language string to use. Only successes are cached."""
    global _lang
    with _lang_lock:
        if _lang:
            return _lang
        try:
            import pytesseract
            from PIL import Image  # noqa: F401  (checks that Pillow is installed too)
        except ImportError as exc:
            raise OCRError(
                "OCR packages are not installed. Run Start.bat again to install them "
                "(or: pip install -r backend/requirements-ocr.txt)."
            ) from exc

        exe = _find_tesseract()
        if not exe:
            raise OCRError("Tesseract OCR was not found. " + _INSTALL_HELP)
        pytesseract.pytesseract.tesseract_cmd = exe

        # optional: language files kept inside the project
        local_data = MODELS_DIR / "tessdata"
        if (local_data / "fas.traineddata").is_file():
            os.environ["TESSDATA_PREFIX"] = str(local_data)

        try:
            available = set(pytesseract.get_languages(config=""))
        except Exception as exc:
            raise OCRError(f"Tesseract was found but could not be started: {exc}") from exc

        if "fas" in OCR_LANGUAGES and "fas" not in available:
            raise OCRError(
                "Tesseract has no Persian language data (fas.traineddata). Re-run the Tesseract "
                "installer and tick Persian, or put fas.traineddata and eng.traineddata "
                "(from https://github.com/tesseract-ocr/tessdata_best) into models/tessdata/."
            )
        wanted = [code for code in OCR_LANGUAGES if code in available]
        if not wanted:
            raise OCRError(f"None of the OCR languages {OCR_LANGUAGES} are installed in Tesseract.")
        missing = [code for code in OCR_LANGUAGES if code not in available]
        if missing:
            log.warning("Tesseract is missing language data for %s; OCR will use %s only.",
                        missing, wanted)
        _lang = "+".join(wanted)
        return _lang


def _render_page(page):
    """Render one page to a grayscale PIL image (PyMuPDF replaces pdf2image + poppler)."""
    from PIL import Image
    pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY, alpha=False)
    return Image.frombytes("L", (pix.width, pix.height), pix.samples)


def _ocr_image(image, lang: str) -> str:
    """Same clean-up as the notebook (contrast, sharpness), then Tesseract."""
    import pytesseract
    from PIL import ImageEnhance
    image = ImageEnhance.Contrast(image).enhance(OCR_CONTRAST)
    image = ImageEnhance.Sharpness(image).enhance(OCR_SHARPNESS)
    return pytesseract.image_to_string(
        image, lang=lang, config=OCR_TESSERACT_CONFIG, timeout=OCR_PAGE_TIMEOUT
    ).strip()


def ocr_pages(doc, page_numbers: list[int]) -> list[dict]:
    """OCR the given 1-based pages. Returns [{'page': n, 'text': '...'}, ...] in page order."""
    if len(page_numbers) > OCR_MAX_PAGES:
        raise OCRError(
            f"{len(page_numbers)} pages need OCR but the limit is {OCR_MAX_PAGES}. "
            "Raise OCR_MAX_PAGES in backend/config.py."
        )
    lang = _prepare_engine()

    results = []
    with ThreadPoolExecutor(max_workers=OCR_WORKERS) as pool:
        for start in range(0, len(page_numbers), OCR_BATCH_SIZE):
            batch = page_numbers[start:start + OCR_BATCH_SIZE]
            jobs = {}
            for number in batch:  # PyMuPDF is not thread-safe: render here, OCR in the workers
                try:
                    image = _render_page(doc[number - 1])
                except Exception as exc:
                    raise OCRError(f"Could not render page {number}: {exc}") from exc
                jobs[pool.submit(_ocr_image, image, lang)] = number
            for job in as_completed(jobs):
                number = jobs[job]
                try:
                    text = job.result()
                except Exception as exc:
                    raise OCRError(f"OCR failed on page {number}: {exc}") from exc
                if text:
                    results.append({"page": number, "text": text})
    results.sort(key=lambda r: r["page"])
    return results
