#!/usr/bin/env python3
"""
Mini Calligraphr-style app using Handwrite + Flask.

Features:
- Downloads the official Handwrite template PDF on first run.
- Serves a page where you can:
    * Download the template
    * Upload a scanned/photographed filled sheet
- Runs the `handwrite` CLI to generate a .ttf font and returns it.

Usage:
    1. Install deps:
        pip install flask requests handwrite
        # plus FontForge via your OS package manager

    2. Run:
        python app.py

    3. Open http://127.0.0.1:5000 in your browser.
"""

import subprocess
from pathlib import Path

import requests
from flask import Flask, request, send_file, render_template

# Official template from the Handwrite repo
TEMPLATE_URL = (
    "https://raw.githubusercontent.com/"
    "yashlamba/handwrite/dev/handwrite_sample.pdf"
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
UPLOAD_DIR = BASE_DIR / "uploads"
FONT_DIR = BASE_DIR / "fonts"
TEMPLATE_PATH = STATIC_DIR / "handwrite_template.pdf"

app = Flask(__name__, template_folder=str(BASE_DIR), static_folder=str(STATIC_DIR))


def ensure_dirs() -> None:
    """Create required directories."""
    for d in (STATIC_DIR, UPLOAD_DIR, FONT_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ensure_template() -> None:
    """
    Download the Handwrite sample template if it's not already present.
    """
    if TEMPLATE_PATH.exists():
        return

    print(f"[INFO] Downloading template from {TEMPLATE_URL} ...")
    resp = requests.get(TEMPLATE_URL, timeout=30)
    resp.raise_for_status()
    TEMPLATE_PATH.write_bytes(resp.content)
    print(f"[INFO] Saved template to {TEMPLATE_PATH}")


def run_handwrite_on_scan(scan_path: Path) -> Path:
    """
    Run the `handwrite` CLI on the uploaded scan and return the .ttf path.

    The `handwrite` CLI signature (from handwrite.cli:main) is roughly:

        handwrite INPUT_PATH OUTPUT_DIR
            [--directory WORK_DIR]
            [--config CONFIG_JSON]
            [--filename FONT_BASENAME]
            [--family FAMILY_NAME]
            [--style STYLE_NAME]

    We set `--filename` so we know the resulting .ttf name.
    """
    scan_path = scan_path.resolve()
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    font_basename = scan_path.stem  # e.g. "my_scan"
    output_ttf = FONT_DIR / f"{font_basename}.ttf"

    cmd = [
        "handwrite",
        str(scan_path),           # input sample sheet (PNG/JPG/PDF)
        str(FONT_DIR),            # directory to put font into
        "--filename",
        font_basename,            # base name for the font file
        "--family",
        font_basename,            # family name inside the font
        "--style",
        "Regular",                # style name
    ]

    print(f"[INFO] Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise RuntimeError(
            "The `handwrite` CLI is not in PATH. "
            "Did you run `pip install handwrite`?"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"`handwrite` failed with exit code {e.returncode}") from e

    if not output_ttf.exists():
        # Fallback: if something changed in handwrite, list the FONT_DIR contents
        candidates = list(FONT_DIR.glob("*.ttf"))
        if not candidates:
            raise RuntimeError(
                "Font generation seemed to run, but no .ttf file was found "
                f"in {FONT_DIR}"
            )
        # Just pick the most recently modified .ttf
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return candidates[0]

    return output_ttf


@app.route("/", methods=["GET"])
def index():
    return render_template("font_page.html")


@app.route("/template", methods=["GET"])
def template_pdf():
    """
    Serve the template PDF for download.
    """
    return send_file(
        TEMPLATE_PATH,
        as_attachment=True,
        download_name="handwrite_template.pdf",
        mimetype="application/pdf",
    )


@app.route("/upload", methods=["POST"])
def upload_scan():
    """
    Accept an uploaded scan and return the generated .ttf.
    """
    file = request.files.get("scan")
    if not file or file.filename == "":
        return "No file uploaded", 400

    # Save uploaded file
    safe_name = file.filename.replace("/", "_").replace("\\", "_")
    dest_path = UPLOAD_DIR / safe_name
    file.save(dest_path)

    try:
        font_path = run_handwrite_on_scan(dest_path)
    except Exception as e:
        # In a real app, log the traceback; here we just return the message.
        return f"Error while generating font: {e}", 500

    # Return the TTF for download
    return send_file(
        font_path,
        as_attachment=True,
        download_name=font_path.name,
        mimetype="font/ttf",
    )


if __name__ == "__main__":
    ensure_dirs()
    ensure_template()
    app.run(host="127.0.0.1", port=5000, debug=True)
