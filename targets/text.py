"""Text Editor insertion and leak-recovery helpers."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets


TEXT_RESTORE_TIMER_INTERVAL = 0.02


def capture_composition_start(target: object) -> models.TextImeSession | None:
    """Start a Text Editor IME session at the current cursor."""
    if not models.is_text_editor_target(target) or target.text is None:
        return None
    body = safe_ops.maybe_get_text_body(target.text)
    if body is None:
        return None
    try:
        return runtime.state.text_ime_session.begin(
            text=target.text,
            body=body,
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
            session=active_text_session(target.text),
            commit_generation=runtime.state.text_ime_session.commit_generation,
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
        select_set = getattr(text_data, "select_set", None)
        if callable(select_set):
            select_set(line, column, line, column)
        else:
            text_data.current_line_index = line
            text_data.current_character = column
            try:
                text_data.select_end_line_index = line
                text_data.select_end_character = column
            except (AttributeError, RuntimeError):
                pass
        return True
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def restore_text_state(snapshot: models.TextRestoreSnapshot) -> bool:
    """Put the Text Editor back after a control key edited real text."""
    return restore_text_body(
        snapshot.text,
        snapshot.body,
        snapshot.line,
        snapshot.column,
    )


def restore_text_body(
    text_data: object,
    body: str,
    line: int,
    column: int,
) -> bool:
    """Replace the whole Text datablock, then restore a known-safe cursor."""
    if text_data is None:
        return False
    try:
        text_data.clear()
        text_data.write(body)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return set_text_cursor(text_data, line, column)


def text_position_to_offset(body: str, line: int, column: int) -> int:
    """Convert a Text cursor position into an offset inside ``as_string``."""
    lines = body.split("\n")
    if not lines:
        return 0

    line = max(0, min(int(line), len(lines) - 1))
    column = max(0, min(int(column), len(lines[line])))
    offset = 0
    for index in range(line):
        offset += len(lines[index]) + 1
    return offset + column


def text_offset_to_position(body: str, offset: int) -> tuple[int, int]:
    """Convert an ``as_string`` offset back to Text line and column indices."""
    offset = max(0, min(int(offset), len(body)))
    line = body.count("\n", 0, offset)
    line_start = body.rfind("\n", 0, offset) + 1
    return line, offset - line_start


def text_cursor_offsets(text_data: object, body: str) -> tuple[int, int] | None:
    """Return the sorted replacement range represented by the Text selection."""
    try:
        select_line = getattr(
            text_data,
            "select_end_line_index",
            text_data.current_line_index,
        )
        select_column = getattr(
            text_data,
            "select_end_character",
            text_data.current_character,
        )
        current = text_position_to_offset(
            body,
            int(text_data.current_line_index),
            int(text_data.current_character),
        )
        selected = text_position_to_offset(
            body,
            int(select_line),
            int(select_column),
        )
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None
    return min(current, selected), max(current, selected)


def insert_text_body_at_cursor(text_data: object, text: str) -> bool:
    """Insert text by rebuilding the body so Blender's Text.write cannot trim it."""
    body = safe_ops.maybe_get_text_body(text_data)
    if body is None:
        return False

    offsets = text_cursor_offsets(text_data, body)
    if offsets is None:
        return False
    start, end = offsets
    new_body = body[:start] + text + body[end:]
    line, column = text_offset_to_position(new_body, start + len(text))
    return restore_text_body(text_data, new_body, line, column)


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
    if not restore_snapshot_is_current(snapshot):
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


def active_text_session(text_data: object) -> models.TextImeSession | None:
    """Find the session currently allowed to guard this Text datablock."""
    session = runtime.state.text_ime_session.active_for_text(text_data)
    if isinstance(session, models.TextImeSession):
        return session
    return None


def restore_snapshot_is_current(snapshot: models.TextRestoreSnapshot) -> bool:
    """Reject stale or committed guards before they can roll text back."""
    if snapshot.commit_generation != runtime.state.text_ime_session.commit_generation:
        return False
    if (
        isinstance(snapshot.session, models.TextImeSession)
        and snapshot.session.committed
    ):
        return False
    current_session = active_text_session(snapshot.text)
    if current_session is not None and snapshot.session is not current_session:
        return False
    return True


def clear_matching_restore_guard(
    text_data: object,
    session: object,
    *,
    unregister_timer: bool = True,
) -> None:
    """Drop a restore guard once the same IME session has a real commit."""
    guard = runtime.state.text_restore_guard
    if (
        isinstance(guard, models.TextRestoreSnapshot)
        and guard.text == text_data
        and (guard.session is None or guard.session is session)
    ):
        runtime.state.text_restore_guard = None
        runtime.state.text_restore_timer_registered = False
        if unregister_timer:
            safe_ops.unregister_timer(restore_text_after_ime_edit_key)


def mark_composition_committed(
    text_session: object,
    *,
    unregister_timer: bool = True,
) -> None:
    """Make stale preedit guards harmless as soon as IME confirms text."""
    if not isinstance(text_session, models.TextImeSession):
        return
    runtime.state.text_ime_session.mark_committed(text_session)
    clear_matching_restore_guard(
        text_session.text,
        text_session,
        unregister_timer=unregister_timer,
    )


def prepare_composition_commit(
    target: object,
    text_session: object,
) -> bool:
    """Restore the pre-composition baseline before inserting the IME result."""
    if (
        not models.is_text_editor_target(target)
        or not isinstance(text_session, models.TextImeSession)
        or not text_session.owns_text(target.text)
    ):
        return False

    mark_composition_committed(text_session)
    current_body = safe_ops.maybe_get_text_body(target.text)
    if current_body is None:
        return False
    if current_body != text_session.body:
        return restore_text_body(
            target.text,
            text_session.body,
            text_session.line,
            text_session.column,
        )
    return set_text_cursor(
        target.text,
        text_session.line,
        text_session.column,
    )


def has_leaked_confirm_space(target: object, text_session: object) -> bool:
    """Detect the classic leak: confirm Space also became real text."""
    if (
        not models.is_text_editor_target(target)
        or not isinstance(text_session, models.TextImeSession)
        or not text_session.owns_text(target.text)
    ):
        return False

    try:
        line = int(target.text.current_line_index)
        column = int(target.text.current_character)
        if (
            line != text_session.line
            or column != text_session.column + 1
            or column <= 0
        ):
            return False
        body = target.text.lines[line].body
        return column <= len(body) and body[column - 1] == " "
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def delete_confirm_space_before_insert(
    target: object,
    text_session: object,
) -> bool:
    """Remove the leaked Space while the Text operator context is active."""
    if not has_leaked_confirm_space(target, text_session):
        return False
    if not bpy.ops.text.delete.poll():
        return False
    bpy.ops.text.delete(type="PREVIOUS_CHARACTER")
    return True


def insert(text: str, target: object, text_session: object = None) -> bool:
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
            if not prepare_composition_commit(target, text_session):
                delete_confirm_space_before_insert(target, text_session)
            bpy.ops.text.insert(text=text)
            return True

    try:
        prepare_composition_commit(target, text_session)
        return insert_text_body_at_cursor(target.text, text)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
