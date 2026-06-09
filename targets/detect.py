"""Target lookup for the Blender editors IMEBridge supports."""

from collections.abc import Iterator

import bpy

from ..core import models
from ..win32 import api as win32_api


TARGET_TEXT_EDITOR = models.TARGET_TEXT_EDITOR
TARGET_FONT_EDIT = models.TARGET_FONT_EDIT


def make_text_editor_target(
    window: object,
    area: object,
    region: object,
    space: object,
) -> models.TextEditorTarget | None:
    """Bind a Text Editor area to its current text datablock."""
    text = getattr(space, "text", None)
    if text is None:
        return None
    return models.TextEditorTarget(
        window=window,
        screen=window.screen,
        area=area,
        region=region,
        space=space,
        text=text,
    )


def make_text_editor_target_from_context(
    context: object,
) -> models.TextEditorTarget | None:
    """Use the active context only, so other editors keep their focus."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if window is None or area is None or area.type != "TEXT_EDITOR":
        return None

    region = win32_api.window_region(area)
    space = area.spaces.active
    if region is None or space is None:
        return None
    return make_text_editor_target(window, area, region, space)


def iter_font_object_candidates(context: object = None) -> Iterator[object]:
    """Walk Blender's usual object handles before scanning edited Font data."""
    contexts = []
    if context is not None:
        contexts.append(context)
    if bpy.context not in contexts:
        contexts.append(bpy.context)

    seen = set()

    def emit(obj: object) -> Iterator[object]:
        """Keep each Font object once, even when Blender exposes it twice."""
        if obj is None or getattr(obj, "type", None) != "FONT":
            return
        pointer = win32_api.ptr_value(obj.as_pointer())
        if pointer in seen:
            return
        seen.add(pointer)
        yield obj

    for ctx in contexts:
        for attr in ("edit_object", "object", "active_object"):
            yield from emit(getattr(ctx, attr, None))

        view_layer = getattr(ctx, "view_layer", None)
        objects = getattr(view_layer, "objects", None)
        yield from emit(getattr(objects, "active", None))

        for obj in getattr(ctx, "selected_objects", None) or []:
            yield from emit(obj)

    for obj in bpy.data.objects:
        if (
            getattr(obj, "type", None) == "FONT"
            and getattr(obj, "mode", None) == "EDIT"
        ):
            yield from emit(obj)


def font_object_for_ime(
    context: object = None,
    require_edit: bool = True,
) -> object | None:
    """Prefer the Font object that is already in edit mode."""
    fallback = None
    for obj in iter_font_object_candidates(context):
        if fallback is None:
            fallback = obj
        if getattr(obj, "mode", None) == "EDIT":
            return obj
    if require_edit:
        return None
    return fallback


def active_font_edit_object(context: object = None) -> object | None:
    """Strict lookup for the edited Font object used by 3D Text input."""
    return font_object_for_ime(context, require_edit=True)


def make_font_edit_target(
    window: object,
    area: object,
    region: object,
    space: object,
    context: object = None,
) -> models.FontEditTarget | None:
    """Bind a View3D area to the Font object currently being edited."""
    obj = active_font_edit_object(context)
    if obj is None:
        return None
    return models.FontEditTarget(
        window=window,
        screen=window.screen,
        area=area,
        region=region,
        space=space,
        obj=obj,
        data=obj.data,
    )


def make_font_edit_target_from_context(
    context: object,
) -> models.FontEditTarget | None:
    """A direct Font target is only trustworthy inside a live View3D context."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if window is None or area is None or area.type != "VIEW_3D":
        return None

    region = win32_api.window_region(area)
    space = area.spaces.active
    if region is None or space is None:
        return None
    return make_font_edit_target(window, area, region, space, context)


def find_font_edit_target(context: object = None) -> models.FontEditTarget | None:
    """Search visible View3D areas for one that can host the edited Font."""
    if active_font_edit_object(context) is None:
        return None

    current = make_font_edit_target_from_context(context or bpy.context)
    if current is not None:
        return current

    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = win32_api.window_region(area)
            space = area.spaces.active
            if region is None or space is None:
                continue
            target = make_font_edit_target(window, area, region, space, context)
            if target is not None:
                return target
    return None


def make_input_target_from_context(context: object) -> object | None:
    """Text Editor is handled first because focus matters more there."""
    target = make_text_editor_target_from_context(context)
    if target is not None:
        return target
    return make_font_edit_target_from_context(context)


def is_supported_input_target(target: object) -> bool:
    """Keep commits away from unrelated Blender state."""
    return models.is_text_editor_target(target) or models.is_font_edit_target(target)


def resolve_input_target(
    composition_target: object = None,
    active_target: object = None,
    context: object = None,
) -> object | None:
    """Delay target choice; IME composition can outlive Blender focus changes."""
    if is_supported_input_target(composition_target):
        return composition_target

    current_target = make_input_target_from_context(context or bpy.context)
    if is_supported_input_target(current_target):
        return current_target

    if is_supported_input_target(active_target):
        return active_target

    return find_font_edit_target(context)


def target_context(target: object) -> dict[str, object] | None:
    """This is the smallest temp override Blender operators need."""
    if target is None:
        return None

    window = getattr(target, "window", None)
    screen = getattr(target, "screen", None) or getattr(window, "screen", None)
    area = getattr(target, "area", None)
    region = getattr(target, "region", None)
    space = getattr(target, "space", None)
    if window is None or screen is None or area is None or region is None:
        return None

    return {
        "window": window,
        "screen": screen,
        "area": area,
        "region": region,
        "space": space,
    }
