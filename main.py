from highlights import highlight_and_margin_comment_pdf

if __name__ == "__main__":
    saved, hi, notes, skipped, placements = highlight_and_margin_comment_pdf(
        pdf_path="Myth.pdf",
        queries=[], comments={},
        annotations_json="myth.json",
        plan_only=True,                 # <— do NOT draw/save; just compute

        # Make more room so we don’t fight the fit
        note_width=240,            # wider than the default 160
        min_note_width=48,
        note_fontsize=9.0,

        # Visuals (no box, no leader)
        note_fill=None, note_border=None, note_border_width=0,
        note_text="red", draw_leader=False, leader_color=None,

        # Placement
        allow_column_footer=True,
        column_footer_max_offset=250,
        max_vertical_offset=90,
        max_scan=420,
        side="outer",
        allow_center_gutter=True,
        center_gutter_tolerance=48.0,

        # Dedupe per page so you get exactly two notes
        dedupe_scope="page",

        # Your font
        note_fontname="PatrickHand",
        note_fontfile=r".\fonts\PatrickHand-Regular.ttf",

        # Debug (to confirm fallback path)
        # debug=True,
    )
    print(f"Saved: {saved}  highlights={hi}  notes={notes}  skipped={skipped}")
    for p in placements:
        print(p.uid, p.page_index, p.note_rect, "->", p.explanation[:50])