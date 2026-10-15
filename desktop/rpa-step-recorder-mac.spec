# -*- mode: python ; coding: utf-8 -*-
# Receta PyInstaller para macOS: genera dist/RPA Step Recorder.app
# Construir desde desktop/:  ./build_mac.sh   (o: pyinstaller rpa-step-recorder-mac.spec)
import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

datas = [('app/assets/fonts/*.ttf', 'app/assets/fonts')] + collect_data_files('docx') + collect_data_files('fpdf')
hiddenimports = collect_submodules('app') + collect_submodules('PIL') + [
    'Quartz', 'ApplicationServices', 'AppKit', 'Foundation', 'psutil',
]
_icon = 'RPAStepRecorder.icns' if os.path.exists('RPAStepRecorder.icns') else None

a = Analysis(['run.py'], pathex=['.'], datas=datas, hiddenimports=hiddenimports,
             excludes=['uiautomation', 'comtypes', 'pynput'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='RPAStepRecorder',
          console=False, argv_emulation=False, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name='RPAStepRecorder')
app = BUNDLE(
    coll, name='RPA Step Recorder.app', icon=_icon,
    bundle_identifier='com.deivimesa.rpastep-recorder',
    info_plist={
        'CFBundleShortVersionString': '4.0.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription': 'Para generar selectores AppleScript de los pasos.',
    },
)
