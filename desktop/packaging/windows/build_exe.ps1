#Requires -Version 5.1
<#
.SYNOPSIS
    Construye el ejecutable Windows de RPA Step Recorder con PyInstaller.

.DESCRIPTION
    - Verifica/instala PyInstaller.
    - Genera un icono .ico desde extension/icons/icon128.png (si Pillow existe).
    - Ejecuta pyinstaller con packaging/windows/rpa-step-recorder.spec.
    - Deja el binario en desktop/dist/RPAStepRecorder.exe y lo copia a
      desktop/releases/windows/RPAStepRecorder.exe (la copia versionada).

    Se puede ejecutar desde cualquier carpeta; por ejemplo, desde desktop/:
        .\packaging\windows\build_exe.ps1

    Los artefactos (build/, dist/, *.ico generado) estan en .gitignore y NO se
    versionan. El ejecutable listo para usar vive en releases/windows/.
#>

$ErrorActionPreference = 'Stop'

# Situarse en la carpeta desktop/ (dos niveles por encima de este script).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DesktopDir = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
Set-Location $DesktopDir

Write-Host '==> RPA Step Recorder - build del ejecutable' -ForegroundColor Cyan

# 1. Asegurar PyInstaller -----------------------------------------------------
Write-Host '--> Comprobando PyInstaller...'
$pyi = python -c "import PyInstaller, sys; sys.stdout.write(PyInstaller.__version__)" 2>$null
if (-not $pyi) {
    Write-Host '    PyInstaller no encontrado. Instalando...' -ForegroundColor Yellow
    python -m pip install pyinstaller
} else {
    Write-Host "    PyInstaller $pyi OK"
}

# 2. Generar icono .ico desde el PNG de la extension -------------------------
$IconPng = Join-Path $DesktopDir '..\extension\icons\icon128.png'
$BuildDir = Join-Path $DesktopDir 'build'
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$IconIco = Join-Path $BuildDir 'RPAStepRecorder.ico'
if (Test-Path $IconPng) {
    Write-Host '--> Generando icono .ico desde icon128.png...'
    $gen = @"
try:
    from PIL import Image
    img = Image.open(r'$IconPng').convert('RGBA')
    sizes = [(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)]
    img.save(r'$IconIco', format='ICO', sizes=sizes)
    print('ok')
except Exception as e:
    print('skip:', e)
"@
    $res = $gen | python -
    Write-Host "    $res"
} else {
    Write-Host '    No se encontro icon128.png; se construye sin icono.' -ForegroundColor Yellow
}

# 3. Build --------------------------------------------------------------------
Write-Host '--> Ejecutando PyInstaller...' -ForegroundColor Cyan
python -m PyInstaller --noconfirm packaging\windows\rpa-step-recorder.spec

# 4. Resultado ----------------------------------------------------------------
$Exe = Join-Path $DesktopDir 'dist\RPAStepRecorder.exe'
if (Test-Path $Exe) {
    $sizeMB = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
    # Copia versionada en git: desktop/releases/windows/RPAStepRecorder.exe
    $ReleaseDir = Join-Path $DesktopDir 'releases\windows'
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    Copy-Item -Path $Exe -Destination (Join-Path $ReleaseDir 'RPAStepRecorder.exe') -Force
    Write-Host ''
    Write-Host "==> OK: $Exe ($sizeMB MB)" -ForegroundColor Green
    Write-Host '    Copiado a releases\windows\RPAStepRecorder.exe' -ForegroundColor Green
} else {
    Write-Host '==> ERROR: no se genero el ejecutable.' -ForegroundColor Red
    exit 1
}
