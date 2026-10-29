# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH).parent.parent
a = Analysis(
    [str(root / '便携版打包' / '源码' / 'ppt_audit.py')],
    pathex=[str(root)], binaries=[],
    datas=collect_data_files('customtkinter') + [(str(root / 'assets'), 'assets')],
    hiddenimports=['PIL._tkinter_finder'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name='PPT批注编号检查工具_v1.7', icon=str(root / 'assets' / 'app.ico'),
    version=str(Path(SPECPATH) / 'version-info-v1.7.txt'),
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False, contents_directory='_internal',
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name='PPT批注编号检查工具_v1.7_Windows64位')
