"""Text Editor datablock state, snapshots, and low-level body writes."""

from ..core import models
from ..core import runtime
from ..core import safe_ops
from . import text_positions as positions


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
    selection = positions.text_selection_position(text_data)
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


def active_text_session(text_data: object) -> models.TextImeSession | None:
    """Find the session currently allowed to guard this Text datablock."""
    session = runtime.state.text_ime_session.active_for_text(text_data)
    if isinstance(session, models.TextImeSession):
        return session
    return None


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
        offsets = positions.text_selection_offsets(
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


def insert_text_body_at_cursor(text_data: object, text: str) -> bool:
    """Insert text by rebuilding the body so Blender's Text.write cannot trim it."""
    body = safe_ops.maybe_get_text_body(text_data)
    if body is None:
        return False

    offsets = positions.text_cursor_offsets(text_data, body)
    if offsets is None:
        return False
    start, end = offsets
    new_body = body[:start] + text + body[end:]
    line, column = positions.text_offset_to_position(new_body, start + len(text))
    return restore_text_body(text_data, new_body, line, column)
