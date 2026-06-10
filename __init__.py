import bpy

from .bridge import ime_context
from .bridge import macos_event_bridge
from .bridge import window_hook
from .preferences import config
from .preferences import i18n


_REGISTERED_CLASSES = (
    config.IMEBridgePreferences,
    macos_event_bridge.IMEBRIDGE_OT_macos_event_bridge,
)


def _unregister_classes(classes: tuple[type, ...] | list[type]) -> None:
    """Blender may leave us half-registered after a failed reload."""
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            continue


def register() -> None:
    """Set up the bridge, and unwind cleanly if any Blender step refuses."""
    registered_classes = []
    try:
        i18n.register()
        for cls in _REGISTERED_CLASSES:
            bpy.utils.register_class(cls)
            registered_classes.append(cls)
        ime_context.register_text_draw_handler()
        window_hook.schedule_auto_enable()
    except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
        window_hook.cancel_auto_enable()
        ime_context.unregister_text_draw_handler()
        window_hook.stop_hooks()
        _unregister_classes(registered_classes)
        i18n.unregister()
        raise


def unregister() -> None:
    """Take down timers, hooks, handlers, classes, and translations."""
    window_hook.cancel_auto_enable()
    ime_context.unregister_text_draw_handler()
    window_hook.stop_hooks()
    _unregister_classes(_REGISTERED_CLASSES)
    i18n.unregister()
