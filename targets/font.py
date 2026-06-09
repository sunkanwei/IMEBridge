"""3D Text insertion helpers."""

from collections.abc import Callable

import bpy

from ..core import models
from ..win32 import api as win32_api
from . import detect as targets


def target_can_accept_insert(target: object) -> bool:
    """Reject stored Font targets that have clearly gone stale."""
    if not models.is_font_edit_target(target):
        return False
    obj = target.obj
    if obj is None or obj.type != "FONT":
        return False
    current = targets.active_font_edit_object()
    return current is None or current == obj


def run_with_target_context(target: object, callback: Callable[[], bool]) -> bool:
    """Font operators need a View3D override with the edited object."""
    if not target_can_accept_insert(target):
        return False

    context = targets.target_context(target)
    if context is None or context["space"] is None or target.obj is None:
        return False

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


def insert_with_target(text: str, target: object) -> bool:
    """Use the stored target first, preserving the intended View3D route."""
    def insert_target() -> bool:
        """The override is active here, so the operator poll is meaningful."""
        if not bpy.ops.font.text_insert.poll():
            return False
        bpy.ops.font.text_insert(text=text)
        return True

    return bool(run_with_target_context(target, insert_target))


def insert_from_active_context(text: str) -> bool:
    """Last resort for an active Font edit object without a trusted target."""
    obj = bpy.context.object
    if obj is None or obj.type != "FONT" or obj.mode != "EDIT":
        return False

    wm = bpy.context.window_manager
    for window in wm.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = win32_api.window_region(area)
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
    return False


def insert(text: str, target: object = None) -> bool:
    """Commit IME text into 3D Text edit mode."""
    if models.is_font_edit_target(target):
        if insert_with_target(text, target):
            return True
    return insert_from_active_context(text)
