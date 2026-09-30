# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

_pyside6_dir = Path(r"C:\Users\lll\Desktop\jianqieban\.venv\Lib\site-packages\PySide6")
_pyside6_runtime_dlls = [
    (str(_pyside6_dir / name), "PySide6")
    for name in (
        "concrt140.dll",
        "msvcp140_codecvt_ids.dll",
        "vcamp140.dll",
        "vccorlib140.dll",
        "vcomp140.dll",
    )
    if (_pyside6_dir / name).exists()
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=_pyside6_runtime_dlls,
    datas=[('C:\\Users\\lll\\Desktop\\jianqieban\\assets\\\\clipnest.ico', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_rth_clipnest_dlls.py"],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ClipNest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['C:\\Users\\lll\\Desktop\\jianqieban\\assets\\clipnest.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ClipNest',
)
