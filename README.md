# Annotator (Anny)

AI‑assisted PDF OCR and annotation tool. Convert PDFs to searchable text, generate or import highlights with margin notes, preview exact placement, and export a clean annotated PDF.

## Features
- OCR: Uses OCRmyPDF + Tesseract to make PDFs searchable.
- AI annotations (optional): Generate quotes + one‑line notes and a consistent color via Google Gemini.
- Exact layout: Places highlights and margin notes without covering text; supports leaders and rotation.
- Live preview: Drag/resize note boxes, edit text, tweak colors/fonts; export what you see.
- Modern UI: Web UI via PyWebView (fallback to Tk wizard if needed).

## Requirements
- Python 3.10+
- Tesseract OCR installed and on PATH
  - Windows: Install the UB Mannheim build (recommended) or any official Tesseract build, then ensure `tesseract.exe` is on PATH.
  - macOS: `brew install tesseract`
  - Linux (Debian/Ubuntu): `sudo apt-get install tesseract-ocr`

Python packages are listed in `requirements.txt`.

## Quickstart
1. Create a virtual environment and install dependencies
   - Windows (PowerShell)
     - `python -m venv .venv`
     - `.venv\\Scripts\\Activate.ps1`
     - `pip install -r requirements.txt`
   - macOS/Linux
     - `python3 -m venv .venv`
     - `source .venv/bin/activate`
     - `pip install -r requirements.txt`
2. (Optional) Set up Gemini for AI annotations
   - Create `.env` in the project root with one of:
     - `GOOGLE_API_KEY=your_api_key_here`  (recommended)
     - or `GEMINI_API_KEY=your_api_key_here`
   - Never commit real API keys. The app loads `.env` automatically.
3. Run the app
   - `python main.py`
   - By default, the modern web UI opens. To force the legacy Tk UI, set `ANNOTATE_USE_MODERN=0` in your environment.

## Workflow
- Step 1: OCR
  - Choose a PDF, set options (language, deskew, clean background), and run OCR. You may also skip OCR if your PDF already contains text.
  - If Tesseract is not on PATH, you can browse to its executable in the UI.
- Step 2: Annotations
  - JSON file: Select an annotations JSON you created before, or
  - Gemini AI: Enter an objective (e.g., “Highlight scientific evidence”), pick a model (default `gemini-2.5-flash`), and generate a JSON next to your PDF.
- Step 3: Preview & Export
  - Inspect exact placements, drag/resize boxes, rotate notes, adjust text and colors, and export to a final annotated PDF.

## Annotations JSON format
The app accepts a JSON array with the following fields per item:

```
[
  {
    "quote": "Exact substring copied verbatim from the PDF text",
    "explanation": "Short note explaining why it matters",
    "color": "#A5D6A7"
  }
]
```

Notes:
- `quote` must appear verbatim in the PDF text (after OCR, if used).
- `color` should be a 7‑char hex like `#RRGGBB`. If omitted, a fallback color is used.
- The tool also tolerates `query` in place of `quote` for compatibility.

## Configuration
- Settings live in the web UI’s Settings page and include:
  - Note width, minimum width, font size, text color
  - Optional fill/border/border width and leader line color
  - Placement options (side, center gutter tolerance, max scan/offsets)
  - Font name/file (TTF/OTF). Default font files are under `fonts/`.
- Defaults are defined in `frontend/defaults.py`.

## Building a standalone app (optional)
- Install PyInstaller: `pip install pyinstaller`
- Use the provided spec (Windows UI app without console):
  - `pyinstaller Anny.spec`  (produces `dist/Anny.exe`)
  - or `pyinstaller Annotator.spec`

## Troubleshooting
- Tesseract not found
  - Ensure Tesseract is installed and available on PATH, or set the explicit path in Step 1.
- OCR errors
  - Some PDFs are image‑heavy or encrypted. Try enabling Force OCR or disabling Clean Background.
- Gemini errors
  - Confirm a valid API key in `.env`. Network access is required. The default model is `gemini-2.5-flash`.
- PyMuPDF import error referencing `fitz`
  - Uninstall the wrong `fitz` and install PyMuPDF: `pip uninstall -y fitz && pip install -U pymupdf`.

## Project structure
- `main.py`: App entry. Web UI (PyWebView) with fallback to Tk.
- `UI.py` + `frontend/step1.py, step2.py, step3.py`: Legacy Tk wizard and logic.
- `frontend/web/`: HTML/JS for the modern UI.
- `frontend/backend.py`: OCR pipeline wrapper around OCRmyPDF.
- `highlights.py`: Core engine for highlights and margin note placement.
- `models/gemini_annotaton.py`: Gemini integration to generate annotations JSON.
- `fonts/`: Default fonts for note rendering.

## License
No license provided yet. 

