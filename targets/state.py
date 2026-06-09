"""Remember the target state for the active IME composition."""

from ..core import models
from ..core import runtime
from . import text as text_target


def set_active_target(target: object) -> None:
    """Remember where the bridge last saw editable Blender focus."""
    runtime.state.active_target = target


def clear_active_target() -> None:
    """Forget the last target when focus no longer belongs to IMEBridge."""
    set_active_target(None)


def capture_composition_start(target: object) -> object | None:
    """Only Text Editor needs a start snapshot; Font input is guarded earlier."""
    if models.is_text_editor_target(target):
        return text_target.capture_composition_start(target)
    return None
