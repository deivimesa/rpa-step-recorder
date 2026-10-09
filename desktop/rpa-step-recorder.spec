# -*- mode: python ; coding: utf-8 -*-
# ---------------------------------------------------------------------------
# Receta de empaquetado PyInstaller para RPA Step Recorder (escritorio).
#
# Genera un único ejecutable Windows sin consola (windowed, --onefile):
#     dist/RPAStepRecorder.exe
#
# Construir desde la carpeta `desktop/`:
#     pyinstaller rpa-step-recorder.spec
#
# Notas de empaquetado:
#   - uiautomation y comtypes generan submódulos/código dinámico en tiempo de
#     ejecución -> se usa collect_all para arrastrar módulos y datos.
#   - pynput carga backends específicos de plataforma (win32) por nombre.
#   - python-docx ("docx") necesita sus plantillas .xml / default.docx como
#     datos -> collect_data_files('docx').
#   - fpdf2 ("fpdf") incluye datos propios -> collect_all('fpdf').
# ---------------------------------------------------------------------------

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# --- Icono opcional --------------------------------------------------------
# No hay .ico en desktop/. Si existe uno generado (ver build_exe.ps1), se usa.
import os
_icon = 'RPAStepRecorder.ico' if os.path.exists('RPAStepRecorder.ico') else None

# --- Recolección de dependencias dinámicas ---------------------------------
datas = []
binaries = []
hiddenimports = []

# Fuentes DejaVu (Unicode) usadas por el exportador PDF. Se incrustan como
# datos para que el .exe las lleve consigo. En onefile se extraen a
# sys._MEIPASS/app/assets/fonts, ruta que pdf._resolve_fonts_dir() comprueba.
datas += [('app/assets/fonts/*.ttf', 'app/assets/fonts')]

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
]

# psutil: extensión C, normalmente detectada; se asegura por si acaso.
hiddenimports += ['psutil']

# El paquete de la app vive en ./app
hiddenimports += collect_submodules('app')


block_cipher = None


a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
