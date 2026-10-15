# Changelog — RPA Step Recorder (escritorio)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

## [4.0.0]

### Añadido
- **Soporte para macOS** (11+): inspección con la API de Accesibilidad (rol AX,
  AXIdentifier, acciones, bundle id), escucha global con un event tap de Quartz
  de solo lectura (se reactiva solo si macOS lo desactiva), capturas Retina con
  el recuadro bien escalado y selectores para Mac: ruta AX, AppleScript
  (System Events) y criterios AX. Aviso y acceso directo a los permisos de
  Accesibilidad, Monitorización de entrada y Grabación de pantalla.
- Arquitectura por *backends* (`app/backends/`): Windows, macOS y genérico.
- Clic derecho, doble clic (fusiona el paso anterior) y atajos de teclado
  (Ctrl+S, Alt+F4, Cmd+C…) como pasos.
- F8 / F9 / F10 funcionan de forma global mientras se graba (antes solo con la
  ventana enfocada). La nota pide su texto.
- Registro rotativo, aviso visible ante errores inesperados, instancia única,
  ajustes persistentes (`settings.json`), exportar/importar grabaciones `.zip`.
- Aviso cuando la app activa se ejecuta como administrador (Windows) o hay
  entrada segura activa (macOS).
- Empaquetado para macOS: `build_mac.sh` / `rpa-step-recorder-mac.spec`.

### Corregido
- Al detener se perdía lo último escrito y las ediciones pendientes.
- Se perdían los espacios al escribir; Tab mezclaba dos campos en un paso.
- El texto se toma del propio campo (pegados, autocompletado, tildes) y se
  registra también lo escrito sin clic previo (Tab, diálogos con foco).
- Guardado atómico de `session.json` con copia `.bak` y recuperación automática.
- La interfaz ya no relee el JSON mientras el grabador escribe.
- Un fallo de captura ya no descarta el paso (se guarda sin imagen).
- "Shipping"/"Opinión" ya no se toman por campos PIN; contraseñas detectadas
  con `IsPassword` real.
- Inspección acotada en tiempo: una app colgada o una lista enorme ya no
  bloquean la grabación.
- Llamadas a Tk desde hilos secundarios (colgaban la app en macOS).
- Scroll con rueda/trackpad en macOS (Tk 8.6 y 9) sobre toda la lista.

## [3.0.0]

### Añadido
- Documento (Word/PDF) más organizado: portada con banda de acento y resumen de
  fiabilidad, índice de pasos en tabla de 3 columnas (nº, descripción y
  fiabilidad con color) y cada paso con secciones claras (Identificación del
  elemento, Ubicación, Selectores para RPA), con pies de figura y control de
  saltos de página.
- Vista de grabación renovada: cada paso es una tarjeta con número, miniatura,
  nivel de fiabilidad, descripción editable y barra de acciones.
- Nuevo "Ver detalle": ventana con la captura ampliada, el detalle del elemento,
  la fiabilidad con sus motivos, la identificación, los selectores RPA (con
  botón de copiar) y las coordenadas.
- Coordenadas cartesianas por paso (punto absoluto, relativo al elemento,
  relativo a la ventana y monitor usado) como respaldo cuando el selector no
  basta.
- Empaquetado a ejecutable Windows con PyInstaller (`rpa-step-recorder.spec` y
  `build_exe.ps1`).

### Cambiado
- El grabador ya no se graba a sí mismo: ignora los clics sobre sus propias
  ventanas.
- Edición en vivo: corregir descripción, borrar o reordenar pasos durante la
  grabación sin perder lo que estás escribiendo.
- Las teclas se atribuyen al control con el foco de teclado, no al que está bajo
  el ratón.

## [2.x] — versiones anteriores

### Añadido
- Inspección robusta de elementos: ControlType, Name, AutomationId, ClassName,
  FrameworkId, RuntimeId, teclas de acceso, patrones de interacción y cadena de
  ancestros con índices.
- Selectores listos para RPA en cada paso: UIA/XPath, pywinauto y UiPath.
- Fiabilidad por paso (alta / media / baja).
- Panel con lista de pasos en vivo, miniaturas y cronómetro.
- Revisión con miniaturas ampliables, badges de fiabilidad, selectores
  copiables y reordenamiento de pasos.
- Atajos: `F9` iniciar/detener · `F8` nota · `F10` pausar/reanudar.
