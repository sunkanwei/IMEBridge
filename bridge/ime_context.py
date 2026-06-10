"""IME context restoration, composition text reading, and candidate geometry."""

import ctypes
import time
from ctypes import wintypes

import bpy

from ..core import models
from ..core import runtime
from ..core import safe_ops
from ..preferences import config
from ..targets import caret as text_caret
from ..targets import detect as targets
from ..targets import state as target_state
from ..win32 import api as win32_api


LINE_EXCLUSION_PADDING = 6
TEXT_CARET_PREPOSITION_INTERVAL = 0.25
# 3D Text edit mode does not expose a Python caret screen position. These
# values anchor the IME candidate window to a stable point inside the View3D
# region instead of pretending to follow an unavailable caret.
FONT_CANDIDATE_REGION_X = 16
FONT_CANDIDATE_REGION_Y = 32
FONT_CANDIDATE_LINE_HEIGHT = 28


def restore_ime_contexts() -> int:
    """Ask IMM32 to give Blender windows their default IME context back."""
    win = win32_api.ensure_windows()
    if win is None:
        return 0

    restored = 0
    for item in win32_api.enum_process_windows(include_children=True):
        ok = bool(
            win.imm32.ImmAssociateContextEx(
                item["hwnd"],
                None,
                win.IACE_DEFAULT,
            )
        )
        if ok:
            restored += 1
    return restored


def read_composition_string(win: object, hwnd: object, index: int) -> str | None:
    """Read a composition buffer; IMM32 reports the size in bytes."""
    himc = win.imm32.ImmGetContext(hwnd)
    if not himc:
        return None
    try:
        size = win.imm32.ImmGetCompositionStringW(himc, index, None, 0)
        if size <= 0:
            return ""

        char_count = (size // ctypes.sizeof(ctypes.c_wchar)) + 1
        buffer = ctypes.create_unicode_buffer(char_count)
        copied = win.imm32.ImmGetCompositionStringW(
            himc,
            index,
            ctypes.byref(buffer),
            size,
        )
        if copied < 0:
            return None
        return buffer.value
    finally:
        win.imm32.ImmReleaseContext(hwnd, himc)


def ghost_window_for_ime(win: object, hwnd: object = None) -> object | None:
    """Find the Blender window IMM32 should talk to right now."""
    if hwnd and win32_api.class_name(win, hwnd) == "GHOST_WindowClass":
        return hwnd

    foreground = win.user32.GetForegroundWindow()
    if (
        foreground
        and win32_api.is_current_process_window(win, foreground)
        and win32_api.class_name(win, foreground) == "GHOST_WindowClass"
    ):
        return foreground

    for item in win32_api.enum_process_windows(include_children=False):
        if item["visible"] and item["class"] == "GHOST_WindowClass":
            return item["hwnd"]
    return None


def line_exclusion_rect(
    win: object,
    hwnd: object,
    info: models.CandidateInfo,
) -> object | None:
    """Keep candidate windows from sitting directly on the active line."""
    client = win32_api.client_rect(win, hwnd)
    caret = win32_api.screen_to_client(win, hwnd, info.screen_x, info.screen_y)
    if client is None or caret is None:
        return None

    line_height = max(12, int(info.line_height))
    top = max(client.top, caret.y - LINE_EXCLUSION_PADDING)
    bottom = min(client.bottom, caret.y + line_height + LINE_EXCLUSION_PADDING)
    if bottom <= top:
        bottom = min(client.bottom, top + line_height)
    return wintypes.RECT(client.left, top, client.right, bottom)


def font_edit_candidate_info(
    win: object,
    hwnd: object,
    target: object,
) -> models.CandidateInfo | None:
    """Use a stable View3D anchor for 3D Text candidate windows."""
    if not models.is_font_edit_target(target):
        return None

    point = win32_api.region_point_to_screen(
        win,
        hwnd,
        target.region,
        FONT_CANDIDATE_REGION_X,
        FONT_CANDIDATE_REGION_Y,
    )
    rect = win32_api.region_rect_to_screen(win, hwnd, target.region)
    if point is None or rect is None:
        return None

    return models.CandidateInfo(
        space=target.space,
        screen_x=point.x,
        screen_y=point.y,
        line_height=FONT_CANDIDATE_LINE_HEIGHT,
        rect=rect,
    )


def font_edit_candidate_position(
    info: models.CandidateInfo,
) -> models.CandidatePosition:
    """3D Text uses the fixed View3D anchor without manual cursor chasing."""
    return models.CandidatePosition(
        screen_x=int(info.screen_x),
        screen_y=int(info.screen_y),
    )


def candidate_info_for_target(
    win: object,
    hwnd: object,
    target: object,
) -> models.CandidateInfo | None:
    """Collect the raw geometry needed by the target-specific placement code."""
    if models.is_text_editor_target(target):
        return text_caret.text_editor_caret_info(hwnd, target)
    if models.is_font_edit_target(target):
        return font_edit_candidate_info(win, hwnd, target)
    return None


def candidate_position_for_target(
    info: models.CandidateInfo,
    target: object,
    requested_char: int = 0,
) -> models.CandidatePosition | None:
    """Let each target decide how raw geometry turns into a candidate point."""
    if models.is_text_editor_target(target):
        return text_caret.ime_candidate_position(info, requested_char)
    if models.is_font_edit_target(target):
        return font_edit_candidate_position(info)
    return None


def build_composition_form(
    win: object,
    client_point: object,
    exclusion: object,
) -> object:
    """Prepare the small IMM32 struct for composition placement."""
    comp_form = win32_api.COMPOSITIONFORM()
    comp_form.dwStyle = win.CFS_POINT
    comp_form.ptCurrentPos.x = client_point.x
    comp_form.ptCurrentPos.y = client_point.y
    comp_form.rcArea = exclusion
    return comp_form


def build_candidate_form(win: object, client_point: object, exclusion: object) -> object:
    """Prepare the candidate form with the active line as an exclusion area."""
    cand_form = win32_api.CANDIDATEFORM()
    cand_form.dwIndex = 0
    cand_form.dwStyle = win.CFS_EXCLUDE
    cand_form.ptCurrentPos.x = client_point.x
    cand_form.ptCurrentPos.y = client_point.y
    cand_form.rcArea = exclusion
    return cand_form


def apply_ime_window_position(
    win: object,
    hwnd: object,
    info: models.CandidateInfo,
    position: models.CandidatePosition,
) -> bool:
    """Apply both composition and candidate positions while the HIMC is held."""
    client_point = win32_api.screen_to_client(
        win,
        hwnd,
        position.screen_x,
        position.screen_y,
    )
    exclusion = line_exclusion_rect(win, hwnd, info)
    if client_point is None or exclusion is None:
        return False

    himc = win.imm32.ImmGetContext(hwnd)
    if not himc:
        return False

    try:
        comp_form = build_composition_form(win, client_point, exclusion)
        cand_form = build_candidate_form(win, client_point, exclusion)

        ok_comp = bool(
            win.imm32.ImmSetCompositionWindow(himc, ctypes.byref(comp_form))
        )
        ok_cand = bool(
            win.imm32.ImmSetCandidateWindow(himc, ctypes.byref(cand_form))
        )
    finally:
        win.imm32.ImmReleaseContext(hwnd, himc)

    return ok_comp or ok_cand


def update_ime_candidate_position(hwnd: object = None, target: object = None) -> bool:
    """Reposition the IME window when Blender gives us enough geometry."""
    if not config.preposition_candidate():
        return False

    win = win32_api.ensure_windows()
    if win is None:
        return False

    hwnd = ghost_window_for_ime(win, hwnd)
    if not hwnd:
        return False

    target = target or runtime.state.composition_target or runtime.state.active_target
    if not targets.is_usable_input_target(target):
        return False

    info = candidate_info_for_target(win, hwnd, target)
    if info is None:
        return False

    position = candidate_position_for_target(info, target)
    if position is None:
        return False
    return apply_ime_window_position(win, hwnd, info, position)


def text_editor_draw_heartbeat() -> None:
    """A light redraw heartbeat keeps the Text Editor candidate near the caret."""
    if bpy.app.background or not runtime.state.insert_on_commit:
        return
    if not models.is_text_editor_target(runtime.state.active_target):
        return
    if not config.preposition_candidate():
        return

    now = time.monotonic()
    if now - runtime.state.last_preposition_at < TEXT_CARET_PREPOSITION_INTERVAL:
        return
    runtime.state.last_preposition_at = now

    try:
        update_ime_candidate_position(target=runtime.state.active_target)
    except (AttributeError, ReferenceError, RuntimeError):
        return


def register_text_draw_handler() -> None:
    """Install the Text Editor heartbeat in UI sessions."""
    if bpy.app.background or runtime.state.text_draw_handler is not None:
        return
    try:
        runtime.state.text_draw_handler = bpy.types.SpaceTextEditor.draw_handler_add(
            text_editor_draw_heartbeat,
            tuple(),
            "WINDOW",
            "POST_PIXEL",
        )
    except (AttributeError, RuntimeError, TypeError):
        runtime.state.text_draw_handler = None


def unregister_text_draw_handler() -> None:
    """Remove the Text Editor heartbeat during reload or shutdown."""
    safe_ops.remove_text_draw_handler(runtime.state.text_draw_handler)
    runtime.state.text_draw_handler = None


def ime_char_position_pointer(lparam: object) -> object | None:
    """Treat the IMR_QUERYCHARPOSITION lparam as an IMECHARPOSITION pointer."""
    l_value = win32_api.ptr_value(lparam)
    if not l_value:
        return None
    return ctypes.cast(
        ctypes.c_void_p(l_value),
        ctypes.POINTER(win32_api.IMECHARPOSITION),
    )


def write_ime_char_position(
    lparam: object,
    info: models.CandidateInfo,
    position: models.CandidatePosition,
) -> bool:
    """Fill the caller-owned IMECHARPOSITION buffer."""
    ptr = ime_char_position_pointer(lparam)
    if ptr is None:
        return False
    ptr.contents.dwSize = ctypes.sizeof(win32_api.IMECHARPOSITION)
    ptr.contents.pt.x = position.screen_x
    ptr.contents.pt.y = position.screen_y
    ptr.contents.cLineHeight = int(info.line_height)
    ptr.contents.rcDocument = info.rect
    return True


def handle_ime_query_char_position(
    win: object,
    hwnd: object,
    lparam: object,
) -> int | None:
    """Answer candidate-position queries from IMEs that ask for caret geometry."""
    target = targets.resolve_input_target(
        runtime.state.composition_target,
        runtime.state.active_target,
        bpy.context,
    )
    if models.is_font_edit_target(target):
        target_state.set_active_target(target)
        return handle_font_query_char_position(win, hwnd, lparam, target)

    info = text_caret.text_editor_caret_info(hwnd, target)
    if info is None:
        return None

    try:
        ptr = ime_char_position_pointer(lparam)
        if ptr is None:
            return None
        requested_char = int(ptr.contents.dwCharPos)
        position = candidate_position_for_target(info, target, requested_char)
        if position is None:
            return None
        if not write_ime_char_position(lparam, info, position):
            return None
    except (AttributeError, ReferenceError, RuntimeError, ValueError):
        return None

    return 1


def handle_font_query_char_position(
    win: object,
    hwnd: object,
    lparam: object,
    target: object,
) -> int | None:
    """Reply to caret queries with the fixed 3D Text View3D anchor."""
    info = font_edit_candidate_info(win, hwnd, target)
    if info is None:
        return None

    try:
        position = font_edit_candidate_position(info)
        if not write_ime_char_position(lparam, info, position):
            return None
    except (AttributeError, ReferenceError, RuntimeError):
        return None

    return 1


def handle_ime_request(
    win: object,
    hwnd: object,
    wparam: object,
    lparam: object,
) -> int | None:
    """Handle the small subset of WM_IME_REQUEST used for positioning."""
    request_value = win32_api.ptr_value(wparam)
    if request_value == win.IMR_QUERYCHARPOSITION:
        result = handle_ime_query_char_position(win, hwnd, lparam)
        if result is not None:
            return result
    return None
