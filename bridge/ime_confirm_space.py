"""Guard the physical Space key while it confirms an IME composition."""

import time

from . import ime_guard_common as common
from . import ime_switch
from ..core import models
from ..core import runtime
from ..platforms import native as platform_api
from ..targets import font_restore
from ..targets import text as text_target


SPACE_CONFIRM_STALE_SECONDS = 2.0
VK_PROCESSKEY = 0xE5
SPACE_EVENT_DOWN = "down"
SPACE_EVENT_UP = "up"
SPACE_EVENT_CHAR = "char"


def clear_ime_confirm_space() -> None:
    """Forget any pending IME-owned Space key sequence."""
    runtime.state.ime_confirm_space.clear()


def clear_hidden_text_ime_activity() -> None:
    """Forget IME key activity that has not yet become a composition."""
    runtime.state.text_hidden_ime_activity.clear()
    runtime.state.font_hidden_ime_activity.clear()


def refresh_ime_confirm_space(hwnd: object) -> None:
    """Keep the current confirmation Space sequence alive briefly."""
    state = runtime.state.ime_confirm_space
    state.hwnd = platform_api.ptr_value(hwnd)
    state.until = time.monotonic() + SPACE_CONFIRM_STALE_SECONDS


def begin_ime_confirm_space(hwnd: object, event_kind: str) -> None:
    """Start tracking one physical Space key owned by IME confirmation."""
    state = runtime.state.ime_confirm_space
    refresh_ime_confirm_space(hwnd)
    state.released = False
    state.char_seen = event_kind == SPACE_EVENT_CHAR


def ime_confirm_space_is_active(hwnd: object) -> bool:
    """Return whether this window still owns a confirmation Space sequence."""
    state = runtime.state.ime_confirm_space
    if not state.hwnd:
        return False
    if time.monotonic() > state.until:
        clear_ime_confirm_space()
        return False
    return state.hwnd == platform_api.ptr_value(hwnd)


def space_event_kind(
    win: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> str:
    """Classify Space messages without treating time as the source of truth."""
    if msg_value == win.WM_INPUT:
        raw = platform_api.read_raw_keyboard(win, lparam)
        if raw is None or raw["vkey"] != win.VK_SPACE:
            return ""
        return SPACE_EVENT_DOWN if raw["key_down"] else SPACE_EVENT_UP

    if not common.is_keyboard_message(win, msg_value):
        return ""
    if platform_api.ptr_value(wparam) != win.VK_SPACE:
        return ""
    if msg_value in {win.WM_KEYUP, win.WM_IME_KEYUP}:
        return SPACE_EVENT_UP
    if msg_value == win.WM_CHAR:
        return SPACE_EVENT_CHAR
    return SPACE_EVENT_DOWN


def feed_ime_keyboard_message(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> None:
    """Forward translated Space messages to IMM while raw input stays local."""
    if msg_value != win.WM_INPUT:
        win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)


def handle_active_ime_confirm_space(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    event_kind: str,
) -> int | None:
    """Swallow only messages that belong to the remembered physical Space key."""
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    state = runtime.state.ime_confirm_space
    if event_kind == SPACE_EVENT_CHAR:
        state.char_seen = True
    if event_kind == SPACE_EVENT_UP:
        state.released = True

    if state.released and state.char_seen:
        clear_ime_confirm_space()
        return 0

    refresh_ime_confirm_space(hwnd)
    return 0


def _native_ime_may_be_composing(win: object, hwnd: object) -> bool:
    """Return whether the window IME is in a native mode worth guarding."""
    if not ime_switch.is_open(win, hwnd):
        return False
    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    return native_mode is not False


def _is_process_key_message(win: object, msg_value: int, wparam: object) -> bool:
    """Detect IME-owned key messages emitted before composition starts."""
    if msg_value not in {win.WM_KEYDOWN, win.WM_IME_KEYDOWN}:
        return False
    process_key = getattr(win, "VK_PROCESSKEY", VK_PROCESSKEY)
    return platform_api.ptr_value(wparam) == process_key


def remember_hidden_text_ime_activity(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> None:
    """Remember IME key activity before IMM exposes a composition string."""
    if not _is_process_key_message(win, msg_value, wparam):
        return
    if common.modifier_shortcut_is_down(win):
        return
    if not _native_ime_may_be_composing(win, hwnd):
        return

    target = common.active_target_for_ime_guard()
    if models.is_font_edit_target(target):
        font_restore.remember_hidden_ime_activity(hwnd, target)
        return

    target_text = text_target.text_data_from_target(target)
    if target_text is None:
        return
    state = runtime.state.text_hidden_ime_activity
    state.hwnd = platform_api.ptr_value(hwnd)
    state.text = target_text
    state.until = time.monotonic() + runtime.TEXT_HIDDEN_IME_ACTIVITY_SECONDS


def hidden_text_ime_activity_is_active(hwnd: object, target: object) -> bool:
    """Return whether a hidden preedit sequence recently targeted this Text."""
    state = runtime.state.text_hidden_ime_activity
    if state.text is None:
        return False
    if state.hwnd and state.hwnd != platform_api.ptr_value(hwnd):
        return False
    if time.monotonic() > state.until:
        clear_hidden_text_ime_activity()
        return False

    target_text = text_target.text_data_from_target(target)
    return target_text is not None and text_target.same_text_data(
        state.text,
        target_text,
    )


def text_space_may_confirm_ime(
    win: object,
    hwnd: object,
    target: object,
) -> bool:
    """Return whether an unowned Space may still belong to IME confirmation."""
    if common.modifier_shortcut_is_down(win):
        return False
    target_text = text_target.text_data_from_target(target)
    if target_text is None:
        return False
    session = runtime.state.text_ime_session.active_for_text(target_text)
    hidden = hidden_text_ime_activity_is_active(hwnd, target)
    return session is not None or hidden


def font_space_may_confirm_ime(
    hwnd: object,
    target: object,
) -> bool:
    """Return whether a Font Space may still belong to hidden IME activity."""
    return (
        models.is_font_edit_target(target)
        and font_restore.hidden_ime_activity_is_active(hwnd, target)
    )


def remember_possible_confirm_space_leak(
    win: object,
    hwnd: object,
    event_kind: str,
) -> None:
    """Snapshot editable target state before a maybe-IME Space passes through."""
    if event_kind not in {SPACE_EVENT_DOWN, SPACE_EVENT_CHAR}:
        return
    target = common.active_target_for_ime_guard()
    if text_space_may_confirm_ime(win, hwnd, target):
        text_target.remember_possible_confirm_space_leak(hwnd, target)
        clear_hidden_text_ime_activity()
    elif font_space_may_confirm_ime(hwnd, target):
        font_restore.remember_possible_confirm_space_leak(hwnd, target)
        clear_hidden_text_ime_activity()


def handle_ime_confirm_space_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: common.CompositionReader,
) -> int | None:
    """Consume the physical Space key used to confirm an active IME composition."""
    event_kind = space_event_kind(win, msg_value, wparam, lparam)
    if not event_kind:
        return None

    state = runtime.state.ime_confirm_space
    active = ime_confirm_space_is_active(hwnd)
    if active:
        if event_kind == SPACE_EVENT_DOWN and state.released and not state.char_seen:
            clear_ime_confirm_space()
        else:
            result = handle_active_ime_confirm_space(
                win,
                hwnd,
                msg_value,
                wparam,
                lparam,
                event_kind,
            )
            if result is not None:
                return result

    if event_kind == SPACE_EVENT_UP:
        return None

    target = common.ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        remember_possible_confirm_space_leak(win, hwnd, event_kind)
        return None

    begin_ime_confirm_space(hwnd, event_kind)
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    return 0
