"""Route native messages into target tracking, IME commits, and guards."""

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
from ..platforms import native as platform_api


INPUT_SCOPE_TIMER_INTERVAL = 0.01
TEXT_AREA_ACTIVATION_INTERVAL = 0.02
TEXT_AREA_ACTIVATION_RETRY_LIMIT = 20


def set_current_scope(scope: input_scope.InputScope) -> None:
    """Store the last resolved Blender editor scope in one place."""
    runtime.state.input_scope.current_kind = scope.kind
    runtime.state.input_scope.current_area_type = input_scope.scope_area_type(scope)


def set_neutral_scope() -> None:
    """Leave bridge-owned input without making a new Blender area claim."""
    runtime.state.input_scope.current_kind = input_scope.SCOPE_NEUTRAL
    runtime.state.input_scope.current_area_type = ""


def clear_native_text_ui_handoff() -> None:
    """Release the temporary handoff to Blender's own text fields."""
    runtime.state.input_scope.native_text_ui_handoff = False


def target_area_type(target: object) -> str:
    """Read the editor type from a resolved bridge target."""
    area = getattr(target, "area", None)
    return str(getattr(area, "type", "") or "")


def text_datablock_key(text_data: object) -> int:
    """Return a stable key for detecting Text Editor datablock changes."""
    if text_data is None:
        return 0
    try:
        return platform_api.ptr_value(text_data.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return 0


def recent_font_target_from_state() -> object | None:
    """Keep a just-committed 3D Text target through late IME messages."""
    target = runtime.state.composition_target or runtime.state.active_target
    if not models.is_font_edit_target(target):
        return None
    if not font_commit.is_recent_font_target(target):
        return None
    if targets.active_font_edit_object() != getattr(target, "obj", None):
        return None
    return target


def clear_bridge_target_state() -> None:
    """Forget only the target state owned by IMEBridge."""
    target_state.clear_active_target()
    runtime.state.composition_target = None
    runtime.state.text_ime_session.end_current()
    ime_guards.clear_space_suppression()
    text_target.cancel_tab_indent()
    runtime.state.font_result_dedup.clear()


def apply_enabled_scope(scope: input_scope.InputScope) -> None:
    """Restore IMEBridge input for a supported Text or 3D Text target."""
    if not targets.is_usable_input_target(scope.target):
        return
    target_state.set_active_target(scope.target)
    ime_switch.restore_if_managed(scope.hwnd)
    arming.request_auto_arm()
    ime_context.update_ime_candidate_position(hwnd=scope.hwnd, target=scope.target)


def apply_shortcut_scope(scope: input_scope.InputScope) -> None:
    """Close the IME where Blender expects direct shortcut keystrokes."""
    if refresh_scope_from_context(scope.hwnd):
        return

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


def text_target_from_area_hit(hit: input_scope.AreaHit) -> object | None:
    """Build a Text Editor target from a remembered area hit."""
    try:
        return targets.make_text_editor_target(
            hit.window,
            hit.area,
            hit.region,
            hit.space,
        )
    except (AttributeError, ReferenceError, RuntimeError):
        return None


def activate_text_area_hit(hit: input_scope.AreaHit, hwnd: object) -> bool:
    """Activate a Text Editor area after Blender finishes a header action."""
    target = text_target_from_area_hit(hit)
    if not targets.is_usable_input_target(target):
        return False

    cancel_pending_scope_application()
    apply_input_scope(
        input_scope.InputScope(
            input_scope.SCOPE_ENABLED_TARGET,
            hwnd=hwnd,
            target=target,
            hit=hit,
        )
    )
    return True


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
    if runtime.state.input_scope.native_text_ui_handoff:
        return False

    target = scope_target_from_context()
    if target is None:
        target = recent_font_target_from_state()
    if not targets.is_usable_input_target(target):
        return False

    runtime.state.input_scope.current_kind = input_scope.SCOPE_ENABLED_TARGET
    runtime.state.input_scope.current_area_type = target_area_type(target)
    target_state.set_active_target(target)
    ime_switch.restore_if_managed(hwnd)
    return True


def _apply_pending_input_scope() -> None:
    """Timer callback used to keep native hooks out of heavier Blender work."""
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
    if safe_ops.register_timer(
        _apply_pending_input_scope,
        first_interval=INPUT_SCOPE_TIMER_INTERVAL,
    ):
        runtime.state.input_scope.scope_timer_registered = True


def cancel_pending_scope_application() -> None:
    """Drop delayed click-scope work without touching other timers."""
    runtime.state.input_scope.pending_scope = None
    runtime.state.input_scope.scope_timer_registered = False
    safe_ops.unregister_timer(_apply_pending_input_scope)


def pending_text_area_key() -> int:
    """Read the current text key for the pending Text Editor area."""
    hit = runtime.state.text_area_activation.hit
    if hit is None:
        return 0
    try:
        return text_datablock_key(getattr(hit.space, "text", None))
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def try_activate_pending_text_area(
    hwnd: object = None,
    *,
    unregister_timer: bool = True,
) -> bool:
    """Promote a header-created Text datablock into an active IME target."""
    state = runtime.state.text_area_activation
    hit = state.hit
    if hit is None:
        return False

    current_key = pending_text_area_key()
    if not current_key or current_key == state.previous_text_key:
        return False

    if not activate_text_area_hit(hit, hwnd or state.hwnd):
        return False

    state.clear()
    if unregister_timer:
        safe_ops.unregister_timer(_apply_pending_text_area_activation)
    return True


def _apply_pending_text_area_activation() -> float | None:
    """Wait briefly for Text Editor header actions to update space.text."""
    state = runtime.state.text_area_activation
    if not state.timer_registered:
        return None

    if try_activate_pending_text_area(unregister_timer=False):
        return None

    state.attempts += 1
    if state.attempts >= TEXT_AREA_ACTIVATION_RETRY_LIMIT:
        state.clear()
        return None
    return TEXT_AREA_ACTIVATION_INTERVAL


def schedule_text_area_activation(
    hwnd: object,
    hit: input_scope.AreaHit,
) -> bool:
    """Remember a Text Editor area while Blender creates or switches text."""
    previous_key = text_datablock_key(getattr(hit.space, "text", None))
    state = runtime.state.text_area_activation
    state.hwnd = hwnd
    state.hit = hit
    state.previous_text_key = previous_key
    state.attempts = 0

    if state.timer_registered:
        return True
    if safe_ops.register_timer(
        _apply_pending_text_area_activation,
        first_interval=TEXT_AREA_ACTIVATION_INTERVAL,
    ):
        state.timer_registered = True
        return True

    state.clear()
    return False


def maybe_schedule_text_area_activation(
    hwnd: object,
    lparam: object,
    scope: input_scope.InputScope,
    allow_activation: bool,
) -> bool:
    """Track Text Editor header clicks that may create a new text target."""
    if not allow_activation or scope.kind != input_scope.SCOPE_NEUTRAL:
        cancel_pending_text_area_activation()
        return False

    hit = input_scope.text_editor_area_from_mouse_lparam(hwnd, lparam)
    if hit is None:
        cancel_pending_text_area_activation()
        return False

    return schedule_text_area_activation(hwnd, hit)


def cancel_pending_text_area_activation() -> None:
    """Drop delayed Text Editor activation work."""
    runtime.state.text_area_activation.clear()
    safe_ops.unregister_timer(_apply_pending_text_area_activation)


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
        clear_bridge_target_state()
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

    handle_mouse_down(
        hwnd,
        lparam,
        allow_text_area_activation=msg_value == win.WM_LBUTTONDOWN,
    )
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
    if msg_value == win.WM_ACTIVATEAPP and not bool(platform_api.ptr_value(wparam)):
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


def shift_is_down(win: object) -> bool:
    """Shift+Tab still belongs to Blender's unindent shortcut."""
    return bool(win.user32.GetKeyState(win.VK_SHIFT) & 0x8000)


def opens_native_text_ui(win: object, msg_value: int, wparam: object) -> bool:
    """Public shortcuts that hand focus to Blender's own text fields."""
    if msg_value != win.WM_KEYDOWN:
        return False

    key = platform_api.ptr_value(wparam)
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
    runtime.state.input_scope.native_text_ui_handoff = True
    cancel_pending_input_scope()
    clear_bridge_target_state()
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


def is_supported_message(win: object, msg_value: int) -> bool:
    """Ignore the native message noise the bridge never handles."""
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
    if runtime.state.input_scope.native_text_ui_handoff:
        return False

    current_kind = runtime.state.input_scope.current_kind
    if current_kind == input_scope.SCOPE_SHORTCUT_SURFACE:
        return False
    if current_kind == input_scope.SCOPE_ENABLED_TARGET:
        target = runtime.state.composition_target or runtime.state.active_target
        return targets.is_usable_input_target(target)
    return targets.is_usable_input_target(runtime.state.active_target)


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
    try_activate_pending_text_area(hwnd)
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
        text_session = runtime.state.text_ime_session.active_for_text(target.text)
        text_target.mark_composition_committed(text_session)
    else:
        text_session = None
    insert_queue.queue(
        result,
        target,
        text_session,
        hwnd=hwnd,
        source=insert_queue.SOURCE_IME_RESULT,
        suppress_space=True,
    )
    ime_guards.mark_space_suppression(hwnd)


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

    if handle_focus_message(win, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    if handle_native_text_ui_shortcut(win, hwnd, msg_value, wparam):
        return message_result.MessageResult.pass_through()

    handle_native_text_ui_release(win, msg_value, wparam)

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
