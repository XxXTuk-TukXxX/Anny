DEFAULTS = {
    # Dimensions
    "note_width": 240,
    "min_note_width": 48,
    "note_fontsize": 9.0,

    # Visuals
    "note_fill": "",  # empty string -> None
    "note_border": "",
    "note_border_width": 0,
    "note_text": "red",
    "draw_leader": False,
    "leader_color": "",

    # Placement
    "allow_column_footer": True,
    "column_footer_max_offset": 250,
    "max_vertical_offset": 90,
    "max_scan": 420,
    "side": "outer",
    "allow_center_gutter": True,
    "center_gutter_tolerance": 48.0,
    "dedupe_scope": "page",

    # Font
    "note_fontname": "AnnotateNote",
    "note_fontfile": "fonts/Roys-Regular.ttf",

    # API
    "gemini_api_key": "",
}

SCALE = 1.5
# Default off: rebuilding the full PDF on every drag makes the UI feel choppy
# and can also cause the layout engine to re-evaluate placements. Users can
# still click the "Refresh preview" button to rebuild when ready.
AUTO_REFRESH_AFTER_DRAG = True
