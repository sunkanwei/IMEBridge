"""Fallback handling for committed characters in 3D Text edit mode."""

import time

import bpy

from . import ime_guards
from ..core import models
from ..core import runtime
from ..targets import detect as targets
from ..targets import queue as insert_queue
from ..targets import state as target_state
from ..platforms import native as platform_api


FONT_RESULT_DEDUP_SECONDS = 0.35
IME_CONTROL_CHAR_VALUES = {0x08, 0x09, 0x0A, 0x0D, 0x1B, 0x7F}
LEGACY_IME_ENCODINGS = ("gbk", "mbcs")
CJK_OR_FULLWIDTH_RANGES = (
    (0x2E80, 0x2EFF, "CJK Radicals Supplement"),
    (0x3000, 0x303F, "CJK Symbols and Punctuation"),
    (0x3400, 0x4DBF, "CJK Unified Ideographs Extension A"),
    (0x4E00, 0x9FFF, "CJK Unified Ideographs"),
    (0xF900, 0xFAFF, "CJK Compatibility Ideographs"),
    (0xFF00, 0xFFEF, "Halfwidth and Fullwidth Forms"),
)


def is_cjk_or_fullwidth(char: str) -> bool:
    """Limit fallback char commits to scripts IMEs commonly emit here."""
    if not char:
        return False
    value = ord(char)
    return any(start <= value <= end for start, end, _name in CJK_OR_FULLWIDTH_RANGES)


def is_control_char_value(value: int) -> bool:
    """Control-key payloads are not committed text."""
    return value <= 0 or value in IME_CONTROL_CHAR_VALUES


def char_from_codepoint(value: int) -> str:
    """Accept direct Unicode payloads, but avoid surrogate garbage."""
    if value > 0x10FFFF:
        return ""
    try:
        char = chr(value)
    except ValueError:
        return ""
    if 0xD800 <= ord(char) <= 0xDFFF:
        return ""
    if is_cjk_or_fullwidth(char):
        return char
    return ""


def decode_legacy_two_byte_ime_char(value: int) -> str:
    """Handle older IMEs that still pack text into two bytes."""
    if not 0x0100 <= value <= 0xFFFF:
        return ""

    data = bytes([(value >> 8) & 0xFF, value & 0xFF])
    for encoding in LEGACY_IME_ENCODINGS:
        try:
            char = data.decode(encoding)
        except UnicodeError:
            continue
        if char and any(is_cjk_or_fullwidth(item) for item in char):
            return char
    return ""


def decode_ime_char_value(value: object) -> str:
    """Normalize the char-shaped fallback messages some IMEs send."""
    value = int(value)
    if is_control_char_value(value):
        return ""

    return char_from_codepoint(value) or decode_legacy_two_byte_ime_char(value)


def font_result_target_key(target: object) -> int:
    """Use the Blender object pointer for short-lived duplicate detection."""
    if not models.is_font_edit_target(target) or target.obj is None:
        return 0
    return platform_api.ptr_value(target.obj.as_pointer())


def mark_recent_font_result(target: object, text: str | None) -> None:
    """Remember the result path so the char fallback does not insert twice."""
    state = runtime.state.font_result_dedup
    state.target_key = font_result_target_key(target)
    state.text = text or ""
    state.echo_index = 0
    state.until = time.monotonic() + FONT_RESULT_DEDUP_SECONDS


def recent_font_commit_active() -> bool:
    """Keep the 3D Text target trusted while late IME messages settle."""
    state = runtime.state.font_result_dedup
    if not state.target_key:
        return False
    if time.monotonic() > state.until:
        state.clear()
        return False
    return True


def is_recent_font_target(target: object) -> bool:
    """Check whether a Font target owns the current settling window."""
    if not recent_font_commit_active():
        return False
    return runtime.state.font_result_dedup.target_key == font_result_target_key(target)


def is_recent_font_result_char(target: object, char: str) -> bool:
    """Check whether a char fallback is just echoing a result string."""
    if not is_recent_font_target(target):
        return False
    state = runtime.state.font_result_dedup
    if not char or state.echo_index >= len(state.text):
        return False
    if char != state.text[state.echo_index]:
        state.clear_echo()
        return False
    state.echo_index += 1
    if state.echo_index >= len(state.text):
        state.clear_echo()
    return True


def font_input_target_from_state() -> object | None:
    """Resolve only the 3D Text target; other editors use their own path."""
    target = targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        bpy.context,
    )
    if models.is_font_edit_target(target):
        return target
    return None


def handle_font_char_commit(
    win: object,
    hwnd: object,
    msg_value: int,
    wparam: object,
) -> int | None:
    """Catch 3D Text commits from IMEs that skip GCS_RESULTSTR."""
    if msg_value not in {win.WM_IME_CHAR, win.WM_CHAR}:
        return None

    target = font_input_target_from_state()
    if target is None:
        return None

    value = platform_api.ptr_value(wparam)
    if msg_value == win.WM_CHAR and value < 0x80:
        return None

    char = decode_ime_char_value(value)
    if not char:
        return None

    if is_recent_font_result_char(target, char):
        return 0

    target_state.set_active_target(target)
    insert_queue.queue(
        char,
        target,
        hwnd=hwnd,
        source=insert_queue.SOURCE_FONT_CHAR,
        suppress_space=True,
    )
    ime_guards.mark_space_suppression(hwnd)
    return 0
