"""Small Blender calls that need reload-safe error handling."""

import bpy


def register_timer(callback: object, *, first_interval: float = 0.0) -> bool:
    """Register a Blender timer without leaving local state half-armed."""
    try:
        bpy.app.timers.register(callback, first_interval=first_interval)
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return False
    return True


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
