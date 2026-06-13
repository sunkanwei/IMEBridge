import bpy

from .bridge import ime_context
from .bridge import window_hook
from .preferences import config
from .preferences import i18n


classes = (
    config.IMEBridgePreferences,
)


def register() -> None:
    """Register Blender classes and start the IME bridge runtime."""
    for cls in classes:
        bpy.utils.register_class(cls)
    i18n.register()
    ime_context.register_text_draw_handler()
    window_hook.schedule_auto_enable()


def unregister() -> None:
    """Stop the IME bridge runtime and unregister Blender classes."""
    window_hook.cancel_auto_enable()
    ime_context.unregister_text_draw_handler()
    window_hook.stop_hooks()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    i18n.unregister()
