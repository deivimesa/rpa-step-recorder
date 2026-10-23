"""Pruebas del híbrido. Desde hybrid/:  python -m unittest discover -s tests -t ."""

import sys
from pathlib import Path

# Como run.py: el paquete ``app`` de la app de escritorio se importa desde ../desktop.
_HYBRID = Path(__file__).resolve().parents[1]
for _path in (_HYBRID, _HYBRID.parent / "desktop"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
