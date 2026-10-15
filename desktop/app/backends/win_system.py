"""Integración con Windows vía ctypes: DPI, ventanas, elevación y capturas.

Todas las funciones son defensivas: si una API no existe en la versión de
Windows del usuario, devuelven un valor neutro en lugar de fallar.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from ctypes import wintypes

log = logging.getLogger("rpa.win")

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetForegroundWindow.argtypes = []
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetCursorPos.restype = wintypes.BOOL
_user32.GetDoubleClickTime.argtypes = []
_user32.GetDoubleClickTime.restype = wintypes.UINT
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]
_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
_user32.FindWindowW.restype = wintypes.HWND
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
_advapi32.OpenProcessToken.restype = wintypes.BOOL
_advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]
_advapi32.GetTokenInformation.restype = wintypes.BOOL

try:
    _user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    _user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
except AttributeError:  # pragma: no cover - Windows muy antiguos
    pass

GA_ROOT = 2
WDA_NONE = 0x0
WDA_EXCLUDEFROMCAPTURE = 0x11
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
SW_RESTORE = 9


def windows_build() -> int:
    try:
        return int(sys.getwindowsversion().build)
    except Exception:
        return 0


def set_dpi_awareness() -> str:
    """Hace el proceso consciente del DPI por monitor.

    Imprescindible para que las coordenadas de UI Automation, de los hooks y
    de las capturas coincidan en píxeles físicos en pantallas al 125 % / 150 %
    y para que la interfaz se vea nítida. Se llama antes de crear ventanas.
    """
    try:
        # Windows 10 1703+: PER_MONITOR_AWARE_V2 (-4).
        if _user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except Exception:
        pass
    try:
        shcore = ctypes.WinDLL("shcore")
        if shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except Exception:
        pass
    try:
        if _user32.SetProcessDPIAware():
            return "system"
    except Exception:
        pass
    return "desconocido"


def pid_of_window(hwnd) -> int | None:
    if not hwnd:
        return None
    pid = wintypes.DWORD(0)
    try:
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    except Exception:
        return None
    return int(pid.value) or None


def pid_at_point(x: int, y: int) -> int | None:
    """PID dueño de la ventana top-level bajo el punto (rápido, sin UIA)."""
    try:
        hwnd = _user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return None
        root = _user32.GetAncestor(hwnd, GA_ROOT) or hwnd
        return pid_of_window(root)
    except Exception:
        return None


def foreground_pid() -> int | None:
    try:
        return pid_of_window(_user32.GetForegroundWindow())
    except Exception:
        return None


def cursor_pos() -> tuple[int, int]:
    point = wintypes.POINT()
    try:
        if _user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y)
    except Exception:
        pass
    return 0, 0


def double_click_time() -> float:
    try:
        return max(0.2, min(2.0, _user32.GetDoubleClickTime() / 1000.0))
    except Exception:
        return 0.5


def double_click_slop() -> int:
    try:
        return max(4, _user32.GetSystemMetrics(36), _user32.GetSystemMetrics(37))  # SM_CXDOUBLECLK / SM_CYDOUBLECLK
    except Exception:
        return 4


def toplevel_hwnd(window) -> int | None:
    """HWND de la ventana top-level de un Toplevel/Tk."""
    try:
        window.update_idletasks()
        frame = window.wm_frame()
        return int(frame, 16) if isinstance(frame, str) else int(frame)
    except Exception:
        return None


def set_capture_excluded(window, excluded: bool) -> bool:
    """Excluye la ventana de las capturas (Windows 10 2004+).

    En versiones anteriores WDA_EXCLUDEFROMCAPTURE se comportaría como
    WDA_MONITOR (la ventana saldría en negro), así que ni se intenta.
    """
    if windows_build() < 19041:
        return False
    hwnd = toplevel_hwnd(window)
    if not hwnd:
        return False
    try:
        ok = bool(_user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if excluded else WDA_NONE))
        if not ok:
            log.debug("SetWindowDisplayAffinity falló: %s", ctypes.get_last_error())
        return ok
    except Exception:
        return False


def is_process_elevated(pid: int | None) -> bool | None:
    """¿El proceso corre como administrador? None si no se puede saber."""
    if not pid:
        return None
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return None
    token = wintypes.HANDLE()
    try:
        if not _advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            elevation = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            if not _advapi32.GetTokenInformation(
                token, TOKEN_ELEVATION, ctypes.byref(elevation), ctypes.sizeof(elevation), ctypes.byref(size)
            ):
                return None
            return bool(elevation.value)
        finally:
            _kernel32.CloseHandle(token)
    finally:
        _kernel32.CloseHandle(handle)


def is_current_process_elevated() -> bool:
    try:
        return bool(is_process_elevated(os.getpid()))
    except Exception:
        return False


def bring_to_front(title: str) -> bool:
    """Trae al frente la ventana con ese título (otra instancia ya abierta)."""
    try:
        hwnd = _user32.FindWindowW(None, title)
        if not hwnd:
            return False
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        return bool(_user32.SetForegroundWindow(hwnd))
    except Exception:
        return False
