# gemini_annotaton.py
from __future__ import annotations

import json, os
from datetime import datetime
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field
from google import genai
from dotenv import load_dotenv

load_dotenv()  # reads .env if present

# --- Structured output schema ---
class Annotation(BaseModel):
    quote: str = Field(description="Exact sentence or short clause copied verbatim from the source text.")
    explanation: str = Field(description="One-sentence note explaining why the quote matters for the objective.")
    color: str = Field(description="Hex color like #A5D6A7.")

def _resolve_api_key() -> str:
    key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "Missing API key. Set GOOGLE_API_KEY (recommended) or GEMINI_API_KEY in your environment or .env."
        )
    return key

def annotate_txt_file(
    txt_path: str,
    objective: str,
    *,
    outfile: str | None = None,
    model: str = "gemini-2.5-flash",
    max_items_hint: int = 12,
) -> list[dict]:
    """
    Read a .txt file, send it with the user's objective to Gemini,
    and return a JSON-ready list of annotations. Also writes a .json file.

    The MODEL chooses exactly one color that semantically fits the objective,
    and uses that same color across all items in the response.
    """
    # --- Read source text ---
    p = Path(txt_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {txt_path}")
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("The provided text file is empty.")

    # --- Prompt: model picks color ---
    prompt = f"""
You are an annotation engine.

GOAL
Select sentences/clauses to highlight for OBJECTIVE.

OUTPUT FORMAT
Return a JSON array of objects with fields:
- quote        (exact substring from SOURCE TEXT; no paraphrasing)
- explanation  (≤ 20 words explaining why it matters for OBJECTIVE)
- color        (a single hex color like #A5D6A7)

COLOR RULES
- Choose EXACTLY ONE hex color that meaningfully fits OBJECTIVE (e.g., economy, religion, politics, science, conflict, society).
- Use the SAME chosen color for EVERY item in this response.
- When OBJECTIVE changes across separate runs, you may choose a different color.

GENERAL RULES
- Only include sentences/clauses that appear verbatim in SOURCE TEXT.
- Avoid duplicates; focus on the most relevant items for OBJECTIVE.
- Prefer complete sentences; a shorter clause is okay if it is a meaningful highlight.
- Return at most ~{max_items_hint} items.
- Output must match the schema exactly; no extra fields or prose.

OBJECTIVE:
{objective}

SOURCE TEXT:
<<<
{text}
>>>
""".strip()

    # --- Call Gemini with structured output ---
    client = genai.Client(api_key=_resolve_api_key())
    resp = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": list[Annotation],  # enforce structure
        },
    )

    # Prefer validated parsed objects; fallback to JSON text if needed
    parsed: List[Annotation] | None = getattr(resp, "parsed", None)
    if parsed is None:
        parsed = [Annotation(**obj) for obj in json.loads(resp.text)]

    # Optional safety: if the model returned multiple colors, normalize to the first one it chose.
    if parsed:
        chosen = parsed[0].color
        for a in parsed:
            a.color = chosen

    # --- Prepare output path and write JSON ---
    if outfile is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        outfile = f"{p.stem}__annotations-{stamp}.json"

    data_dicts = [a.model_dump() for a in parsed]
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(data_dicts, f, ensure_ascii=False, indent=2)

    return data_dicts


# Example usage (delete or keep for testing)
if __name__ == "__main__":
    result = annotate_txt_file(
        txt_path="sample.txt",
        objective="Annotate for conflicts between religious authority and dissent.",
        model="gemini-2.5-flash",
    )
    print(f"Wrote {len(result)} annotations.")
