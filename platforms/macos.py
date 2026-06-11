"""macOS Cocoa backend for Blender's native IME bridge."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import sys

import bpy

from ..core import runtime
from .macos_objc import NSPoint, NSRange, ObjC
from .macos_text_hook import MacOSTextInputHookMixin


SUPPORTS_NATIVE_BRIDGE = sys.platform == "darwin"
COCOA_CANDIDATE_Y_PADDING = 56


@dataclass
class Point:
    """Small point object matching the geometry attributes bridge code uses."""

    x: int = 0
    y: int = 0


@dataclass
class Rect:
    """Small rect object matching the geometry attributes bridge code uses."""

    left: int = 0
    top: int = 0
    right: int = 0
    bottom: int = 0


RECT = Rect
POINT = Point


class DWord:
    """Tiny value holder matching the attribute shape of a DWORD."""

    def __init__(self, value: int = 0) -> None:
        """Store the value the same way ctypes scalar objects do."""
        self.value = int(value)


DWORD = DWord


class IMECHARPOSITION(ctypes.Structure):
    """Placeholder for request buffers used only by message-based backends."""

    _fields_: list[tuple[str, object]] = []


class COMPOSITIONFORM(ctypes.Structure):
    """Placeholder for composition forms used only by message-based backends."""

    _fields_: list[tuple[str, object]] = []


class CANDIDATEFORM(ctypes.Structure):
    """Placeholder for candidate forms used only by message-based backends."""

    _fields_: list[tuple[str, object]] = []


class MacOSApi(MacOSTextInputHookMixin):
    """Small Cocoa facade used by the platform-neutral bridge code."""

    def __init__(self) -> None:
        """Prepare Objective-C calls and text-input hooks for this session."""
        self.objc = ObjC()
        self._init_text_input_hook()

    def application(self) -> int:
        """Return the shared NSApplication object."""
        if not self.objc.ns_application:
            return 0
        return ptr_value(
            self.objc.send_id(self.objc.ns_application, self.objc.shared_application)
        )

    def active_ns_window(self) -> int:
        """Prefer the key window, then fall back to the main window."""
        app = self.application()
        if not app:
            return 0

        window = ptr_value(self.objc.send_id(app, self.objc.key_window))
        if window:
            return window
        return ptr_value(self.objc.send_id(app, self.objc.main_window))

    def backing_scale_factor(self, window: int = 0) -> float:
        """Return the NSWindow backing scale used to convert pixels to points."""
        window = ptr_value(window) or self.active_ns_window()
        if not window or not self.objc.responds(window, self.objc.backing_scale_factor):
            return 1.0
        try:
            scale = float(
                self.objc.send_double(window, self.objc.backing_scale_factor)
            )
        except (OSError, TypeError, ValueError):
            return 1.0
        if scale <= 0.0:
            return 1.0
        return scale

    def mouse_location(self, window: int = 0) -> Point | None:
        """Return the mouse location relative to the bottom-left corner of the window in pixels."""
        window = ptr_value(window) or self.active_ns_window()
        if not window:
            return None

        sel_mouse = self.objc.sel("mouseLocationOutsideOfEventStream")
        if not self.objc.responds(window, sel_mouse):
            return None

        try:
            pt = self.objc.send_point(window, sel_mouse)
            scale = self.backing_scale_factor(window)
            return Point(int(round(pt.x * scale)), int(round(pt.y * scale)))
        except (OSError, TypeError, ValueError):
            return None

    def _first_ime_view(self, view: int, depth: int = 0) -> int:
        """Find Blender's Cocoa view without assuming the immediate hierarchy."""
        if not view or depth > 3:
            return 0
        if self.objc.responds(view, self.objc.begin_ime):
            return view

        if not self.objc.responds(view, self.objc.subviews):
            return 0
        subviews = ptr_value(self.objc.send_id(view, self.objc.subviews))
        if not subviews:
            return 0
        count = int(self.objc.send_ulong(subviews, self.objc.count))
        for index in range(count):
            child = ptr_value(
                self.objc.send_id_ulong(subviews, self.objc.object_at_index, index)
            )
            match = self._first_ime_view(child, depth + 1)
            if match:
                return match
        return 0

    def active_view(self) -> int:
        """Return the Cocoa view that implements Blender's IME methods."""
        window = self.active_ns_window()
        if not window:
            return 0
        if self.objc.responds(window, self.objc.is_visible):
            try:
                if not self.objc.send_bool(window, self.objc.is_visible):
                    return 0
            except (OSError, ValueError):
                return 0

        content = ptr_value(self.objc.send_id(window, self.objc.content_view))
        return self._first_ime_view(content)

    def begin_ime(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        completed: bool = False,
    ) -> bool:
        """Tell Blender's Cocoa view where the native candidate UI belongs."""
        view = self.active_view()
        if not view:
            return False
        try:
            self.objc.send_begin_ime(
                view,
                self.objc.begin_ime,
                int(x),
                int(y),
                int(width),
                int(height),
                bool(completed),
            )
        except (OSError, ValueError):
            return False
        return True

    def end_ime(self) -> bool:
        """Ask Blender's Cocoa view to leave IME input focus."""
        view = self.active_view()
        if not view or not self.objc.responds(view, self.objc.end_ime):
            return False
        try:
            self.objc.send_void(view, self.objc.end_ime)
        except (OSError, ValueError):
            return False
        return True

    def text_from_objc_string(self, value: int) -> str:
        """Convert NSString or NSAttributedString into Python text."""
        value = ptr_value(value)
        if not value:
            return ""
        try:
            if self.objc.responds(value, self.objc.string):
                value = ptr_value(self.objc.send_id(value, self.objc.string))
            if not value or not self.objc.responds(value, self.objc.utf8_string):
                return ""
            data = self.objc.send_char_p(value, self.objc.utf8_string)
        except (OSError, ValueError):
            return ""
        if not data:
            return ""
        try:
            return data.decode("utf-8")
        except UnicodeError:
            return ""

def ensure() -> MacOSApi | None:
    """Create the Cocoa bridge lazily in macOS UI sessions."""
    if not SUPPORTS_NATIVE_BRIDGE:
        return None
    if runtime.state.win is None:
        runtime.state.win = MacOSApi()
    return runtime.state.win


def ptr_value(value: object) -> int:
    """Normalize pointer-like values without relying on Win32 handles."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return int(value.value or 0)
    return int(value)


def active_window(api: MacOSApi, window: object = None) -> int:
    """Use Blender's window pointer as the backend-local window key."""
    if window:
        return ptr_value(window)
    key = blender_window_key()
    if key:
        return key
    return api.active_view()


def enum_process_windows(include_children: bool = True) -> list[dict[str, object]]:
    """Expose the active Cocoa IME view as a single hook-like target."""
    api = ensure()
    if api is None:
        return []
    window = active_window(api)
    if not window:
        return []
    return [
        {
            "hwnd": window,
            "hwnd_value": window,
            "visible": True,
            "class": "GHOST_WindowClass",
        }
    ]


def class_name(_api: MacOSApi, window: object) -> str:
    """Return the class label expected by shared target lookup code."""
    return "GHOST_WindowClass" if ptr_value(window) else ""


def is_current_process_window(_api: MacOSApi, window: object) -> bool:
    """Cocoa objects found through NSApp belong to this Blender process."""
    return bool(ptr_value(window))


def window_region(area: object) -> object | None:
    """Return Blender's main WINDOW region."""
    for region in area.regions:
        if region.type == "WINDOW":
            return region
    return None


def blender_window_key(window: object = None) -> int:
    """Return Blender's RNA window pointer when one is available."""
    window = window or getattr(bpy.context, "window", None)
    if window is None:
        return 0
    try:
        return ptr_value(window.as_pointer())
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def _window_from_key(window: object) -> object | None:
    """Find a Blender window by the backend-local pointer key."""
    key = ptr_value(window)
    if not key:
        return getattr(bpy.context, "window", None)
    try:
        windows = tuple(bpy.context.window_manager.windows)
    except (AttributeError, ReferenceError, RuntimeError):
        windows = ()
    for item in windows:
        if blender_window_key(item) == key:
            return item
    return getattr(bpy.context, "window", None)


def _layout_size(window: object = None) -> tuple[int, int]:
    """Read Blender's current screen layout size in region coordinates."""
    window = _window_from_key(window)
    try:
        areas = tuple(window.screen.areas)
    except (AttributeError, ReferenceError, RuntimeError):
        areas = ()
    if areas:
        right = max(int(area.x + area.width) for area in areas)
        top = max(int(area.y + area.height) for area in areas)
        if right > 0 and top > 0:
            return right, top
    width = int(getattr(window, "width", 0) or 0)
    height = int(getattr(window, "height", 0) or 0)
    return width, height


def client_height(_api: MacOSApi, window: object) -> int | None:
    """Return the active Blender window height."""
    _width, height = _layout_size(window)
    return height or None


def client_rect(_api: MacOSApi, window: object) -> Rect | None:
    """Return the active Blender client rectangle."""
    width, height = _layout_size(window)
    if width <= 0 or height <= 0:
        return None
    return Rect(0, 0, width, height)


def client_to_screen(_api: MacOSApi, _window: object, x: float, y: float) -> Point:
    """Mac bridge keeps coordinates in GHOST client space until beginIME."""
    return Point(int(round(x)), int(round(y)))


def screen_to_client(_api: MacOSApi, _window: object, x: float, y: float) -> Point:
    """Mac bridge keeps coordinates in GHOST client space until beginIME."""
    return Point(int(round(x)), int(round(y)))


def region_point_to_screen(
    api: MacOSApi,
    window: object,
    region: object,
    x: float,
    y: float,
) -> Point | None:
    """Convert Blender region coordinates into GHOST client coordinates."""
    height = client_height(api, window)
    if height is None:
        return None
    client_x = region.x + int(round(x))
    client_y = height - (region.y + int(round(y)))
    return Point(client_x, client_y)


def region_rect_to_screen(
    api: MacOSApi,
    window: object,
    region: object,
) -> Rect | None:
    """Convert a Blender region box into GHOST client coordinates."""
    height = client_height(api, window)
    if height is None:
        return None
    return Rect(
        region.x,
        height - (region.y + region.height),
        region.x + region.width,
        height - region.y,
    )


def read_raw_keyboard(_api: MacOSApi, _payload: object) -> dict[str, int] | None:
    """Raw keyboard packets are not exposed through this Cocoa bridge."""
    return None


def restore_ime_contexts() -> int:
    """Cocoa IME focus is activated by beginIME, not context association."""
    return 0


def apply_ime_window_position(
    api: MacOSApi,
    window: object,
    _info: object,
    position: object,
) -> bool:
    """Apply candidate placement through Blender's Cocoa IME entry point."""
    point = screen_to_client(api, window, position.screen_x, position.screen_y)
    if point is None:
        return False
    scale = api.backing_scale_factor()
    height = max(12, int(getattr(_info, "line_height", 18) or 18))
    candidate_y = point.y + height + COCOA_CANDIDATE_Y_PADDING
    return api.begin_ime(
        round(point.x / scale),
        round(candidate_y / scale),
        1,
        max(12, round(height / scale)),
        False,
    )


def end_ime() -> bool:
    """End the current Cocoa IME session if Blender has an active view."""
    api = ensure()
    if api is None:
        return False
    return api.end_ime()


def install_text_commit_hook(
    commit_handler: object,
    ime_allowed_callback: object = None,
) -> int:
    """Install the backend hook that mirrors committed Cocoa IME text."""
    api = ensure()
    if api is None:
        return 0
    return api.install_insert_text_hook(commit_handler, ime_allowed_callback)


def uninstall_text_commit_hook() -> int:
    """Restore any Cocoa text input methods patched by IMEBridge."""
    api = ensure()
    if api is None:
        return 0
    return api.uninstall_insert_text_hook()
