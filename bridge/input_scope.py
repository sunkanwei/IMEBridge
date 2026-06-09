"""Classify Blender click targets before the IME bridge touches them."""

from dataclasses import dataclass

import bpy

from . import nexus_whitelist
from ..targets import detect as targets
from ..win32 import api as win32_api


SCOPE_ENABLED_TARGET = "enabled_target"
SCOPE_SHORTCUT_SURFACE = "shortcut_surface"
SCOPE_NEUTRAL = "neutral"

SHORTCUT_SURFACE_AREAS = {
    "VIEW_3D",
    "NODE_EDITOR",
    "DOPESHEET_EDITOR",
    "GRAPH_EDITOR",
    "NLA_EDITOR",
    "SEQUENCE_EDITOR",
    "IMAGE_EDITOR",
    "CLIP_EDITOR",
}


@dataclass(frozen=True)
class AreaHit:
    """A click resolved to Blender's main WINDOW region for one area."""

    window: object
    area: object
    region: object
    space: object
    client_x: int = 0
    client_y: int = 0
    window_x: int = 0
    window_y: int = 0
    area_x: int = 0
    area_y: int = 0


@dataclass(frozen=True)
class InputScope:
    """The bridge's answer to: should this click allow IME input here?"""

    kind: str
    hwnd: object = None
    target: object = None
    hit: AreaHit | None = None


def client_point_from_lparam(lparam: object) -> tuple[int, int]:
    """Mouse coordinates arrive packed as signed 16-bit client values."""
    value = win32_api.ptr_value(lparam)
    x = value & 0xFFFF
    y = (value >> 16) & 0xFFFF
    if x >= 0x8000:
        x -= 0x10000
    if y >= 0x8000:
        y -= 0x10000
    return x, y


def area_hit_at_client_point(
    hwnd: object,
    client_x: int,
    client_y: int,
) -> AreaHit | None:
    """Map a Win32 mouse point back to Blender's current screen layout."""
    win = win32_api.ensure_windows()
    if win is None:
        return None

    client_height = win32_api.client_height(win, hwnd)
    if client_height is None:
        return None

    blender_y = client_height - client_y
    for window in candidate_windows():
        screen = window.screen
        for area in screen.areas:
            region = win32_api.window_region(area)
            if region is None:
                continue
            if not (region.x <= client_x < region.x + region.width):
                continue
            if region.y <= blender_y < region.y + region.height:
                return AreaHit(
                    window,
                    area,
                    region,
                    area.spaces.active,
                    client_x=client_x,
                    client_y=client_y,
                    window_x=client_x,
                    window_y=blender_y,
                    area_x=client_x - region.x,
                    area_y=blender_y - region.y,
                )
    return None


def candidate_windows() -> list[object]:
    """Prefer Blender's active window, then fall back to all known windows."""
    windows = []
    seen = set()

    def add(window: object) -> None:
        """Keep window ordering stable without trusting object identity."""
        if window is None:
            return
        key = win32_api.ptr_value(window.as_pointer())
        if key in seen:
            return
        seen.add(key)
        windows.append(window)

    add(getattr(bpy.context, "window", None))
    for window in bpy.context.window_manager.windows:
        add(window)
    return windows


def enabled_target_from_hit(hit: AreaHit) -> object | None:
    """Return a bridge-owned text target only for areas we can handle."""
    area_type = getattr(hit.area, "type", None)
    if area_type == "TEXT_EDITOR":
        return targets.make_text_editor_target(
            hit.window,
            hit.area,
            hit.region,
            hit.space,
        )
    if area_type == "VIEW_3D":
        return targets.make_font_edit_target(
            hit.window,
            hit.area,
            hit.region,
            hit.space,
        )
    return None


def classify_hit(hwnd: object, hit: AreaHit | None) -> InputScope:
    """Prefer explicit targets, then explicit shortcut surfaces, then neutral."""
    if hit is None:
        return InputScope(SCOPE_NEUTRAL, hwnd=hwnd)

    target = enabled_target_from_hit(hit)
    if target is not None:
        return InputScope(
            SCOPE_ENABLED_TARGET,
            hwnd=hwnd,
            target=target,
            hit=hit,
        )

    if nexus_whitelist.is_nexusui_surface_hit(hit):
        return InputScope(SCOPE_NEUTRAL, hwnd=hwnd, hit=hit)

    area_type = getattr(hit.area, "type", None)
    if area_type in SHORTCUT_SURFACE_AREAS:
        return InputScope(SCOPE_SHORTCUT_SURFACE, hwnd=hwnd, hit=hit)

    return InputScope(SCOPE_NEUTRAL, hwnd=hwnd, hit=hit)


def from_mouse_lparam(hwnd: object, lparam: object) -> InputScope:
    """Resolve a mouse-down message into an IMEBridge input scope."""
    client_x, client_y = client_point_from_lparam(lparam)
    return classify_hit(hwnd, area_hit_at_client_point(hwnd, client_x, client_y))


def scope_area_type(scope: InputScope) -> str:
    """Expose the editor type without leaking AreaHit details to callers."""
    if scope.hit is None:
        return ""
    return str(getattr(scope.hit.area, "type", "") or "")
