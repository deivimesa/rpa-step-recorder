# RPA Step Recorder

Graba lo que haces, paso a paso, y genera automáticamente la documentación del
proceso (PDD) en **Word** y **PDF**. En cada paso captura la pantalla, resalta
en rojo el elemento con el que interactúas, escribe una descripción automática
e incluye los datos técnicos que necesita un bot de RPA para localizar el
elemento.

Todo ocurre **en tu equipo**: no envía nada a internet y funciona sin conexión.

El proyecto tiene **dos versiones independientes**, pensadas para escenarios
distintos:

| | 🧩 Extensión de navegador | 🖥️ App de escritorio |
|---|---|---|
| **Carpeta** | [`extension/`](extension/) | [`desktop/`](desktop/) |
| **Dónde graba** | Páginas web en Chrome / Edge | Cualquier app de Windows o macOS (ERPs, SAP GUI, escritorio, utilidades...) |
| **Plataforma** | Windows, macOS, Linux | Windows 10 / 11 y macOS 11+ |
| **Instalación** | Cargar como extensión en modo desarrollador | Python + dependencias, o el `.exe` empaquetado |
| **Datos técnicos** | Selector CSS, XPath, id, URL | Windows: UI Automation (`AutomationId`, selectores UiPath / pywinauto). macOS: Accesibilidad (rol AX, AXIdentifier, ruta AX, AppleScript) |
| **Requisitos** | Solo el navegador | Python 3.12 (o el ejecutable) |
| **Salida** | Word y PDF | Word y PDF |

## ¿Cuál me conviene?

- **Documentas procesos web** (aplicaciones en el navegador, portales, SaaS):
  usa la **extensión**. No instala nada, funciona en cualquier sistema
  operativo y captura el DOM (CSS/XPath).
- **Documentas aplicaciones de escritorio Windows** (ERP instalado, SAP GUI,
  programas nativos, utilidades del sistema): usa la **app de escritorio**.
  Inspecciona el árbol de UI Automation, que es lo que necesitan los bots de
  RPA de escritorio (UiPath, Power Automate, pywinauto).

## Estructura del repositorio

```
rpa-step-recorder/
├── extension/        Extensión Chrome / Edge (Manifest V3)
│   ├── manifest.json
│   ├── background.js, content.js, popup.*, review.*
│   ├── lib/          Librerías de generación de documentos (docx, pdf, zip...)
│   ├── icons/        Iconos de la extensión (16/32/48/128 px)
│   └── README.md     → Guía de instalación y uso de la extensión
│
├── desktop/          App de escritorio Python / Tkinter (Windows)
│   ├── run.py        Punto de entrada: python run.py
│   ├── requirements.txt
│   ├── app/          Paquete principal (recorder, inspector, exporters...)
│   ├── rpa-step-recorder.spec   Receta de empaquetado PyInstaller
│   ├── build_exe.ps1            Script de build del .exe
│   └── README.md     → Instalación, uso y cómo construir el .exe
│
├── README.md         (este archivo)
├── LICENSE           Licencia MIT
└── .gitignore
```

## Documentación por versión

- 🧩 **Extensión de navegador** → [`extension/README.md`](extension/README.md)
- 🖥️ **App de escritorio Windows** → [`desktop/README.md`](desktop/README.md)

## Privacidad

Ninguna de las dos versiones envía datos a servidores externos. Las capturas,
las grabaciones y los documentos se generan y se guardan solo en tu equipo.
Las contraseñas nunca se registran: el paso correspondiente dice únicamente
"Escribir la contraseña".

## Licencia

Distribuido bajo licencia [MIT](LICENSE).
