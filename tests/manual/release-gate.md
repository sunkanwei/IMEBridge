# Release Gate

Run this short, high-value checklist before publishing. It is required when
changes touch `bridge/`, `targets/`, `platforms/`, `win32/`, or when preparing a
release tag.

## Windows

- [ ] New or reset preferences: Shortcut IME Avoidance is unchecked by default.
- [ ] Microsoft Pinyin: committed Chinese text appears once in Text Editor with no extra space.
- [ ] Microsoft Pinyin: selected English text in Text Editor is replaced correctly by committed Chinese text.
- [ ] Microsoft Pinyin: Backspace and arrow keys during composition only edit the IME preedit/candidate state, not the Text datablock.
- [ ] Microsoft Pinyin: after Space confirms Chinese text, the next real Space key still inserts a space normally.
- [ ] Microsoft Pinyin: with Caps Lock on and Chinese IME open, uppercase letters and English symbols commit exactly once.
- [ ] 3D Text edit mode: committed Chinese text appears once, with no duplicated text, missing text, or extra space.
- [ ] With Shortcut IME Avoidance enabled: after clicking View3D, Node Editor, and Graph Editor, Blender shortcuts are not captured by Chinese IME.
- [ ] With Shortcut IME Avoidance disabled: clicking shortcut-heavy canvases does not close the window IME, and committed text is not inserted into a stale Text Editor or 3D Text target.
- [ ] Returning to Text Editor restores only window IME state that IMEBridge temporarily closed itself.
- [ ] Ctrl+F, F2, and F3: Blender native text UI remains outside IMEBridge ownership.
- [ ] Pressing Tab after Chinese identifier text indents instead of triggering Unicode autocomplete behavior.

## macOS

- [ ] System IME: committed Chinese text appears once in Text Editor.
- [ ] 3D Text edit mode: committed Chinese text appears once, without duplicates.
- [ ] With Shortcut IME Avoidance enabled: while the mouse is over shortcut-heavy canvases, IME focus/input context does not steal Blender shortcuts.
- [ ] With Shortcut IME Avoidance disabled: shortcut-heavy canvases do not end the Cocoa IME session, and committed text is not inserted into a stale text target.
- [ ] Returning to a text target moves the candidate window back near the active target.

## Packaging

- [ ] `python tests/run.py full` passes.
- [ ] Blender extension build succeeds.
- [ ] `python tests/run.py release --package <zip>` passes.
- [ ] The git repository contains `tests/`, and the built zip does not contain `tests/`.
