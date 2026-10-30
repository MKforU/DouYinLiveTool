# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH).resolve()

datas = [
    (str(ROOT / "base"), "base"),
    (str(ROOT / "service"), "service"),
    (str(ROOT / "ui"), "ui"),
    (str(ROOT / "sign.js"), "."),
    (str(ROOT / "cookie.txt"), "."),
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "rooms.txt"), "."),
    (str(ROOT / "assets"), "assets"),
]
if (ROOT / "tools").is_dir():
    datas.append((str(ROOT / "tools"), "tools"))

try:
    import flet_desktop

    fd = Path(flet_desktop.__file__).resolve().parent / "app"
    if fd.is_dir() and any(fd.iterdir()):
        datas.append((str(fd), "flet_desktop/app"))
except Exception:
    pass

try:
    import flet as _f

    fr = Path(_f.__file__).resolve().parent
    for rel in ("controls/material/icons.json", "controls/cupertino/cupertino_icons.json"):
        s = fr / rel
        if s.is_file():
            datas.append((str(s), str(Path("flet") / Path(rel).parent.as_posix())))
except Exception:
    pass

hiddenimports = [
    "flet",
    "flet_desktop",
    "requests",
    "websocket",
    "google.protobuf",
    "proto",
    "yaml",
    "certifi",
    "base",
    "service",
    "ui",
    "service.fetcher",
    "service.network",
    "service.signer",
    "service.recorder",
    "base.output",
    "base.parser",
    "base.messages",
    "base.utils",
]

a = Analysis(
    [str(ROOT / "run_ui.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="抖音直播助手",
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
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="抖音直播助手",
)
