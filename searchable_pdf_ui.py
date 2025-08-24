# ocr_gui.py
# Frontend (Tkinter GUI) for selecting a PDF and running OCR using ocr_backend.

from __future__ import annotations

import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from searchable_pdf import run_ocr  # <-- backend import


class OCRApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF OCR (searchable PDF)")
        self.geometry("560x300")
        self.resizable(False, False)

        pad = {"padx": 8, "pady": 6}

        # Input
        tk.Label(self, text="Input PDF:").grid(row=0, column=0, sticky="e", **pad)
        self.input_var = tk.StringVar()
        tk.Entry(self, textvariable=self.input_var, width=52).grid(row=0, column=1, **pad)
        ttk.Button(self, text="Browse...", command=self.browse_input).grid(row=0, column=2, **pad)

        # Output
        tk.Label(self, text="Output PDF:").grid(row=1, column=0, sticky="e", **pad)
        self.output_var = tk.StringVar()
        tk.Entry(self, textvariable=self.output_var, width=52).grid(row=1, column=1, **pad)
        ttk.Button(self, text="Save As...", command=self.browse_output).grid(row=1, column=2, **pad)

        # Language + options
        tk.Label(self, text="Languages (Tesseract):").grid(row=2, column=0, sticky="e", **pad)
        self.lang_var = tk.StringVar(value="eng")
        tk.Entry(self, textvariable=self.lang_var, width=20).grid(row=2, column=1, sticky="w", **pad)

        self.force_var = tk.BooleanVar(value=False)
        self.deskew_var = tk.BooleanVar(value=True)
        self.clean_var = tk.BooleanVar(value=True)
        self.optimize_var = tk.IntVar(value=0)

        ttk.Checkbutton(self, text="Force OCR (re-OCR pages with text)", variable=self.force_var)\
            .grid(row=3, column=1, sticky="w", **pad)
        ttk.Checkbutton(self, text="Deskew", variable=self.deskew_var)\
            .grid(row=4, column=1, sticky="w", **pad)
        ttk.Checkbutton(self, text="Clean background", variable=self.clean_var)\
            .grid(row=5, column=1, sticky="w", **pad)

        tk.Label(self, text="Optimize (0–3):").grid(row=6, column=0, sticky="e", **pad)
        tk.Spinbox(self, from_=0, to=3, textvariable=self.optimize_var, width=5)\
            .grid(row=6, column=1, sticky="w", **pad)

        # Tesseract path (optional)
        tk.Label(self, text="Tesseract path (optional):").grid(row=7, column=0, sticky="e", **pad)
        self.tess_var = tk.StringVar()  # e.g. C:\Program Files\Tesseract-OCR\tesseract.exe
        tk.Entry(self, textvariable=self.tess_var, width=52).grid(row=7, column=1, **pad)
        ttk.Button(self, text="Find...", command=self.browse_tesseract).grid(row=7, column=2, **pad)

        # Run + status
        self.run_btn = ttk.Button(self, text="Run OCR", command=self.on_run)
        self.run_btn.grid(row=8, column=1, **pad)

        self.status_var = tk.StringVar(value="Idle")
        tk.Label(self, textvariable=self.status_var, anchor="w", fg="gray")\
            .grid(row=9, column=0, columnspan=3, sticky="we", padx=10, pady=(2, 6))

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.grid(row=10, column=0, columnspan=3, sticky="we", padx=10, pady=(0, 10))

    # ---- Browsers ----
    def browse_input(self):
        p = filedialog.askopenfilename(title="Choose input PDF", filetypes=[("PDF files", "*.pdf")])
        if p:
            self.input_var.set(p)
            if not self.output_var.get():
                self.output_var.set(str(Path(p).with_suffix(".ocr.pdf")))

    def browse_output(self):
        p = filedialog.asksaveasfilename(
            title="Save OCR'd PDF as...",
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
        )
        if p:
            self.output_var.set(p)

    def browse_tesseract(self):
        p = filedialog.askopenfilename(
            title="Locate Tesseract executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if p:
            self.tess_var.set(p)

    # ---- Run + thread ----
    def on_run(self):
        in_pdf = self.input_var.get().strip()
        out_pdf = self.output_var.get().strip() or None
        langs = self.lang_var.get().strip() or "eng"
        force = self.force_var.get()
        deskew = self.deskew_var.get()
        clean = self.clean_var.get()
        optimize = int(self.optimize_var.get())
        tpath = self.tess_var.get().strip() or None

        if not in_pdf:
            messagebox.showwarning("Missing file", "Please choose an input PDF.")
            return

        self.run_btn.config(state="disabled")
        self.progress.start(10)
        self.status_var.set("Running OCR…")

        def worker():
            try:
                out = run_ocr(
                    input_pdf=in_pdf,
                    output_pdf=out_pdf,
                    languages=langs,
                    force=force,
                    optimize=optimize,
                    deskew=deskew,
                    clean=clean,
                    custom_tesseract_path=tpath,
                )
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}"
                self.after(0, lambda m=err_msg: self.on_done(error=m))
                return

            self.after(0, lambda p=str(out): self.on_done(result=p))

        threading.Thread(target=worker, daemon=True).start()

    def on_done(self, result: str | None = None, error: str | None = None):
        self.progress.stop()
        self.run_btn.config(state="normal")
        if error:
            self.status_var.set("Error")
            messagebox.showerror("OCR failed", error)
        else:
            self.status_var.set("Done")
            messagebox.showinfo("Success", f"OCR complete:\n{result}")


if __name__ == "__main__":
    app = OCRApp()
    app.mainloop()
