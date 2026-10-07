# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path

_pyside6_dir = Path(r"C:\Users\lll\Desktop\jianqieban\.venv\Lib\site-packages\PySide6")
# 仅补充 Qt 运行时真正需要的 VC 运行库。
# vccorlib140/vcamp140/vcomp140/concrt140/msvcp140_codecvt_ids 为
# C++/CX、OpenMP 等组件，Qt 用不到；新版会引入旧系统缺失的依赖，
# 曾在部分电脑上导致 “找不到指定的程序”，故不打包。
_pyside6_runtime_dlls = [
    (str(_pyside6_dir / name), "PySide6")
    for name in (
        "MSVCP140.dll",
        "MSVCP140_1.dll",
        "MSVCP140_2.dll",
        "VCRUNTIME140.dll",
        "VCRUNTIME140_1.dll",
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

# 排除 Windows 系统 UCRT / api-set 组件：目标系统自带，
# 随构建机打包新版反而会遮蔽系统版本，导致旧系统加载失败。
_excluded_system_dlls = ("api-ms-win-", "ucrtbase", "ucrtbased")
a.binaries = [
    entry for entry in a.binaries
    if not entry[0].lower().startswith(_excluded_system_dlls)
]
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
