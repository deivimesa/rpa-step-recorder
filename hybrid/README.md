# RPA Step Recorder — Híbrido (web + escritorio, Windows y macOS)

Una sola app para documentar **procesos web y de escritorio**. Al abrirla
eliges qué vas a grabar:

- **Web**: escribes la URL de inicio y la app abre el navegador en una
  ventana propia de la grabación. Cada clic, texto escrito, opción elegida o
  tecla se registra con su captura y los datos del DOM: selector CSS, XPath,
  id, URL y selectores listos para Playwright, Selenium y UiPath.
- **Escritorio**: el grabador de la [app de escritorio](../desktop/) de
  siempre (UI Automation en Windows, Accesibilidad en macOS).

Las dos comparten panel, revisión, grabaciones y exportación a **Word** y
**PDF**. Funciona **sin conexión**: todo ocurre en tu equipo.

## Requisitos

- Windows 10 u 11, o macOS 11 o posterior (Intel o Apple Silicon).
- Para el modo web, un navegador basado en Chromium: Google Chrome, Microsoft
  Edge, Brave, Vivaldi o Chromium.
- Python 3.12 (solo si la ejecutas desde el código fuente), o el ejecutable de
  Windows [`releases/windows/RPAStepRecorderHibrido.exe`](releases/windows/).

## Instalación (desde el código fuente)

El híbrido reutiliza el código de `../desktop` (paquete `app`), así que el
repositorio tiene que estar completo.

**Windows** (PowerShell, en la carpeta `hybrid/`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

**macOS** (en la carpeta `hybrid/`):

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python 3.12+ de python.org o uv
pip install -r requirements.txt
python run.py
```

`requirements.txt` incluye las dependencias de la app de escritorio más
`websocket-client`, que conecta con el navegador.

## Modo web

### Qué navegador se usa

La grabación controla el navegador con su protocolo de depuración (CDP), que
solo tienen los navegadores basados en Chromium:

| Tu navegador predeterminado | Se graba con |
|---|---|
| Chrome, Edge, Brave, Vivaldi o Chromium | Ese mismo |
| Firefox, Safari, Opera… (Windows) | Microsoft Edge (viene con Windows) o Google Chrome |
| Firefox, Safari, Opera… (macOS) | Google Chrome, Microsoft Edge o Brave, el primero instalado |

La pantalla de elección avisa de cuál se va a usar y por qué.

El navegador se abre con un **perfil propio de la grabación**: no toca tu
sesión habitual, y los inicios de sesión que hagas allí se recuerdan para la
próxima grabación. Cerrar el panel no cierra el navegador. Si lo cierras
mientras grabas, haz clic en el aviso del panel para volver a abrirlo.

### Qué se registra

- Clic, clic derecho (en Mac también Ctrl+clic) y doble clic.
- Texto escrito en un campo, al salir de él. Las contraseñas y los campos
  sensibles (tarjeta, CVV, PIN, token…) nunca se guardan.
- Opción elegida en una lista desplegable.
- Enter y Esc.
- Elementos dentro de iframes, también de otro dominio: el paso indica los
  marcos que hay que atravesar y los selectores ya los incluyen.

La captura se toma **antes** de que el clic cambie la página, con el elemento
resaltado. En pantallas Retina o con escala de Windows el recuadro se ajusta
solo.

### macOS

En el modo web la app **no necesita permisos de macOS**: no escucha el
teclado del sistema ni captura la pantalla, sino solo la pestaña del
navegador. El modo escritorio sí necesita los permisos de Accesibilidad,
Monitorización de entrada y Grabación de pantalla (ver
[desktop/README.md](../desktop/README.md#macos)).

## Atajos de teclado

| Acción | Tecla | Alternativa |
|---|---|---|
| Iniciar / detener grabación | F9 | Ctrl+Mayús+9 (Windows) · Cmd+Mayús+9 (macOS) |
| Pausar / reanudar | F10 | Ctrl+Mayús+0 · Cmd+Mayús+0 |
| Añadir nota | F8 | Ctrl+Mayús+8 · Cmd+Mayús+8 |

En el modo web funcionan con la página del navegador enfocada. En portátiles
Mac, F8/F9/F10 se pulsan con `fn`.

## Construir el ejecutable

**Windows** → `hybrid/dist/RPAStepRecorderHibrido.exe`, copiado también a
`releases/windows/`:

```powershell
.\packaging\windows\build_exe.ps1
```

**macOS** → `hybrid/dist/RPA Step Recorder Hibrido.app` y
`RPAStepRecorderHibrido.dmg`:

```bash
./packaging/macos/build_mac.sh
```

Ambos scripts se pueden lanzar desde cualquier carpeta. La `.app` lleva una
firma ad hoc: macOS pedirá los permisos del modo escritorio de nuevo tras
cada recompilación.

## Dónde se guardan las grabaciones

En la misma carpeta que la app de escritorio, así que las grabaciones de una
aparecen en la otra:

- Windows: `%LOCALAPPDATA%\RPAStepRecorder\sessions\`
- macOS: `~/Library/Application Support/RPAStepRecorder/sessions/`

Los perfiles del navegador de grabación están en `web-profiles/`, dentro de
esa misma carpeta. Como comparten carpeta, no se pueden abrir a la vez la app
de escritorio y el híbrido.

## Pruebas

Desde `hybrid/`:

```bash
python -m unittest discover -s tests -t .
```

## Estructura del código

```
hybrid/
├── run.py                     Punto de entrada: python run.py (añade ../desktop al path)
├── requirements.txt           Las de ../desktop + websocket-client
├── hybrid/                    Código fuente
│   ├── main.py                Arranque: pantalla de elección ⇄ panel del modo elegido
│   ├── ui/
│   │   ├── chooser.py         Pantalla «¿Qué proceso vas a documentar?»
│   │   └── apps.py            Paneles web y escritorio (el panel de desktop + cambio de modo)
│   └── web/                   Grabación web
│       ├── agent.js           Agente inyectado en cada página e iframe (mundo aislado)
│       ├── cdp.py             Cliente mínimo del protocolo CDP sobre WebSocket
│       ├── backend.py         Engancha pestañas e iframes, inyecta el agente, pide capturas
│       ├── recorder.py        Grabador de desktop alimentado por los eventos del navegador
│       ├── elements.py        Del evento al paso: elemento, fiabilidad, selectores, texto
│       └── browser/           Navegador: elección y arranque con perfil propio
│           ├── windows.py     Predeterminado según el registro
│           └── macos.py       Predeterminado según LaunchServices; paquetes .app
├── tests/                     Pruebas (unittest)
├── packaging/
│   ├── windows/               build_exe.ps1 + .spec → RPAStepRecorderHibrido.exe
│   └── macos/                 build_mac.sh + .spec → RPA Step Recorder Hibrido.app / .dmg
├── releases/windows/          RPAStepRecorderHibrido.exe listo para usar
├── README.md
└── CHANGELOG.md
```

## Historial de cambios

Ver [CHANGELOG.md](CHANGELOG.md).
