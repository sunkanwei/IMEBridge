"""Public target helpers shared by the IME bridge."""

from .detect import (
    TARGET_FONT_EDIT,
    TARGET_TEXT_EDITOR,
    active_font_edit_object,
    find_font_edit_target,
    is_supported_input_target,
    make_font_edit_target,
    make_font_edit_target_from_context,
    make_input_target_from_context,
    make_text_editor_target,
    make_text_editor_target_from_context,
    resolve_input_target,
    target_context,
)
from .state import (
    capture_composition_start,
    clear_active_target,
    set_active_target,
)

__all__ = (
    "TARGET_FONT_EDIT",
    "TARGET_TEXT_EDITOR",
    "active_font_edit_object",
    "capture_composition_start",
    "clear_active_target",
    "find_font_edit_target",
    "is_supported_input_target",
    "make_font_edit_target",
    "make_font_edit_target_from_context",
    "make_input_target_from_context",
    "make_text_editor_target",
    "make_text_editor_target_from_context",
    "resolve_input_target",
    "set_active_target",
    "target_context",
)
