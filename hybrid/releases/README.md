# Ejecutables listos para usar

| Archivo | Sistema | Versión |
|---|---|---|
| [`windows/RPAStepRecorderHibrido.exe`](windows/RPAStepRecorderHibrido.exe) | Windows 10 / 11 | 1.0.0 |

No necesita Python ni instalación: descárgalo y ábrelo. La primera vez tarda
unos segundos en arrancar.

> El `.exe` actual es de la versión **1.0.0** y todavía no incluye los cambios
> de la 1.1.0 (ver [CHANGELOG](../CHANGELOG.md)). Para actualizarlo hay que
> compilarlo en Windows con `packaging\windows\build_exe.ps1`, que deja aquí la
> versión nueva.

La app de macOS (`.app` / `.dmg`) no se versiona: se genera con
`packaging/macos/build_mac.sh`.
