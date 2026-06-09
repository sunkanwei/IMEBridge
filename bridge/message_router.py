"""Route Win32 messages into target tracking, IME commits, and guards."""

import bpy

from . import arming
from . import font_commit
from . import ime_switch
from . import ime_context
from . import ime_guards
from . import input_scope
from ..core import message_result
from ..core import models
from ..core import runtime
from ..core import safe_ops
from ..preferences import config
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..targets import text as text_target
from ..win32 import api as win32_api


INPUT_SCOPE_TIMER_INTERVAL = 0.01


def set_current_scope(scope: input_scope.InputScope) -> None:
    """Store the last resolved Blender editor scope in one place."""
    runtime.state.input_scope.current_kind = scope.kind
    runtime.state.input_scope.current_area_type = input_scope.scope_area_type(scope)


def set_neutral_scope() -> None:
    """Leave bridge-owned input without making a new Blender area claim."""
    runtime.state.input_scope.current_kind = input_scope.SCOPE_NEUTRAL
    runtime.state.input_scope.current_area_type = ""


def target_area_type(target: object) -> str:
    """Read the editor type from a resolved bridge target."""
    area = getattr(target, "area", None)
    return str(getattr(area, "type", "") or "")


def clear_bridge_target_state() -> None:
    """Forget only the target state owned by IMEBridge."""
    target_state.clear_active_target()
    runtime.state.composition_target = None
    runtime.state.text_ime_session.end_current()
    ime_guards.clear_ime_activity()
    ime_guards.clear_space_suppression()
    runtime.state.font_result_dedup.clear()


def apply_enabled_scope(scope: input_scope.InputScope) -> None:
    """Restore IMEBridge input for a supported Text or 3D Text target."""
    if scope.target is None:
        return
    target_state.set_active_target(scope.target)
    ime_switch.restore_if_managed(scope.hwnd)
    arming.request_auto_arm()
    ime_context.update_ime_candidate_position(hwnd=scope.hwnd, target=scope.target)


def apply_shortcut_scope(scope: input_scope.InputScope) -> None:
    """Close the IME where Blender expects direct shortcut keystrokes."""
    clear_bridge_target_state()
    if config.auto_english_on_shortcuts():
        ime_switch.close_for_shortcut_surface(scope.hwnd)


def apply_neutral_scope(scope: input_scope.InputScope) -> None:
    """Step away from bridge-owned targets without touching native UI fields."""
    clear_bridge_target_state()
    ime_switch.restore_if_managed(scope.hwnd)


def apply_input_scope(scope: input_scope.InputScope) -> None:
    """Apply the latest click scope after Blender focus has settled."""
    set_current_scope(scope)
    if scope.kind == input_scope.SCOPE_ENABLED_TARGET:
        apply_enabled_scope(scope)
    elif scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        apply_shortcut_scope(scope)
    else:
        apply_neutral_scope(scope)


def scope_target_from_context() -> object | None:
    """Catch mode changes such as Tab entering 3D Text edit mode."""
    current_kind = runtime.state.input_scope.current_kind
    current_area_type = runtime.state.input_scope.current_area_type

    if (
        current_kind == input_scope.SCOPE_SHORTCUT_SURFACE
        and current_area_type == "VIEW_3D"
    ):
        return targets.find_font_edit_target(bpy.context)

    if current_kind != input_scope.SCOPE_SHORTCUT_SURFACE:
        return targets.make_input_target_from_context(bpy.context)

    return None


def refresh_scope_from_context(hwnd: object) -> bool:
    """Promote a stale shortcut scope when Blender now has a text target."""
    target = scope_target_from_context()
    if target is None:
        return False

    runtime.state.input_scope.current_kind = input_scope.SCOPE_ENABLED_TARGET
    runtime.state.input_scope.current_area_type = target_area_type(target)
    target_state.set_active_target(target)
    ime_switch.restore_if_managed(hwnd)
    return True


def _apply_pending_input_scope() -> None:
    """Timer callback used to keep Win32 hooks out of heavier Blender work."""
    if not runtime.state.input_scope.scope_timer_registered:
        return None
    runtime.state.input_scope.scope_timer_registered = False

    scope = runtime.state.input_scope.pending_scope
    runtime.state.input_scope.pending_scope = None
    if scope is not None:
        apply_input_scope(scope)
    return None


def schedule_input_scope_application(scope: input_scope.InputScope) -> None:
    """Apply only the newest click when several arrive in quick succession."""
    runtime.state.input_scope.pending_scope = scope
    if runtime.state.input_scope.scope_timer_registered:
        return
    runtime.state.input_scope.scope_timer_registered = True
    bpy.app.timers.register(
        _apply_pending_input_scope,
        first_interval=INPUT_SCOPE_TIMER_INTERVAL,
    )


def cancel_pending_input_scope() -> None:
    """Drop delayed scope work during reload or shutdown."""
    runtime.state.input_scope.pending_scope = None
    runtime.state.input_scope.scope_timer_registered = False
    safe_ops.unregister_timer(_apply_pending_input_scope)


def handle_mouse_down(hwnd: object, lparam: object) -> None:
    """Mouse clicks are our best signal that Blender focus moved."""
    scope = input_scope.from_mouse_lparam(hwnd, lparam)
    set_current_scope(scope)

    if scope.kind == input_scope.SCOPE_ENABLED_TARGET and scope.target is not None:
        target_state.set_active_target(scope.target)
        arming.request_auto_arm()
    else:
        clear_bridge_target_state()

    schedule_input_scope_application(scope)


def handle_mouse_message(
    win: object,
    hwnd: object,
    msg_value: int,
    lparam: object,
) -> bool:
    """Track focus changes before IME composition starts using stale state."""
    if msg_value not in {
        win.WM_LBUTTONDOWN,
        win.WM_LBUTTONDBLCLK,
        win.WM_RBUTTONDOWN,
        win.WM_RBUTTONDBLCLK,
        win.WM_MBUTTONDOWN,
        win.WM_MBUTTONDBLCLK,
    }:
        return False

    handle_mouse_down(hwnd, lparam)
    if (
        runtime.state.composition_target
        and runtime.state.composition_target != runtime.state.active_target
    ):
        clear_bridge_target_state()
    return True


def handle_focus_message(win: object, msg_value: int, wparam: object) -> bool:
    """Window focus loss makes any stored Blender text target suspicious."""
    if msg_value == win.WM_KILLFOCUS:
        set_neutral_scope()
        cancel_pending_input_scope()
        clear_bridge_target_state()
        return True
    if msg_value == win.WM_ACTIVATEAPP and not bool(win32_api.ptr_value(wparam)):
        set_neutral_scope()
        cancel_pending_input_scope()
        clear_bridge_target_state()
        return True
    return msg_value == win.WM_SETFOCUS


def ctrl_is_down(win: object) -> bool:
    """Check Ctrl without importing the keyboard guards into routing policy."""
    return bool(win.user32.GetKeyState(win.VK_CONTROL) & 0x8000)


def alt_is_down(win: object) -> bool:
    """Alt usually belongs to menus, so Ctrl+Alt+F is not treated as find."""
    return bool(win.user32.GetKeyState(win.VK_MENU) & 0x8000)


def opens_native_text_ui(win: object, msg_value: int, wparam: object) -> bool:
    """Public shortcuts that hand focus to Blender's own text fields."""
    if msg_value != win.WM_KEYDOWN:
        return False

    key = win32_api.ptr_value(wparam)
    if key in {win.VK_F2, win.VK_F3}:
        return True
    return key == ord("F") and ctrl_is_down(win) and not alt_is_down(win)


def handle_native_text_ui_shortcut(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> bool:
    """Step aside before Blender opens search, rename, or find text fields."""
    if not opens_native_text_ui(win, msg_value, wparam):
        return False

    set_neutral_scope()
    cancel_pending_input_scope()
    clear_bridge_target_state()
    ime_switch.restore_if_managed(hwnd)
    return True


def is_supported_message(win: object, msg_value: int) -> bool:
    """Ignore the Win32 noise the bridge never handles."""
    return msg_value in {
        win.WM_SETFOCUS,
        win.WM_KILLFOCUS,
        win.WM_ACTIVATEAPP,
        win.WM_INPUT,
        win.WM_LBUTTONDOWN,
        win.WM_LBUTTONDBLCLK,
        win.WM_RBUTTONDOWN,
        win.WM_RBUTTONDBLCLK,
        win.WM_MBUTTONDOWN,
        win.WM_MBUTTONDBLCLK,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
        win.WM_IME_CHAR,
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_IME_REQUEST,
        win.WM_IME_STARTCOMPOSITION,
        win.WM_IME_COMPOSITION,
        win.WM_IME_ENDCOMPOSITION,
    }


def bridge_ime_allowed() -> bool:
    """Keep IMEBridge away from native Blender UI text fields."""
    current_kind = runtime.state.input_scope.current_kind
    if current_kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        return False
    if current_kind == input_scope.SCOPE_ENABLED_TARGET:
        return True
    return targets.is_supported_input_target(runtime.state.active_target)


def is_bridge_ime_message(win: object, msg_value: int) -> bool:
    """Messages that can otherwise leak into stale bridge targets."""
    return msg_value in {
        win.WM_IME_CHAR,
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_IME_REQUEST,
        win.WM_IME_STARTCOMPOSITION,
        win.WM_IME_COMPOSITION,
        win.WM_IME_ENDCOMPOSITION,
    }


def handle_out_of_scope_ime_message(
    win: object,
    hwnd: object,
    msg_value: int,
) -> message_result.MessageResult | None:
    """Pass native fields through, but suppress IME on shortcut canvases."""
    if not is_bridge_ime_message(win, msg_value) or bridge_ime_allowed():
        return None

    if refresh_scope_from_context(hwnd):
        return None

    if runtime.state.input_scope.current_kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        clear_bridge_target_state()
        if config.auto_english_on_shortcuts():
            ime_switch.close_for_shortcut_surface(hwnd)
            return message_result.MessageResult.handled_value(0)
        return message_result.MessageResult.pass_through()

    return message_result.MessageResult.pass_through()


def resolve_input_target_from_state() -> object | None:
    """Favor the composition target, then fall back to the last active target."""
    return targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        bpy.context,
    )


def handle_ime_start_composition(hwnd: object) -> None:
    """Lock onto a Blender target at the start of an IME session."""
    refresh_scope_from_context(hwnd)
    if not bridge_ime_allowed():
        clear_bridge_target_state()
        return

    current_target = targets.make_input_target_from_context(bpy.context)
    if current_target is not None:
        target_state.set_active_target(current_target)

    runtime.state.composition_target = targets.resolve_input_target(
        current_target,
        runtime.state.active_target,
        bpy.context,
    )
    text_session = target_state.capture_composition_start(
        runtime.state.composition_target
    )
    if text_session is None:
        runtime.state.text_ime_session.end_current()
    ime_guards.mark_ime_activity(hwnd)
    ime_context.update_ime_candidate_position(
        hwnd=hwnd,
        target=runtime.state.composition_target,
    )


def queue_ime_result(hwnd: object, result: str | None) -> None:
    """Move committed text onto Blender's timer-safe insertion path."""
    if not runtime.state.insert_on_commit or not result:
        return
    if not bridge_ime_allowed():
        return

    target = resolve_input_target_from_state()
    if models.is_text_editor_target(target):
        text_session = runtime.state.text_ime_session.active_for_text(target.text)
        text_target.mark_composition_committed(text_session)
    else:
        text_session = None
    insert_queue.queue(result, target, text_session)

    if models.is_font_edit_target(target):
        font_commit.mark_recent_font_result(target, result)
    if targets.is_supported_input_target(target):
        ime_guards.mark_space_suppression(hwnd)


def handle_ime_composition(win: object, hwnd: object, l_value: int) -> None:
    """Follow preedit movement and capture committed result strings."""
    if not bridge_ime_allowed():
        return

    ime_guards.mark_ime_activity(hwnd)
    if l_value & win.GCS_COMPSTR:
        ime_context.update_ime_candidate_position(
            hwnd=hwnd,
            target=resolve_input_target_from_state(),
        )
    if l_value & win.GCS_RESULTSTR:
        result = ime_context.read_composition_string(win, hwnd, win.GCS_RESULTSTR)
        queue_ime_result(hwnd, result)


def handle_ime_end_composition() -> None:
    """Release composition state once the IME is done."""
    runtime.state.composition_target = None
    runtime.state.text_ime_session.end_current()
    ime_guards.clear_ime_activity()


def dispatch_ime_message(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> message_result.MessageResult:
    """Handle the IME messages left after keyboard guards have had first pass."""
    if msg_value == win.WM_IME_REQUEST:
        result = ime_context.handle_ime_request(win, hwnd, wparam, lparam)
        if result is not None:
            return message_result.MessageResult.handled_value(result)
    elif msg_value == win.WM_IME_STARTCOMPOSITION:
        handle_ime_start_composition(hwnd)
    elif msg_value == win.WM_IME_COMPOSITION:
        handle_ime_composition(win, hwnd, win32_api.ptr_value(lparam))
    elif msg_value == win.WM_IME_ENDCOMPOSITION:
        handle_ime_end_composition()

    return message_result.MessageResult.pass_through()


def handle_window_message(
    hwnd: object,
    msg: object,
    wparam: object,
    lparam: object,
) -> message_result.MessageResult:
    """Main entry point from the hooked window procedure."""
    win = win32_api.ensure_windows()
    if win is None:
        return message_result.MessageResult.pass_through()

    msg_value = win32_api.ptr_value(msg)
    if not is_supported_message(win, msg_value):
        return message_result.MessageResult.pass_through()

    if handle_focus_message(win, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    if handle_native_text_ui_shortcut(win, hwnd, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    refresh_scope_from_context(hwnd)

    guard_result = ime_guards.handle_message_guards(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        ime_context.read_composition_string,
    )
    if guard_result is not None:
        return message_result.MessageResult.handled_value(guard_result)

    if handle_mouse_message(win, hwnd, msg_value, lparam):
        return message_result.MessageResult.pass_through()

    scope_result = handle_out_of_scope_ime_message(win, hwnd, msg_value)
    if scope_result is not None:
        return scope_result

    font_char_result = font_commit.handle_font_char_commit(
        win,
        hwnd,
        msg_value,
        wparam,
    )
    if font_char_result is not None:
        return message_result.MessageResult.handled_value(font_char_result)

    return dispatch_ime_message(win, hwnd, msg_value, wparam, lparam)
