"""Text Editor position and selection offset helpers."""


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
