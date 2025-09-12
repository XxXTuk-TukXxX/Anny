from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("Usage: legacy_preview_runner.py <pdf_path> <annotations_json>", file=sys.stderr)
        return 2
    pdf_path = Path(argv[1]).resolve()
    ann_json = Path(argv[2]).resolve()
    if not pdf_path.exists() or not ann_json.exists():
        print("Input paths do not exist", file=sys.stderr)
        return 2

    # Lazy import to avoid Tk dependency unless invoked
    import tkinter as tk
    from preview_tk import PDFPreviewApp

    root = tk.Tk()
    app = PDFPreviewApp(root, str(pdf_path), str(ann_json))
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

