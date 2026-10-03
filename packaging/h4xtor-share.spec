# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build specification for h4xtor-share.

Build a single-file, windowed executable for the current platform:

    python -m PyInstaller --clean --noconfirm packaging/h4xtor-share.spec

On Windows the executable embeds a version resource and the application
icon; on macOS and Linux the PNG icon is used for the bundle.
"""

import platform
from pathlib import Path

from h4xtor_share import __version__

APP_NAME = "h4xtor-share"
VERSION = __version__
HERE = Path(SPECPATH)
REPO = HERE.parent
SRC = REPO / "src"

BLOCK_CIPHER_HIDDEN_IMPORTS = [
    "cryptography.hazmat.backends.openssl",
    "cryptography.hazmat.primitives.asymmetric.rsa",
    "cryptography.hazmat.primitives.hashes",
    "cryptography.hazmat.primitives.serialization",
]

HIDDEN_IMPORTS = [
    "segno",
    "aiofiles",
    "aiohttp",
    "ifaddr",
    "platformdirs",
    "zeroconf",
    *BLOCK_CIPHER_HIDDEN_IMPORTS,
]
if platform.system() == "Windows":
    HIDDEN_IMPORTS += ["pystray._win32", "PIL.Image", "PIL.ImageDraw", "winreg"]

# Keep the frozen binary lean; these modules are not used by the app.
EXCLUDES = [
    "numpy",
    "pytest",
    "setuptools",
    "tkinter.test",
    "unittest",
]

# --- Windows version resource -------------------------------------------------
VERSION_INFO = None
if platform.system() == "Windows":
    try:
        from PyInstaller.utils.win32.versioninfo import (
            FixedFileInfo,
            StringFileInfo,
            StringStruct,
            StringTable,
            VarFileInfo,
            VarStruct,
            VSVersionInfo,
        )

        major, minor, patch = (int(part) for part in VERSION.split(".")[:3])
        VERSION_INFO = VSVersionInfo(
            ffi=FixedFileInfo(
                filevers=(major, minor, patch, 0),
                prodvers=(major, minor, patch, 0),
                mask=0x3F,
                flags=0x0,
                OS=0x40004,
                fileType=0x1,
                subtype=0x0,
                date=(0, 0),
            ),
            kids=[
                StringFileInfo(
                    [
                        StringTable(
                            "040904B0",
                            [
                                StringStruct("CompanyName", "h4xtor"),
                                StringStruct("FileDescription", "h4xtor-share"),
                                StringStruct("FileVersion", VERSION),
                                StringStruct(
                                    "InternalName", APP_NAME
                                ),
                                StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                                StringStruct(
                                    "ProductName", "h4xtor-share"
                                ),
                                StringStruct("ProductVersion", VERSION),
                            ],
                        )
                    ]
                ),
                VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
            ],
        )
    except ImportError:
        VERSION_INFO = None

# --- Executable ---------------------------------------------------------------
a = Analysis(
    [str(SRC / "h4xtor_share" / "__main__.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=[(str(SRC / "h4xtor_share" / "chrome_extension"), "h4xtor_share/chrome_extension")],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[str(HERE)],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_kwargs = dict(
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(HERE / "h4xtor-share.ico") if platform.system() == "Windows" else None,
    version=VERSION_INFO,
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    **exe_kwargs,
)
