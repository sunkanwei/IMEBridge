"""Open and close the window IME without touching the system input layout."""

import ctypes
from ctypes import wintypes

from ..core import runtime
from ..win32 import api as win32_api


def hwnd_key(hwnd: object) -> int:
    """Use a stable integer key for ctypes HWND values."""
    return win32_api.ptr_value(hwnd)


def conversion_status_for_context(
    win: object,
    himc: object,
) -> tuple[int, int] | None:
    """Read conversion and sentence modes from an already acquired HIMC."""
    conversion = wintypes.DWORD()
    sentence = wintypes.DWORD()
    if not win.imm32.ImmGetConversionStatus(
        himc,
        ctypes.byref(conversion),
        ctypes.byref(sentence),
    ):
        return None
    return int(conversion.value), int(sentence.value)


def remember_open_status(win: object, hwnd: object, himc: object) -> None:
    """Keep the user's IME state so a plugin-driven close can be undone later."""
    key = hwnd_key(hwnd)
    if key in runtime.state.input_scope.managed_open_status:
        return
    was_open = bool(win.imm32.ImmGetOpenStatus(himc))
    status = conversion_status_for_context(win, himc)
    conversion = None
    sentence = None
    if status is not None:
        conversion, sentence = status
    runtime.state.input_scope.managed_open_status[key] = runtime.ManagedImeState(
        hwnd=hwnd,
        was_open=was_open,
        conversion=conversion,
        sentence=sentence,
    )


def cancel_composition(win: object, himc: object) -> None:
    """Ask the IME to drop preedit text and hide candidates before closing."""
    win.imm32.ImmNotifyIME(
        himc,
        win.NI_COMPOSITIONSTR,
        win.CPS_CANCEL,
        0,
    )
    win.imm32.ImmNotifyIME(
        himc,
        win.NI_CLOSECANDIDATE,
        0,
        0,
    )


def is_open(win: object, hwnd: object) -> bool:
    """Read the current window IME open flag and release the HIMC promptly."""
    if not hwnd:
        return False

    himc = win.imm32.ImmGetContext(hwnd)
    if not himc:
        return False

    try:
        return bool(win.imm32.ImmGetOpenStatus(himc))
    finally:
        win.imm32.ImmReleaseContext(hwnd, himc)


def conversion_status(win: object, hwnd: object) -> tuple[int, int] | None:
    """Read the current IME conversion and sentence modes."""
    if not hwnd:
        return None

    himc = win.imm32.ImmGetContext(hwnd)
    if not himc:
        return None

    try:
        return conversion_status_for_context(win, himc)
    finally:
        win.imm32.ImmReleaseContext(hwnd, himc)


def is_native_conversion_mode(win: object, hwnd: object) -> bool | None:
    """Return whether the IME is in native text mode instead of alphanumeric."""
    status = conversion_status(win, hwnd)
    if status is None:
        return None

    conversion, _sentence = status
    if conversion & win.IME_CMODE_NOCONVERSION:
        return False
    return bool(conversion & win.IME_CMODE_NATIVE)


def restore_conversion_status(
    win: object,
    himc: object,
    record: runtime.ManagedImeState,
) -> bool:
    """Best-effort restore for IMEs that expose conversion modes."""
    if record.conversion is None or record.sentence is None:
        return True
    return bool(
        win.imm32.ImmSetConversionStatus(
            himc,
            record.conversion,
            record.sentence,
        )
    )


def close_for_shortcut_surface(hwnd: object) -> bool:
    """Temporarily put this Blender window into direct-input mode."""
    win = win32_api.ensure_windows()
    if win is None or not hwnd:
        return False

    himc = win.imm32.ImmGetContext(hwnd)
    if not himc:
        return False

    try:
        remember_open_status(win, hwnd, himc)
        cancel_composition(win, himc)
        return bool(win.imm32.ImmSetOpenStatus(himc, False))
    finally:
        win.imm32.ImmReleaseContext(hwnd, himc)


def restore_if_managed(hwnd: object) -> bool:
    """Restore only IME states that IMEBridge changed itself."""
    win = win32_api.ensure_windows()
    if win is None:
        return False

    key = hwnd_key(hwnd)
    record = runtime.state.input_scope.managed_open_status.pop(key, None)
    if record is None:
        return False
    if not record.was_open:
        return True

    himc = win.imm32.ImmGetContext(record.hwnd)
    if not himc:
        runtime.state.input_scope.managed_open_status[key] = record
        return False

    try:
        restored = bool(win.imm32.ImmSetOpenStatus(himc, True))
        if restored:
            restore_conversion_status(win, himc, record)
        else:
            runtime.state.input_scope.managed_open_status[key] = record
        return restored
    finally:
        win.imm32.ImmReleaseContext(record.hwnd, himc)


def restore_all_managed(attempts: int = 3) -> int:
    """Best-effort cleanup for reloads and add-on shutdown."""
    restored = 0
    attempts = max(1, int(attempts))
    for _attempt in range(attempts):
        for _key, record in list(runtime.state.input_scope.managed_open_status.items()):
            if restore_if_managed(record.hwnd):
                restored += 1
        if not runtime.state.input_scope.managed_open_status:
            break
    return restored
