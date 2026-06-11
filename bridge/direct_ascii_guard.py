"""Guard Caps Lock direct ASCII input while an IME is open."""

import time

from . import ime_guard_common as common
from . import ime_switch
from ..core import runtime
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..platforms import native as platform_api


DIRECT_ASCII_STALE_SECONDS = 2.0


def clear_ime_direct_ascii() -> None:
    """Forget pending direct ASCII input diverted from raw keyboard events."""
    runtime.state.ime_direct_ascii.clear()


def caps_lock_is_on(win: object) -> bool:
    """Read Caps Lock as a toggle state, not as a held modifier."""
    return bool(win.user32.GetKeyState(win.VK_CAPITAL) & 0x0001)


def direct_ascii_state_is_active(hwnd: object) -> bool:
    """Return whether this window has a recent raw key waiting for WM_CHAR."""
    state = runtime.state.ime_direct_ascii
    if not state.hwnd:
        return False
    if time.monotonic() > state.until:
        clear_ime_direct_ascii()
        return False
    return state.hwnd == platform_api.ptr_value(hwnd)


def refresh_direct_ascii_state(hwnd: object) -> None:
    """Keep the direct ASCII handoff alive until the translated char arrives."""
    state = runtime.state.ime_direct_ascii
    state.hwnd = platform_api.ptr_value(hwnd)
    state.until = time.monotonic() + DIRECT_ASCII_STALE_SECONDS


def finish_direct_ascii_if_idle() -> None:
    """Clear the handoff when no key or translated char is still pending."""
    state = runtime.state.ime_direct_ascii
    if state.pending_chars <= 0 and not state.active_vkeys:
        state.clear()


def remember_direct_ascii_key(hwnd: object, vkey: int, target: object) -> None:
    """Record one raw keydown that must be completed by a WM_CHAR."""
    state = runtime.state.ime_direct_ascii
    refresh_direct_ascii_state(hwnd)
    state.target = target
    state.active_vkeys.add(int(vkey))
    state.pending_chars += 1


def release_direct_ascii_key(hwnd: object, vkey: int) -> None:
    """Finish the translated keyup that belongs to a diverted ASCII key."""
    state = runtime.state.ime_direct_ascii
    if not direct_ascii_state_is_active(hwnd):
        return
    state.active_vkeys.discard(int(vkey))
    refresh_direct_ascii_state(hwnd)
    finish_direct_ascii_if_idle()


def consume_direct_ascii_char(hwnd: object) -> None:
    """Use one pending translated character for direct ASCII insertion."""
    state = runtime.state.ime_direct_ascii
    if not direct_ascii_state_is_active(hwnd):
        return
    state.pending_chars = max(0, state.pending_chars - 1)
    refresh_direct_ascii_state(hwnd)
    finish_direct_ascii_if_idle()


def direct_ascii_has_key(hwnd: object, vkey: int) -> bool:
    """Check whether a raw key sequence is already owned by direct ASCII mode."""
    if not direct_ascii_state_is_active(hwnd):
        return False
    return int(vkey) in runtime.state.ime_direct_ascii.active_vkeys


def direct_ascii_has_pending_char(hwnd: object) -> bool:
    """Check whether a WM_CHAR should complete a diverted raw key."""
    if not direct_ascii_state_is_active(hwnd):
        return False
    return runtime.state.ime_direct_ascii.pending_chars > 0


def direct_ascii_pending_target(hwnd: object) -> object | None:
    """Return the target captured when raw input was diverted."""
    if not direct_ascii_state_is_active(hwnd):
        return None
    target = runtime.state.ime_direct_ascii.target
    if not targets.is_usable_input_target(target):
        clear_ime_direct_ascii()
        return None
    return target


def is_direct_ascii_vkey(win: object, vkey: int) -> bool:
    """Limit raw interception to keys that can normally translate to ASCII text."""
    if vkey == win.VK_SPACE:
        return True
    if 0x30 <= vkey <= 0x5A:
        return True
    if 0xBA <= vkey <= 0xC0:
        return True
    if 0xDB <= vkey <= 0xDF:
        return True
    return vkey == win.VK_OEM_102


def is_direct_ascii_char(value: int) -> bool:
    """Accept only printable ASCII produced by the active keyboard layout."""
    return 0x20 <= value <= 0x7E


def direct_ascii_target(
    win: object,
    hwnd: object,
    comp_string_reader: common.CompositionReader,
) -> object | None:
    """Find the target for Caps Lock direct ASCII while Chinese IME is open."""
    if common.modifier_shortcut_is_down(win) or not caps_lock_is_on(win):
        return None
    if not ime_switch.is_open(win, hwnd):
        return None

    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    if native_mode is False:
        return None
    if common.ime_is_composing(win, hwnd, comp_string_reader):
        return None

    return common.active_target_for_ime_guard()


def handle_direct_ascii_raw_input(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: common.CompositionReader,
) -> int | None:
    """Divert raw printable keys so WM_CHAR can become the single text source."""
    raw = platform_api.read_raw_keyboard(win, lparam)
    if raw is None or not is_direct_ascii_vkey(win, raw["vkey"]):
        return None

    if not raw["key_down"]:
        if direct_ascii_has_key(hwnd, raw["vkey"]):
            refresh_direct_ascii_state(hwnd)
            return 0
        return None

    target = direct_ascii_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    remember_direct_ascii_key(hwnd, raw["vkey"], target)
    return 0


def handle_direct_ascii_key_message(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> int | None:
    """Swallow translated key messages for raw keys already diverted."""
    if msg_value not in {
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
    }:
        return None

    vkey = platform_api.ptr_value(wparam)
    if not direct_ascii_has_key(hwnd, vkey):
        return None

    if msg_value in {win.WM_KEYUP, win.WM_IME_KEYUP}:
        release_direct_ascii_key(hwnd, vkey)
    else:
        refresh_direct_ascii_state(hwnd)
    return 0


def handle_direct_ascii_char(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> int | None:
    """Insert the actual printable character generated for a diverted raw key."""
    if msg_value != win.WM_CHAR:
        return None
    if not direct_ascii_has_pending_char(hwnd):
        return None

    value = platform_api.ptr_value(wparam)
    if not is_direct_ascii_char(value):
        consume_direct_ascii_char(hwnd)
        return 0

    target = direct_ascii_pending_target(hwnd)
    if target is None:
        return 0

    insert_queue.queue(
        chr(value),
        target,
        hwnd=hwnd,
        source=insert_queue.SOURCE_DIRECT_ASCII,
    )
    consume_direct_ascii_char(hwnd)
    return 0


def handle_direct_ascii_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: common.CompositionReader,
) -> int | None:
    """Route Caps Lock ASCII through WM_CHAR instead of Blender raw input."""
    if msg_value == win.WM_INPUT:
        return handle_direct_ascii_raw_input(
            win,
            hwnd,
            lparam,
            comp_string_reader,
        )

    char_result = handle_direct_ascii_char(
        win,
        hwnd,
        msg_value,
        wparam,
    )
    if char_result is not None:
        return char_result

    return handle_direct_ascii_key_message(
        win,
        hwnd,
        msg_value,
        wparam,
    )
