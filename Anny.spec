# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

datas = [('frontend/web', 'frontend/web')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('ocrmypdf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

def _add_tree(base: Path, target_prefix: str) -> None:
    for path in base.rglob('*'):
        if path.is_file():
            rel = path.relative_to(base).as_posix()
            rel_parent = Path(rel).parent.as_posix()
            dest_dir = f"{target_prefix}/{rel_parent}" if rel_parent not in ('.', '') else target_prefix
            datas.append((str(path), dest_dir))


tess_root = Path('third_party/tesseract-macos')
if tess_root.exists():
    bin_path = tess_root / 'bin' / 'tesseract'
    if bin_path.exists():
        binaries.append((str(bin_path), 'tesseract/bin'))
    lib_path = tess_root / 'lib'
    if lib_path.exists():
        for lib in lib_path.glob('*.dylib'):
            binaries.append((str(lib), 'tesseract/lib'))
    tessdata_path = tess_root / 'share' / 'tessdata'
    if tessdata_path.exists():
        _add_tree(tessdata_path, 'tesseract/share/tessdata')
    license_path = tess_root / 'LICENSES'
    if license_path.exists():
        _add_tree(license_path, 'tesseract/licenses')

ghost_root = Path('third_party/ghostscript-macos')
if ghost_root.exists():
    gs_bin = ghost_root / 'bin' / 'gs'
    if gs_bin.exists():
        datas.append((str(gs_bin), 'ghostscript/bin'))
    gs_real = ghost_root / 'bin' / 'gs.real'
    if gs_real.exists():
        binaries.append((str(gs_real), 'ghostscript/bin'))
    gs_lib_dir = ghost_root / 'lib'
    if gs_lib_dir.exists():
        for lib in gs_lib_dir.glob('*.dylib'):
            binaries.append((str(lib), 'ghostscript/lib'))
    share_dir = ghost_root / 'share'
    if share_dir.exists():
        _add_tree(share_dir, 'ghostscript/share')
    etc_dir = ghost_root / 'etc'
    if etc_dir.exists():
        _add_tree(etc_dir, 'ghostscript/etc')
    license_dir = ghost_root / 'LICENSES'
    if license_dir.exists():
        _add_tree(license_dir, 'ghostscript/licenses')

ENABLE_CONSOLE = os.environ.get('ANNY_CONSOLE', '0').lower() in {'1', 'true', 'yes'}


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
    [],
    exclude_binaries=True,
    name='Anny',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=ENABLE_CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['anny.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Anny',
)
app = BUNDLE(
    coll,
    name='Anny.app',
    icon='anny.icns',
    bundle_identifier=None,
)
