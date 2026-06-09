"""Text Editor insertion and leak-recovery helpers."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets


TEXT_RESTORE_TIMER_INTERVAL = 0.02


def capture_composition_start(target: object) -> models.TextCompositionStart | None:
    """Remember the Text Editor cursor before the IME starts composing."""
    if not models.is_text_editor_target(target) or target.text is None:
        return None
    try:
        return models.TextCompositionStart(
            text=target.text,
            line=int(target.text.current_line_index),
            column=int(target.text.current_character),
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def capture_restore_snapshot(target: object) -> models.TextRestoreSnapshot | None:
    """Save enough state to undo IME edit-key leaks cleanly."""
    if not models.is_text_editor_target(target) or target.text is None:
        return None

    body = safe_ops.maybe_get_text_body(target.text)
    if body is None:
        return None

    try:
        return models.TextRestoreSnapshot(
            target=target,
            text=target.text,
            body=body,
            line=int(target.text.current_line_index),
            column=int(target.text.current_character),
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def clamped_text_cursor(text_data: object, line: int, column: int) -> tuple[int, int]:
    """Clamp a cursor that may be stale by the time Blender handles it."""
    line = max(0, min(int(line), len(text_data.lines) - 1))
    column = max(0, int(column))
    column = min(column, len(text_data.lines[line].body))
    return line, column


def set_text_cursor(text_data: object, line: int, column: int) -> bool:
    """Move the cursor defensively across editor and datablock changes."""
    try:
        line, column = clamped_text_cursor(text_data, line, column)
        text_data.current_line_index = line
        text_data.current_character = column
        return True
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def restore_text_state(snapshot: models.TextRestoreSnapshot) -> bool:
    """Put the Text Editor back after a control key edited real text."""
    text_data = snapshot.text
    if text_data is None:
        return False
    try:
        text_data.clear()
        text_data.write(snapshot.body)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return set_text_cursor(text_data, snapshot.line, snapshot.column)


def restore_text_cursor(snapshot: models.TextRestoreSnapshot) -> bool:
    """Move only the caret when the text body stayed intact."""
    if snapshot.text is None:
        return False
    return set_text_cursor(snapshot.text, snapshot.line, snapshot.column)


def restore_text_after_ime_edit_key() -> None:
    """Repair the Text Editor after the short guard window expires."""
    runtime.state.text_restore_timer_registered = False
    snapshot = runtime.state.text_restore_guard
    runtime.state.text_restore_guard = None
    if snapshot is None or snapshot.text is None:
        return None

    current_body = safe_ops.maybe_get_text_body(snapshot.text)
    if current_body is None:
        return None

    try:
        current_line = int(snapshot.text.current_line_index)
        current_column = int(snapshot.text.current_character)
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None

    if current_body != snapshot.body:
        restore_text_state(snapshot)
        return None

    if current_line != snapshot.line or current_column != snapshot.column:
        restore_text_cursor(snapshot)
    return None


def schedule_restore_guard(target: object) -> None:
    """Arm the guard while the IME owns keys such as Backspace."""
    if runtime.state.text_restore_timer_registered:
        return

    snapshot = capture_restore_snapshot(target)
    if snapshot is None:
        return

    runtime.state.text_restore_guard = snapshot
    runtime.state.text_restore_timer_registered = True
    bpy.app.timers.register(
        restore_text_after_ime_edit_key,
        first_interval=TEXT_RESTORE_TIMER_INTERVAL,
    )


def cancel_restore_guard() -> None:
    """Drop the Text Editor guard during shutdown or target changes."""
    runtime.state.text_restore_timer_registered = False
    runtime.state.text_restore_guard = None
    safe_ops.unregister_timer(restore_text_after_ime_edit_key)


def has_leaked_confirm_space(target: object, composition_start: object) -> bool:
    """Detect the classic leak: confirm Space also became real text."""
    if (
        not models.is_text_editor_target(target)
        or not isinstance(composition_start, models.TextCompositionStart)
        or target.text != composition_start.text
    ):
        return False

    try:
        line = int(target.text.current_line_index)
        column = int(target.text.current_character)
        if (
            line != composition_start.line
            or column != composition_start.column + 1
            or column <= 0
        ):
            return False
        body = target.text.lines[line].body
        return column <= len(body) and body[column - 1] == " "
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def delete_confirm_space_before_insert(target: object, composition_start: object) -> bool:
    """Remove the leaked Space while the Text operator context is active."""
    if not has_leaked_confirm_space(target, composition_start):
        return False
    if not bpy.ops.text.delete.poll():
        return False
    bpy.ops.text.delete(type="PREVIOUS_CHARACTER")
    return True


def insert(text: str, target: object, composition_start: object = None) -> bool:
    """Commit IME text through Blender's Text Editor operator."""
    if not models.is_text_editor_target(target):
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None or target.text is None:
        return False
    if getattr(context["space"], "text", None) != target.text:
        return False

    with bpy.context.temp_override(
        window=context["window"],
        screen=context["screen"],
        area=context["area"],
        region=context["region"],
        space_data=context["space"],
    ):
        if bpy.ops.text.insert.poll():
            delete_confirm_space_before_insert(target, composition_start)
            bpy.ops.text.insert(text=text)
            return True

    try:
        target.text.write(text)
        return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False
