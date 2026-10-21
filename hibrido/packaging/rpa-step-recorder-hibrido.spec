# -*- mode: python ; coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Receta de empaquetado PyInstaller del RPA Step Recorder HÍBRIDO (web + escritorio).
#
# Genera un único ejecutable Windows sin consola (windowed, --onefile):
#     hibrido/dist/RPAStepRecorderHibrido.exe
#
# Construir con el script (recomendado):
#     hibrido\packaging\build_exe.ps1
# o a mano, desde la carpeta `hibrido/`:
#     pyinstaller packaging/rpa-step-recorder-hibrido.spec
#
# Empaqueta dos paquetes:
#   - app    (../desktop/app): grabador de escritorio, interfaz, documentos.
#   - hybrid (hibrido/hybrid): pantalla de elección y grabación web por CDP.
# El agente web (hybrid/web/agent.js) va como dato: se inyecta en el navegador.
# ---------------------------------------------------------------------------

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# --- Rutas -------------------------------------------------------------------
HIBRIDO = os.path.abspath(os.path.join(SPECPATH, '..'))
DESKTOP = os.path.abspath(os.path.join(HIBRIDO, '..', 'desktop'))
sys.path[:0] = [HIBRIDO, DESKTOP]  # collect_submodules necesita importar ambos paquetes

_ico = os.path.join(HIBRIDO, 'build', 'RPAStepRecorderHibrido.ico')
_icon = _ico if os.path.exists(_ico) else None

datas = []
binaries = []
hiddenimports = []

# Fuentes DejaVu del PDF (pdf._resolve_fonts_dir las busca en _MEIPASS/app/assets/fonts).
datas += [(os.path.join(DESKTOP, 'app', 'assets', 'fonts', '*.ttf'), 'app/assets/fonts')]
# Agente que se inyecta en las páginas web (backend._agent_source lo busca en _MEIPASS/hybrid/web).
datas += [(os.path.join(HIBRIDO, 'hybrid', 'web', 'agent.js'), 'hybrid/web')]

# Paquetes con submódulos/datos dinámicos.
for _pkg in ('uiautomation', 'comtypes', 'pynput', 'mss', 'fpdf', 'websocket'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

hiddenimports += collect_submodules('PIL')
datas += collect_data_files('docx')
hiddenimports += collect_submodules('docx')

hiddenimports += [
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'psutil',
]
hiddenimports += collect_submodules('app')
hiddenimports += collect_submodules('hybrid')


a = Analysis(
    [os.path.join(HIBRIDO, 'run.py')],
    pathex=[HIBRIDO, DESKTOP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['Quartz', 'AppKit', 'ApplicationServices', 'objc'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RPAStepRecorderHibrido',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # windowed: sin ventana de consola
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
