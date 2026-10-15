"""Almacén local en disco: una carpeta por grabación con session.json y sus PNG.

Garantías que no tenía la versión anterior:
  - Escritura atómica: session.json se escribe en un temporal y se reemplaza
    de golpe. Un corte de luz o un cierre forzado nunca deja el JSON a medias.
  - Copia de respaldo (.bak) al detener/reanudar una grabación; si el JSON
    principal está dañado se recupera automáticamente del respaldo.
  - Reintentos ante bloqueos de archivo en Windows (antivirus, indexador).
  - Migración de grabaciones antiguas al esquema actual al leerlas.
  - Listado con caché por fecha de modificación: no relee todos los JSON en
    cada refresco de la interfaz.
  - Exportar / importar una grabación completa como .zip, validando nombres
    (sin rutas peligrosas) y tamaños.

Todo es offline: nada sale del equipo.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import threading
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image

from .. import __version__
from . import paths

log = logging.getLogger("rpa.storage")

SCHEMA_VERSION = 2
SESSION_FILE = "session.json"
BACKUP_FILE = "session.json.bak"
BUNDLE_FORMAT = "rpa-step-recorder-bundle"

# Ids y nombres de imagen permitidos: impiden rutas como "../../x".
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{4,64}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,96}\.(?:png|jpg|jpeg)$", re.IGNORECASE)

# Límites de importación (protección ante zips corruptos o malintencionados).
_IMPORT_MAX_FILES = 6000
_IMPORT_MAX_BYTES = 4 * 1024 ** 3


class StorageError(Exception):
    """Error de almacenamiento con un mensaje apto para el usuario."""


# ── utilidades de escritura ─────────────────────────────────


def _retry(action, attempts: int = 6, delay: float = 0.05):
    """Reintenta una operación de archivo que Windows puede bloquear un instante."""
    last = None
    for i in range(attempts):
        try:
            return action()
        except PermissionError as err:  # archivo abierto por otro proceso
            last = err
            time.sleep(delay * (i + 1))
    raise last  # type: ignore[misc]


def atomic_write_text(path: Path, text: str) -> None:
    """Escribe ``text`` en ``path`` de forma atómica (temporal + reemplazo)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError:
                pass
        _retry(lambda: os.replace(tmp, path))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def uid() -> str:
    return uuid.uuid4().hex[:16]


def _check_id(session_id: str) -> str:
    if not isinstance(session_id, str) or not _ID_RE.match(session_id):
        raise ValueError(f"id de grabación no válido: {session_id!r}")
    return session_id


def is_valid_image_name(name: str) -> bool:
    return bool(name) and bool(_IMAGE_RE.match(name))


# ── rutas ───────────────────────────────────────────────────


def session_dir(session_id: str, create: bool = False) -> Path:
    path = paths.sessions_dir() / _check_id(session_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def image_path(session_id: str, name: str) -> Path:
    if not is_valid_image_name(name):
        # Nombre vacío o sospechoso: una ruta que nunca existe.
        return session_dir(session_id) / "__invalid__.png"
    return session_dir(session_id) / name


# ── modelo ──────────────────────────────────────────────────


def new_session(name: str, author: str, system: str, platform: str) -> dict:
    now = datetime.now()
    title = (name or "").strip() or f"Proceso {now.strftime('%d/%m/%Y %H:%M')}"
    return {
        "schema": SCHEMA_VERSION,
        "id": uid(),
        "name": title,
        "author": (author or "").strip(),
        "system": (system or "").strip(),
        "platform": platform,
        "app_version": __version__,
        "started_at": now.isoformat(timespec="seconds"),
        "finished_at": "",
        "active_seconds": 0,
        "steps": [],
        # Contador propio para nombrar imágenes: borrar o reordenar pasos
        # nunca provoca colisiones de archivos.
        "image_seq": 0,
    }


def migrate_session(session: dict) -> dict:
    """Completa campos que las grabaciones antiguas no tenían (idempotente)."""
    steps = session.get("steps")
    if not isinstance(steps, list):
        steps = []
    session["steps"] = [s for s in steps if isinstance(s, dict)]
    session.setdefault("name", "Proceso")
    session.setdefault("author", "")
    session.setdefault("system", "")
    session.setdefault("started_at", "")
    session.setdefault("finished_at", "")
    # Las grabaciones anteriores a la 4.0 solo podían ser de Windows.
    session.setdefault("platform", "windows")
    session.setdefault("active_seconds", 0)
    session.setdefault("image_seq", len(session["steps"]))
    for i, step in enumerate(session["steps"], start=1):
        step.setdefault("id", uid())
        step["index"] = i
        step.setdefault("kind", "click")
        step.setdefault("suggestion", "")
        step.setdefault("description", step.get("suggestion", ""))
        step.setdefault("full_image", "")
        step.setdefault("zoom_image", "")
        step.setdefault("thumb_image", "")
        step.setdefault("hide_image", False)
        step.setdefault("value", "")
        step.setdefault("secret", False)
    session["schema"] = SCHEMA_VERSION
    return session


# ── sesiones ────────────────────────────────────────────────

_list_lock = threading.Lock()
_summary_cache: dict[str, tuple[tuple, dict]] = {}


def save_session(session: dict) -> None:
    folder = session_dir(session["id"], create=True)
    session["updated_at"] = datetime.now().isoformat(timespec="seconds")
    atomic_write_text(folder / SESSION_FILE, json.dumps(session, ensure_ascii=False, indent=1))


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except FileNotFoundError:
        return None
    except (ValueError, OSError) as err:
        log.warning("no se pudo leer %s: %s", path, err)
        return None


def get_session(session_id: str) -> dict | None:
    """Lee una grabación; si el JSON está dañado, recurre a la copia .bak."""
    try:
        folder = session_dir(session_id)
    except ValueError:
        return None
    data = _read_json(folder / SESSION_FILE)
    if data is None and (folder / BACKUP_FILE).exists():
        data = _read_json(folder / BACKUP_FILE)
        if data is not None:
            log.warning("grabación %s recuperada desde la copia de respaldo", session_id)
            try:
                atomic_write_text(folder / SESSION_FILE, json.dumps(data, ensure_ascii=False, indent=1))
            except OSError:
                pass
    if data is None:
        return None
    data["id"] = session_id
    return migrate_session(data)


def backup_session(session_id: str) -> None:
    """Copia session.json a session.json.bak (al detener o reanudar)."""
    try:
        folder = session_dir(session_id)
        src = folder / SESSION_FILE
        if src.exists():
            tmp = folder / f".{BACKUP_FILE}.tmp"
            shutil.copyfile(src, tmp)
            _retry(lambda: os.replace(tmp, folder / BACKUP_FILE))
    except (OSError, ValueError) as err:
        log.warning("no se pudo crear la copia de respaldo de %s: %s", session_id, err)


def _folder_size(folder: Path) -> int:
    total = 0
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False):
                        total += entry.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _summarize(session: dict, folder: Path) -> dict:
    steps = session.get("steps", [])
    first_thumb = ""
    for step in steps:
        name = step.get("thumb_image") or step.get("full_image")
        if name:
            first_thumb = name
            break
    return {
        "id": session.get("id", folder.name),
        "name": session.get("name", "") or "Proceso",
        "author": session.get("author", ""),
        "system": session.get("system", ""),
        "platform": session.get("platform", "windows"),
        "started_at": session.get("started_at", ""),
        "finished_at": session.get("finished_at", ""),
        "updated_at": session.get("updated_at", ""),
        "step_count": len(steps),
        "size": _folder_size(folder),
        "first_image": first_thumb,
    }


def list_sessions() -> list[dict]:
    """Resúmenes de todas las grabaciones, de la más reciente a la más antigua.

    Cada resumen se cachea con la fecha de modificación de la carpeta y del
    JSON: solo se relee lo que cambió.
    """
    result: list[dict] = []
    seen: set[str] = set()
    with _list_lock:
        try:
            entries = list(os.scandir(paths.sessions_dir()))
        except OSError:
            entries = []
        for entry in entries:
            if not entry.is_dir() or not _ID_RE.match(entry.name):
                continue
            folder = Path(entry.path)
            json_path = folder / SESSION_FILE
            try:
                key = (json_path.stat().st_mtime_ns, entry.stat().st_mtime_ns)
            except OSError:
                # Sin session.json: quizá solo quede la copia de respaldo.
                if not (folder / BACKUP_FILE).exists():
                    continue
                key = (0, 0)
            seen.add(entry.name)
            cached = _summary_cache.get(entry.name)
            if cached and cached[0] == key:
                result.append(dict(cached[1]))
                continue
            session = get_session(entry.name)
            if not session:
                continue
            summary = _summarize(session, folder)
            _summary_cache[entry.name] = (key, summary)
            result.append(dict(summary))
        for stale in set(_summary_cache) - seen:
            _summary_cache.pop(stale, None)
    result.sort(key=lambda s: str(s.get("started_at", "")), reverse=True)
    return result


def invalidate_cache(session_id: str | None = None) -> None:
    with _list_lock:
        if session_id:
            _summary_cache.pop(session_id, None)
        else:
            _summary_cache.clear()


def delete_session(session_id: str) -> None:
    folder = session_dir(session_id)
    if not folder.exists():
        return

    def _on_error(func, path, *_):
        # Archivos de solo lectura o bloqueados un instante (Windows).
        try:
            os.chmod(path, 0o600)
            time.sleep(0.05)
            func(path)
        except OSError:
            pass

    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(folder, onexc=_on_error)
        else:  # pragma: no cover - Python 3.10/3.11
            shutil.rmtree(folder, onerror=_on_error)
    except OSError as err:
        raise StorageError(
            f"No se pudo borrar la grabación: {err}. Cierra los documentos o imágenes que la usen e inténtalo de nuevo."
        ) from err
    if folder.exists():
        raise StorageError("No se pudo borrar la grabación por completo (algún archivo está en uso).")
    invalidate_cache(session_id)


# ── imágenes ────────────────────────────────────────────────


def put_image(session_id: str, name: str, image: Image.Image, compress_level: int = 3) -> int:
    """Guarda una imagen PNG y devuelve su tamaño en bytes."""
    if not is_valid_image_name(name):
        raise ValueError(f"nombre de imagen no válido: {name!r}")
    target = session_dir(session_id, create=True) / name
    tmp = target.with_name(f".{name}.tmp")
    image.save(tmp, format="PNG", compress_level=compress_level)
    _retry(lambda: os.replace(tmp, target))
    return target.stat().st_size


def delete_images(session_id: str, names: list[str]) -> None:
    for name in names:
        if not name or not is_valid_image_name(name):
            continue
        target = session_dir(session_id) / name
        try:
            _retry(lambda t=target: t.unlink(missing_ok=True))
        except OSError as err:
            log.warning("no se pudo borrar la imagen %s: %s", name, err)


def usage() -> dict:
    """Espacio ocupado por todas las grabaciones, en bytes."""
    return {"used": sum(s.get("size", 0) for s in list_sessions())}


def free_space() -> int:
    """Bytes libres en el disco donde se guardan las grabaciones."""
    try:
        return shutil.disk_usage(paths.sessions_dir()).free
    except OSError:
        return -1


# ── paquetes .zip (compartir / respaldar una grabación) ─────


def export_bundle(session_id: str, dest: str | Path) -> Path:
    """Empaqueta session.json + imágenes en un .zip portable."""
    session = get_session(session_id)
    if not session:
        raise StorageError("Esa grabación ya no existe.")
    dest = Path(dest)
    folder = session_dir(session_id)
    names: set[str] = set()
    for step in session.get("steps", []):
        for key in ("full_image", "zoom_image", "thumb_image"):
            name = step.get(key) or ""
            if is_valid_image_name(name) and (folder / name).exists():
                names.add(name)
    manifest = {
        "format": BUNDLE_FORMAT,
        "version": 1,
        "app_version": __version__,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
            zf.writestr(SESSION_FILE, json.dumps(session, ensure_ascii=False, indent=1))
            for name in sorted(names):
                # Las PNG ya van comprimidas: se guardan sin recomprimir.
                zf.write(folder / name, f"images/{name}", compress_type=zipfile.ZIP_STORED)
        _retry(lambda: os.replace(tmp, dest))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return dest


def import_bundle(src: str | Path) -> str:
    """Importa un .zip exportado; devuelve el id (nuevo) de la grabación."""
    src = Path(src)
    try:
        zf = zipfile.ZipFile(src)
    except (zipfile.BadZipFile, OSError) as err:
        raise StorageError("El archivo no es un paquete de grabación válido (.zip).") from err
    with zf:
        infos = zf.infolist()
        if len(infos) > _IMPORT_MAX_FILES:
            raise StorageError("El paquete contiene demasiados archivos.")
        if sum(i.file_size for i in infos) > _IMPORT_MAX_BYTES:
            raise StorageError("El paquete es demasiado grande para importarlo.")
        try:
            session = json.loads(zf.read(SESSION_FILE).decode("utf-8"))
        except KeyError as err:
            raise StorageError("Al paquete le falta session.json.") from err
        except (ValueError, UnicodeDecodeError) as err:
            raise StorageError("El session.json del paquete está dañado.") from err
        if not isinstance(session, dict):
            raise StorageError("El session.json del paquete no es válido.")

        new_id = uid()
        session["id"] = new_id
        session = migrate_session(session)
        folder = session_dir(new_id, create=True)
        try:
            for info in infos:
                if info.is_dir() or not info.filename.startswith("images/"):
                    continue
                name = info.filename[len("images/"):]
                # Solo nombres planos y seguros: nada de subcarpetas ni "..".
                if not is_valid_image_name(name):
                    continue
                with zf.open(info) as source, open(folder / name, "wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            save_session(session)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
    invalidate_cache()
    return new_id
