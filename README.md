# RPA Step Recorder

Graba lo que haces, paso a paso, y genera automáticamente la documentación del
proceso (PDD) en **Word** y **PDF**. En cada paso captura la pantalla, resalta
en rojo el elemento con el que interactúas, escribe una descripción automática
e incluye los datos técnicos que necesita un bot de RPA para localizar el
elemento.

Todo ocurre **en tu equipo**: no envía nada a internet y funciona sin conexión.

El proyecto tiene **tres versiones**, pensadas para escenarios distintos:

| | 🧩 Extensión de navegador | 🖥️ App de escritorio | 🔀 Híbrido (web + escritorio) |
|---|---|---|---|
| **Carpeta** | [`extension/`](extension/) | [`desktop/`](desktop/) | [`hybrid/`](hybrid/) |
| **Dónde graba** | Páginas web en Chrome / Edge | Cualquier app de Windows o macOS (ERPs, SAP GUI, escritorio, utilidades...) | Lo que elijas al abrirla: la web (en un navegador abierto por la app) o el escritorio |
| **Plataforma** | Windows, macOS, Linux | Windows 10 / 11 y macOS 11+ | Windows 10 / 11 y macOS 11+ |
| **Instalación** | Cargar como extensión en modo desarrollador | Python + dependencias, o el `.exe` de [`desktop/releases/`](desktop/releases/) | Python + dependencias, o el `.exe` de [`hybrid/releases/`](hybrid/releases/) |
| **Datos técnicos** | Selector CSS, XPath, id, URL | Windows: UI Automation (`AutomationId`, selectores UiPath / pywinauto). macOS: Accesibilidad (rol AX, AXIdentifier, ruta AX, AppleScript) | Web: CSS, XPath, id, URL y selectores Playwright / Selenium / UiPath. Escritorio: los de la app de escritorio |
| **Requisitos** | Solo el navegador | Python 3.12 (o el ejecutable) | Python 3.12 (o el ejecutable) y, para la web, Chrome, Edge o Brave |
| **Salida** | Word y PDF | Word y PDF | Word y PDF |

## ¿Cuál me conviene?

- **Documentas procesos web** (aplicaciones en el navegador, portales, SaaS):
  usa la **extensión**. No instala nada, funciona en cualquier sistema
  operativo y captura el DOM (CSS/XPath).
- **Documentas aplicaciones de escritorio** (ERP instalado, SAP GUI,
  programas nativos, utilidades del sistema): usa la **app de escritorio**.
  Inspecciona el árbol de UI Automation (Windows) o de Accesibilidad (macOS),
  que es lo que necesitan los bots de RPA de escritorio (UiPath, Power
  Automate, pywinauto).
- **Documentas procesos que mezclan web y escritorio**, o quieres una sola
  app instalada para todo: usa el **híbrido**. Reutiliza la app de escritorio
  y le añade un modo web que no necesita instalar la extensión (ni, en macOS,
  dar permisos al sistema).

## Estructura del repositorio

```
rpa-step-recorder/
├── extension/                 🧩 Extensión Chrome / Edge (Manifest V3)
│   ├── manifest.json          La carpeta extension/ es la que se carga en el navegador
│   ├── icons/                 Iconos 16/32/48/128 px
│   ├── src/
│   │   ├── background/        Service worker: capturas, pasos e IndexedDB
│   │   ├── content/           Script inyectado en las páginas + tarjeta del paso
│   │   ├── popup/             Panel del icono de la barra
│   │   ├── review/            Página «Revisar y exportar»
│   │   ├── lib/               Word, PDF, ZIP, anotación de capturas e IndexedDB
│   │   └── styles/            Tokens de diseño compartidos
│   ├── README.md              Instalación y uso
│   └── LEEME.txt              Guía para el usuario final (texto plano)
│
├── desktop/                   🖥️ App de escritorio Python / Tkinter (Windows y macOS)
│   ├── run.py                 Punto de entrada: python run.py
│   ├── requirements.txt
│   ├── app/                   Código fuente
│   │   ├── main.py            Arranque: registro, instancia única y ventana
│   │   ├── core/              Grabación, capturas, sesiones, ajustes y rutas
│   │   ├── ui/                Ventanas: panel, revisión, detalle y tema
│   │   ├── backends/          Integración con el sistema operativo
│   │   │   ├── windows/       UI Automation, hooks y Win32
│   │   │   └── macos/         Accesibilidad (AX) y event tap de Quartz
│   │   ├── exporters/         Documentos Word y PDF
│   │   └── assets/fonts/      Fuentes del PDF
│   ├── packaging/             Empaquetado con PyInstaller
│   │   ├── windows/           build_exe.ps1 + .spec → RPAStepRecorder.exe
│   │   └── macos/             build_mac.sh + .spec → RPA Step Recorder.app / .dmg
│   ├── releases/windows/      RPAStepRecorder.exe listo para usar
│   ├── README.md              Instalación, uso y empaquetado
│   └── CHANGELOG.md
│
├── hybrid/                    🔀 Híbrido web + escritorio (Windows y macOS); reutiliza desktop/app
│   ├── run.py                 Punto de entrada: python run.py
│   ├── requirements.txt       Las de desktop/ + websocket-client
│   ├── hybrid/                Código fuente
│   │   ├── main.py            Arranque: pantalla de elección ⇄ panel del modo elegido
│   │   ├── ui/                Pantalla de elección y paneles web / escritorio
│   │   └── web/               Grabación web por CDP: agente, navegador, grabador, selectores
│   ├── tests/                 Pruebas (unittest)
│   ├── packaging/             Empaquetado con PyInstaller
│   │   ├── windows/           build_exe.ps1 + .spec → RPAStepRecorderHibrido.exe
│   │   └── macos/             build_mac.sh + .spec → RPA Step Recorder Hibrido.app / .dmg
│   ├── releases/windows/      RPAStepRecorderHibrido.exe listo para usar
│   ├── README.md              Instalación, uso y empaquetado
│   └── CHANGELOG.md
│
├── design/                    Design tokens de marca (CSS y JSON) de los que salen las paletas
├── README.md                  (este archivo)
├── LICENSE                    Licencia MIT
└── .gitignore
```

## Documentación por versión

- 🧩 **Extensión de navegador** → [`extension/README.md`](extension/README.md)
- 🖥️ **App de escritorio (Windows y macOS)** → [`desktop/README.md`](desktop/README.md)
- 🔀 **Híbrido web + escritorio (Windows y macOS)** → [`hybrid/README.md`](hybrid/README.md)
- 📦 **Ejecutables de Windows** → [`desktop/releases/`](desktop/releases/) y [`hybrid/releases/`](hybrid/releases/)

## Privacidad

Ninguna de las versiones envía datos a servidores externos. Las capturas,
las grabaciones y los documentos se generan y se guardan solo en tu equipo.
Las contraseñas nunca se registran: el paso correspondiente dice únicamente
"Escribir la contraseña".

## Licencia

Distribuido bajo licencia [MIT](LICENSE).
