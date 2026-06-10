# IMEBridge Architecture

IMEBridge is a Windows IME bridge for Blender. It enables IME-based text input
in Blender's Text Editor and 3D Text edit mode without requiring manual panel
buttons after installation.

## Layers

- `__init__.py`: add-on lifecycle, registration rollback, and cleanup.
- `preferences/`: add-on preferences and localized preference labels.
- `core/`: shared models, runtime state, safe cleanup, and message results.
- `win32/`: Win32, IMM32, window enumeration, and coordinate conversion.
- `bridge/`: window hooks, message routing, IME scope switching,
  positioning, and guards.
- `targets/`: Blender target discovery plus Text Editor and 3D Text insertion.

## Input Flow

During registration, the add-on schedules automatic enablement. The bridge
restores IME contexts for Blender windows, hooks the main GHOST window
procedure, and routes supported Win32 and IME messages through Blender-aware
target handling.

Mouse clicks are classified into three scopes: supported text targets,
shortcut-heavy editor canvases, and neutral UI. Supported targets keep IMEBridge
active. Shortcut canvases temporarily close the current Blender window IME so
Blender shortcuts remain direct input. Neutral UI clears IMEBridge targets and
undoes any plugin-driven close, but does not guess at Blender's native text
widgets. Shortcuts that open Blender's own text UI, such as search, rename, and
Text Editor find, are treated as neutral before Blender handles them.
Known add-on surfaces such as NexusUI are also classified as neutral before the
shortcut-canvas rule when their own visible UI layers are hit.

The Text Editor path records the composition start body and selection range,
protects the text buffer from IME editing keys, removes leaked confirmation
spaces, and commits the IME result as a small text transaction. The transaction
first tries Blender's Text Editor operator, then verifies the expected body and
falls back to rebuilding the Text datablock when the operator cannot preserve
the saved replacement semantics.

The 3D Text path intentionally uses a different strategy. It suppresses the
confirmation space at the Win32 message layer before Blender's native font edit
mode can consume it, then inserts committed text through Blender's font operator.

## Invariants

- Exceptions must never escape a Win32 window procedure.
- Hook restoration only runs when the current window procedure is still ours.
- Text Editor and 3D Text input paths are intentionally separate.
- IMEBridge only restores IME states it closed itself.
- Native Blender UI fields stay outside the bridge target whitelist.
- Non-Windows and background sessions degrade to safe no-op behavior.
