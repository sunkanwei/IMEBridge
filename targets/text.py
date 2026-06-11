"""Text Editor insertion and leak-recovery helpers."""

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import detect as targets


TEXT_RESTORE_TIMER_INTERVAL = 0.02
TEXT_TAB_INDENT_TIMER_INTERVAL = 0.0


def text_data_from_target(target: object) -> object | None:
    """Return a target's Text datablock without trusting stale RNA."""
    if not models.is_text_editor_target(target):
        return None
    try:
        return target.text
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def session_text_data(target: object, text_session: object) -> object | None:
    """Return target text only when the IME session still owns it."""
    text_data = text_data_from_target(target)
    if (
        text_data is None
        or not isinstance(text_session, models.TextImeSession)
        or not text_session.owns_text(text_data)
    ):
        return None
    return text_data


def same_text_data(left: object, right: object) -> bool:
    """Compare Text datablocks without trusting stale RNA references."""
    try:
        return left == right
    except (ReferenceError, RuntimeError):
        return False


def is_non_ascii_identifier_char(char: str) -> bool:
    """Match Unicode identifier tails that Blender autocomplete can misread."""
    if not char:
        return False
    return not char.isascii() and char.isalnum()


def text_has_selection(text_data: object) -> bool:
    """Check whether Text Editor selection is active."""
    selection = text_selection_position(text_data)
    if selection is None:
        return False
    line, column, select_line, select_column = selection
    return line != select_line or column != select_column


def char_before_cursor(text_data: object) -> str:
    """Read the Unicode character directly before the Text Editor cursor."""
    try:
        line_index = int(text_data.current_line_index)
        column = int(text_data.current_character)
        line = text_data.lines[line_index].body
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return ""
    if column <= 0:
        return ""
    column = min(column, len(line))
    return line[column - 1 : column]


def cursor_after_non_ascii_identifier(target: object) -> bool:
    """Detect Unicode word tails where Tab should indent, not autocomplete."""
    text_data = text_data_from_target(target)
    if text_data is None or text_has_selection(text_data):
        return False
    return is_non_ascii_identifier_char(char_before_cursor(text_data))


def capture_composition_start(target: object) -> models.TextImeSession | None:
    """Start a Text Editor IME session with the current replacement range."""
    text_data = text_data_from_target(target)
    if text_data is None:
        return None
    body = safe_ops.maybe_get_text_body(text_data)
    if body is None:
        return None
    try:
        line = int(text_data.current_line_index)
        column = int(text_data.current_character)
        select_line = int(getattr(text_data, "select_end_line_index", line))
        select_column = int(getattr(text_data, "select_end_character", column))
        offsets = text_selection_offsets(
            body,
            line,
            column,
            select_line,
            select_column,
        )
        if offsets is None:
            return None
        replace_start, replace_end = offsets
        return runtime.state.text_ime_session.begin(
            text=text_data,
            body=body,
            line=line,
            column=column,
            select_line=select_line,
            select_column=select_column,
            replace_start=replace_start,
            replace_end=replace_end,
        )
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None


def capture_restore_snapshot(target: object) -> models.TextRestoreSnapshot | None:
    """Save enough state to undo IME edit-key leaks cleanly."""
    text_data = text_data_from_target(target)
    if text_data is None:
        return None

    body = safe_ops.maybe_get_text_body(text_data)
    if body is None:
        return None

    try:
        line = int(text_data.current_line_index)
        column = int(text_data.current_character)
        return models.TextRestoreSnapshot(
            text=text_data,
            body=body,
            line=line,
            column=column,
            select_line=int(getattr(text_data, "select_end_line_index", line)),
            select_column=int(getattr(text_data, "select_end_character", column)),
            session=active_text_session(text_data),
            commit_generation=runtime.state.text_ime_session.commit_generation,
        )
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None


def clamped_text_cursor(text_data: object, line: int, column: int) -> tuple[int, int]:
    """Clamp a cursor that may be stale by the time Blender handles it."""
    if len(text_data.lines) == 0:
        return 0, 0
    line = max(0, min(int(line), len(text_data.lines) - 1))
    column = max(0, int(column))
    column = min(column, len(text_data.lines[line].body))
    return line, column


def set_text_selection(
    text_data: object,
    line: int,
    column: int,
    select_line: int,
    select_column: int,
) -> bool:
    """Restore a Text selection defensively across editor changes."""
    try:
        line, column = clamped_text_cursor(text_data, line, column)
        select_line, select_column = clamped_text_cursor(
            text_data,
            select_line,
            select_column,
        )
        select_set = getattr(text_data, "select_set", None)
        if callable(select_set):
            select_set(line, column, select_line, select_column)
        else:
            text_data.current_line_index = line
            text_data.current_character = column
            try:
                text_data.select_end_line_index = select_line
                text_data.select_end_character = select_column
            except (AttributeError, RuntimeError):
                pass
        return True
    except (AttributeError, IndexError, ReferenceError, RuntimeError, ValueError):
        return False


def set_text_cursor(text_data: object, line: int, column: int) -> bool:
    """Move the cursor defensively across editor and datablock changes."""
    return set_text_selection(text_data, line, column, line, column)


def restore_text_state(snapshot: models.TextRestoreSnapshot) -> bool:
    """Put the Text Editor back after a control key edited real text."""
    return restore_text_body(
        snapshot.text,
        snapshot.body,
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )


def restore_text_body(
    text_data: object,
    body: str,
    line: int,
    column: int,
    select_line: int | None = None,
    select_column: int | None = None,
) -> bool:
    """Replace the whole Text datablock, then restore a known-safe selection."""
    if text_data is None:
        return False
    try:
        text_data.clear()
        text_data.write(body)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    if select_line is None:
        select_line = line
    if select_column is None:
        select_column = column
    return set_text_selection(text_data, line, column, select_line, select_column)


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


def text_selection_offsets(
    body: str,
    line: int,
    column: int,
    select_line: int,
    select_column: int,
) -> tuple[int, int] | None:
    """Return sorted offsets for a Text selection in ``body``."""
    try:
        current = text_position_to_offset(body, int(line), int(column))
        selected = text_position_to_offset(
            body,
            int(select_line),
            int(select_column),
        )
    except (TypeError, ValueError):
        return None
    return min(current, selected), max(current, selected)


def text_selection_position(text_data: object) -> tuple[int, int, int, int] | None:
    """Read the current Text selection endpoints."""
    try:
        line = int(text_data.current_line_index)
        column = int(text_data.current_character)
        select_line = int(getattr(text_data, "select_end_line_index", line))
        select_column = int(getattr(text_data, "select_end_character", column))
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None
    return line, column, select_line, select_column


def text_cursor_offsets(text_data: object, body: str) -> tuple[int, int] | None:
    """Return the sorted replacement range represented by the Text selection."""
    selection = text_selection_position(text_data)
    if selection is None:
        return None
    return text_selection_offsets(body, *selection)


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
    """Move only the selection when the text body stayed intact."""
    if snapshot.text is None:
        return False
    return set_text_selection(
        snapshot.text,
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )


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

    selection = text_selection_position(snapshot.text)
    if selection is None:
        return None

    if current_body != snapshot.body:
        restore_text_state(snapshot)
        return None

    snapshot_selection = (
        snapshot.line,
        snapshot.column,
        snapshot.select_line,
        snapshot.select_column,
    )
    if selection != snapshot_selection:
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
    if safe_ops.register_timer(
        restore_text_after_ime_edit_key,
        first_interval=TEXT_RESTORE_TIMER_INTERVAL,
    ):
        runtime.state.text_restore_timer_registered = True
    else:
        runtime.state.text_restore_guard = None


def cancel_restore_guard() -> None:
    """Drop the Text Editor guard during shutdown or target changes."""
    runtime.state.text_restore_timer_registered = False
    runtime.state.text_restore_guard = None
    safe_ops.unregister_timer(restore_text_after_ime_edit_key)


def indent_once(target: object) -> bool:
    """Run Blender's plain Text indent operator for one suppressed Tab."""
    if not models.is_text_editor_target(target):
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None:
        return False
    if getattr(context["space"], "text", None) != text_data_from_target(target):
        return False

    try:
        with bpy.context.temp_override(
            window=context["window"],
            screen=context["screen"],
            area=context["area"],
            region=context["region"],
            space_data=context["space"],
        ):
            if bpy.ops.text.indent.poll():
                bpy.ops.text.indent()
                return True
    except (AttributeError, ReferenceError, RuntimeError):
        return False
    return False


def flush_tab_indent_queue() -> None:
    """Apply any Tab presses that were diverted away from autocomplete."""
    state = runtime.state.tab_indent
    state.timer_registered = False
    target = state.target
    count = state.count
    state.target = None
    state.count = 0

    for _index in range(count):
        if not indent_once(target):
            break
    return None


def schedule_tab_indent(target: object) -> bool:
    """Queue one plain indent action after suppressing Unicode autocomplete."""
    state = runtime.state.tab_indent
    state.target = target
    state.count += 1
    if state.timer_registered:
        return True

    if safe_ops.register_timer(
        flush_tab_indent_queue,
        first_interval=TEXT_TAB_INDENT_TIMER_INTERVAL,
    ):
        state.timer_registered = True
        return True

    state.count = max(0, state.count - 1)
    if state.count == 0:
        state.target = None
    return False


def cancel_tab_indent() -> None:
    """Drop pending autocomplete-safe Tab indentation."""
    runtime.state.tab_indent.clear()
    safe_ops.unregister_timer(flush_tab_indent_queue)


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
        and same_text_data(guard.text, text_data)
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


def restore_composition_baseline(
    target: object,
    text_session: object,
) -> bool:
    """Restore the pre-composition body and selection."""
    text_data = session_text_data(target, text_session)
    if text_data is None:
        return False

    current_body = safe_ops.maybe_get_text_body(text_data)
    if current_body is None:
        return False
    if current_body != text_session.body:
        return restore_text_body(
            text_data,
            text_session.body,
            text_session.line,
            text_session.column,
            text_session.select_line,
            text_session.select_column,
        )
    return set_text_selection(
        text_data,
        text_session.line,
        text_session.column,
        text_session.select_line,
        text_session.select_column,
    )


def text_session_replacement_offsets(
    text_session: models.TextImeSession,
) -> tuple[int, int]:
    """Clamp a session replacement range to its saved body."""
    body_length = len(text_session.body)
    start = max(0, min(int(text_session.replace_start), body_length))
    end = max(0, min(int(text_session.replace_end), body_length))
    return min(start, end), max(start, end)


def text_session_commit_result(
    text_session: models.TextImeSession,
    text: str,
) -> tuple[str, int, int]:
    """Return the committed body and collapsed cursor for an IME session."""
    start, end = text_session_replacement_offsets(text_session)
    new_body = text_session.body[:start] + text + text_session.body[end:]
    line, column = text_offset_to_position(new_body, start + len(text))
    return new_body, line, column


def insert_text_session_result(
    target: object,
    text: str,
    text_session: object,
    *,
    use_operator: bool,
) -> bool:
    """Commit text by applying the session's saved replacement range."""
    text_data = session_text_data(target, text_session)
    if text_data is None:
        return False

    expected_body, cursor_line, cursor_column = text_session_commit_result(
        text_session,
        text,
    )
    mark_composition_committed(text_session)

    if use_operator and restore_composition_baseline(target, text_session):
        try:
            if bpy.ops.text.insert.poll():
                bpy.ops.text.insert(text=text)
                if safe_ops.maybe_get_text_body(text_data) == expected_body:
                    return set_text_cursor(
                        text_data,
                        cursor_line,
                        cursor_column,
                    )
        except (AttributeError, ReferenceError, RuntimeError):
            pass

    return restore_text_body(
        text_data,
        expected_body,
        cursor_line,
        cursor_column,
    )


def insert(text: str, target: object, text_session: object = None) -> bool:
    """Commit IME text through Blender's Text Editor operator."""
    text_data = text_data_from_target(target)
    if text_data is None:
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None:
        return False
    if getattr(context["space"], "text", None) != text_data:
        return False

    with bpy.context.temp_override(
        window=context["window"],
        screen=context["screen"],
        area=context["area"],
        region=context["region"],
        space_data=context["space"],
    ):
        if isinstance(text_session, models.TextImeSession):
            return insert_text_session_result(
                target,
                text,
                text_session,
                use_operator=True,
            )

        if bpy.ops.text.insert.poll():
            bpy.ops.text.insert(text=text)
            return True

    try:
        if isinstance(text_session, models.TextImeSession):
            return insert_text_session_result(
                target,
                text,
                text_session,
                use_operator=False,
            )
        return insert_text_body_at_cursor(text_data, text)
    except (AttributeError, ReferenceError, RuntimeError):
        return False
