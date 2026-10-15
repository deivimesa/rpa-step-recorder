# -*- mode: python ; coding: utf-8 -*-
# Receta PyInstaller para macOS: genera dist/RPA Step Recorder.app
# Construir:  desktop/packaging/macos/build_mac.sh
#   (o, desde desktop/:  pyinstaller packaging/macos/rpa-step-recorder-mac.spec)
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Este .spec vive en desktop/packaging/macos/: las rutas se calculan desde desktop/.
DESKTOP = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
sys.path.insert(0, DESKTOP)  # collect_submodules('app') necesita importar el paquete

datas = [(os.path.join(DESKTOP, 'app', 'assets', 'fonts', '*.ttf'), 'app/assets/fonts')] \
    + collect_data_files('docx') + collect_data_files('fpdf')
hiddenimports = collect_submodules('app') + collect_submodules('PIL') + [
    'Quartz', 'ApplicationServices', 'AppKit', 'Foundation', 'psutil',
]
_icns = os.path.join(DESKTOP, 'build', 'RPAStepRecorder.icns')
_icon = _icns if os.path.exists(_icns) else None

a = Analysis([os.path.join(DESKTOP, 'run.py')], pathex=[DESKTOP], datas=datas, hiddenimports=hiddenimports,
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
