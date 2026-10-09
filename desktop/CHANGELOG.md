# Changelog — RPA Step Recorder (escritorio)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

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
