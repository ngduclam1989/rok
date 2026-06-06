# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, copy_metadata

# Get the path to site-packages dynamically
site_packages_dir = None
for path in sys.path:
    if 'site-packages' in path:
        site_packages_dir = Path(path)
        break
if not site_packages_dir:
    site_packages_dir = Path(sys.prefix) / "Lib" / "site-packages"

# Collect all resources (datas, binaries, hiddenimports) for heavy packages
datas = []
binaries = []
hiddenimports = []

# List of packages to collect all assets and binaries for
packages_to_collect = ['paddle', 'paddleocr', 'paddlex', 'airtest']

for pkg in packages_to_collect:
    try:
        p_datas, p_binaries, p_hiddenimports = collect_all(pkg)
        datas.extend(p_datas)
        binaries.extend(p_binaries)
        hiddenimports.extend(p_hiddenimports)
    except Exception as e:
        print(f"Warning: Failed to collect {pkg}: {e}")

# Copy metadata for packages that might need them
metadata_packages = ['shapely', 'pyclipper', 'paddleocr', 'paddle', 'paddlex']
for pkg in metadata_packages:
    try:
        datas.extend(copy_metadata(pkg))
    except Exception as e:
        print(f"Warning: Failed to copy metadata for {pkg}: {e}")

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='RoKBot',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
