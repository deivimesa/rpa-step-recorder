"""Almacén local en disco. Reemplaza IndexedDB (lib/db.js).

Cada sesión es una carpeta bajo %LOCALAPPDATA%/RPAStepRecorder/sessions/<id>/
con un session.json y los PNG de cada paso. Todo offline, sin servidor.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from PIL import Image


def _root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    root = Path(base) / "RPAStepRecorder" / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    return root


def uid() -> str:
    import random

    return format(random.getrandbits(40), "x") + format(int(time.time() * 1000) & 0xFFFF, "x")


def _dir(session_id: str) -> Path:
    path = _root() / session_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_session(session: dict) -> None:
    path = _dir(session["id"]) / "session.json"
    path.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")


def get_session(session_id: str) -> dict | None:
    path = _root() / session_id / "session.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def list_sessions() -> list[dict]:
    sessions = []
    for folder in _root().iterdir():
        if not folder.is_dir():
            continue
        session = get_session(folder.name)
        if session:
            sessions.append(session)
    sessions.sort(key=lambda s: str(s.get("started_at", "")), reverse=True)
    return sessions


def delete_session(session_id: str) -> None:
    folder = _root() / session_id
    if folder.exists():
        shutil.rmtree(folder, ignore_errors=True)


def put_image(session_id: str, name: str, image: Image.Image) -> None:
    image.save(_dir(session_id) / name, format="PNG")


def image_path(session_id: str, name: str) -> Path:
    return _root() / session_id / name


def delete_images(session_id: str, names: list[str]) -> None:
    for name in names:
        if not name:
            continue
        target = _root() / session_id / name
        if target.exists():
            target.unlink(missing_ok=True)


def usage() -> dict:
    """Espacio ocupado por todas las grabaciones, en bytes."""
    total = 0
    for folder in _root().rglob("*"):
        if folder.is_file():
            try:
                total += folder.stat().st_size
            except OSError:
                pass
    return {"used": total}
