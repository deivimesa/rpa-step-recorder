#!/usr/bin/env bash
# Construye "RPA Step Recorder Hibrido.app" (y un .dmg) en hybrid/dist/.
# Requiere Python 3.12+ con Tk 8.6/9 (python.org o uv; NO el Python 3.9 del sistema).
# Se puede lanzar desde cualquier carpeta:  hybrid/packaging/macos/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/../.."   # carpeta hybrid/
PY="${PYTHON:-python3}"
"$PY" -c 'import sys, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6, "Python 3.10+ con Tk 8.6+ requerido"'
"$PY" -m pip install -q -r requirements.txt pyinstaller
# Icono .icns a partir del PNG de la extensión (en build/, que no se versiona).
mkdir -p build
"$PY" - <<'PYEOF' || echo "  (sin icono)"
from PIL import Image
Image.open('../extension/icons/icon128.png').convert('RGBA').resize((512, 512), Image.LANCZOS).save('build/RPAStepRecorderHibrido.icns')
PYEOF
"$PY" -m PyInstaller --noconfirm packaging/macos/rpa-step-recorder-hibrido-mac.spec
hdiutil create -quiet -volname "RPA Step Recorder Hibrido" -srcfolder "dist/RPA Step Recorder Hibrido.app" -ov -format UDZO "dist/RPAStepRecorderHibrido.dmg" || true
echo "==> OK: dist/RPA Step Recorder Hibrido.app"
