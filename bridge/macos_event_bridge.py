"""macOS modal event bridge built on Blender's Cocoa IME support."""

from __future__ import annotations

import time

import bpy

from . import ime_context
from . import input_scope
from ..core import models
from ..core import runtime
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..targets import text as text_target
from ..platforms import native as platform_api


MOUSE_PRESS_EVENTS = {"LEFTMOUSE", "MIDDLEMOUSE", "RIGHTMOUSE"}
CANDIDATE_REFRESH_SECONDS = 0.05

_RUNNING = False
_STOP_REQUESTED = False
_OPERATOR = None
_GENERATION = 0
_LAST_CANDIDATE_REFRESH = 0.0


def is_available() -> bool:
    """Return whether the selected backend is the real macOS bridge."""
    return (
        platform_api.backend_name() == "macos"
        and platform_api.supports_native_bridge()
    )


def is_running() -> bool:
    """Return whether the modal bridge has an active operator instance."""
    return _RUNNING and not _STOP_REQUESTED


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
    runtime.state.text_ime_session.end_current()
    runtime.state.font_result_dedup.clear()


def clear_native_text_ui_handoff() -> None:
    """Release the temporary handoff to Blender's own text fields."""
    runtime.state.input_scope.native_text_ui_handoff = False


def end_ime() -> bool:
    """Ask the Cocoa backend to leave IME input focus."""
    backend_end = getattr(platform_api, "end_ime", None)
    if callable(backend_end):
        return bool(backend_end())
    return False


def set_scope(scope: input_scope.InputScope) -> None:
    """Store the current Blender input scope for shared diagnostics."""
    runtime.state.input_scope.current_kind = scope.kind
    runtime.state.input_scope.current_area_type = input_scope.scope_area_type(scope)


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
    """Make a Blender text target the owner of following TEXTINPUT events."""
    if not targets.is_usable_input_target(target):
        return False
    target_state.set_active_target(target)
    runtime.state.composition_target = None
    runtime.state.insert_on_commit = True
    update_candidate(target, hwnd, force=True)
    return True


def target_from_context(context: object) -> object | None:
    """Use Blender's current context as a fallback when no click target exists."""
    target = targets.make_input_target_from_context(context)
    if target is not None:
        return target
    return targets.find_font_edit_target(context)


def refresh_target_from_context(context: object, hwnd: object = None) -> object | None:
    """Promote context focus changes into an active bridge target."""
    target = target_from_context(context)
    if activate_target(target, hwnd):
        return target
    return None


def apply_enabled_scope(scope: input_scope.InputScope) -> None:
    """Allow IMEBridge input for a supported Text or 3D Text target."""
    set_scope(scope)
    activate_target(scope.target, scope.hwnd)


def apply_passive_scope(scope: input_scope.InputScope) -> None:
    """Step away from bridge-owned targets in neutral or shortcut-heavy UI."""
    set_scope(scope)
    clear_native_text_ui_handoff()
    clear_bridge_target_state()
    end_ime()


def apply_mouse_scope(context: object, event: object) -> None:
    """Classify a mouse press and update the macOS bridge target."""
    clear_native_text_ui_handoff()
    hwnd = active_hwnd()
    scope = input_scope.from_event(context, event, hwnd=hwnd)
    if scope.kind == input_scope.SCOPE_ENABLED_TARGET:
        apply_enabled_scope(scope)
    else:
        apply_passive_scope(scope)


def event_text(event: object) -> str:
    """Extract committed text from Blender's public event surface."""
    text = getattr(event, "unicode", "") or ""
    if text:
        return text
    if getattr(event, "type", "") == "TEXTINPUT":
        return getattr(event, "ascii", "") or ""
    return ""


def queue_text_input(context: object, event: object) -> bool:
    """Queue committed macOS text into the existing Blender insertion path."""
    if runtime.state.input_scope.native_text_ui_handoff:
        return False

    text = event_text(event)
    if not text:
        return False

    hwnd = active_hwnd()
    target = targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        context,
    )
    if not targets.is_usable_input_target(target):
        target = refresh_target_from_context(context, hwnd)
    if not targets.is_usable_input_target(target):
        return False

    text_session = None
    if models.is_text_editor_target(target):
        text_session = runtime.state.text_ime_session.active_for_text(target.text)

    insert_queue.queue(
        text,
        target,
        text_session,
        hwnd=hwnd,
        source=insert_queue.SOURCE_IME_RESULT,
    )
    update_candidate(target, hwnd, force=True)
    return True


def opens_native_text_ui(event: object) -> bool:
    """Shortcuts that hand focus to Blender's own text fields."""
    if getattr(event, "value", "") != "PRESS":
        return False

    event_type = getattr(event, "type", "")
    if event_type in {"F2", "F3"}:
        return True
    if event_type != "F":
        return False
    if getattr(event, "alt", False):
        return False
    return bool(getattr(event, "ctrl", False) or getattr(event, "oskey", False))


def handle_native_text_ui_shortcut(event: object) -> bool:
    """Step aside before Blender opens search, rename, or find text fields."""
    if not opens_native_text_ui(event):
        return False
    runtime.state.input_scope.native_text_ui_handoff = True
    clear_bridge_target_state()
    end_ime()
    return True


def handle_native_text_ui_release(event: object) -> bool:
    """Keyboard-closing native text UI should not leave the bridge paused."""
    if not runtime.state.input_scope.native_text_ui_handoff:
        return False
    if getattr(event, "value", "") != "PRESS":
        return False
    if getattr(event, "type", "") not in {"ESC", "RET"}:
        return False
    clear_native_text_ui_handoff()
    return True


def start(insert_on_commit: bool = False) -> int:
    """Start the hidden modal operator that receives macOS text events."""
    if bpy.app.background or not is_available():
        return 0
    if _RUNNING and not _STOP_REQUESTED:
        runtime.state.insert_on_commit = bool(insert_on_commit)
        return 1

    runtime.state.insert_on_commit = bool(insert_on_commit)
    try:
        result = bpy.ops.ime_bridge.macos_event_bridge("INVOKE_DEFAULT")
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return 0
    return 1 if "RUNNING_MODAL" in result or is_running() else 0


def stop() -> int:
    """Request modal shutdown and clean up bridge-owned IME state."""
    global _GENERATION, _STOP_REQUESTED

    if not _RUNNING:
        clear_bridge_target_state()
        end_ime()
        return 0
    _STOP_REQUESTED = True
    _GENERATION += 1
    clear_bridge_target_state()
    end_ime()
    return 1


class IMEBRIDGE_OT_macos_event_bridge(bpy.types.Operator):
    """Hidden operator that keeps macOS text input inside IMEBridge targets."""

    bl_idname = "ime_bridge.macos_event_bridge"
    bl_label = "IMEBridge macOS Event Bridge"
    bl_options = {"INTERNAL"}

    @classmethod
    def poll(cls, context: object) -> bool:
        """Run only in UI sessions with a selected macOS backend."""
        return not bpy.app.background and is_available()

    def invoke(self, context: object, _event: object) -> set[str]:
        """Install the modal event handler once."""
        global _GENERATION, _OPERATOR, _RUNNING, _STOP_REQUESTED

        if _RUNNING and not _STOP_REQUESTED:
            return {"CANCELLED"}
        _GENERATION += 1
        self._generation = _GENERATION
        _OPERATOR = self
        _RUNNING = True
        _STOP_REQUESTED = False
        context.window_manager.modal_handler_add(self)
        refresh_target_from_context(context, active_hwnd())
        return {"RUNNING_MODAL"}

    def finish(self, *, clear_state: bool = True) -> set[str]:
        """Clear modal globals when the operator exits."""
        global _OPERATOR, _RUNNING, _STOP_REQUESTED

        if _OPERATOR is self:
            _OPERATOR = None
            _RUNNING = False
            _STOP_REQUESTED = False
        if clear_state:
            clear_bridge_target_state()
            end_ime()
            text_target.cancel_restore_guard()
        return {"CANCELLED"}

    def modal(self, context: object, event: object) -> set[str]:
        """Route public Blender events into the macOS IME bridge."""
        if _STOP_REQUESTED and _OPERATOR is self:
            return self.finish()
        if getattr(self, "_generation", 0) != _GENERATION:
            return self.finish(clear_state=False)
        if not is_available():
            return self.finish()

        event_type = getattr(event, "type", "")
        event_value = getattr(event, "value", "")

        if event_type == "WINDOW_DEACTIVATE":
            clear_native_text_ui_handoff()
            apply_passive_scope(
                input_scope.InputScope(
                    input_scope.SCOPE_NEUTRAL,
                    hwnd=active_hwnd(),
                )
            )
            return {"PASS_THROUGH"}

        if handle_native_text_ui_shortcut(event):
            return {"PASS_THROUGH"}
        handle_native_text_ui_release(event)

        if event_type in MOUSE_PRESS_EVENTS and event_value == "PRESS":
            apply_mouse_scope(context, event)
            return {"PASS_THROUGH"}

        if event_type == "TEXTINPUT" and queue_text_input(context, event):
            return {"RUNNING_MODAL"}

        target = runtime.state.active_target
        if targets.is_usable_input_target(target):
            update_candidate(target, active_hwnd())

        return {"PASS_THROUGH"}
