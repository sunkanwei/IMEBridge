"""Small Blender calls that need reload-safe error handling."""

import bpy


def unregister_timer(callback: object) -> bool:
    """Timers may already be gone during reload or failed registration."""
    try:
        if bpy.app.timers.is_registered(callback):
            bpy.app.timers.unregister(callback)
    except RuntimeError:
        return False
    return True


def remove_text_draw_handler(handler: object) -> bool:
    """Draw-handler tokens can outlive the editor area they came from."""
    if handler is None:
        return False
    try:
        bpy.types.SpaceTextEditor.draw_handler_remove(handler, "WINDOW")
    except (ValueError, RuntimeError):
        return False
    return True


def maybe_get_text_body(text_data: object) -> str | None:
    """Text datablocks can go stale between a callback and a timer tick."""
    try:
        return text_data.as_string()
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def maybe_get_font_body(data: object) -> str | None:
    """Font datablocks follow the same stale-RNA rules as Text datablocks."""
    try:
        return data.body
    except (AttributeError, ReferenceError, RuntimeError):
        return None
