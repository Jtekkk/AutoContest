# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller build spec for AutoContest.
#
# Build a standalone, single-file executable:
#     pip install -r requirements.txt pyinstaller 2captcha-python
#     pyinstaller AutoContest.spec
#
# The result is placed in dist/ — "AutoContest.exe" on Windows, "AutoContest"
# on macOS/Linux. PyInstaller does NOT cross-compile: run it on the OS you want
# the executable for (the bundled GitHub Actions workflow builds all three).

a = Analysis(
    ['AutoContest.py'],
    pathex=[],
    binaries=[],
    datas=[],
    # Optional 2Captcha support is imported lazily inside a function, so it is
    # declared here to make sure it is bundled when the library is installed.
    hiddenimports=['twocaptcha'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AutoContest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # this is a terminal (rich) application
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
