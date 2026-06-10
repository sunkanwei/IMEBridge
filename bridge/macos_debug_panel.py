"""macOS-only diagnostics panel for verifying the Cocoa IME bridge."""

from __future__ import annotations

import ctypes
import ctypes.util
import time
import traceback

import bpy

from . import ime_context
from . import macos_event_bridge
from . import window_hook
from ..core import models
from ..core import runtime
from ..core import safe_ops
from ..platforms import native as platform_api
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import state as target_state


LOG_TEXT_NAME = "IMEBridge_macOS_Diagnostics"
DEBUG_TEXT_PROP = "imebridge_macos_debug_text"
MONITOR_INTERVAL = 0.1
MONITOR_SECONDS = 30.0

_TRACE_ACTIVE = False
_MARKED_TRACE_ACTIVE = False
_MARKED_TRACE_CALLBACKS: list[object] = []
_MARKED_TRACE_RECORDS: list[dict[str, object]] = []
_KEY_TRACE_ACTIVE = False
_KEY_TRACE_CALLBACKS: list[object] = []
_KEY_TRACE_RECORDS: list[dict[str, object]] = []
_KEY_TRACE_COUNT = 0
_LAST_UNMARK_LOG_AT = 0.0
_UNMARK_SUPPRESSED = 0
_MONITOR_ACTIVE = False
_MONITOR_STARTED_AT = 0.0
_MONITOR_TICK = 0
_DIAGNOSTIC_TARGET = None
_DIAGNOSTIC_HWND = None
_LAST_MONITOR_SIGNATURE = ""


def _log(message: object) -> None:
    """Write one diagnostic line to the console and a Blender Text datablock."""
    stamp = time.strftime("%H:%M:%S")
    line = f"[{stamp}] {message}"
    print(f"[IMEBridge macOS] {line}")
    try:
        text = bpy.data.texts.get(LOG_TEXT_NAME) or bpy.data.texts.new(LOG_TEXT_NAME)
        text.write(line + "\n")
    except (AttributeError, ReferenceError, RuntimeError):
        return


def _clear_log() -> None:
    """Clear the shared diagnostic Text datablock."""
    text = bpy.data.texts.get(LOG_TEXT_NAME) or bpy.data.texts.new(LOG_TEXT_NAME)
    text.clear()


def _rect_tuple(rect: object) -> object:
    """Format a RECT-like object without caring about its exact backend type."""
    if rect is None:
        return None
    return (
        getattr(rect, "left", None),
        getattr(rect, "top", None),
        getattr(rect, "right", None),
        getattr(rect, "bottom", None),
    )


def _range_tuple(value: object) -> tuple[object, object]:
    """Format an NSRange-like value for logs."""
    return (
        getattr(value, "location", None),
        getattr(value, "length", None),
    )


def _objc_class_name(api: object, obj: int) -> str:
    """Return an Objective-C object's runtime class name for diagnostics."""
    if not api or not obj:
        return ""
    try:
        object_get_class_name = api.objc.lib.object_getClassName
        object_get_class_name.argtypes = [ctypes.c_void_p]
        object_get_class_name.restype = ctypes.c_char_p
        data = object_get_class_name(obj)
    except (AttributeError, OSError, ValueError):
        return ""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeError:
        return ""


def _objc_subviews(api: object, view: int) -> list[int]:
    """Read child views from an NSView-like object."""
    if not api or not view or not api.objc.responds(view, api.objc.subviews):
        return []
    try:
        subviews = api.objc.send_id(view, api.objc.subviews)
        if not subviews:
            return []
        count = int(api.objc.send_ulong(subviews, api.objc.count))
        return [
            int(api.objc.send_id_ulong(subviews, api.objc.object_at_index, index) or 0)
            for index in range(count)
        ]
    except (OSError, ValueError):
        return []


def _objc_text(api: object, obj: int, selector_name: str) -> str:
    """Read a string property from an Objective-C object."""
    if not api or not obj:
        return ""
    try:
        selector = api.objc.sel(selector_name)
        value = api.objc.send_id(obj, selector)
    except (OSError, ValueError):
        return ""
    return api.text_from_objc_string(value)


def _objc_ulong(api: object, obj: int, selector_name: str) -> object:
    """Read an unsigned integer property from an Objective-C object."""
    if not api or not obj:
        return None
    try:
        selector = api.objc.sel(selector_name)
        return int(api.objc.send_ulong(obj, selector))
    except (OSError, TypeError, ValueError):
        return None


def _current_input_source_snapshot(api: object) -> str:
    """Return Blender-equivalent macOS input source state for diagnostics."""
    if api is None:
        return "input_source unavailable: no native api"

    carbon_path = ctypes.util.find_library("Carbon")
    core_foundation_path = ctypes.util.find_library("CoreFoundation")
    if not carbon_path or not core_foundation_path:
        return "input_source unavailable: missing Carbon/CoreFoundation"

    try:
        carbon = ctypes.CDLL(carbon_path)
        core_foundation = ctypes.CDLL(core_foundation_path)
        carbon.TISCopyCurrentKeyboardInputSource.argtypes = []
        carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        core_foundation.CFBooleanGetValue.argtypes = [ctypes.c_void_p]
        core_foundation.CFBooleanGetValue.restype = ctypes.c_bool
        core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        core_foundation.CFRelease.restype = None
    except (AttributeError, OSError, TypeError):
        return "input_source unavailable: failed to load Carbon API"

    def property_key(name: str) -> int:
        try:
            return int(ctypes.c_void_p.in_dll(carbon, name).value or 0)
        except (TypeError, ValueError):
            return 0

    source = 0
    try:
        source = int(carbon.TISCopyCurrentKeyboardInputSource() or 0)
        if not source:
            return "input_source unavailable: no current source"

        def read_text(name: str) -> str:
            key = property_key(name)
            if not key:
                return ""
            value = carbon.TISGetInputSourceProperty(source, key)
            return api.text_from_objc_string(value)

        def read_bool(name: str) -> object:
            key = property_key(name)
            if not key:
                return None
            value = carbon.TISGetInputSourceProperty(source, key)
            if not value:
                return None
            return bool(core_foundation.CFBooleanGetValue(value))

        source_id = read_text("kTISPropertyInputSourceID")
        mode_id = read_text("kTISPropertyInputModeID")
        name = read_text("kTISPropertyLocalizedName")
        ascii_capable = read_bool("kTISPropertyInputSourceIsASCIICapable")
        return (
            "input_source: "
            f"name={name!r} id={source_id!r} mode={mode_id!r} "
            f"ascii_capable={ascii_capable}"
        )
    except (AttributeError, OSError, TypeError, ValueError):
        return "input_source unavailable: property read failed"
    finally:
        if source:
            try:
                core_foundation.CFRelease(source)
            except (NameError, OSError, TypeError, ValueError):
                pass


def _debug_first_ime_view(api: object, view: int, depth: int = 0) -> int:
    """Find a Cocoa view with Blender IME methods using a diagnostic depth."""
    if not view or depth > 8:
        return 0
    if api.objc.responds(view, api.objc.begin_ime):
        return int(view)
    for child in _objc_subviews(api, view):
        match = _debug_first_ime_view(api, child, depth + 1)
        if match:
            return match
    return 0


def _iter_ns_windows(api: object) -> list[int]:
    """Return NSApplication windows for diagnostics."""
    if not api:
        return []
    try:
        app = api.application()
        windows_sel = api.objc.sel("windows")
        windows = api.objc.send_id(app, windows_sel)
        if not windows:
            return []
        count = int(api.objc.send_ulong(windows, api.objc.count))
        return [
            int(api.objc.send_id_ulong(windows, api.objc.object_at_index, index) or 0)
            for index in range(count)
        ]
    except (OSError, ValueError):
        return []


def _debug_active_ime_view(api: object) -> tuple[int, str]:
    """Find the IME view with fallback paths used only by diagnostics."""
    if api is None:
        return 0, "no-api"

    view = api.active_view()
    if view:
        return int(view), "active_view"

    window = api.active_ns_window()
    if window:
        try:
            content = api.objc.send_id(window, api.objc.content_view)
        except (OSError, ValueError):
            content = 0
        view = _debug_first_ime_view(api, int(content or 0))
        if view:
            return view, "active_window_deep"

    for index, window in enumerate(_iter_ns_windows(api)):
        try:
            content = api.objc.send_id(window, api.objc.content_view)
        except (OSError, ValueError):
            continue
        view = _debug_first_ime_view(api, int(content or 0))
        if view:
            return view, f"windows[{index}]_deep"
    return 0, "missing"


def _visible_ime_views(api: object) -> list[tuple[int, int, int, str, float]]:
    """Return visible NSWindows and their first IME-capable Cocoa view."""
    if api is None:
        return []

    views: list[tuple[int, int, int, str, float]] = []
    for index, window in enumerate(_iter_ns_windows(api)):
        try:
            if api.objc.responds(window, api.objc.is_visible):
                if not api.objc.send_bool(window, api.objc.is_visible):
                    continue
            content = api.objc.send_id(window, api.objc.content_view)
        except (OSError, ValueError):
            continue
        view = _debug_first_ime_view(api, int(content or 0))
        if not view:
            continue
        title = _objc_text(api, window, "title")
        scale = 1.0
        try:
            scale = float(api.backing_scale_factor(window))
        except (AttributeError, OSError, TypeError, ValueError):
            scale = 1.0
        views.append((index, int(window), int(view), title, scale))
    return views


def _send_begin_ime_to_view(
    api: object,
    view: int,
    position: object,
    line_height: int,
    scale: float = 1.0,
) -> tuple[bool, tuple[int, int, int]]:
    """Call Blender's private beginIME selector on a specific Cocoa view."""
    scale = scale if scale > 0.0 else 1.0
    try:
        from ..platforms import macos

        y_padding = int(macos.cocoa_candidate_y_padding())
    except (AttributeError, ImportError, TypeError, ValueError):
        y_padding = 0
    raw_x = int(position.screen_x)
    raw_y = int(position.screen_y) + int(line_height or 18) + y_padding
    raw_height = max(12, int(line_height or 18))
    logical = (
        round(raw_x / scale),
        round(raw_y / scale),
        max(12, round(raw_height / scale)),
    )
    try:
        api.objc.send_begin_ime(
            int(view),
            api.objc.begin_ime,
            logical[0],
            logical[1],
            1,
            logical[2],
            False,
        )
    except (OSError, ValueError):
        return False, logical
    return True, logical


def _dump_view_tree(api: object, view: int, *, depth: int = 0, limit: int = 6) -> None:
    """Log a compact Cocoa view tree and IME selector support."""
    if not api or not view or depth > limit:
        return
    indent = "  " * depth
    class_name = _objc_class_name(api, view)
    responds_begin = api.objc.responds(view, api.objc.begin_ime)
    responds_insert = api.objc.responds(view, api.objc.insert_text)
    responds_marked = api.objc.responds(
        view,
        api.objc.sel("setMarkedText:selectedRange:replacementRange:"),
    )
    responds_unmark = api.objc.responds(view, api.objc.sel("unmarkText"))
    children = _objc_subviews(api, view)
    _log(
        f"{indent}view ptr={view} class={class_name} "
        f"beginIME={responds_begin} insertText={responds_insert} "
        f"setMarkedText={responds_marked} unmarkText={responds_unmark} "
        f"children={len(children)}"
    )
    for child in children:
        _dump_view_tree(api, child, depth=depth + 1, limit=limit)


def _target_label(target: object) -> str:
    """Summarize a Blender input target for logs."""
    target_type = models.target_type(target)
    if target_type is None:
        return "None"

    try:
        area_type = getattr(getattr(target, "area", None), "type", None)
        region = getattr(target, "region", None)
        region_box = None
        if region is not None:
            region_box = (
                getattr(region, "x", None),
                getattr(region, "y", None),
                getattr(region, "width", None),
                getattr(region, "height", None),
            )
        if models.is_text_editor_target(target):
            text = getattr(target, "text", None)
            name = getattr(text, "name", None)
            return f"{target_type}(area={area_type}, text={name}, region={region_box})"
        if models.is_font_edit_target(target):
            obj = getattr(target, "obj", None)
            name = getattr(obj, "name", None)
            mode = getattr(obj, "mode", None)
            return f"{target_type}(area={area_type}, obj={name}, mode={mode}, region={region_box})"
    except (AttributeError, ReferenceError, RuntimeError):
        return f"{target_type}(stale)"
    return str(target_type)


def _context_target(context: object = None) -> object | None:
    """Pick the target the macOS bridge should use for the current UI state."""
    context = context or bpy.context
    target = targets.make_input_target_from_context(context)
    if target is not None:
        return target
    return targets.find_font_edit_target(context)


def _target_key(target: object) -> tuple[object, ...]:
    """Build a stable-ish key for diagnostic target de-duplication."""
    try:
        window = getattr(target, "window", None)
        area = getattr(target, "area", None)
        payload = getattr(target, "text", None) or getattr(target, "obj", None)
        return (
            models.target_type(target),
            platform_api.ptr_value(window.as_pointer()) if window else 0,
            platform_api.ptr_value(area.as_pointer()) if area else 0,
            platform_api.ptr_value(payload.as_pointer()) if payload else 0,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return (models.target_type(target), id(target))


def _append_target(targets_out: list[object], seen: set[tuple[object, ...]], target: object) -> None:
    """Append a usable diagnostic target once."""
    if not targets.is_usable_input_target(target):
        return
    key = _target_key(target)
    if key in seen:
        return
    seen.add(key)
    targets_out.append(target)


def _scan_text_editor_targets() -> list[object]:
    """Find Text Editor targets across all Blender windows."""
    found = []
    seen = set()
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        windows = ()

    for window in windows:
        try:
            areas = tuple(window.screen.areas)
        except (AttributeError, ReferenceError, RuntimeError):
            continue
        for area in areas:
            try:
                if area.type != "TEXT_EDITOR":
                    continue
                region = platform_api.window_region(area)
                space = area.spaces.active
            except (AttributeError, ReferenceError, RuntimeError):
                continue
            if region is None or space is None:
                continue
            _append_target(
                found,
                seen,
                targets.make_text_editor_target(window, area, region, space),
            )
    return found


def _scan_font_edit_targets(context: object = None) -> list[object]:
    """Find visible View3D routes for the edited 3D Text object."""
    if targets.active_font_edit_object(context or bpy.context) is None:
        return []

    found = []
    seen = set()
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        windows = ()

    for window in windows:
        try:
            areas = tuple(window.screen.areas)
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
            _append_target(
                found,
                seen,
                targets.make_font_edit_target(window, area, region, space, context),
            )
    return found


def _discover_targets(context: object = None) -> list[object]:
    """Find diagnostic targets from context first, then from all windows."""
    found = []
    seen = set()
    _append_target(found, seen, _context_target(context))
    for target in _scan_text_editor_targets():
        _append_target(found, seen, target)
    for target in _scan_font_edit_targets(context):
        _append_target(found, seen, target)
    return found


def _log_discovered_targets(candidates: list[object]) -> None:
    """Log the target candidates considered by automatic acquisition."""
    _log(f"target candidates = {len(candidates)}")
    for index, target in enumerate(candidates):
        _log(f"target candidate[{index}] = {_target_label(target)}")


def _target_hwnd(target: object) -> object:
    """Use the target's Blender window key when one is available."""
    window = getattr(target, "window", None)
    try:
        if window is not None:
            return platform_api.ptr_value(window.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        pass
    return macos_event_bridge.active_hwnd()


def _locked_target(context: object = None) -> object | None:
    """Prefer the target captured when full diagnostics started."""
    if targets.is_usable_input_target(_DIAGNOSTIC_TARGET):
        return _DIAGNOSTIC_TARGET
    return _context_target(context)


def _lock_target(context: object = None) -> object | None:
    """Capture the current target so timers can keep diagnosing it."""
    global _DIAGNOSTIC_TARGET, _DIAGNOSTIC_HWND

    candidates = _discover_targets(context)
    target = candidates[0] if candidates else None
    hwnd = _target_hwnd(target)
    _DIAGNOSTIC_TARGET = target if targets.is_usable_input_target(target) else None
    _DIAGNOSTIC_HWND = hwnd
    if _DIAGNOSTIC_TARGET is not None:
        macos_event_bridge.activate_target(_DIAGNOSTIC_TARGET, hwnd)
    return _DIAGNOSTIC_TARGET


def _acquire_target_if_needed(context: object = None) -> bool:
    """Automatically lock the first available target during diagnostics."""
    if targets.is_usable_input_target(_DIAGNOSTIC_TARGET):
        return True
    candidates = _discover_targets(context)
    if not candidates:
        return False
    _log("target acquired during monitor")
    _log_discovered_targets(candidates)
    _lock_target(context)
    _log(f"locked target = {_target_label(_DIAGNOSTIC_TARGET)}")
    _force_begin_ime(context)
    return True


def _clear_locked_target() -> None:
    """Forget any target captured by the diagnostic session."""
    global _DIAGNOSTIC_TARGET, _DIAGNOSTIC_HWND, _LAST_MONITOR_SIGNATURE

    _DIAGNOSTIC_TARGET = None
    _DIAGNOSTIC_HWND = None
    _LAST_MONITOR_SIGNATURE = ""


def _candidate_snapshot(target: object, hwnd: object) -> tuple[object, object]:
    """Collect candidate geometry without moving the IME window."""
    api = platform_api.ensure()
    if api is None or not targets.is_usable_input_target(target):
        return None, None
    info = ime_context.candidate_info_for_target(api, hwnd, target)
    if info is None:
        return None, None
    position = ime_context.candidate_position_for_target(info, target)
    return info, position


def _log_candidate_details(target: object, hwnd: object) -> None:
    """Log client, target, and candidate geometry in the same place."""
    api = platform_api.ensure()
    if api is None:
        _log("candidate: no native api")
        return
    client = platform_api.client_rect(api, hwnd)
    info, position = _candidate_snapshot(target, hwnd)
    _log(f"client rect = {_rect_tuple(client)}")
    _log(f"candidate info = {info!r}")
    _log(f"candidate position = {position!r}")
    if info is not None:
        _log(f"candidate info rect = {_rect_tuple(info.rect)}")


def _dump_status(context: object = None, *, compact: bool = False) -> None:
    """Dump the current bridge state needed to explain macOS IME failures."""
    context = context or bpy.context
    api = platform_api.ensure()
    hwnd = macos_event_bridge.active_hwnd()
    context_target = _context_target(context)
    target = _locked_target(context)
    active_target = runtime.state.active_target
    records = getattr(api, "_insert_text_records", {}) if api is not None else {}
    view = api.active_view() if api is not None else 0
    debug_view, debug_view_source = _debug_active_ime_view(api)
    area = getattr(context, "area", None)

    _log(
        "status: "
        f"backend={platform_api.backend_name()} "
        f"supports={platform_api.supports_native_bridge()} "
        f"running={macos_event_bridge.is_running()} "
        f"trace={_TRACE_ACTIVE} "
        f"marked_trace={_MARKED_TRACE_ACTIVE} "
        f"key_trace={_KEY_TRACE_ACTIVE} "
        f"area={getattr(area, 'type', None)} "
        f"hwnd={hwnd} "
        f"view={view} "
        f"debug_view={debug_view}({debug_view_source}) "
        f"hook_records={len(records)}"
    )
    _log(
        "runtime: "
        f"insert_on_commit={runtime.state.insert_on_commit} "
        f"pending={len(runtime.state.pending_inserts)} "
        f"insert_timer={runtime.state.insert_timer_registered} "
        f"auto_enable={runtime.state.auto_enable_timer_registered} "
        f"auto_arm={runtime.state.auto_arm_timer_registered}"
    )
    _log(f"context target = {_target_label(context_target)}")
    _log(f"context target usable = {targets.is_usable_input_target(context_target)}")
    _log(f"locked target = {_target_label(_DIAGNOSTIC_TARGET)}")
    _log(f"diagnostic target = {_target_label(target)}")
    _log(f"diagnostic target usable = {targets.is_usable_input_target(target)}")
    _log(f"active target = {_target_label(active_target)}")
    _log(_current_input_source_snapshot(api))
    if not compact:
        _log_candidate_details(target, _DIAGNOSTIC_HWND or hwnd)


def _ensure_bridge(context: object) -> int:
    """Start the bridge through the same lifecycle path used by the add-on."""
    _restored, started = window_hook.initialize_input_bridge(context)
    return int(started)


def _trace_commit_handler(text: str) -> bool:
    """Log real Cocoa commits before passing them to the normal macOS handler."""
    _log(f"Cocoa insertText callback text = {text!r}")
    try:
        result = macos_event_bridge.handle_committed_text(text)
    except Exception:
        _log(traceback.format_exc())
        return False
    _log(
        "handle_committed_text: "
        f"result={result} pending={len(runtime.state.pending_inserts)} "
        f"active={_target_label(runtime.state.active_target)}"
    )

    if not result and targets.is_usable_input_target(_DIAGNOSTIC_TARGET):
        hwnd = _DIAGNOSTIC_HWND or macos_event_bridge.active_hwnd()
        text_session = None
        if models.is_text_editor_target(_DIAGNOSTIC_TARGET):
            text_session = runtime.state.text_ime_session.active_for_text(
                _DIAGNOSTIC_TARGET.text
            )
        insert_queue.queue(
            text,
            _DIAGNOSTIC_TARGET,
            text_session,
            hwnd=hwnd,
            source=insert_queue.SOURCE_IME_RESULT,
        )
        macos_event_bridge.update_candidate(_DIAGNOSTIC_TARGET, hwnd, force=True)
        result = True
        _log(
            "diagnostic locked-target fallback queued: "
            f"pending={len(runtime.state.pending_inserts)} "
            f"target={_target_label(_DIAGNOSTIC_TARGET)}"
        )
    return bool(result)


def _install_trace_handler(context: object) -> int:
    """Replace the commit handler with a logging wrapper."""
    global _TRACE_ACTIVE

    _ensure_bridge(context)
    install_hook = getattr(platform_api, "install_text_commit_hook", None)
    installed = int(install_hook(_trace_commit_handler)) if callable(install_hook) else 0
    _TRACE_ACTIVE = installed > 0
    return installed


def _restore_normal_commit_handler() -> int:
    """Restore the normal commit handler while keeping the hook installed."""
    global _TRACE_ACTIVE

    install_hook = getattr(platform_api, "install_text_commit_hook", None)
    installed = 0
    if callable(install_hook) and macos_event_bridge.is_running():
        installed = int(install_hook(macos_event_bridge.handle_committed_text))
    _TRACE_ACTIVE = False
    return installed


def _install_marked_text_trace_hooks() -> int:
    """Trace Cocoa composition callbacks during diagnostics."""
    global _LAST_UNMARK_LOG_AT, _MARKED_TRACE_ACTIVE, _UNMARK_SUPPRESSED

    from ..platforms import macos

    if _MARKED_TRACE_RECORDS:
        _MARKED_TRACE_ACTIVE = True
        return len(_MARKED_TRACE_RECORDS)

    _LAST_UNMARK_LOG_AT = 0.0
    _UNMARK_SUPPRESSED = 0
    api = platform_api.ensure()
    if api is None:
        return 0

    installed = 0
    set_marked_selector = api.objc.sel("setMarkedText:selectedRange:replacementRange:")
    unmark_selector = api.objc.sel("unmarkText")
    set_marked_type = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        macos.NSRange,
        macos.NSRange,
    )
    unmark_type = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    for class_name in ("CocoaMetalView", "CocoaOpenGLView"):
        cls = api.objc.cls(class_name)
        if not cls:
            continue

        try:
            method = platform_api.ptr_value(
                api.objc.class_getInstanceMethod(cls, set_marked_selector)
            )
            old_imp = platform_api.ptr_value(api.objc.method_getImplementation(method))
        except (OSError, TypeError, ValueError):
            method = 0
            old_imp = 0
        if method and old_imp:
            original = set_marked_type(old_imp)

            def set_marked_callback(
                obj: int,
                selector: int,
                text_obj: int,
                selected_range: object,
                replacement_range: object,
                *,
                original: object = original,
                class_name: str = class_name,
            ) -> None:
                text = api.text_from_objc_string(text_obj)
                _log(
                    "Cocoa setMarkedText callback: "
                    f"class={class_name} text={text!r} "
                    f"selected={_range_tuple(selected_range)} "
                    f"replacement={_range_tuple(replacement_range)}"
                )
                original(obj, selector, text_obj, selected_range, replacement_range)

            callback = set_marked_type(set_marked_callback)
            callback_ptr = ctypes.cast(callback, ctypes.c_void_p).value
            if callback_ptr:
                try:
                    previous = platform_api.ptr_value(
                        api.objc.method_setImplementation(method, callback_ptr)
                    )
                except (OSError, TypeError, ValueError):
                    previous = 0
                if previous:
                    _MARKED_TRACE_CALLBACKS.append(callback)
                    _MARKED_TRACE_RECORDS.append(
                        {
                            "method": method,
                            "old_imp": previous,
                            "selector": "setMarkedText",
                            "class": class_name,
                        }
                    )
                    installed += 1

        try:
            method = platform_api.ptr_value(
                api.objc.class_getInstanceMethod(cls, unmark_selector)
            )
            old_imp = platform_api.ptr_value(api.objc.method_getImplementation(method))
        except (OSError, TypeError, ValueError):
            method = 0
            old_imp = 0
        if method and old_imp:
            original = unmark_type(old_imp)

            def unmark_callback(
                obj: int,
                selector: int,
                *,
                original: object = original,
                class_name: str = class_name,
            ) -> None:
                global _LAST_UNMARK_LOG_AT, _UNMARK_SUPPRESSED

                now = time.monotonic()
                if now - _LAST_UNMARK_LOG_AT >= 1.0:
                    suffix = (
                        f" suppressed={_UNMARK_SUPPRESSED}"
                        if _UNMARK_SUPPRESSED
                        else ""
                    )
                    _log(f"Cocoa unmarkText callback: class={class_name}{suffix}")
                    _LAST_UNMARK_LOG_AT = now
                    _UNMARK_SUPPRESSED = 0
                else:
                    _UNMARK_SUPPRESSED += 1
                original(obj, selector)

            callback = unmark_type(unmark_callback)
            callback_ptr = ctypes.cast(callback, ctypes.c_void_p).value
            if callback_ptr:
                try:
                    previous = platform_api.ptr_value(
                        api.objc.method_setImplementation(method, callback_ptr)
                    )
                except (OSError, TypeError, ValueError):
                    previous = 0
                if previous:
                    _MARKED_TRACE_CALLBACKS.append(callback)
                    _MARKED_TRACE_RECORDS.append(
                        {
                            "method": method,
                            "old_imp": previous,
                            "selector": "unmarkText",
                            "class": class_name,
                        }
                    )
                    installed += 1

    _MARKED_TRACE_ACTIVE = installed > 0
    return installed


def _restore_marked_text_trace_hooks() -> int:
    """Restore Cocoa composition methods patched by diagnostics."""
    global _MARKED_TRACE_ACTIVE, _UNMARK_SUPPRESSED

    api = platform_api.ensure()
    restored = 0
    if api is not None:
        for record in list(_MARKED_TRACE_RECORDS):
            method = platform_api.ptr_value(record.get("method"))
            old_imp = platform_api.ptr_value(record.get("old_imp"))
            if not method or not old_imp:
                continue
            try:
                api.objc.method_setImplementation(method, old_imp)
                restored += 1
            except (OSError, TypeError, ValueError):
                pass
    _MARKED_TRACE_RECORDS.clear()
    _MARKED_TRACE_CALLBACKS.clear()
    _MARKED_TRACE_ACTIVE = False
    if _UNMARK_SUPPRESSED:
        _log(f"Cocoa unmarkText suppressed total = {_UNMARK_SUPPRESSED}")
        _UNMARK_SUPPRESSED = 0
    return restored


def _install_key_down_trace_hooks() -> int:
    """Trace Cocoa keyDown events before Blender decides whether IME handles them."""
    global _KEY_TRACE_ACTIVE, _KEY_TRACE_COUNT

    if _KEY_TRACE_RECORDS:
        _KEY_TRACE_ACTIVE = True
        return len(_KEY_TRACE_RECORDS)

    api = platform_api.ensure()
    if api is None:
        return 0

    installed = 0
    _KEY_TRACE_COUNT = 0
    key_down_selector = api.objc.sel("keyDown:")
    key_down_type = ctypes.CFUNCTYPE(
        None,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
    )

    for class_name in ("CocoaMetalView", "CocoaOpenGLView"):
        cls = api.objc.cls(class_name)
        if not cls:
            continue
        try:
            method = platform_api.ptr_value(
                api.objc.class_getInstanceMethod(cls, key_down_selector)
            )
            old_imp = platform_api.ptr_value(api.objc.method_getImplementation(method))
        except (OSError, TypeError, ValueError):
            method = 0
            old_imp = 0
        if not method or not old_imp:
            continue

        original = key_down_type(old_imp)

        def key_down_callback(
            obj: int,
            selector: int,
            event: int,
            *,
            original: object = original,
            class_name: str = class_name,
        ) -> None:
            global _KEY_TRACE_COUNT

            if _KEY_TRACE_COUNT < 20:
                _KEY_TRACE_COUNT += 1
                event_window = 0
                first_responder = 0
                is_key_window = None
                try:
                    event_window = int(
                        api.objc.send_id(event, api.objc.sel("window")) or 0
                    )
                    if event_window:
                        is_key_window = bool(
                            api.objc.send_bool(
                                event_window,
                                api.objc.sel("isKeyWindow"),
                            )
                        )
                        first_responder = int(
                            api.objc.send_id(
                                event_window,
                                api.objc.sel("firstResponder"),
                            )
                            or 0
                        )
                except (OSError, TypeError, ValueError):
                    event_window = 0
                    first_responder = 0
                    is_key_window = None

                _log(
                    "Cocoa keyDown callback: "
                    f"class={class_name} view={int(obj)} "
                    f"keyCode={_objc_ulong(api, event, 'keyCode')} "
                    f"modifiers={_objc_ulong(api, event, 'modifierFlags')} "
                    f"chars={_objc_text(api, event, 'characters')!r} "
                    f"charsIgnoring={_objc_text(api, event, 'charactersIgnoringModifiers')!r} "
                    f"window={event_window} title={_objc_text(api, event_window, 'title')!r} "
                    f"is_key={is_key_window} "
                    f"first_responder={first_responder} "
                    f"first_class={_objc_class_name(api, first_responder)} "
                    f"{_current_input_source_snapshot(api)}"
                )
            elif _KEY_TRACE_COUNT == 20:
                _KEY_TRACE_COUNT += 1
                _log("Cocoa keyDown callback: further events suppressed")

            original(obj, selector, event)

        callback = key_down_type(key_down_callback)
        callback_ptr = ctypes.cast(callback, ctypes.c_void_p).value
        if not callback_ptr:
            continue
        try:
            previous = platform_api.ptr_value(
                api.objc.method_setImplementation(method, callback_ptr)
            )
        except (OSError, TypeError, ValueError):
            previous = 0
        if previous:
            _KEY_TRACE_CALLBACKS.append(callback)
            _KEY_TRACE_RECORDS.append(
                {
                    "method": method,
                    "old_imp": previous,
                    "selector": "keyDown",
                    "class": class_name,
                }
            )
            installed += 1

    _KEY_TRACE_ACTIVE = installed > 0
    return installed


def _restore_key_down_trace_hooks() -> int:
    """Restore Cocoa keyDown methods patched by diagnostics."""
    global _KEY_TRACE_ACTIVE, _KEY_TRACE_COUNT

    api = platform_api.ensure()
    restored = 0
    if api is not None:
        for record in list(_KEY_TRACE_RECORDS):
            method = platform_api.ptr_value(record.get("method"))
            old_imp = platform_api.ptr_value(record.get("old_imp"))
            if not method or not old_imp:
                continue
            try:
                api.objc.method_setImplementation(method, old_imp)
                restored += 1
            except (OSError, TypeError, ValueError):
                pass
    _KEY_TRACE_RECORDS.clear()
    _KEY_TRACE_CALLBACKS.clear()
    _KEY_TRACE_ACTIVE = False
    _KEY_TRACE_COUNT = 0
    return restored


def _monitor_signature(context: object = None) -> tuple[object, ...]:
    """Build a compact state signature so unchanged ticks stay quiet."""
    context = context or bpy.context
    api = platform_api.ensure()
    hwnd = macos_event_bridge.active_hwnd()
    area = getattr(context, "area", None)
    view = api.active_view() if api is not None else 0
    debug_view, debug_view_source = _debug_active_ime_view(api)
    records = getattr(api, "_insert_text_records", {}) if api is not None else {}
    context_target = _context_target(context)
    target = _locked_target(context)
    return (
        macos_event_bridge.is_running(),
        _TRACE_ACTIVE,
        _MARKED_TRACE_ACTIVE,
        _KEY_TRACE_ACTIVE,
        getattr(area, "type", None),
        hwnd,
        view,
        debug_view,
        debug_view_source,
        len(records),
        _target_label(context_target),
        _target_label(_DIAGNOSTIC_TARGET),
        _target_label(target),
        _target_label(runtime.state.active_target),
        len(runtime.state.pending_inserts),
        runtime.state.insert_timer_registered,
    )


def _monitor_timer() -> float | None:
    """Log a compact bridge snapshot repeatedly while the user types."""
    global _LAST_MONITOR_SIGNATURE, _MONITOR_ACTIVE, _MONITOR_TICK

    if not _MONITOR_ACTIVE:
        return None
    _MONITOR_TICK += 1
    try:
        _acquire_target_if_needed(bpy.context)
        _keep_locked_target_alive()
        signature = _monitor_signature(bpy.context)
        if signature != _LAST_MONITOR_SIGNATURE:
            _LAST_MONITOR_SIGNATURE = signature
            _log(f"monitor tick {_MONITOR_TICK}: state changed")
            _dump_status(bpy.context, compact=True)
    except Exception:
        _log(traceback.format_exc())

    if time.monotonic() - _MONITOR_STARTED_AT >= MONITOR_SECONDS:
        _MONITOR_ACTIVE = False
        _log("monitor finished")
        return None
    return MONITOR_INTERVAL


def _start_monitor() -> bool:
    """Start the repeating diagnostic timer."""
    global _LAST_MONITOR_SIGNATURE, _MONITOR_ACTIVE, _MONITOR_STARTED_AT, _MONITOR_TICK

    _MONITOR_ACTIVE = True
    _MONITOR_STARTED_AT = time.monotonic()
    _MONITOR_TICK = 0
    _LAST_MONITOR_SIGNATURE = ""
    if safe_ops.register_timer(_monitor_timer, first_interval=0.0):
        return True
    _MONITOR_ACTIVE = False
    return False


def _stop_monitor() -> bool:
    """Stop the repeating diagnostic timer."""
    global _MONITOR_ACTIVE

    _MONITOR_ACTIVE = False
    return safe_ops.unregister_timer(_monitor_timer)


def _keep_locked_target_alive() -> bool:
    """Keep the captured target active while diagnostic monitoring is running."""
    if not targets.is_usable_input_target(_DIAGNOSTIC_TARGET):
        return False
    target_state.set_active_target(_DIAGNOSTIC_TARGET)
    runtime.state.composition_target = None
    runtime.state.insert_on_commit = True
    return True


def _force_begin_ime(context: object = None) -> bool:
    """Call beginIME for the locked or current diagnostic target."""
    api = platform_api.ensure()
    target = _locked_target(context)
    hwnd = _DIAGNOSTIC_HWND or macos_event_bridge.active_hwnd()
    if target is not None:
        macos_event_bridge.activate_target(target, hwnd)
    info, position = _candidate_snapshot(target, hwnd)
    if api is None or info is None or position is None:
        _log("force beginIME skipped: missing api, target, or position")
        _log_candidate_details(target, hwnd)
        return False

    line_height = max(12, int(getattr(info, "line_height", 18) or 18))
    ok_any = False
    sent_views: set[int] = set()

    view, source = _debug_active_ime_view(api)
    if view:
        try:
            active_scale = float(api.backing_scale_factor(api.active_ns_window()))
        except (AttributeError, OSError, TypeError, ValueError):
            active_scale = 1.0
        ok, logical = _send_begin_ime_to_view(
            api,
            view,
            position,
            line_height,
            active_scale,
        )
        ok_any = ok_any or ok
        sent_views.add(int(view))
        _log(
            "force beginIME result = "
            f"{ok}, view_source = {source}, view = {view}, "
            f"scale = {active_scale}, logical = {logical}"
        )
    else:
        _log("force beginIME active-view skipped: missing Cocoa IME view")

    visible_views = _visible_ime_views(api)
    _log(f"visible IME views = {len(visible_views)}")
    for index, window, visible_view, title, scale in visible_views:
        if visible_view in sent_views:
            continue
        ok, logical = _send_begin_ime_to_view(
            api,
            visible_view,
            position,
            line_height,
            scale,
        )
        ok_any = ok_any or ok
        sent_views.add(visible_view)
        _log(
            "broadcast beginIME "
            f"window[{index}] title={title!r} nswindow={window} "
            f"view={visible_view} scale={scale} logical={logical} result={ok}"
        )

    if not sent_views:
        _log("force beginIME skipped: no visible Cocoa IME view")
    _log_candidate_details(target, hwnd)
    return ok_any


def _dump_cocoa_tree() -> bool:
    """Dump NSWindow and NSView details used to find Blender's IME view."""
    api = platform_api.ensure()
    if api is None:
        _log("cocoa tree skipped: no native api")
        return False

    active_window = api.active_ns_window()
    _log(f"active NSWindow = {active_window}")
    view, source = _debug_active_ime_view(api)
    _log(f"debug active IME view = {view}, source = {source}")

    windows = _iter_ns_windows(api)
    _log(f"NSApplication windows = {len(windows)}")
    for index, window in enumerate(windows):
        class_name = _objc_class_name(api, window)
        title = _objc_text(api, window, "title")
        visible = None
        scale = 1.0
        try:
            if api.objc.responds(window, api.objc.is_visible):
                visible = bool(api.objc.send_bool(window, api.objc.is_visible))
            scale = float(api.backing_scale_factor(window))
            content = api.objc.send_id(window, api.objc.content_view)
        except (AttributeError, OSError, TypeError, ValueError):
            content = 0
        _log(
            f"window[{index}] ptr={window} class={class_name} "
            f"title={title!r} visible={visible} scale={scale} content={content}"
        )
        _dump_view_tree(api, int(content or 0), depth=1)
    return True


def _dump_blender_windows() -> None:
    """Log Blender RNA windows and editor areas visible to diagnostics."""
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        windows = ()
    _log(f"Blender RNA windows = {len(windows)}")
    for window_index, window in enumerate(windows):
        try:
            pointer = platform_api.ptr_value(window.as_pointer())
            screen = window.screen
            screen_name = getattr(screen, "name", "")
            areas = tuple(screen.areas)
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            _log(f"rna window[{window_index}] stale")
            continue
        _log(
            f"rna window[{window_index}] ptr={pointer} "
            f"screen={screen_name!r} areas={len(areas)}"
        )
        for area_index, area in enumerate(areas):
            try:
                area_type = area.type
                box = (area.x, area.y, area.width, area.height)
                label = ""
                if area_type == "TEXT_EDITOR":
                    text = getattr(area.spaces.active, "text", None)
                    label = f" text={getattr(text, 'name', None)!r}"
                elif area_type == "VIEW_3D":
                    obj = targets.active_font_edit_object()
                    label = (
                        f" active_font={getattr(obj, 'name', None)!r}"
                        if obj is not None
                        else ""
                    )
            except (AttributeError, ReferenceError, RuntimeError):
                _log(f"  area[{area_index}] stale")
                continue
            _log(f"  area[{area_index}] type={area_type} box={box}{label}")


def _start_full_diagnostic(context: object) -> bool:
    """Start the one-click macOS diagnostic session."""
    _stop_monitor()
    _restore_key_down_trace_hooks()
    _restore_marked_text_trace_hooks()
    _clear_log()
    _clear_locked_target()
    _log("full diagnostic started")
    started = _ensure_bridge(context)
    _log(f"start bridge result = {started}")

    candidates = _discover_targets(context)
    _log_discovered_targets(candidates)
    target = _lock_target(context)
    _log(f"locked target = {_target_label(target)}")
    _log(f"locked target usable = {targets.is_usable_input_target(target)}")

    installed = _install_trace_handler(context)
    _log(f"trace handler installed = {installed}")
    marked_installed = _install_marked_text_trace_hooks()
    _log(f"marked text trace hooks installed = {marked_installed}")
    key_installed = _install_key_down_trace_hooks()
    _log(f"keyDown trace hooks installed = {key_installed}")
    _dump_status(context)
    if target is not None:
        _force_begin_ime(context)
    else:
        _log("waiting target: no Text Editor or 3D Text target found yet")
    _dump_blender_windows()
    _dump_cocoa_tree()

    monitor_ok = _start_monitor()
    _log(f"monitor start = {monitor_ok}")
    _log("请现在回到目标区域，切中文输入法并输入。日志只会在状态变化时追加。")
    return started > 0 and installed > 0 and monitor_ok


def _stop_full_diagnostic() -> int:
    """Stop diagnostics and restore the normal commit handler."""
    _stop_monitor()
    _restore_normal_commit_handler()
    key_restored = _restore_key_down_trace_hooks()
    _log(f"keyDown trace hooks restored = {key_restored}")
    marked_restored = _restore_marked_text_trace_hooks()
    _log(f"marked text trace hooks restored = {marked_restored}")
    _clear_locked_target()
    stopped = window_hook.stop_hooks()
    _log(f"stop bridge result = {stopped}")
    return stopped


class IMEBRIDGE_OT_macos_debug_clear_log(bpy.types.Operator):
    """Clear the macOS diagnostic log."""

    bl_idname = "ime_bridge.macos_debug_clear_log"
    bl_label = "清空诊断日志"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        _clear_log()
        _log("log cleared")
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_dump(bpy.types.Operator):
    """Dump current macOS bridge status."""

    bl_idname = "ime_bridge.macos_debug_dump"
    bl_label = "打印当前状态"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        _dump_status(context)
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_full_start(bpy.types.Operator):
    """Run the complete macOS diagnostic setup with one click."""

    bl_idname = "ime_bridge.macos_debug_full_start"
    bl_label = "开始完整诊断"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        ok = _start_full_diagnostic(context)
        return {"FINISHED" if ok else "CANCELLED"}


class IMEBRIDGE_OT_macos_debug_full_stop(bpy.types.Operator):
    """Stop the one-click diagnostic session."""

    bl_idname = "ime_bridge.macos_debug_full_stop"
    bl_label = "停止诊断"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        _stop_full_diagnostic()
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_start(bpy.types.Operator):
    """Start the macOS bridge and log what was installed."""

    bl_idname = "ime_bridge.macos_debug_start"
    bl_label = "启动桥接"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        started = _ensure_bridge(context)
        _log(f"start bridge result = {started}")
        _dump_status(context)
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_stop(bpy.types.Operator):
    """Stop hooks and diagnostic timers."""

    bl_idname = "ime_bridge.macos_debug_stop"
    bl_label = "停止桥接"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        _stop_full_diagnostic()
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_probe_target(bpy.types.Operator):
    """Probe current Blender target and candidate placement."""

    bl_idname = "ime_bridge.macos_debug_probe_target"
    bl_label = "探测当前目标"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        if _DIAGNOSTIC_TARGET is None:
            _lock_target(context)
        target = _locked_target(context)
        hwnd = _DIAGNOSTIC_HWND or macos_event_bridge.active_hwnd()
        activated = macos_event_bridge.activate_target(target, hwnd) if target else False
        updated = (
            ime_context.update_ime_candidate_position(hwnd=hwnd, target=target)
            if target is not None
            else False
        )
        _log(f"probe target = {_target_label(target)}")
        _log(f"probe activated = {activated}")
        _log(f"probe update candidate = {updated}")
        _log_candidate_details(target, hwnd)
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_force_begin_ime(bpy.types.Operator):
    """Call Blender's Cocoa beginIME with the current candidate position."""

    bl_idname = "ime_bridge.macos_debug_force_begin_ime"
    bl_label = "强制 beginIME"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        if _DIAGNOSTIC_TARGET is None:
            _lock_target(context)
        ok = _force_begin_ime(context)
        return {"FINISHED" if ok else "CANCELLED"}


class IMEBRIDGE_OT_macos_debug_dump_cocoa_tree(bpy.types.Operator):
    """Dump NSWindow and NSView details used to find Blender's IME view."""

    bl_idname = "ime_bridge.macos_debug_dump_cocoa_tree"
    bl_label = "打印 Cocoa 视图树"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        ok = _dump_cocoa_tree()
        return {"FINISHED" if ok else "CANCELLED"}


class IMEBRIDGE_OT_macos_debug_simulate_insert(bpy.types.Operator):
    """Simulate a Cocoa insertText commit through Blender's active IME view."""

    bl_idname = "ime_bridge.macos_debug_simulate_insert"
    bl_label = "模拟提交文本"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        if platform_api.backend_name() != "macos":
            _log("simulate insert skipped: backend is not macOS")
            return {"CANCELLED"}

        from ..platforms import macos

        _ensure_bridge(context)
        if _DIAGNOSTIC_TARGET is None:
            _lock_target(context)
        target = _locked_target(context)
        hwnd = _DIAGNOSTIC_HWND or macos_event_bridge.active_hwnd()
        if target is not None:
            macos_event_bridge.activate_target(target, hwnd)

        api = platform_api.ensure()
        view, view_source = _debug_active_ime_view(api)
        if api is None or not view:
            _log("simulate insert skipped: missing Cocoa IME view")
            return {"CANCELLED"}

        value = getattr(context.window_manager, DEBUG_TEXT_PROP, "") or "诊"
        send_id_charp = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_char_p,
        )(("objc_msgSend", api.objc.lib))
        insert_text = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            macos.NSRange,
        )(("objc_msgSend", api.objc.lib))
        nsstring = api.objc.cls("NSString")
        string_with_utf8 = api.objc.sel("stringWithUTF8String:")
        ns_text = send_id_charp(nsstring, string_with_utf8, value.encode("utf-8"))

        _log(
            "simulate insert before: "
            f"value={value!r} target={_target_label(target)} "
            f"view={view} source={view_source}"
        )
        insert_text(view, api.objc.insert_text, ns_text, macos.NSRange(0, 0))
        insert_queue.flush()
        _log(
            "simulate insert after: "
            f"pending={len(runtime.state.pending_inserts)} "
            f"active={_target_label(runtime.state.active_target)}"
        )
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_trace_on(bpy.types.Operator):
    """Log real Cocoa insertText callbacks while keeping normal insertion."""

    bl_idname = "ime_bridge.macos_debug_trace_on"
    bl_label = "开启提交追踪"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        if _DIAGNOSTIC_TARGET is None:
            _lock_target(context)
        installed = _install_trace_handler(context)
        _log(f"trace handler installed = {installed}")
        _dump_status(context)
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_trace_off(bpy.types.Operator):
    """Restore the normal macOS commit handler."""

    bl_idname = "ime_bridge.macos_debug_trace_off"
    bl_label = "关闭提交追踪"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        installed = _restore_normal_commit_handler()
        _log(f"trace handler restored normal handler = {installed}")
        return {"FINISHED"}


class IMEBRIDGE_OT_macos_debug_monitor_start(bpy.types.Operator):
    """Start compact state logging for a short typing window."""

    bl_idname = "ime_bridge.macos_debug_monitor_start"
    bl_label = "开始 30 秒监控"
    bl_options = {"INTERNAL"}

    def execute(self, context: object) -> set[str]:
        _ensure_bridge(context)
        if _DIAGNOSTIC_TARGET is None:
            _lock_target(context)
        ok = _start_monitor()
        _log(f"monitor start = {ok}")
        return {"FINISHED" if ok else "CANCELLED"}


class IMEBRIDGE_OT_macos_debug_monitor_stop(bpy.types.Operator):
    """Stop compact state logging."""

    bl_idname = "ime_bridge.macos_debug_monitor_stop"
    bl_label = "停止监控"
    bl_options = {"INTERNAL"}

    def execute(self, _context: object) -> set[str]:
        ok = _stop_monitor()
        _log(f"monitor stop = {ok}")
        return {"FINISHED"}


class IMEBRIDGE_PT_macos_debug_view3d(bpy.types.Panel):
    """macOS diagnostic panel in the View3D sidebar."""

    bl_label = "IMEBridge 诊断"
    bl_idname = "IMEBRIDGE_PT_macos_debug_view3d"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "IMEBridge"

    @classmethod
    def poll(cls, _context: object) -> bool:
        return platform_api.backend_name() == "macos"

    def draw(self, context: object) -> None:
        _draw_panel(self.layout, context)


class IMEBRIDGE_PT_macos_debug_text_editor(bpy.types.Panel):
    """macOS diagnostic panel in the Text Editor sidebar."""

    bl_label = "IMEBridge 诊断"
    bl_idname = "IMEBRIDGE_PT_macos_debug_text_editor"
    bl_space_type = "TEXT_EDITOR"
    bl_region_type = "UI"
    bl_category = "IMEBridge"

    @classmethod
    def poll(cls, _context: object) -> bool:
        return platform_api.backend_name() == "macos"

    def draw(self, context: object) -> None:
        _draw_panel(self.layout, context)


def _draw_panel(layout: object, context: object) -> None:
    """Draw the shared macOS diagnostic controls."""
    from ..platforms import macos

    col = layout.column(align=True)
    col.label(text=f"运行: {macos_event_bridge.is_running()}")
    col.label(text=f"追踪: {_TRACE_ACTIVE}")
    col.label(text=f"监控: {_MONITOR_ACTIVE}")
    col.label(text=f"日志: {LOG_TEXT_NAME}")
    col.label(text=f"锁定: {_target_label(_DIAGNOSTIC_TARGET)}")

    wm = getattr(context, "window_manager", None)
    if wm is not None and hasattr(wm, macos.COCOA_CANDIDATE_Y_PADDING_PROP):
        col.separator()
        col.prop(
            wm,
            macos.COCOA_CANDIDATE_Y_PADDING_PROP,
            text="候选框Y补偿",
        )

    col.separator()
    col.operator("ime_bridge.macos_debug_full_start")
    col.operator("ime_bridge.macos_debug_full_stop")

    col.separator()
    col.operator("ime_bridge.macos_debug_clear_log")


CLASSES = (
    IMEBRIDGE_OT_macos_debug_clear_log,
    IMEBRIDGE_OT_macos_debug_dump,
    IMEBRIDGE_OT_macos_debug_full_start,
    IMEBRIDGE_OT_macos_debug_full_stop,
    IMEBRIDGE_OT_macos_debug_start,
    IMEBRIDGE_OT_macos_debug_stop,
    IMEBRIDGE_OT_macos_debug_probe_target,
    IMEBRIDGE_OT_macos_debug_force_begin_ime,
    IMEBRIDGE_OT_macos_debug_dump_cocoa_tree,
    IMEBRIDGE_OT_macos_debug_simulate_insert,
    IMEBRIDGE_OT_macos_debug_trace_on,
    IMEBRIDGE_OT_macos_debug_trace_off,
    IMEBRIDGE_OT_macos_debug_monitor_start,
    IMEBRIDGE_OT_macos_debug_monitor_stop,
    IMEBRIDGE_PT_macos_debug_view3d,
    IMEBRIDGE_PT_macos_debug_text_editor,
)


def register_properties() -> None:
    """Register transient WindowManager properties used by the panel."""
    from ..platforms import macos

    setattr(
        bpy.types.WindowManager,
        DEBUG_TEXT_PROP,
        bpy.props.StringProperty(
            name="Simulated Commit Text",
            description="Text passed through the Cocoa insertText diagnostic path",
            default="诊",
        ),
    )
    setattr(
        bpy.types.WindowManager,
        macos.COCOA_CANDIDATE_Y_PADDING_PROP,
        bpy.props.IntProperty(
            name="macOS Candidate Y Padding",
            description="Diagnostic vertical correction before Cocoa beginIME",
            default=macos.COCOA_CANDIDATE_Y_PADDING,
            min=-120,
            max=200,
            step=1,
        ),
    )


def unregister_properties() -> None:
    """Remove transient WindowManager properties and timers."""
    from ..platforms import macos

    _stop_monitor()
    _restore_key_down_trace_hooks()
    _restore_marked_text_trace_hooks()
    _clear_locked_target()
    if hasattr(bpy.types.WindowManager, DEBUG_TEXT_PROP):
        delattr(bpy.types.WindowManager, DEBUG_TEXT_PROP)
    if hasattr(bpy.types.WindowManager, macos.COCOA_CANDIDATE_Y_PADDING_PROP):
        delattr(bpy.types.WindowManager, macos.COCOA_CANDIDATE_Y_PADDING_PROP)
