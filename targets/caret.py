"""Caret geometry for Blender's Text Editor."""

from ..core import models
from ..preferences import config
from ..win32 import api as win32_api


def text_line_height(space: object, region: object) -> int:
    """Blender gives us lines and regions, so keep this estimate conservative."""
    if getattr(space, "visible_lines", 0) > 0:
        return max(12, int(round(region.height / space.visible_lines)))
    if getattr(space, "font_size", 0) > 0:
        return max(12, int(round(space.font_size * 1.35)))
    return 18


def cursor_region_coordinates(
    space: object,
    line: int,
    column: int,
) -> tuple[int, int] | None:
    """Ask Blender for the caret point and reject unusable answers."""
    try:
        cursor = space.region_location_from_cursor(line, column)
    except (AttributeError, ReferenceError, RuntimeError):
        return None

    if cursor is None or len(cursor) < 2:
        return None

    region_x = int(cursor[0])
    region_y = int(cursor[1])
    if region_x < 0 or region_y < 0:
        return None
    return region_x, region_y


def text_editor_caret_info(
    hwnd: object,
    target: object,
) -> models.CandidateInfo | None:
    """Collect the geometry IMM32 needs for Text Editor candidate placement."""
    if not models.is_text_editor_target(target):
        return None

    win = win32_api.ensure_windows()
    if win is None:
        return None

    line = int(target.text.current_line_index)
    column = int(target.text.current_character)
    region_point = cursor_region_coordinates(target.space, line, column)
    if region_point is None:
        return None
    region_x, region_y = region_point

    point = win32_api.region_point_to_screen(
        win, hwnd, target.region, region_x, region_y
    )
    rect = win32_api.region_rect_to_screen(win, hwnd, target.region)
    if point is None or rect is None:
        return None

    return models.CandidateInfo(
        area=target.area,
        region=target.region,
        space=target.space,
        text=target.text,
        line=line,
        column=column,
        region_x=region_x,
        region_y=region_y,
        screen_x=point.x,
        screen_y=point.y,
        line_height=text_line_height(target.space, target.region),
        rect=rect,
    )


def text_editor_char_width(info: models.CandidateInfo) -> int:
    """Prefer measured cursor steps; fall back to the editor font size."""
    candidates = []
    for left, right in ((info.column, info.column + 1), (0, 1), (1, 2)):
        try:
            p0 = info.space.region_location_from_cursor(info.line, left)
            p1 = info.space.region_location_from_cursor(info.line, right)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        if p0 is None or p1 is None or len(p0) < 2 or len(p1) < 2:
            continue
        width = int(round(p1[0] - p0[0]))
        if 4 <= width <= 80:
            candidates.append(width)

    if candidates:
        return candidates[0]
    if getattr(info.space, "font_size", 0) > 0:
        return max(6, int(round(info.space.font_size * 0.65)))
    return 9


def ime_candidate_position(
    info: models.CandidateInfo,
    requested_char: int = 0,
) -> models.CandidatePosition:
    """Apply IME cursor math and the user's final manual offsets."""
    char_width = text_editor_char_width(info)
    requested_x_offset = (
        requested_char * char_width if config.add_requested_char_offset() else 0
    )
    manual_x_offset = config.x_offset()
    manual_y_offset = config.y_offset()
    return models.CandidatePosition(
        screen_x=int(info.screen_x + requested_x_offset + manual_x_offset),
        screen_y=int(info.screen_y + manual_y_offset),
        char_width=char_width,
        requested_x_offset=requested_x_offset,
        manual_x_offset=manual_x_offset,
        manual_y_offset=manual_y_offset,
    )
