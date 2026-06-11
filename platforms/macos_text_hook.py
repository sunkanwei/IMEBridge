"""Cocoa text input swizzling for the macOS backend."""

import ctypes

from .macos_objc import NSRange


def _ptr_value(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if hasattr(value, "value"):
        return int(value.value or 0)
    return int(value)


class MacOSTextInputHookMixin:
    """Install and restore Cocoa text input methods patched by IMEBridge."""

    def _init_text_input_hook(self) -> None:
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
        self._ime_allowed_callback = None
        self._input_context_callback = None
        self._input_context_records: dict[int, dict[str, object]] = {}
        self._input_context_imp_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )

    def _record_for_object(self, obj: int) -> dict[str, object] | None:
        """Find the saved original IMP for a Cocoa view object."""
        cls = _ptr_value(self.objc.object_getClass(obj))
        if cls in self._insert_text_records:
            return self._insert_text_records[cls]
        for record in self._insert_text_records.values():
            return record
        return None

    def _input_context_record_for_object(self, obj: int) -> dict[str, object] | None:
        """Find the saved original IMP of inputContext for a Cocoa view object."""
        cls = _ptr_value(self.objc.object_getClass(obj))
        if cls in self._input_context_records:
            return self._input_context_records[cls]
        for record in self._input_context_records.values():
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
        """Handle committed IME text and safely clear OS marked state."""
        handled = False
        try:
            text = self.text_from_objc_string(chars)
            handler = self._commit_handler
            if text and callable(handler):
                handled = bool(handler(text))
        except Exception:
            pass

        if not handled:
            try:
                self._call_original_insert_text(obj, selector, chars, replacement_range)
            except Exception:
                pass
        else:
            try:
                if self.objc.responds(obj, self.objc.unmark_text):
                    self.objc.send_void(obj, self.objc.unmark_text)
            except Exception:
                pass

    def install_insert_text_hook(
        self,
        commit_handler: object,
        ime_allowed_callback: object = None,
    ) -> int:
        """Patch Blender Cocoa view classes so committed IME text is managed."""
        self._commit_handler = commit_handler
        self._ime_allowed_callback = ime_allowed_callback
        if self._insert_text_records:
            return len(self._insert_text_records)

        def callback(
            obj: int,
            selector: int,
            chars: int,
            replacement_range: NSRange,
        ) -> None:
            self._handle_insert_text(obj, selector, chars, replacement_range)

        def input_context_callback(obj: int, selector: int) -> int:
            try:
                allowed_cb = self._ime_allowed_callback
                allowed = allowed_cb() if callable(allowed_cb) else True
                if not allowed:
                    return 0
                record = self._input_context_record_for_object(obj)
                if record is not None:
                    original = record.get("callable")
                    if original is not None:
                        return _ptr_value(original(obj, selector))
            except Exception:
                pass
            return 0

        self._insert_text_callback = self._insert_text_imp_type(callback)
        callback_ptr = ctypes.cast(
            self._insert_text_callback,
            ctypes.c_void_p,
        ).value

        self._input_context_callback = self._input_context_imp_type(
            input_context_callback,
        )
        ic_callback_ptr = ctypes.cast(
            self._input_context_callback,
            ctypes.c_void_p,
        ).value

        if not callback_ptr or not ic_callback_ptr:
            self._insert_text_callback = None
            self._input_context_callback = None
            self._commit_handler = None
            self._ime_allowed_callback = None
            return 0

        installed = 0
        for class_name in ("CocoaMetalView", "CocoaOpenGLView"):
            cls = self.objc.cls(class_name)
            if not cls:
                continue
            try:
                method = _ptr_value(
                    self.objc.class_getInstanceMethod(cls, self.objc.insert_text)
                )
                if not method:
                    continue
                old_imp = _ptr_value(self.objc.method_getImplementation(method))
                if not old_imp:
                    continue
                previous = _ptr_value(
                    self.objc.method_setImplementation(method, callback_ptr)
                )
                original_imp = previous or old_imp
                self._insert_text_records[cls] = {
                    "method": method,
                    "old_imp": original_imp,
                    "callable": self._insert_text_imp_type(original_imp),
                }

                method_ic = _ptr_value(
                    self.objc.class_getInstanceMethod(cls, self.objc.input_context)
                )
                if method_ic:
                    old_imp_ic = _ptr_value(self.objc.method_getImplementation(method_ic))
                    if old_imp_ic:
                        previous_ic = _ptr_value(
                            self.objc.method_setImplementation(
                                method_ic,
                                ic_callback_ptr,
                            )
                        )
                        original_imp_ic = previous_ic or old_imp_ic
                        self._input_context_records[cls] = {
                            "method": method_ic,
                            "old_imp": original_imp_ic,
                            "callable": self._input_context_imp_type(original_imp_ic),
                        }
            except (OSError, TypeError, ValueError):
                continue
            installed += 1

        if installed == 0:
            self.uninstall_insert_text_hook()
        return installed

    def uninstall_insert_text_hook(self) -> int:
        """Restore Cocoa text input methods patched by IMEBridge."""
        restored = 0
        for record in list(self._insert_text_records.values()):
            method = _ptr_value(record.get("method"))
            old_imp = _ptr_value(record.get("old_imp"))
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

        for record in list(self._input_context_records.values()):
            method = _ptr_value(record.get("method"))
            old_imp = _ptr_value(record.get("old_imp"))
            if not method or not old_imp:
                continue
            try:
                self.objc.method_setImplementation(method, old_imp)
            except (OSError, ValueError):
                pass
        self._input_context_records.clear()
        self._input_context_callback = None
        self._ime_allowed_callback = None
        return restored
