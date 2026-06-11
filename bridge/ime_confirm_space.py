"""Guard the physical Space key while it confirms an IME composition."""

import time

from . import ime_guard_common as common
from ..core import runtime
from ..platforms import native as platform_api


SPACE_CONFIRM_STALE_SECONDS = 2.0
SPACE_EVENT_DOWN = "down"
SPACE_EVENT_UP = "up"
SPACE_EVENT_CHAR = "char"


def clear_ime_confirm_space() -> None:
    """Forget any pending IME-owned Space key sequence."""
    runtime.state.ime_confirm_space.clear()


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
    if ime_confirm_space_is_active(hwnd):
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
        return None

    begin_ime_confirm_space(hwnd, event_kind)
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    return 0
