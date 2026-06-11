"""Route native messages into target tracking, IME commits, and guards."""

import bpy

from . import arming
from . import font_commit
from . import ime_switch
from . import ime_context
from . import ime_guards
from . import input_scope
from . import message_keys
from . import message_scope
from . import text_area_activation
from ..core import message_result
from ..core import models
from ..core import runtime
from ..preferences import config
from ..targets import detect as targets
from ..targets import font_restore
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..targets import text as text_target
from ..platforms import native as platform_api

ctrl_is_down = message_keys.ctrl_is_down
alt_is_down = message_keys.alt_is_down
shift_is_down = message_keys.shift_is_down
opens_native_text_ui = message_keys.opens_native_text_ui
is_supported_message = message_keys.is_supported_message
is_bridge_ime_message = message_keys.is_bridge_ime_message

INPUT_SCOPE_TIMER_INTERVAL = message_scope.INPUT_SCOPE_TIMER_INTERVAL
TEXT_AREA_ACTIVATION_INTERVAL = text_area_activation.TEXT_AREA_ACTIVATION_INTERVAL
TEXT_AREA_ACTIVATION_RETRY_LIMIT = (
    text_area_activation.TEXT_AREA_ACTIVATION_RETRY_LIMIT
)
set_current_scope = message_scope.set_current_scope
set_neutral_scope = message_scope.set_neutral_scope
clear_native_text_ui_handoff = message_scope.clear_native_text_ui_handoff
target_area_type = message_scope.target_area_type
recent_font_target_from_state = message_scope.recent_font_target_from_state
clear_bridge_target_state = message_scope.clear_bridge_target_state
apply_enabled_scope = message_scope.apply_enabled_scope
apply_shortcut_scope = message_scope.apply_shortcut_scope
apply_neutral_scope = message_scope.apply_neutral_scope
apply_input_scope = message_scope.apply_input_scope
scope_target_from_context = message_scope.scope_target_from_context
schedule_input_scope_application = message_scope.schedule_input_scope_application
cancel_pending_scope_application = message_scope.cancel_pending_scope_application
refresh_scope_from_context = message_scope.refresh_scope_from_context
text_datablock_key = text_area_activation.text_datablock_key
text_target_from_area_hit = text_area_activation.text_target_from_area_hit
activate_text_area_hit = text_area_activation.activate_text_area_hit
pending_text_area_key = text_area_activation.pending_text_area_key
try_activate_pending_text_area = text_area_activation.try_activate_pending_text_area
schedule_text_area_activation = text_area_activation.schedule_text_area_activation
maybe_schedule_text_area_activation = (
    text_area_activation.maybe_schedule_text_area_activation
)
cancel_pending_text_area_activation = (
    text_area_activation.cancel_pending_text_area_activation
)

__all__ = (
    "INPUT_SCOPE_TIMER_INTERVAL",
    "TEXT_AREA_ACTIVATION_INTERVAL",
    "TEXT_AREA_ACTIVATION_RETRY_LIMIT",
    "set_current_scope",
    "set_neutral_scope",
    "clear_native_text_ui_handoff",
    "target_area_type",
    "text_datablock_key",
    "recent_font_target_from_state",
    "clear_bridge_target_state",
    "apply_enabled_scope",
    "apply_shortcut_scope",
    "apply_neutral_scope",
    "apply_input_scope",
    "text_target_from_area_hit",
    "activate_text_area_hit",
    "scope_target_from_context",
    "refresh_scope_from_context",
    "schedule_input_scope_application",
    "cancel_pending_scope_application",
    "pending_text_area_key",
    "try_activate_pending_text_area",
    "schedule_text_area_activation",
    "maybe_schedule_text_area_activation",
    "cancel_pending_text_area_activation",
    "cancel_pending_input_scope",
    "handle_mouse_down",
    "handle_mouse_message",
    "handle_focus_message",
    "ctrl_is_down",
    "alt_is_down",
    "shift_is_down",
    "opens_native_text_ui",
    "handle_native_text_ui_shortcut",
    "handle_native_text_ui_release",
    "handle_unicode_text_tab",
    "is_supported_message",
    "bridge_ime_allowed",
    "is_bridge_ime_message",
    "handle_out_of_scope_ime_message",
    "resolve_input_target_from_state",
    "handle_ime_start_composition",
    "queue_ime_result",
    "handle_ime_composition",
    "handle_ime_end_composition",
    "dispatch_ime_message",
    "handle_window_message",
)


def cancel_pending_input_scope() -> None:
    """Drop delayed scope work during reload or shutdown."""
    cancel_pending_scope_application()
    cancel_pending_text_area_activation()


def handle_mouse_down(
    hwnd: object,
    lparam: object,
    *,
    allow_text_area_activation: bool = False,
) -> None:
    """Mouse clicks are our best signal that Blender focus moved."""
    scope = input_scope.from_mouse_lparam(hwnd, lparam)
    if runtime.state.input_scope.native_text_ui_handoff:
        clear_native_text_ui_handoff()
        set_neutral_scope()
        cancel_pending_text_area_activation()
        clear_bridge_target_state(hwnd)
        schedule_input_scope_application(
            input_scope.InputScope(
                input_scope.SCOPE_NEUTRAL,
                hwnd=hwnd,
                hit=scope.hit,
            )
        )
        return

    set_current_scope(scope)
    maybe_schedule_text_area_activation(
        hwnd,
        lparam,
        scope,
        allow_text_area_activation,
    )

    if scope.kind == input_scope.SCOPE_ENABLED_TARGET and scope.target is not None:
        target_state.set_active_target(scope.target)
        arming.request_auto_arm()
    elif scope.kind == input_scope.SCOPE_SHORTCUT_SURFACE and refresh_scope_from_context(
        hwnd
    ):
        pass
    else:
        clear_bridge_target_state(hwnd)

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

    handle_mouse_down(
        hwnd,
        lparam,
        allow_text_area_activation=msg_value == win.WM_LBUTTONDOWN,
    )
    if (
        runtime.state.composition_target
        and runtime.state.composition_target != runtime.state.active_target
    ):
        clear_bridge_target_state(hwnd)
    return True


def handle_focus_message(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> bool:
    """Handle focus messages and tell the caller whether routing should stop."""
    if msg_value == win.WM_KILLFOCUS:
        set_neutral_scope()
        cancel_pending_input_scope()
        clear_bridge_target_state(hwnd)
        return True
    if msg_value == win.WM_ACTIVATEAPP and not bool(platform_api.ptr_value(wparam)):
        set_neutral_scope()
        cancel_pending_input_scope()
        clear_bridge_target_state(hwnd)
        return True
    return msg_value == win.WM_SETFOCUS


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
    runtime.state.input_scope.native_text_ui_handoff = True
    cancel_pending_input_scope()
    clear_bridge_target_state(hwnd)
    ime_switch.restore_if_managed(hwnd)
    return True


def handle_native_text_ui_release(
    win: object,
    msg_value: int,
    wparam: object,
) -> bool:
    """Keyboard-closing native text UI should not leave the bridge paused."""
    if not runtime.state.input_scope.native_text_ui_handoff:
        return False
    if msg_value != win.WM_KEYUP:
        return False
    if platform_api.ptr_value(wparam) not in {win.VK_ESCAPE, win.VK_RETURN}:
        return False
    clear_native_text_ui_handoff()
    set_neutral_scope()
    return True


def handle_unicode_text_tab(
    win: object,
    hwnd: object,
    msg_value: int,
    lparam: object,
) -> int | None:
    """Turn raw Tab after Unicode text into indentation instead of autocomplete."""
    if msg_value != win.WM_INPUT:
        return None

    raw = platform_api.read_raw_keyboard(win, lparam)
    if raw is None or raw["vkey"] != win.VK_TAB:
        return None
    if not raw["key_down"]:
        return None

    if ctrl_is_down(win) or alt_is_down(win) or shift_is_down(win):
        return None
    if not bridge_ime_allowed():
        return None
    if ime_guards.ime_is_composing(win, hwnd, ime_context.read_composition_string):
        return None

    target = targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        bpy.context,
    )
    if not models.is_text_editor_target(target):
        return None

    if not text_target.cursor_after_non_ascii_identifier(target):
        return None

    if not text_target.schedule_tab_indent(target):
        return None

    return 0


def bridge_ime_allowed() -> bool:
    """Keep IMEBridge away from native Blender UI text fields."""
    if runtime.state.input_scope.native_text_ui_handoff:
        return False

    current_kind = runtime.state.input_scope.current_kind
    if current_kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        return False
    if current_kind == input_scope.SCOPE_ENABLED_TARGET:
        target = runtime.state.composition_target or runtime.state.active_target
        return targets.is_usable_input_target(target)

    current_target = targets.make_input_target_from_context(bpy.context)
    return targets.is_usable_input_target(current_target)


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
        clear_bridge_target_state(hwnd)
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
    ime_guards.clear_hidden_text_ime_activity()
    try_activate_pending_text_area(hwnd)
    refresh_scope_from_context(hwnd)
    if not bridge_ime_allowed():
        clear_bridge_target_state(hwnd)
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
    if not targets.is_usable_input_target(target):
        return
    if models.is_text_editor_target(target):
        target_text = text_target.text_data_from_target(target)
        if target_text is None:
            return
        text_session = runtime.state.text_ime_session.active_for_text(target_text)
        leak_session, result = text_target.consume_confirm_space_leak_session(
            hwnd,
            target,
            result,
        )
        if leak_session is not None:
            polluted_session = text_session
            text_session = leak_session
        else:
            polluted_session = None
    else:
        text_session = None
        polluted_session = None
    if models.is_font_edit_target(target):
        font_space_leak, result = font_restore.consume_confirm_space_leak_snapshot(
            hwnd,
            target,
            result,
        )
    else:
        font_space_leak = None
    queued = insert_queue.queue(
        result,
        target,
        text_session,
        hwnd=hwnd,
        source=insert_queue.SOURCE_IME_RESULT,
        font_space_leak=font_space_leak,
    )
    if not queued:
        return
    if polluted_session is not None:
        runtime.state.text_ime_session.mark_committed(polluted_session)
    if models.is_text_editor_target(target):
        text_target.mark_composition_committed(text_session)


def handle_ime_composition(win: object, hwnd: object, l_value: int) -> None:
    """Follow preedit movement and capture committed result strings."""
    if not bridge_ime_allowed():
        return

    if l_value & win.GCS_COMPSTR:
        ime_context.update_ime_candidate_position(
            hwnd=hwnd,
            target=resolve_input_target_from_state(),
        )
    if l_value & win.GCS_RESULTSTR:
        result = ime_context.read_composition_string(win, hwnd, win.GCS_RESULTSTR)
        queue_ime_result(hwnd, result)


def handle_ime_end_composition(hwnd: object) -> None:
    """Release composition state once the IME is done."""
    runtime.state.composition_target = None
    runtime.state.text_ime_session.end_current()


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
        handle_ime_composition(win, hwnd, platform_api.ptr_value(lparam))
    elif msg_value == win.WM_IME_ENDCOMPOSITION:
        handle_ime_end_composition(hwnd)

    return message_result.MessageResult.pass_through()


def handle_window_message(
    hwnd: object,
    msg: object,
    wparam: object,
    lparam: object,
) -> message_result.MessageResult:
    """Main entry point from the hooked native message procedure."""
    win = platform_api.ensure()
    if win is None:
        return message_result.MessageResult.pass_through()

    msg_value = platform_api.ptr_value(msg)
    if not is_supported_message(win, msg_value):
        return message_result.MessageResult.pass_through()

    if handle_focus_message(win, hwnd, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    if handle_native_text_ui_shortcut(win, hwnd, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    if handle_native_text_ui_release(win, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    refresh_scope_from_context(hwnd)
    if is_bridge_ime_message(win, msg_value):
        try_activate_pending_text_area(hwnd)

    tab_result = handle_unicode_text_tab(win, hwnd, msg_value, lparam)
    if tab_result is not None:
        return message_result.MessageResult.handled_value(tab_result)

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
