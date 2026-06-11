"""macOS event bridge backed by Blender's Cocoa text input callbacks."""

from __future__ import annotations

import time

import bpy

from . import ime_context
from . import input_scope
from ..core import models
from ..core import runtime
from ..core import safe_ops
from ..targets import detect as targets
from ..targets import font_restore
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..targets import text as text_target
from ..platforms import native as platform_api


TARGET_POLL_INTERVAL = 0.05
CANDIDATE_REFRESH_SECONDS = 0.12

_RUNNING = False
_TIMER_REGISTERED = False
_LAST_CANDIDATE_REFRESH = 0.0


def is_available() -> bool:
    """Return whether the selected backend is the real macOS bridge."""
    return (
        platform_api.backend_name() == "macos"
        and platform_api.supports_native_bridge()
    )


def is_running() -> bool:
    """Return whether the macOS bridge hook is active."""
    return _RUNNING


def active_hwnd() -> object:
    """Return the backend-local window key used by shared state."""
    win = platform_api.ensure()
    if win is None:
        return None
    active_window = getattr(platform_api, "active_window", None)
    if not callable(active_window):
        return None
    return active_window(win)


def clear_bridge_target_state() -> None:
    """Forget only the target state owned by the macOS bridge."""
    target_state.clear_active_target()
    runtime.state.composition_target = None
    runtime.state.text_ime_session.clear()
    runtime.state.text_hidden_ime_activity.clear()
    text_target.cancel_tab_indent()
    text_target.clear_confirm_space_leak()
    runtime.state.font_result_dedup.clear()
    font_restore.clear_confirm_space_leak()
    runtime.state.font_hidden_ime_activity.clear()


def end_ime() -> bool:
    """Ask the Cocoa backend to leave IME input focus."""
    backend_end = getattr(platform_api, "end_ime", None)
    if callable(backend_end):
        return bool(backend_end())
    return False


def update_candidate(target: object, hwnd: object = None, *, force: bool = False) -> None:
    """Move the native candidate UI near the active target."""
    global _LAST_CANDIDATE_REFRESH

    if not targets.is_usable_input_target(target):
        return
    now = time.monotonic()
    if not force and now - _LAST_CANDIDATE_REFRESH < CANDIDATE_REFRESH_SECONDS:
        return
    _LAST_CANDIDATE_REFRESH = now
    try:
        ime_context.update_ime_candidate_position(
            hwnd=hwnd or active_hwnd(),
            target=target,
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return


def activate_target(target: object, hwnd: object = None) -> bool:
    """Make a Blender text target own following Cocoa insertText commits."""
    if not targets.is_usable_input_target(target):
        return False
    target_state.set_active_target(target)
    runtime.state.composition_target = None
    runtime.state.insert_on_commit = True
    update_candidate(target, hwnd, force=True)
    return True


def is_ime_allowed() -> bool:
    """Return whether the current active Blender area should allow IME input."""
    api = platform_api.ensure()
    if api is None:
        return True

    pt = getattr(api, "mouse_location", None)
    if not callable(pt):
        return True

    loc = pt()
    if loc is None:
        return True

    window = getattr(bpy.context, "window", None)
    hit = input_scope.area_hit_at_window_point(loc.x, loc.y, window)
    if hit is None:
        return True

    scope = input_scope.classify_hit(None, hit)
    if scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        return False

    return True


def target_from_context(context: object = None) -> object | None:
    """Use Blender's current context as the active macOS input target."""
    context = context or bpy.context
    api = platform_api.ensure()
    if api is None:
        return None

    pt = getattr(api, "mouse_location", None)
    if callable(pt):
        loc = pt()
        if loc is not None:
            hit = input_scope.area_hit_at_window_point(loc.x, loc.y, context.window)
            if hit is not None:
                scope = input_scope.classify_hit(None, hit)
                if scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE:
                    if hit.area.type == "VIEW_3D":
                        return targets.find_font_edit_target(context)
                    return None
                elif scope.kind == input_scope.SCOPE_ENABLED_TARGET:
                    target = input_scope.enabled_target_from_hit(hit)
                    if targets.is_usable_input_target(target):
                        return target

    target = targets.make_input_target_from_context(context)
    if target is not None:
        return target
    target = targets.find_font_edit_target(context)
    if target is not None:
        return target
    return targets.find_text_editor_target(context)


def refresh_target_from_context(
    context: object = None,
    hwnd: object = None,
) -> object | None:
    """Promote context focus changes into an active bridge target."""
    target = target_from_context(context)
    if activate_target(target, hwnd):
        return target
    return None


def resolve_commit_target() -> object | None:
    """Choose where a committed Cocoa IME string should be inserted."""
    target = targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        bpy.context,
    )
    if targets.is_usable_input_target(target):
        return target
    return refresh_target_from_context(bpy.context, active_hwnd())


def handle_committed_text(text: str) -> bool:
    """Queue committed Cocoa IME text into the existing insertion path."""
    if not _RUNNING or not text:
        return False

    hwnd = active_hwnd()
    target = resolve_commit_target()
    if not targets.is_usable_input_target(target):
        return False

    text_session = None
    if models.is_text_editor_target(target):
        target_text = text_target.text_data_from_target(target)
        if target_text is None:
            return False
        text_session = runtime.state.text_ime_session.active_for_text(target_text)

    queued = insert_queue.queue(
        text,
        target,
        text_session,
        hwnd=hwnd,
        source=insert_queue.SOURCE_IME_RESULT,
    )
    if not queued:
        return False
    update_candidate(target, hwnd, force=True)
    return True


def _target_poll_timer() -> float | None:
    """Keep macOS target and candidate state aligned with Blender focus."""
    global _TIMER_REGISTERED

    if not _RUNNING:
        _TIMER_REGISTERED = False
        return None

    api = platform_api.ensure()
    if api is None:
        return TARGET_POLL_INTERVAL

    hwnd = active_hwnd()
    context = bpy.context

    is_shortcut = False
    is_editing_3d_text = False

    pt = getattr(api, "mouse_location", None)
    if callable(pt):
        loc = pt()
        if loc is not None:
            hit = input_scope.area_hit_at_window_point(loc.x, loc.y, context.window)
            if hit is not None:
                scope = input_scope.classify_hit(None, hit)
                if scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE:
                    is_shortcut = True
                    if hit.area.type == "VIEW_3D":
                        if targets.font_object_for_ime(context, require_edit=True) is not None:
                            is_editing_3d_text = True

    if is_shortcut and not is_editing_3d_text:
        # Force clear active target and end IME on shortcut surfaces
        clear_bridge_target_state()
        end_ime()
        return TARGET_POLL_INTERVAL

    target = target_from_context(context)
    if targets.is_usable_input_target(target):
        activate_target(target, hwnd)
    elif targets.is_usable_input_target(runtime.state.active_target):
        update_candidate(runtime.state.active_target, hwnd)
    elif runtime.state.active_target is not None:
        clear_bridge_target_state()
        end_ime()

    return TARGET_POLL_INTERVAL


def _register_target_poll() -> bool:
    """Start the timer that keeps macOS target state current."""
    global _TIMER_REGISTERED

    if _TIMER_REGISTERED:
        return True
    if safe_ops.register_timer(_target_poll_timer, first_interval=0.0):
        _TIMER_REGISTERED = True
        return True
    return False


def start(insert_on_commit: bool = False) -> int:
    """Install Cocoa text callbacks and start lightweight target polling."""
    global _RUNNING

    if bpy.app.background or not is_available():
        return 0

    runtime.state.insert_on_commit = bool(insert_on_commit)
    install_hook = getattr(platform_api, "install_text_commit_hook", None)
    installed = int(install_hook(handle_committed_text, is_ime_allowed)) if callable(install_hook) else 0
    if installed <= 0:
        return 0

    _RUNNING = True
    _register_target_poll()
    refresh_target_from_context(bpy.context, active_hwnd())
    return installed


def stop() -> int:
    """Restore Cocoa callbacks and clear bridge-owned state."""
    global _RUNNING, _TIMER_REGISTERED

    was_running = _RUNNING
    _RUNNING = False
    _TIMER_REGISTERED = False
    safe_ops.unregister_timer(_target_poll_timer)

    uninstall_hook = getattr(platform_api, "uninstall_text_commit_hook", None)
    restored = int(uninstall_hook()) if callable(uninstall_hook) else 0

    clear_bridge_target_state()
    text_target.cancel_restore_guard()
    end_ime()
    return restored or int(was_running)
