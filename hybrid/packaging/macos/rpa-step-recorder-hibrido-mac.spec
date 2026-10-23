# -*- mode: python ; coding: utf-8 -*-
# Receta PyInstaller del híbrido para macOS: genera dist/RPA Step Recorder Hibrido.app
# Construir:  hybrid/packaging/macos/build_mac.sh
#   (o, desde hybrid/:  pyinstaller packaging/macos/rpa-step-recorder-hibrido-mac.spec)
#
# Empaqueta dos paquetes:
#   - app    (../desktop/app): grabador de escritorio, interfaz, documentos.
#   - hybrid (hybrid/hybrid):  pantalla de elección y grabación web por CDP.
# El agente web (hybrid/web/agent.js) va como dato: se inyecta en el navegador.
import os
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Este .spec vive en hybrid/packaging/macos/: las rutas se calculan desde hybrid/.
HIBRIDO = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
DESKTOP = os.path.abspath(os.path.join(HIBRIDO, '..', 'desktop'))
sys.path[:0] = [HIBRIDO, DESKTOP]  # collect_submodules necesita importar ambos paquetes

datas = [
    (os.path.join(DESKTOP, 'app', 'assets', 'fonts', '*.ttf'), 'app/assets/fonts'),
    (os.path.join(HIBRIDO, 'hybrid', 'web', 'agent.js'), 'hybrid/web'),
] + collect_data_files('docx') + collect_data_files('fpdf')
hiddenimports = collect_submodules('app') + collect_submodules('hybrid') + collect_submodules('PIL') \
    + collect_submodules('websocket') + ['Quartz', 'ApplicationServices', 'AppKit', 'Foundation', 'psutil']
_icns = os.path.join(HIBRIDO, 'build', 'RPAStepRecorderHibrido.icns')
_icon = _icns if os.path.exists(_icns) else None

a = Analysis([os.path.join(HIBRIDO, 'run.py')], pathex=[HIBRIDO, DESKTOP], datas=datas,
             hiddenimports=hiddenimports, excludes=['uiautomation', 'comtypes', 'pynput'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='RPAStepRecorderHibrido',
          console=False, argv_emulation=False, codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name='RPAStepRecorderHibrido')
app = BUNDLE(
    coll, name='RPA Step Recorder Hibrido.app', icon=_icon,
    bundle_identifier='com.deivimesa.rpastep-recorder.hibrido',
    info_plist={
        'CFBundleDisplayName': 'RPA Step Recorder Híbrido',
        'CFBundleShortVersionString': '1.1.0',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSAppleEventsUsageDescription': 'Para generar selectores AppleScript de los pasos.',
    },
)
