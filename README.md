# PDF Q&A (typed PDFs)

Upload a typed PDF, ask questions, get answers from a local LLM.
Every question and answer is saved to a CSV, and every uploaded PDF is saved as a version.

## Run
1. Install **Python 3.10+** (tick "Add to PATH") and **Ollama** (https://ollama.com/download).
2. Double-click `Start.bat`.
   First run creates a virtual environment, installs packages and downloads the models
   (several GB), so it takes a while. The browser opens automatically.

## Test how PDFs are read (no LLM needed)
Double-click `Test_PDF.bat` (or drag a PDF onto it). It reads the PDF with the same modules as the app
(typed text, OCR for picture pages, chunking) and opens a report in your browser that shows **each page image
next to the text that was read**, so you can check by eye whether it is correct. A plain `.txt` copy is saved too.
Reports go to `test_output/` (not committed to Git).

## Folders
| Folder      | Purpose |
|-------------|---------|
| `models/`   | Local models (Ollama stores them here) |
| `logs/`     | `pdfs/` = saved version of each uploaded PDF, `qa_log.csv` = questions + answers |
| `frontend/` | Plain HTML / CSS / JS page |
| `backend/`  | Python (FastAPI). One file per task |

## Backend files
| File | Task |
|------|------|
| `config.py` | All settings (paths, model names, chunk size) |
| `pdf_loader.py` | Receive + validate the upload, save a versioned copy |
| `pdf_reader.py` | Extract text page by page (PyMuPDF) |
| `ocr_reader.py` | OCR for scanned (picture) pages, Persian + English (Tesseract, based on the Persian_OCR_Simple notebook) |
| `text_chunker.py` | Split text into overlapping chunks |
| `retriever.py` | Find the chunks relevant to the question |
| `llm_client.py` | Talk to the LLM (Ollama) |
| `qa_service.py` | Build the prompt and get the answer |
| `qa_logger.py` | Write the Q&A CSV |
| `main.py` | API + serves the frontend; connects all of the above |

## Notes
- Scanned pages are read with OCR (Tesseract, Persian + English). Typed pages are read directly; only pages with almost no text and a large picture are OCR'd. `Start.bat` installs the Python packages (`pytesseract`, `Pillow`) on first run, but **Tesseract itself must be installed once**: https://github.com/UB-Mannheim/tesseract/wiki (tick *Persian* under Additional language data). Alternatively copy `tesseract.exe` into `models/tesseract/` and `fas.traineddata` + `eng.traineddata` into `models/tessdata/`. OCR settings (DPI, workers, contrast, limits) are the `OCR_*` lines in `backend/config.py`.
- `Start.bat` uses Ollama on port 5005 (not the default 11434, which Windows can block); it reuses a running Ollama or starts one. By default it reuses the models already installed in `%USERPROFILE%\.ollama\models`; see the top of `Start.bat` to store models in `models/` instead.
- Downloads need access to registry.ollama.ai (a VPN may be needed on some networks). Without `bge-m3` the app still works using keyword search.
- To use a smaller/faster model, change `LLM_MODEL` in `Start.bat` (e.g. `qwen2.5:3b`) and in `backend/config.py`.
