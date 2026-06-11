"""Keyboard guards that keep IME composition from editing Blender text directly."""

from collections.abc import Callable
import time

from . import ime_switch
from ..core import models
from ..core import runtime
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import text as text_target
from ..platforms import native as platform_api


SPACE_CONFIRM_STALE_SECONDS = 2.0
DIRECT_ASCII_STALE_SECONDS = 2.0
SPACE_EVENT_DOWN = "down"
SPACE_EVENT_UP = "up"
SPACE_EVENT_CHAR = "char"


CompositionReader = Callable[[object, object, int], str | None]


def clear_ime_confirm_space() -> None:
    """Forget any pending IME-owned Space key sequence."""
    runtime.state.ime_confirm_space.clear()


def clear_ime_direct_ascii() -> None:
    """Forget pending direct ASCII input diverted from raw keyboard events."""
    runtime.state.ime_direct_ascii.clear()


def refresh_ime_confirm_space(hwnd: object) -> None:
    """Keep the current confirmation Space sequence alive briefly."""
    state = runtime.state.ime_confirm_space
    state.hwnd = platform_api.ptr_value(hwnd)
    state.until = time.monotonic() + SPACE_CONFIRM_STALE_SECONDS


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

    if not is_keyboard_message(win, msg_value):
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
    if event_kind == SPACE_EVENT_UP:
        clear_ime_confirm_space()
    else:
        refresh_ime_confirm_space(hwnd)
    return 0


def handle_ime_confirm_space_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Consume the physical Space key used to confirm an active IME composition."""
    event_kind = space_event_kind(win, msg_value, wparam, lparam)
    if not event_kind:
        return None

    if ime_confirm_space_is_active(hwnd):
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

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    refresh_ime_confirm_space(hwnd)
    feed_ime_keyboard_message(win, hwnd, msg_value, wparam, lparam)
    return 0


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
    comp_string_reader: CompositionReader,
) -> object | None:
    """Find the target for Caps Lock direct ASCII while Chinese IME is open."""
    if modifier_shortcut_is_down(win) or not caps_lock_is_on(win):
        return None
    if not ime_switch.is_open(win, hwnd):
        return None

    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    if native_mode is False:
        return None
    if ime_is_composing(win, hwnd, comp_string_reader):
        return None

    return active_target_for_ime_guard()


def handle_direct_ascii_raw_input(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: CompositionReader,
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
    comp_string_reader: CompositionReader,
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


def is_keyboard_message(win: object, msg_value: int) -> bool:
    """Small local predicate for the keyboard messages we care about."""
    return msg_value in {
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
    }


def modifier_shortcut_is_down(win: object) -> bool:
    """Ctrl and Alt chords belong to Blender or the system, not to this guard."""
    control_down = bool(win.user32.GetKeyState(win.VK_CONTROL) & 0x8000)
    alt_down = bool(win.user32.GetKeyState(win.VK_MENU) & 0x8000)
    return control_down or alt_down


def is_preedit_vkey(value: int) -> bool:
    """Letters, digits, and common punctuation keys can feed IME preedit."""
    if 0x30 <= value <= 0x5A:
        return True
    if 0xBA <= value <= 0xC0:
        return True
    return 0xDB <= value <= 0xDF


def is_preedit_char(value: int) -> bool:
    """Printable non-space ASCII chars are the usual leaked pinyin payload."""
    return 0x21 <= value <= 0x7E


def ime_can_accept_preedit_text(win: object, hwnd: object) -> bool:
    """Allow ASCII preedit guards only in an IME conversion mode that needs them."""
    if not ime_switch.is_open(win, hwnd):
        return False

    native_mode = ime_switch.is_native_conversion_mode(win, hwnd)
    if native_mode is None:
        return True
    return native_mode


def ime_edit_guard_vkeys(win: object) -> set[int]:
    """Keys that should edit the IME preedit string, not Blender's buffer."""
    return {
        win.VK_BACK,
        win.VK_DELETE,
        win.VK_LEFT,
        win.VK_RIGHT,
        win.VK_UP,
        win.VK_DOWN,
        win.VK_HOME,
        win.VK_END,
        win.VK_PRIOR,
        win.VK_NEXT,
        win.VK_ESCAPE,
    }


def active_target_for_ime_guard() -> object | None:
    """Pick the target currently at risk from IME edit keys."""
    target = runtime.state.composition_target or runtime.state.active_target
    if not targets.is_usable_input_target(target):
        return None
    return target


def ime_is_composing(
    win: object,
    hwnd: object,
    comp_string_reader: CompositionReader,
) -> bool:
    """Return whether the IME is currently composing."""
    comp = comp_string_reader(win, hwnd, win.GCS_COMPSTR)
    return bool(runtime.state.composition_target) or bool(comp)


def ime_edit_guard_target(
    win: object,
    hwnd: object,
    comp_string_reader: CompositionReader,
) -> object | None:
    """Expose a target to guards only while the IME owns the keystrokes."""
    target = active_target_for_ime_guard()
    if target is None or not ime_is_composing(win, hwnd, comp_string_reader):
        return None
    return target


def protect_text_target_from_ime_edit(target: object) -> None:
    """Snapshot the Text Editor before swallowing an edit key."""
    if models.is_text_editor_target(target):
        text_target.schedule_restore_guard(target)


def handle_preedit_text_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
) -> int | None:
    """Stop pinyin preedit keystrokes from becoming real Blender text."""
    if not is_keyboard_message(win, msg_value):
        return None
    if modifier_shortcut_is_down(win) or not ime_can_accept_preedit_text(win, hwnd):
        return None

    target = active_target_for_ime_guard()
    if not models.is_text_editor_target(target):
        return None

    value = platform_api.ptr_value(wparam)
    if msg_value == win.WM_CHAR and not is_preedit_char(value):
        return None
    if msg_value != win.WM_CHAR and not is_preedit_vkey(value):
        return None

    protect_text_target_from_ime_edit(target)
    win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
    return 0


def handle_raw_input_guard(
    win: object,
    hwnd: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Raw input can reach Blender before translated IME messages do."""
    raw = platform_api.read_raw_keyboard(win, lparam)
    if raw is None:
        return None

    if raw["vkey"] not in ime_edit_guard_vkeys(win):
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    protect_text_target_from_ime_edit(target)
    return 0


def handle_ime_edit_key_guard(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Let the native IME consume navigation and deletion keys during composition."""
    w_value = platform_api.ptr_value(wparam)
    is_guarded_char = msg_value == win.WM_CHAR and w_value in {
        win.VK_BACK,
        win.VK_ESCAPE,
        0x7F,
    }
    if w_value not in ime_edit_guard_vkeys(win) and not is_guarded_char:
        return None

    target = ime_edit_guard_target(win, hwnd, comp_string_reader)
    if target is None:
        return None

    if msg_value in {
        win.WM_IME_KEYDOWN,
        win.WM_IME_KEYUP,
        win.WM_KEYDOWN,
        win.WM_KEYUP,
        win.WM_CHAR,
    }:
        protect_text_target_from_ime_edit(target)
        win.imm32.ImmIsUIMessageW(hwnd, msg_value, wparam, lparam)
        return 0

    return None


def handle_message_guards(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
    lparam: object,
    comp_string_reader: CompositionReader,
) -> int | None:
    """Run the keyboard shields before normal IME dispatch."""
    space_result = handle_ime_confirm_space_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if space_result is not None:
        return space_result

    direct_ascii_result = handle_direct_ascii_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if direct_ascii_result is not None:
        return direct_ascii_result

    if msg_value == win.WM_INPUT:
        raw_result = handle_raw_input_guard(win, hwnd, lparam, comp_string_reader)
        if raw_result is not None:
            return raw_result

    edit_result = handle_ime_edit_key_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
        comp_string_reader,
    )
    if edit_result is not None:
        return edit_result

    preedit_result = handle_preedit_text_guard(
        win,
        hwnd,
        msg_value,
        wparam,
        lparam,
    )
    if preedit_result is not None:
        return preedit_result

    return None
