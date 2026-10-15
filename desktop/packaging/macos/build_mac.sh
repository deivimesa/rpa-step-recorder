#!/usr/bin/env bash
# Construye "RPA Step Recorder.app" (y un .dmg) en desktop/dist/.
# Requiere Python 3.12+ con Tk 8.6/9 (python.org o uv; NO el Python 3.9 del sistema).
# Se puede lanzar desde cualquier carpeta:  desktop/packaging/macos/build_mac.sh
set -euo pipefail
cd "$(dirname "$0")/../.."   # carpeta desktop/
PY="${PYTHON:-python3}"
"$PY" -c 'import sys, tkinter; assert sys.version_info >= (3, 10) and tkinter.TkVersion >= 8.6, "Python 3.10+ con Tk 8.6+ requerido"'
"$PY" -m pip install -q -r requirements.txt pyinstaller
# Icono .icns a partir del PNG de la extensión (en build/, que no se versiona).
mkdir -p build
"$PY" - <<'PYEOF' || echo "  (sin icono)"
from PIL import Image
Image.open('../extension/icons/icon128.png').convert('RGBA').resize((512, 512), Image.LANCZOS).save('build/RPAStepRecorder.icns')
PYEOF
"$PY" -m PyInstaller --noconfirm packaging/macos/rpa-step-recorder-mac.spec
hdiutil create -quiet -volname "RPA Step Recorder" -srcfolder "dist/RPA Step Recorder.app" -ov -format UDZO "dist/RPAStepRecorder.dmg" || true
echo "==> OK: dist/RPA Step Recorder.app"
