# Changelog — RPA Step Recorder (híbrido)

Formato basado en [Keep a Changelog](https://keepachangelog.com/es/1.0.0/).

## [1.1.0]

### Añadido
- **Soporte para macOS** (11+): el modo web detecta el navegador
  predeterminado con LaunchServices y, si no es compatible (Safari,
  Firefox…), usa Chrome, Edge o Brave. No necesita permisos de macOS. El
  modo escritorio usa el backend de Accesibilidad de la app de escritorio.
- Empaquetado para macOS: `packaging/macos/build_mac.sh` →
  `RPA Step Recorder Hibrido.app` y `.dmg`.
- Atajos sin teclas F en el modo web: Cmd+Mayús+8/9/0 (macOS) y
  Ctrl+Mayús+8/9/0 (Windows), como en la app de escritorio.
- En macOS, Ctrl+clic se registra como clic derecho.
- Pruebas automáticas (`tests/`) de la descripción de elementos, los
  selectores y la detección del navegador.
- README propio.

### Corregido
- Los pasos dentro de un iframe llevaban como título de la página su URL en
  vez del título real (afectaba al selector UiPath). Ahora se usa el título
  que manda el marco superior.
- La URL y el título de un paso se toman de la pestaña donde ocurrió, no de
  la última pestaña tocada.
- En macOS, la tarjeta de la pantalla de elección con el foco se pintaba con
  borde negro.

### Cambiado
- Carpeta `hibrido/` renombrada a `hybrid/`, como `extension/` y `desktop/`.
- Detección del navegador separada por sistema en `web/browser/`
  (`windows.py`, `macos.py`); el navegador elegido se calcula una vez por
  ejecución.
- Empaquetado por sistema en `packaging/windows/` y `packaging/macos/`; el
  ejecutable de Windows pasa a `releases/windows/`.
- El navegador de grabación se abre sin heredar la salida de la app y, en
  macOS, en una sesión propia (no se cierra con la terminal que lanzó la app).

## [1.0.0]

### Añadido
- Primera versión (solo Windows): pantalla de elección web / escritorio y
  grabación web por CDP con el navegador predeterminado, perfil propio,
  iframes de otro dominio y selectores CSS, XPath, Playwright, Selenium y
  UiPath.
