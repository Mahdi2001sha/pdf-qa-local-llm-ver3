"""Manual test tool: turn a PDF (typed or scanned) into text and write a report you can read.

Uses the same modules as the app (pdf_reader -> ocr_reader, then text_chunker) but no LLM
and nothing is written to logs/. Run it with Test_PDF.bat (drag a PDF onto it, or double-click).
The report shows every page image next to the text that was read from it.
"""
import base64
import html
import logging
import os
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):      # never crash on Persian text in a Windows console
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import pymupdf

from config import BASE_DIR
from pdf_reader import PDFReadError, read_pdf
from text_chunker import chunk_pages

OUTPUT_DIR = BASE_DIR / "test_output"
PREVIEW_DPI = 80           # size of the page pictures in the report
MAX_PREVIEW_PAGES = 50     # pictures for the first 50 pages only (keeps the report small)
SHORT_TEXT_CHARS = 30      # pages with less text than this are flagged

CSS = """
:root { color-scheme: light dark; --line: #c9d0da; --muted: #667085; --ok: #1b7a43;
        --warn: #9a6200; --bad: #b3261e; --accent: #0f6b63; }
body { font-family: "Segoe UI", Tahoma, system-ui, sans-serif; margin: 0; padding: 24px; line-height: 1.6; }
h1 { font-size: 1.25rem; margin: 0 0 4px; }
.meta { color: var(--muted); margin-bottom: 16px; }
.warn { border: 1px solid var(--warn); color: var(--warn); padding: 8px 12px; border-radius: 6px; margin: 8px 0; }
.page { border: 1px solid var(--line); border-radius: 6px; margin: 16px 0; overflow: hidden; }
.page > header { display: flex; justify-content: space-between; padding: 8px 12px;
                 border-bottom: 1px solid var(--line); font-weight: 600; }
.typed { color: var(--ok); } .ocr { color: var(--accent); } .short { color: var(--warn); } .none { color: var(--bad); }
.cols { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.cols > div { padding: 12px; min-width: 0; }
.cols > div + div { border-left: 1px solid var(--line); }
.cols h2 { font-size: .8rem; color: var(--muted); margin: 0 0 8px; font-weight: 600; }
img { max-width: 100%; height: auto; border: 1px solid var(--line); }
.line { white-space: pre-wrap; word-break: break-word; min-height: 1.6em; }
@media (max-width: 800px) { .cols { grid-template-columns: 1fr; }
  .cols > div + div { border-left: 0; border-top: 1px solid var(--line); } }
"""


class _WarningCollector(logging.Handler):
    """Collects warnings that the reading modules log (for example 'OCR skipped')."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record):
        message = record.getMessage()
        if message not in self.messages:
            self.messages.append(message)


def check_pdf(path: Path):
    """Return an error text if the file cannot be tested, else None."""
    if not path.is_file():
        return "File not found."
    with open(path, "rb") as f:
        head = f.read(1024)
    if not head.lstrip().startswith(b"%PDF"):
        return "This does not look like a PDF file."
    return None


def render_previews(path: Path) -> dict[int, str]:
    """Small JPEG of each page (as data URIs) so the report is one self-contained file."""
    previews = {}
    try:
        with pymupdf.open(path) as doc:
            for number, page in enumerate(doc, start=1):
                if number > MAX_PREVIEW_PAGES:
                    break
                pix = page.get_pixmap(dpi=PREVIEW_DPI, alpha=False)
                try:
                    data = pix.tobytes("jpeg", jpg_quality=70)
                except TypeError:
                    data = pix.tobytes("jpeg")
                previews[number] = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
    except Exception:
        pass
    return previews


def page_status(page):
    """-> (css class, label) for one page."""
    if page is None:
        return "none", "No text found"
    if page["ocr"]:
        return "ocr", f"OCR - {len(page['text'])} characters"
    if len(page["text"]) < SHORT_TEXT_CHARS:
        return "short", f"Typed text - only {len(page['text'])} characters"
    return "typed", f"Typed text - {len(page['text'])} characters"


def build_html(info: dict) -> str:
    out = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width, initial-scale=1'>",
           f"<title>PDF reading test - {html.escape(info['name'])}</title><style>{CSS}</style></head><body>",
           f"<h1>PDF reading test: {html.escape(info['name'])}</h1>",
           f"<div class='meta'>{info['total']} pages &middot; {info['typed']} typed &middot; "
           f"{info['ocr']} read with OCR &middot; {info['empty']} without text &middot; "
           f"{info['chunks']} chunks &middot; {info['seconds']:.1f} s &middot; {info['when']}</div>"]
    for message in info["warnings"]:
        out.append(f"<div class='warn'>{html.escape(message)}</div>")

    for number in range(1, info["total"] + 1):
        page = info["by_no"].get(number)
        css, label = page_status(page)
        out.append(f"<section class='page'><header><span>Page {number}</span>"
                   f"<span class='{css}'>{html.escape(label)}</span></header><div class='cols'><div>"
                   "<h2>PAGE IMAGE</h2>")
        if number in info["previews"]:
            out.append(f"<img src='{info['previews'][number]}' alt='Page {number}'>")
        else:
            out.append("<div class='line'>(no picture for this page)</div>")
        out.append("</div><div><h2>TEXT THAT WAS READ</h2>")
        if page is None:
            out.append("<div class='line none'>(nothing was read from this page)</div>")
        else:
            for line in page["text"].split("\n"):   # dir=auto: each line gets its own direction
                out.append(f"<div class='line' dir='auto'>{html.escape(line) or '&nbsp;'}</div>")
        out.append("</div></div></section>")
    out.append("</body></html>")
    return "".join(out)


def build_txt(info: dict) -> str:
    lines = ["PDF reading test", f"File : {info['name']}", f"Date : {info['when']}",
             f"Pages: {info['total']} ({info['typed']} typed, {info['ocr']} OCR, {info['empty']} without text)",
             f"Time : {info['seconds']:.1f} s", ""]
    for message in info["warnings"]:
        lines.append(f"WARNING: {message}")
    for number in range(1, info["total"] + 1):
        page = info["by_no"].get(number)
        _css, label = page_status(page)
        lines += ["", f"========== Page {number} - {label} ==========",
                  page["text"] if page else "(nothing was read from this page)"]
    return "\n".join(lines) + "\n"


def open_file(path: Path):
    try:
        if os.name == "nt":
            os.startfile(str(path))
        else:
            webbrowser.open(path.as_uri())
    except Exception:
        pass


def test_one(path: Path, open_report: bool) -> bool:
    print("\n" + "=" * 60)
    print(f"File: {path.name}")
    problem = check_pdf(path)
    if problem:
        print(f"CANNOT TEST: {problem}")
        return False
    size_mb = path.stat().st_size / (1024 * 1024)

    collector = _WarningCollector()
    logging.getLogger().addHandler(collector)
    try:
        print("Step 1/2 - reading text (OCR is used for picture pages) ...")
        started = time.time()
        try:
            pages = read_pdf(path)
        except PDFReadError as exc:
            print(f"FAILED: {exc}")
            return False
        seconds = time.time() - started
    finally:
        logging.getLogger().removeHandler(collector)

    with pymupdf.open(path) as doc:
        total = doc.page_count
    by_no = {p["page"]: p for p in pages}
    ocr_count = sum(1 for p in pages if p["ocr"])
    empty = [n for n in range(1, total + 1) if n not in by_no]

    print("Step 2/2 - splitting into chunks ...")
    chunks = chunk_pages(pages)

    warnings = list(collector.messages)
    if empty:
        shown = ", ".join(map(str, empty[:20])) + (" ..." if len(empty) > 20 else "")
        warnings.append(f"No text was read from page(s): {shown}. They are blank, or pictures that could not be read.")
    short = [p["page"] for p in pages if not p["ocr"] and len(p["text"]) < SHORT_TEXT_CHARS]
    if short:
        warnings.append(f"Very little text on page(s): {', '.join(map(str, short[:20]))}. Compare with the page image.")
    if total > MAX_PREVIEW_PAGES:
        warnings.append(f"Page pictures are shown for the first {MAX_PREVIEW_PAGES} pages only.")

    info = {"name": path.name, "total": total, "typed": len(pages) - ocr_count, "ocr": ocr_count,
            "empty": len(empty), "chunks": len(chunks), "seconds": seconds, "by_no": by_no,
            "warnings": warnings, "previews": render_previews(path),
            "when": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    html_path = OUTPUT_DIR / f"{stamp}_{path.stem[:40]}.html"
    txt_path = OUTPUT_DIR / f"{stamp}_{path.stem[:40]}.txt"
    html_path.write_text(build_html(info), encoding="utf-8")
    txt_path.write_text(build_txt(info), encoding="utf-8-sig")   # BOM so Notepad shows Persian correctly

    print(f"\nPages: {total} ({info['typed']} typed text, {ocr_count} read with OCR, {len(empty)} without text)")
    print(f"Chunks that would go to the model: {len(chunks)}")
    print(f"Time: {seconds:.1f} s   Size: {size_mb:.1f} MB")
    for message in warnings:
        print(f"WARNING: {message}")
    print(f"\nReport (page image next to text): {html_path}")
    print(f"Plain text file                 : {txt_path}")
    if open_report:
        open_file(html_path)
    return True


def pick_file() -> str:
    """File-open window; falls back to typing a path if no window is possible."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        chosen = filedialog.askopenfilename(title="Choose a PDF to test",
                                            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        root.destroy()
        return chosen
    except Exception:
        return input("Paste the full path of a PDF (or press Enter to quit): ").strip().strip('"')


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    open_report = "--no-open" not in sys.argv
    paths = [Path(a) for a in args]

    while True:
        if not paths:
            chosen = pick_file()
            if not chosen:
                break
            paths = [Path(chosen)]
        for path in paths:
            test_one(path, open_report)
        paths = []
        try:
            answer = input("\nPress Enter to test another PDF, or type Q to quit: ").strip().lower()
        except EOFError:
            break
        if answer.startswith("q"):
            break


if __name__ == "__main__":
    main()
