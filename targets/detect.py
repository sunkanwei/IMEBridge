"""Target lookup for the Blender editors IMEBridge supports."""

from collections.abc import Iterator

import bpy

from ..core import models
from ..platforms import native as platform_api


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

    try:
        region = platform_api.window_region(area)
        space = area.spaces.active
    except (AttributeError, ReferenceError, RuntimeError):
        return None
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
        try:
            if obj is None or getattr(obj, "type", None) != "FONT":
                return
            pointer = platform_api.ptr_value(obj.as_pointer())
        except (AttributeError, ReferenceError, RuntimeError):
            return
        if pointer in seen:
            return
        seen.add(pointer)
        yield obj

    for ctx in contexts:
        for attr in ("edit_object", "object", "active_object"):
            yield from emit(getattr(ctx, attr, None))

        try:
            view_layer = getattr(ctx, "view_layer", None)
            objects = getattr(view_layer, "objects", None)
            active = getattr(objects, "active", None)
        except (AttributeError, ReferenceError, RuntimeError):
            active = None
        yield from emit(active)

        try:
            selected_objects = tuple(getattr(ctx, "selected_objects", None) or ())
        except (AttributeError, ReferenceError, RuntimeError):
            selected_objects = ()
        for obj in selected_objects:
            yield from emit(obj)

    try:
        data_objects = tuple(bpy.data.objects)
    except (AttributeError, ReferenceError, RuntimeError):
        data_objects = ()
    for obj in data_objects:
        try:
            is_edited_font = (
                getattr(obj, "type", None) == "FONT"
                and getattr(obj, "mode", None) == "EDIT"
            )
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        if is_edited_font:
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
        try:
            if getattr(obj, "mode", None) == "EDIT":
                return obj
        except (AttributeError, ReferenceError, RuntimeError):
            continue
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
    try:
        screen = window.screen
    except (AttributeError, ReferenceError, RuntimeError):
        return None
    return models.FontEditTarget(
        window=window,
        screen=screen,
        area=area,
        region=region,
        space=space,
        obj=obj,
    )


def make_font_edit_target_from_context(
    context: object,
) -> models.FontEditTarget | None:
    """A direct Font target is only trustworthy inside a live View3D context."""
    window = getattr(context, "window", None)
    area = getattr(context, "area", None)
    if window is None or area is None or area.type != "VIEW_3D":
        return None

    try:
        region = platform_api.window_region(area)
        space = area.spaces.active
    except (AttributeError, ReferenceError, RuntimeError):
        return None
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

    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        windows = ()
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
                space = area.spaces.active
            except (AttributeError, ReferenceError, RuntimeError):
                continue
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


def is_live_text_editor_target(target: object) -> bool:
    """Reject Text targets whose RNA context no longer points at the datablock."""
    if not models.is_text_editor_target(target):
        return False
    try:
        context = target_context(target)
        if context is None or context["space"] is None:
            return False
        area = context["area"]
        if getattr(area, "type", None) != "TEXT_EDITOR":
            return False
        if getattr(area.spaces, "active", None) != target.space:
            return False
        if not any(region == target.region for region in area.regions):
            return False
        return getattr(context["space"], "text", None) == target.text
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def is_live_font_edit_target(target: object) -> bool:
    """Reject Font targets that no longer represent the edited object."""
    if not models.is_font_edit_target(target):
        return False
    try:
        obj = target.obj
        if obj is None or getattr(obj, "type", None) != "FONT":
            return False
        if getattr(obj, "mode", None) != "EDIT":
            return False
        current = active_font_edit_object()
        return current is None or current == obj
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def is_usable_input_target(target: object) -> bool:
    """Check both target type and the minimum live Blender RNA it needs."""
    return is_live_text_editor_target(target) or is_live_font_edit_target(target)


def resolve_input_target(
    composition_target: object = None,
    active_target: object = None,
    context: object = None,
) -> object | None:
    """Delay target choice; IME composition can outlive Blender focus changes."""
    if is_usable_input_target(composition_target):
        return composition_target

    current_target = make_input_target_from_context(context or bpy.context)
    if is_usable_input_target(current_target):
        return current_target

    if is_usable_input_target(active_target):
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
