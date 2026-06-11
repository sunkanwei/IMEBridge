"""3D Text insertion helpers."""

from collections.abc import Callable

import bpy

from ..core import models
from ..platforms import native as platform_api
from . import detect as targets


def target_key(target: object) -> int:
    """Use the Blender object pointer for short-lived Font target state."""
    if not models.is_font_edit_target(target):
        return 0
    try:
        obj = target.obj
        if obj is None:
            return 0
        return platform_api.ptr_value(obj.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def body_from_target(target: object) -> str | None:
    """Read the editable 3D Text body without assuming the object is still live."""
    if not models.is_font_edit_target(target):
        return None
    try:
        body = target.obj.data.body
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    if not isinstance(body, str):
        return None
    return body


def set_body(target: object, body: str) -> bool:
    """Write a 3D Text body only after the target has been validated."""
    if not models.is_font_edit_target(target):
        return False
    try:
        target.obj.data.body = body
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return False
    return True


def single_inserted_space_index(before: str, after: str) -> int | None:
    """Return the index if ``after`` is ``before`` plus one inserted Space."""
    if len(after) != len(before) + 1:
        return None

    for index, char in enumerate(after):
        if index < len(before) and char == before[index]:
            continue
        if char == " " and after[index + 1:] == before[index:]:
            return index
        return None
    return len(before) if after.endswith(" ") else None


def confirm_space_leak_index(
    target: object,
    snapshot: object,
) -> int | None:
    """Validate that the current Font body only gained the suspected Space."""
    if not isinstance(snapshot, models.FontBodySnapshot):
        return None
    if snapshot.target_key != target_key(target):
        return None

    current_body = body_from_target(target)
    if current_body is None:
        return None
    return single_inserted_space_index(snapshot.body, current_body)


def _font_delete_previous_character() -> bool:
    delete = getattr(bpy.ops.font, "delete", None)
    if delete is None:
        return False
    try:
        if not delete.poll():
            return False
        delete(type="PREVIOUS_CHARACTER")
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return False
    return True


def _replace_confirm_space_directly(
    text: str,
    target: object,
    snapshot: models.FontBodySnapshot,
    index: int,
) -> bool:
    body = snapshot.body
    return set_body(target, body[:index] + text + body[index:])


def _repair_confirm_space_leak(
    text: str,
    target: object,
    snapshot: object,
) -> bool:
    index = confirm_space_leak_index(target, snapshot)
    if index is None or not isinstance(snapshot, models.FontBodySnapshot):
        return False

    leaked_body = body_from_target(target)
    if _font_delete_previous_character() and body_from_target(target) == snapshot.body:
        bpy.ops.font.text_insert(text=text)
        return True

    if leaked_body is not None:
        set_body(target, leaked_body)
    return _replace_confirm_space_directly(text, target, snapshot, index)


def target_can_accept_insert(target: object) -> bool:
    """Reject stored Font targets that have clearly gone stale."""
    if not models.is_font_edit_target(target):
        return False
    try:
        obj = target.obj
        if obj is None or obj.type != "FONT":
            return False
        current = targets.active_font_edit_object()
        return current is None or current == obj
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def run_with_target_context(target: object, callback: Callable[[], bool]) -> bool:
    """Font operators need a View3D override with the edited object."""
    if not target_can_accept_insert(target):
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None or target.obj is None:
        return False

    try:
        with bpy.context.temp_override(
            window=context["window"],
            screen=context["screen"],
            area=context["area"],
            region=context["region"],
            space_data=context["space"],
            active_object=target.obj,
            object=target.obj,
            edit_object=target.obj,
        ):
            return callback()
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return False


def insert_with_target(
    text: str,
    target: object,
    font_space_leak: object = None,
) -> bool:
    """Use the stored target first, preserving the intended View3D route."""
    def insert_target() -> bool:
        """The override is active here, so the operator poll is meaningful."""
        if not bpy.ops.font.text_insert.poll():
            return False
        if font_space_leak is not None and _repair_confirm_space_leak(
            text,
            target,
            font_space_leak,
        ):
            return True
        bpy.ops.font.text_insert(text=text)
        return True

    return bool(run_with_target_context(target, insert_target))


def insert_from_active_context(text: str) -> bool:
    """Last resort for an active Font edit object without a trusted target."""
    try:
        obj = bpy.context.object
        if obj is None or obj.type != "FONT" or obj.mode != "EDIT":
            return False
        wm = bpy.context.window_manager
        windows = tuple(wm.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        return False

    for window in windows:
        try:
            screen = window.screen
            areas = tuple(screen.areas)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for area in areas:
            try:
                if area.type != "VIEW_3D":
                    continue
                region = platform_api.window_region(area)
                if region is None:
                    continue
                with bpy.context.temp_override(
                    window=window,
                    screen=screen,
                    area=area,
                    region=region,
                    active_object=obj,
                    object=obj,
                    edit_object=obj,
                ):
                    if bpy.ops.font.text_insert.poll():
                        bpy.ops.font.text_insert(text=text)
                        return True
            except (AttributeError, ReferenceError, RuntimeError, ValueError):
                continue
    return False


def insert(
    text: str,
    target: object = None,
    font_space_leak: object = None,
) -> bool:
    """Commit IME text into 3D Text edit mode."""
    if models.is_font_edit_target(target):
        return insert_with_target(text, target, font_space_leak)
    if target is not None:
        return False
    return insert_from_active_context(text)
