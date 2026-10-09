# RPA Step Recorder — App de escritorio (Windows)

Graba lo que haces en **cualquier aplicación de Windows** (no solo el
navegador): programas instalados, ERPs, SAP GUI, utilidades del sistema, etc.
En cada clic inspecciona el elemento con **UI Automation**, captura la pantalla
con el elemento resaltado en rojo y genera la documentación del proceso en
**Word** y **PDF**. Funciona **sin conexión**: todo ocurre en tu equipo.

## Requisitos

- Windows 10 u 11.
- Python 3.12 (solo si la ejecutas desde el código fuente).
- O, como alternativa, el ejecutable `RPAStepRecorder.exe` (no necesita Python).

## Instalación (desde el código fuente)

Se recomienda usar un **entorno virtual** para no tocar tus otras librerías.
Abre una terminal (PowerShell) en la carpeta `desktop/` y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> Si PowerShell bloquea la activación del entorno, ejecuta una vez:
> `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`

### Dependencias

| Paquete | Para qué |
|---|---|
| `uiautomation` | Inspección del árbol de UI Automation (ControlType, Name, AutomationId...) |
| `psutil` | Nombre del ejecutable (`.exe`) dueño de la ventana |
| `pynput` | Hooks globales de ratón y teclado |
| `mss` | Captura de pantalla rápida y multi-monitor |
| `Pillow` | Anotación de capturas (recuadro rojo y zoom) |
| `python-docx` | Exportación a Word |
| `fpdf2` | Exportación a PDF |

## Cómo ejecutarla

Desde la carpeta `desktop/`:

```powershell
python run.py
```

1. Escribe el nombre del proceso (y opcionalmente autor y sistema) y pulsa
   **"Iniciar grabación"**.
2. Trabaja normal en tus aplicaciones. Cada clic sobre un botón, enlace,
   casilla o elemento se convierte en un paso con su captura y su descripción
   automática. Lo que escribes en un campo se registra como paso al salir del
   campo o al pulsar Enter.
   - Las contraseñas nunca se guardan: el paso dice "Escribir la contraseña".
3. Usa **"Pausar"** para hacer algo que no es parte del proceso.
   **"Agregar nota"** crea un paso de solo texto.
4. Pulsa **"Detener y revisar"** para corregir descripciones o borrar pasos.
5. Pulsa **"Exportar Word"** o **"Exportar PDF"** y elige dónde guardar.

### Atajos de teclado

| Atajo | Acción |
|---|---|
| `F9` | Iniciar / detener la grabación |
| `F8` | Agregar nota |
| `F10` | Pausar / reanudar |

## Construir el ejecutable (.exe)

El empaquetado usa **PyInstaller** con la receta `rpa-step-recorder.spec`.
Produce un único archivo `RPAStepRecorder.exe` sin consola (modo *windowed*).

### Opción A — Script automático (recomendado)

Desde la carpeta `desktop/`:

```powershell
.\build_exe.ps1
```

El script:
1. Verifica que PyInstaller esté instalado (lo instala si falta).
2. Genera un icono `.ico` a partir de `extension/icons/icon128.png` (si Pillow
   está disponible).
3. Ejecuta `pyinstaller rpa-step-recorder.spec`.
4. Deja el ejecutable en `desktop/dist/RPAStepRecorder.exe`.

### Opción B — Manual

```powershell
pip install pyinstaller
pyinstaller rpa-step-recorder.spec
```

El `.spec` incluye explícitamente los submódulos dinámicos y datos que estas
librerías necesitan para funcionar empaquetadas: `uiautomation`, `comtypes`,
`pynput`, `mss`, `PIL`, `python-docx` (plantillas `.docx`), `fpdf` y `psutil`.

> **Nota:** los artefactos de build (`build/` y `dist/`) están en `.gitignore`
> y **no se versionan**. El binario se publica como *Release* en GitHub.

## Dónde se guardan las grabaciones

```
%LOCALAPPDATA%\RPAStepRecorder\sessions\
```

Cada grabación es una carpeta con un `session.json` y los PNG de cada paso.
Puedes borrarlas desde el panel con el botón ✕.

## Qué contiene el documento

- Portada con el proceso, el sistema, el autor y la fecha.
- Tabla resumen con todos los pasos numerados.
- Una página por paso: descripción, captura con el elemento resaltado, detalle
  ampliado y los datos técnicos para quien programe el bot (ControlType,
  AutomationId, ClassName y la ruta jerárquica del control), además de
  selectores listos para RPA (UIA/XPath, pywinauto y UiPath).

## Notas

- Para capturar algunas aplicaciones que corren **como administrador**, puede
  que debas ejecutar la app (o el `.exe`) también como administrador.
- La precisión de los datos técnicos depende de que la aplicación exponga su
  árbol de UI Automation. La mayoría de apps de Windows lo hacen; algunas muy
  antiguas o hechas con tecnologías no estándar exponen menos información.
- La primera vez que arranca el `.exe` puede tardar unos segundos (descomprime
  el entorno en una carpeta temporal, propio de `--onefile`).

## Diferencias con la versión de navegador

En vez del selector CSS y el XPath del DOM, la versión de escritorio registra
los identificadores de UI Automation (AutomationId, ClassName, ControlType y la
ruta del control), que es lo que necesita un bot de RPA de escritorio (UiPath,
Power Automate, pywinauto) para localizar el elemento. Para documentar procesos
**web**, usa la [extensión de navegador](../extension/README.md).

## Historial de cambios

Ver [CHANGELOG.md](CHANGELOG.md).
