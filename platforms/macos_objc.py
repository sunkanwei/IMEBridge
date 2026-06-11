"""Typed Objective-C runtime bindings used by the macOS backend."""

import ctypes


class NSRange(ctypes.Structure):
    """Objective-C NSRange passed by value on Cocoa text input callbacks."""

    _fields_ = [
        ("location", ctypes.c_ulong),
        ("length", ctypes.c_ulong),
    ]


class NSPoint(ctypes.Structure):
    """Objective-C NSPoint/CGPoint representing 2D coordinates."""

    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
    ]


class ObjC:
    """Typed Objective-C runtime calls used by the Cocoa IME bridge."""

    def __init__(self) -> None:
        """Load libobjc and cache the selectors the bridge uses."""
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
        self.send_point = ctypes.CFUNCTYPE(
            NSPoint,
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
        self.input_context = self.sel("inputContext")
        self.string = self.sel("string")
        self.unmark_text = self.sel("unmarkText")
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
