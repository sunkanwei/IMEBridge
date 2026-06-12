"""Cocoa text input swizzling for the macOS backend."""

import ctypes

from .macos_objc import NSRange


def _ptr_value(value: object) -> int:
    """Turn pointer-like ctypes values into a plain integer."""
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
        """Set up callback slots and restore records before any swizzling."""
        self._commit_handler = None
        self._bridge_owner_callback = None
        self._insert_text_callback = None
        self._insert_text_records: dict[int, dict[str, object]] = {}
        self._insert_text_imp_type = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            NSRange,
        )
        self._set_marked_text_callback = None
        self._set_marked_text_records: dict[int, dict[str, object]] = {}
        self._set_marked_text_imp_type = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
            NSRange,
            NSRange,
        )
        self._unmark_text_callback = None
        self._unmark_text_records: dict[int, dict[str, object]] = {}
        self._void_text_imp_type = ctypes.CFUNCTYPE(
            None,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self._ime_allowed_callback = None
        self._input_context_callback = None
        self._input_context_records: dict[int, dict[str, object]] = {}
        self._input_context_imp_type = ctypes.CFUNCTYPE(
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        )
        self._bridge_session_active = False

    def _record_from_object(
        self,
        records: dict[int, dict[str, object]],
        obj: int,
    ) -> dict[str, object] | None:
        """Find the saved original IMP for a Cocoa view object."""
        cls = _ptr_value(self.objc.object_getClass(obj))
        if cls in records:
            return records[cls]
        for record in records.values():
            return record
        return None

    def _record_for_object(self, obj: int) -> dict[str, object] | None:
        """Find the saved original IMP for insertText."""
        return self._record_from_object(self._insert_text_records, obj)

    def _input_context_record_for_object(self, obj: int) -> dict[str, object] | None:
        """Find the saved original IMP of inputContext for a Cocoa view object."""
        return self._record_from_object(self._input_context_records, obj)

    def _install_method_patch(
        self,
        records: dict[int, dict[str, object]],
        cls: int,
        method: int,
        replacement: int,
        imp_type: object,
    ) -> bool:
        """Replace one Objective-C IMP only after its restore record is ready."""
        old_imp = _ptr_value(self.objc.method_getImplementation(method))
        if not old_imp:
            return False

        original_imp = old_imp
        original_callable = imp_type(original_imp)
        replaced = False
        try:
            previous = _ptr_value(
                self.objc.method_setImplementation(method, replacement)
            )
            replaced = True
            original_imp = previous or old_imp
            if original_imp != old_imp:
                original_callable = imp_type(original_imp)
        except (OSError, TypeError, ValueError):
            if replaced:
                try:
                    self.objc.method_setImplementation(method, original_imp)
                except (OSError, TypeError, ValueError):
                    pass
            raise

        records[cls] = {
            "method": method,
            "old_imp": original_imp,
            "callable": original_callable,
        }
        return True

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

    def _call_original_set_marked_text(
        self,
        obj: int,
        selector: int,
        chars: int,
        selected_range: NSRange,
        replacement_range: NSRange,
    ) -> None:
        """Forward marked text to Blender's original implementation."""
        record = self._record_from_object(self._set_marked_text_records, obj)
        if record is None:
            return
        original = record.get("callable")
        if original is None:
            return
        original(obj, selector, chars, selected_range, replacement_range)

    def _call_original_unmark_text(self, obj: int, selector: int) -> None:
        """Forward unmarkText to Blender's original implementation."""
        record = self._record_from_object(self._unmark_text_records, obj)
        if record is None:
            return
        original = record.get("callable")
        if original is None:
            return
        original(obj, selector)

    def _original_input_context(self, obj: int) -> int:
        """Return Blender's original NSTextInputContext for a patched view."""
        record = self._input_context_record_for_object(obj)
        if record is None:
            return 0
        original = record.get("callable")
        if original is None:
            return 0
        return _ptr_value(original(obj, self.objc.input_context))

    def _discard_marked_text(self, obj: int) -> None:
        """Ask Cocoa to drop preedit text owned by IMEBridge."""
        try:
            context = self._original_input_context(obj)
            if context and self.objc.responds(context, self.objc.discard_marked_text):
                self.objc.send_void(context, self.objc.discard_marked_text)
        except Exception:
            pass

    def _clear_bridge_session(self) -> None:
        """Forget the marked text owned by IMEBridge."""
        self._bridge_session_active = False

    def _finish_bridge_session(self, obj: int, *, discard: bool = True) -> None:
        """Release IMEBridge ownership of the active Cocoa text session."""
        self._clear_native_marked_text(obj)
        self._clear_bridge_session()
        if discard:
            self._discard_marked_text(obj)

    def _bridge_should_own_text_input(self) -> bool:
        """Return whether the current Cocoa text session belongs to IMEBridge."""
        try:
            callback = self._bridge_owner_callback
            return bool(callback()) if callable(callback) else False
        except Exception:
            return False

    def _set_bridge_marked_text(self, chars: int) -> None:
        """Remember that the current native preedit belongs to IMEBridge."""
        text = self.text_from_objc_string(chars)
        if not text:
            self._clear_bridge_session()
            return

        self._bridge_session_active = True

    def _clear_native_marked_text(self, obj: int) -> None:
        """End Blender's native IME composition without committing text to its UI."""
        try:
            self._call_original_set_marked_text(
                obj,
                self.objc.set_marked_text,
                0,
                NSRange(0, 0),
                NSRange(0, 0),
            )
        except Exception:
            pass

    def _handle_set_marked_text(
        self,
        obj: int,
        selector: int,
        chars: int,
        selected_range: NSRange,
        replacement_range: NSRange,
    ) -> None:
        """Let native preedit drive candidates while tracking IMEBridge ownership."""
        owns_session = (
            self._bridge_session_active or self._bridge_should_own_text_input()
        )
        try:
            self._call_original_set_marked_text(
                obj,
                selector,
                chars,
                selected_range,
                replacement_range,
            )
        except Exception:
            pass

        if owns_session:
            try:
                self._set_bridge_marked_text(chars)
            except Exception:
                self._clear_bridge_session()

    def _handle_insert_text(
        self,
        obj: int,
        selector: int,
        chars: int,
        replacement_range: NSRange,
    ) -> None:
        """Handle committed IME text and safely clear OS marked state."""
        handled = False
        owns_session = (
            self._bridge_session_active or self._bridge_should_own_text_input()
        )
        try:
            text = self.text_from_objc_string(chars)
            handler = self._commit_handler
            if owns_session and text and callable(handler):
                handled = bool(handler(text))
        except Exception:
            pass

        if owns_session:
            self._finish_bridge_session(obj, discard=True)
            return

        if not handled:
            try:
                self._call_original_insert_text(obj, selector, chars, replacement_range)
            except Exception:
                pass

    def _handle_unmark_text(self, obj: int, selector: int) -> None:
        """Release bridge ownership on cancellation; otherwise defer to Blender."""
        if self._bridge_session_active:
            self._finish_bridge_session(obj, discard=False)
            return

        try:
            self._call_original_unmark_text(obj, selector)
        except Exception:
            pass

    def install_insert_text_hook(
        self,
        commit_handler: object,
        ime_allowed_callback: object = None,
        bridge_owner_callback: object = None,
    ) -> int:
        """Patch Blender Cocoa view classes so committed IME text is managed."""
        self._commit_handler = commit_handler
        self._ime_allowed_callback = ime_allowed_callback
        self._bridge_owner_callback = bridge_owner_callback
        if self._insert_text_records:
            return len(self._insert_text_records)

        def callback(
            obj: int,
            selector: int,
            chars: int,
            replacement_range: NSRange,
        ) -> None:
            """Pass insertText calls through the hook handler."""
            self._handle_insert_text(obj, selector, chars, replacement_range)

        def set_marked_text_callback(
            obj: int,
            selector: int,
            chars: int,
            selected_range: NSRange,
            replacement_range: NSRange,
        ) -> None:
            """Pass setMarkedText calls through the hook handler."""
            self._handle_set_marked_text(
                obj,
                selector,
                chars,
                selected_range,
                replacement_range,
            )

        def unmark_text_callback(obj: int, selector: int) -> None:
            """Pass unmarkText calls through the hook handler."""
            self._handle_unmark_text(obj, selector)

        def input_context_callback(obj: int, selector: int) -> int:
            """Return nil when IME input should stay quiet."""
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
        self._set_marked_text_callback = self._set_marked_text_imp_type(
            set_marked_text_callback,
        )
        set_marked_text_callback_ptr = ctypes.cast(
            self._set_marked_text_callback,
            ctypes.c_void_p,
        ).value
        self._unmark_text_callback = self._void_text_imp_type(
            unmark_text_callback,
        )
        unmark_text_callback_ptr = ctypes.cast(
            self._unmark_text_callback,
            ctypes.c_void_p,
        ).value

        self._input_context_callback = self._input_context_imp_type(
            input_context_callback,
        )
        ic_callback_ptr = ctypes.cast(
            self._input_context_callback,
            ctypes.c_void_p,
        ).value

        if not all(
            (
                callback_ptr,
                set_marked_text_callback_ptr,
                unmark_text_callback_ptr,
                ic_callback_ptr,
            )
        ):
            self._clear_hook_callbacks()
            self._commit_handler = None
            self._ime_allowed_callback = None
            self._bridge_owner_callback = None
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
                if not self._install_method_patch(
                    self._insert_text_records,
                    cls,
                    method,
                    callback_ptr,
                    self._insert_text_imp_type,
                ):
                    continue
            except (OSError, TypeError, ValueError):
                continue

            required_patches = (
                (
                    self._set_marked_text_records,
                    self.objc.set_marked_text,
                    set_marked_text_callback_ptr,
                    self._set_marked_text_imp_type,
                ),
                (
                    self._unmark_text_records,
                    self.objc.unmark_text,
                    unmark_text_callback_ptr,
                    self._void_text_imp_type,
                ),
                (
                    self._input_context_records,
                    self.objc.input_context,
                    ic_callback_ptr,
                    self._input_context_imp_type,
                ),
            )
            try:
                for records, selector, replacement, imp_type in required_patches:
                    method = _ptr_value(
                        self.objc.class_getInstanceMethod(cls, selector)
                    )
                    if not method:
                        raise ValueError("missing Cocoa text input method")
                    self._install_method_patch(
                        records,
                        cls,
                        method,
                        replacement,
                        imp_type,
                    )
            except (OSError, TypeError, ValueError):
                self.uninstall_insert_text_hook()
                return 0
            installed += 1

        if installed == 0:
            self.uninstall_insert_text_hook()
        return installed

    def _clear_hook_callbacks(self) -> None:
        """Release Python callback references held for Objective-C IMPs."""
        self._insert_text_callback = None
        self._set_marked_text_callback = None
        self._unmark_text_callback = None
        self._input_context_callback = None

    def _restore_method_records(self, records: dict[int, dict[str, object]]) -> int:
        """Restore one family of swizzled Objective-C methods."""
        restored = 0
        for record in list(records.values()):
            method = _ptr_value(record.get("method"))
            old_imp = _ptr_value(record.get("old_imp"))
            if not method or not old_imp:
                continue
            try:
                self.objc.method_setImplementation(method, old_imp)
                restored += 1
            except (OSError, TypeError, ValueError):
                pass
        records.clear()
        return restored

    def uninstall_insert_text_hook(self) -> int:
        """Restore Cocoa text input methods patched by IMEBridge."""
        restored = self._restore_method_records(self._insert_text_records)
        self._restore_method_records(self._set_marked_text_records)
        self._restore_method_records(self._unmark_text_records)
        self._restore_method_records(self._input_context_records)
        self._clear_hook_callbacks()
        self._commit_handler = None
        self._ime_allowed_callback = None
        self._bridge_owner_callback = None
        self._clear_bridge_session()
        return restored
