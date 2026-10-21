"""Punto de entrada del híbrido (web + escritorio).

Uso:  python run.py

Reutiliza el código de la app de escritorio: desde el código fuente se añade
../desktop al path; en el .exe el paquete ``app`` ya va empaquetado.
"""

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop"))

from hybrid.main import run  # noqa: E402

if __name__ == "__main__":
    run()
