"""macOS Cocoa backend for Blender's native IME bridge."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import sys

import bpy

from ..core import runtime


SUPPORTS_NATIVE_BRIDGE = sys.platform == "darwin"
COCOA_CANDIDATE_Y_PADDING = 56
COCOA_CANDIDATE_Y_PADDING_PROP = "imebridge_macos_candidate_y_padding"


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


class NSRange(ctypes.Structure):
    """Objective-C NSRange passed by value on Cocoa text input callbacks."""

    _fields_ = [
        ("location", ctypes.c_ulong),
        ("length", ctypes.c_ulong),
    ]


class ObjC:
    """Typed Objective-C runtime calls used by the Cocoa IME bridge."""

    def __init__(self) -> None:
        self.lib = ctypes.CDLL("/usr/lib/libobjc.A.dylib")
        self.objc_getClass = self.lib.objc_getClass
        self.objc_getClass.argtypes = [ctypes.c_char_p]
        self.objc_getClass.restype = ctypes.c_void_p
        self.sel_registerName = self.lib.sel_registerName
        self.sel_registerName.argtypes = [ctypes.c_char_p]
        self.sel_registerName.restype = ctypes.c_void_p
        self.class_getInstanceMethod = self.lib.class_getInstanceMethod
        self.class_getInstanceMethod.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.class_getInstanceMethod.restype = ctypes.c_void_p
        self.method_getImplementation = self.lib.method_getImplementation
        self.method_getImplementation.argtypes = [ctypes.c_void_p]
        self.method_getImplementation.restype = ctypes.c_void_p
        self.method_setImplementation = self.lib.method_setImplementation
        self.method_setImplementation.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self.method_setImplementation.restype = ctypes.c_void_p
        self.object_getClass = self.lib.object_getClass
        self.object_getClass.argtypes = [ctypes.c_void_p]
        self.object_getClass.restype = ctypes.c_void_p

        self.send_id = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_bool = ctypes.CFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_bool_sel = ctypes.CFUNCTYPE(
            ctypes.c_bool,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_ulong = ctypes.CFUNCTYPE(
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_double = ctypes.CFUNCTYPE(
            ctypes.c_double,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_id_ulong = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
        )(("objc_msgSend", self.lib))
        self.send_void = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_char_p = ctypes.CFUNCTYPE(
            ctypes.c_char_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )(("objc_msgSend", self.lib))
        self.send_begin_ime = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_int32,
            ctypes.c_bool,
        )(("objc_msgSend", self.lib))

        self.ns_application = self.cls("NSApplication")
        self.shared_application = self.sel("sharedApplication")
        self.key_window = self.sel("keyWindow")
        self.main_window = self.sel("mainWindow")
        self.content_view = self.sel("contentView")
        self.backing_scale_factor = self.sel("backingScaleFactor")
        self.is_visible = self.sel("isVisible")
        self.responds_to_selector = self.sel("respondsToSelector:")
        self.subviews = self.sel("subviews")
        self.count = self.sel("count")
        self.object_at_index = self.sel("objectAtIndex:")
        self.begin_ime = self.sel("beginIME:y:w:h:completed:")
        self.end_ime = self.sel("endIME")
        self.insert_text = self.sel("insertText:replacementRange:")
        self.string = self.sel("string")
        self.utf8_string = self.sel("UTF8String")

    def cls(self, name: str) -> int:
        """Return an Objective-C class pointer."""
        return int(self.objc_getClass(name.encode("utf-8")) or 0)

    def sel(self, name: str) -> int:
        """Return a selector pointer."""
        return int(self.sel_registerName(name.encode("utf-8")) or 0)

    def responds(self, obj: int, selector: int) -> bool:
        """Check whether an Objective-C object implements a selector."""
        if not obj or not selector:
            return False
        return bool(self.send_bool_sel(obj, self.responds_to_selector, selector))


class MacOSApi:
    """Small Cocoa facade used by the platform-neutral bridge code."""

    def __init__(self) -> None:
        self.objc = ObjC()
        self._commit_handler = None
        self._insert_text_callback = None
        self._insert_text_records: dict[int, dict[str, object]] = {}
        self._insert_text_imp_type = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            NSRange,
        )

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

    def _record_for_object(self, obj: int) -> dict[str, object] | None:
        """Find the saved original IMP for a Cocoa view object."""
        cls = ptr_value(self.objc.object_getClass(obj))
        if cls in self._insert_text_records:
            return self._insert_text_records[cls]
        for record in self._insert_text_records.values():
            return record
        return None

    def _call_original_insert_text(
        self,
        obj: int,
        selector: int,
        chars: int,
        replacement_range: NSRange,
    ) -> None:
        """Forward Cocoa text input to Blender's original implementation."""
        record = self._record_for_object(obj)
        if record is None:
            return
        original = record.get("callable")
        if original is None:
            return
        original(obj, selector, chars, replacement_range)

    def _handle_insert_text(
        self,
        obj: int,
        selector: int,
        chars: int,
        replacement_range: NSRange,
    ) -> None:
        """Mirror committed IME text, then forward to Blender's implementation."""
        try:
            text = self.text_from_objc_string(chars)
            handler = self._commit_handler
            if text and callable(handler):
                handler(text)
            self._call_original_insert_text(obj, selector, chars, replacement_range)
        except Exception:
            try:
                self._call_original_insert_text(
                    obj,
                    selector,
                    chars,
                    replacement_range,
                )
            except Exception:
                return

    def install_insert_text_hook(self, commit_handler: object) -> int:
        """Patch Blender Cocoa view classes so committed IME text is observable."""
        self._commit_handler = commit_handler
        if self._insert_text_records:
            return len(self._insert_text_records)

        def callback(
            obj: int,
            selector: int,
            chars: int,
            replacement_range: NSRange,
        ) -> None:
            self._handle_insert_text(obj, selector, chars, replacement_range)

        self._insert_text_callback = self._insert_text_imp_type(callback)
        callback_ptr = ctypes.cast(
            self._insert_text_callback,
            ctypes.c_void_p,
        ).value
        if not callback_ptr:
            self._insert_text_callback = None
            self._commit_handler = None
            return 0

        installed = 0
        for class_name in ("CocoaMetalView", "CocoaOpenGLView"):
            cls = self.objc.cls(class_name)
            if not cls:
                continue
            try:
                method = ptr_value(
                    self.objc.class_getInstanceMethod(cls, self.objc.insert_text)
                )
                if not method:
                    continue
                old_imp = ptr_value(self.objc.method_getImplementation(method))
                if not old_imp:
                    continue
                previous = ptr_value(
                    self.objc.method_setImplementation(method, callback_ptr)
                )
            except (OSError, TypeError, ValueError):
                continue
            original_imp = previous or old_imp
            self._insert_text_records[cls] = {
                "method": method,
                "old_imp": original_imp,
                "callable": self._insert_text_imp_type(original_imp),
            }
            installed += 1
        if installed == 0:
            self._insert_text_callback = None
            self._commit_handler = None
        return installed

    def uninstall_insert_text_hook(self) -> int:
        """Restore Cocoa text input methods patched by IMEBridge."""
        restored = 0
        for record in list(self._insert_text_records.values()):
            method = ptr_value(record.get("method"))
            old_imp = ptr_value(record.get("old_imp"))
            if not method or not old_imp:
                continue
            try:
                self.objc.method_setImplementation(method, old_imp)
                restored += 1
            except (OSError, ValueError):
                pass
        self._insert_text_records.clear()
        self._insert_text_callback = None
        self._commit_handler = None
        return restored


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


def cocoa_candidate_y_padding(context: object = None) -> int:
    """Runtime-tunable macOS candidate baseline correction in physical pixels."""
    try:
        context = context or bpy.context
        wm = getattr(context, "window_manager", None)
        if wm is None:
            return COCOA_CANDIDATE_Y_PADDING
        return int(
            getattr(
                wm,
                COCOA_CANDIDATE_Y_PADDING_PROP,
                COCOA_CANDIDATE_Y_PADDING,
            )
        )
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        return COCOA_CANDIDATE_Y_PADDING


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
    candidate_y = point.y + height + cocoa_candidate_y_padding()
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


def install_text_commit_hook(commit_handler: object) -> int:
    """Install the backend hook that mirrors committed Cocoa IME text."""
    api = ensure()
    if api is None:
        return 0
    return api.install_insert_text_hook(commit_handler)


def uninstall_text_commit_hook() -> int:
    """Restore any Cocoa text input methods patched by IMEBridge."""
    api = ensure()
    if api is None:
        return 0
    return api.uninstall_insert_text_hook()
