# ClipNest (PySide6 + SQLite)

A cross-platform clipboard manager for Windows and macOS.

## Features

- Real-time clipboard text capture.
- Real-time clipboard image capture and local SQLite BLOB storage.
- Per-tab dedupe (`UNIQUE(tab_id, content_hash)`).
- Tab/category management (create, rename, delete).
- Manual item creation and item list management.
- Right-click menu on item list: edit, delete, clear list.
- Click item to copy + auto paste into active app.
- Custom global hotkey (top-right settings menu, key recording dialog).
- Optional always-on-top window.
- Local persistence via SQLite.

## Quick start

Recommended Python version: `3.10 - 3.12` (PySide6 wheels are commonly available).

```bash
pip install -r requirements.txt
python main.py
```

## Default behavior

- Default tabs: `常用语 / 代码 / 地址 / 账号`
- Max items per tab: `500` (oldest entries auto-evicted)
- Global hotkey:
  - Windows: `Ctrl+Shift+V`
  - macOS: `Cmd+Shift+V`
  - Press once to open main window, press again to hide to background tray.

## Notes

- Data is stored in plaintext SQLite in local app data directory.
- On macOS, Accessibility permission may be needed for global hotkey and simulated paste.

## Build Windows EXE (onedir)

Use the included script:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Optional custom icon:

- Place `assets\clipnest.ico` (preferred), or
- Place `assets\clipnest.png` (script auto-converts to `ico`).

Output:

- EXE directory: `dist\ClipNest\`
- App executable: `dist\ClipNest\ClipNest.exe`
- Desktop shortcut: `ClipNest.lnk` (created automatically)

## Build macOS App (run on Mac)

> macOS `.app` cannot be built on Windows.  
> Please run the script below on a macOS machine.

```bash
chmod +x ./scripts/build_macos.sh
./scripts/build_macos.sh
```

Output (separate folder):

- App bundle: `release/macos/ClipNest.app`
- Distributable zip: `release/macos/ClipNest_macOS.zip`

Optional icon for macOS dock:

- Put `assets/clipnest.icns` (recommended).
