# -*- mode: python ; coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Receta de empaquetado PyInstaller para RPA Step Recorder (escritorio).
#
# Genera un único ejecutable Windows sin consola (windowed, --onefile):
#     dist/RPAStepRecorder.exe
#
# Construir con el script (recomendado):
#     desktop\packaging\windows\build_exe.ps1
# o a mano, desde la carpeta `desktop/`:
#     pyinstaller packaging/windows/rpa-step-recorder.spec
#
# Notas de empaquetado:
#   - uiautomation y comtypes generan submódulos/código dinámico en tiempo de
#     ejecución -> se usa collect_all para arrastrar módulos y datos.
#   - pynput carga backends específicos de plataforma (win32) por nombre.
#   - python-docx ("docx") necesita sus plantillas .xml / default.docx como
#     datos -> collect_data_files('docx').
#   - fpdf2 ("fpdf") incluye datos propios -> collect_all('fpdf').
# ---------------------------------------------------------------------------

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# --- Rutas -------------------------------------------------------------------
# Este .spec vive en desktop/packaging/windows/. Las rutas se calculan desde
# desktop/ para que el build no dependa de la carpeta desde la que se lance.
DESKTOP = os.path.abspath(os.path.join(SPECPATH, '..', '..'))
sys.path.insert(0, DESKTOP)  # collect_submodules('app') necesita importar el paquete

# --- Icono opcional --------------------------------------------------------
# build_exe.ps1 genera build/RPAStepRecorder.ico a partir del PNG de la extensión.
_ico = os.path.join(DESKTOP, 'build', 'RPAStepRecorder.ico')
_icon = _ico if os.path.exists(_ico) else None

# --- Recolección de dependencias dinámicas ---------------------------------
datas = []
binaries = []
hiddenimports = []

# Fuentes DejaVu (Unicode) usadas por el exportador PDF. Se incrustan como
# datos para que el .exe las lleve consigo. En onefile se extraen a
# sys._MEIPASS/app/assets/fonts, ruta que pdf._resolve_fonts_dir() comprueba.
datas += [(os.path.join(DESKTOP, 'app', 'assets', 'fonts', '*.ttf'), 'app/assets/fonts')]

# Paquetes con submódulos/datos dinámicos: traer todo para evitar sorpresas.
for _pkg in ('uiautomation', 'comtypes', 'pynput', 'mss', 'fpdf'):
    _d, _b, _h = collect_all(_pkg)
    datas += _d
    binaries += _b
    hiddenimports += _h

# Pillow: los plugins de imagen se importan dinámicamente.
hiddenimports += collect_submodules('PIL')

# python-docx se importa como "docx" y necesita sus plantillas de datos.
datas += collect_data_files('docx')
hiddenimports += collect_submodules('docx')

# Backends de pynput en Windows (se cargan por nombre).
hiddenimports += [
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'app.backends.windows',
    'app.backends.windows.backend',
    'app.backends.windows.uia',
    'app.backends.windows.hooks',
    'app.backends.windows.system',
]

# psutil: extensión C, normalmente detectada; se asegura por si acaso.
hiddenimports += ['psutil']

# El paquete de la app vive en desktop/app
hiddenimports += collect_submodules('app')


block_cipher = None


a = Analysis(
    [os.path.join(DESKTOP, 'run.py')],
    pathex=[DESKTOP],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['Quartz', 'AppKit', 'ApplicationServices', 'objc'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='RPAStepRecorder',
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
