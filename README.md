# Annotator (Anny)

AI‑assisted PDF OCR and annotation tool. Convert PDFs to searchable text, generate or import highlights with margin notes, preview exact placement, and export a clean annotated PDF.

## Features
- OCR: Uses OCRmyPDF + Tesseract to make PDFs searchable.
- AI annotations (optional): Generate quotes + one‑line notes and a consistent color via Google Gemini.
- Exact layout: Places highlights and margin notes without covering text; supports leaders and rotation.
- Live preview: Drag/resize note boxes, edit text, tweak colors/fonts; export what you see.
- Modern UI: Web UI via PyWebView (fallback to Tk wizard if needed).

## Installer
### Windows:
- Download the latest setup bundle from the Releases page (grab the most recent `.exe`).
- Run the installer; it places Anny under `C:\Program Files\Anny` by default.
- If Search or the Start menu can't find the shortcut, launch `C:\Program Files\Anny\anny.exe` directly.
- You can right-click `anny.exe` to pin it to Start, Taskbar, or create a desktop shortcut.

### Gemini API:
If you want to use the built-in Gemini AI, request an API key at https://aistudio.google.com/app/apikey and paste it into the Settings screen after installation.
<img width="1099" height="851" alt="883F3D99-8E3A-42F9-A53C-5F912DB84564" src="https://github.com/user-attachments/assets/3f223b28-e332-405d-b55d-2493dd529452" />

<img width="1100" height="383" alt="1F14BD7C-8E72-4867-9DFF-B7D4797FB360" src="https://github.com/user-attachments/assets/66d82285-3053-4a05-911d-509e4f3f0562" />



## Quickstart
### Requirements
- Python 3.10+
- Tesseract OCR installed and on PATH
  - Windows: Install the UB Mannheim build (recommended) or any official Tesseract build, then ensure `tesseract.exe` is on PATH.
  - macOS: `brew install tesseract`
  - Linux (Debian/Ubuntu): `sudo apt-get install tesseract-ocr`

Python packages are listed in `requirements.txt`.
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
   - Or run as a local Flask web app: `PORT=5001 python flask_app.py` then open http://localhost:5001/ in your browser. (Flask mode is single-user and intended for local use only.)

### Deploying to Railway (web)
- Railway runs in a headless Linux container, so the desktop UI (`pywebview` / GTK / Qt) cannot start there.
- This repo includes a `Procfile` that starts the Flask app with Gunicorn:
  - `web: gunicorn flask_app:app --bind 0.0.0.0:${PORT:-5000}`
- If you previously set Railway’s Start Command to `python main.py`, change it to `gunicorn flask_app:app --bind 0.0.0.0:$PORT`.
- OCR requires system dependencies (Tesseract + Ghostscript).
  - If you use Railway’s Nixpacks builder, this repo includes `nixpacks.toml`; redeploy after adding it.
  - If you use Railway’s Railpack builder (log shows “Railpack”), it ignores `nixpacks.toml`. Use the provided `Dockerfile` and switch the service to Dockerfile builder.

### Building a standalone app (optional)
- Install PyInstaller: `pip install pyinstaller`
- Use the provided spec (Windows UI app without console):
  - `pyinstaller Anny.spec`  (produces `dist/Anny.exe`)
  - or `pyinstaller Annotator.spec`

## Configuration
- Settings live in the web UI’s Settings page and include:
  - Note width, minimum width, font size, text color
  - Optional fill/border/border width and leader line color
  - Placement options (side, center gutter tolerance, max scan/offsets)
  - Font name/file (TTF/OTF). Default font files are under `fonts/`.
<img width="960" height="885" alt="Screenshot 2025-09-19 at 14 35 43" src="https://github.com/user-attachments/assets/300b109f-e438-4215-aaf3-f647a144bc8d" />

- Defaults are defined in `frontend/defaults.py`.


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

### Workflow
- Step 1: OCR
  - Choose a PDF, set options (language, deskew, clean background), and run OCR. You may also skip OCR if your PDF already contains text.
  - If Tesseract is not on PATH, you can browse to its executable in the UI.
- Step 2: Annotations
  - JSON file: Select an annotations JSON you created before, or
  - Gemini AI: Enter an objective (e.g., “Highlight scientific evidence”), pick a model (default `gemini-2.5-flash`), and generate a JSON next to your PDF.
- Step 3: Preview & Export
  - Inspect exact placements, drag/resize boxes, rotate notes, adjust text and colors, and export to a final annotated PDF.

### Annotations JSON format
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

## License
No license provided yet. 
