#Requires -Version 5.1
<#
.SYNOPSIS
    Construye el ejecutable Windows de RPA Step Recorder con PyInstaller.

.DESCRIPTION
    - Verifica/instala PyInstaller.
    - Genera un icono .ico desde extension/icons/icon128.png (si Pillow existe).
    - Ejecuta pyinstaller con rpa-step-recorder.spec.
    - Deja el binario en desktop/dist/RPAStepRecorder.exe.

    Ejecutar desde la carpeta desktop/:
        .\build_exe.ps1

    Los artefactos (build/, dist/, *.ico generado) estan en .gitignore y NO se
    versionan: el binario se publica como Release en GitHub.
#>

$ErrorActionPreference = 'Stop'

# Situarse en la carpeta del script (desktop/).
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

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
$IconPng = Join-Path $ScriptDir '..\extension\icons\icon128.png'
$IconIco = Join-Path $ScriptDir 'RPAStepRecorder.ico'
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
python -m PyInstaller --noconfirm rpa-step-recorder.spec

# 4. Resultado ----------------------------------------------------------------
$Exe = Join-Path $ScriptDir 'dist\RPAStepRecorder.exe'
if (Test-Path $Exe) {
    $sizeMB = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
    Write-Host ''
    Write-Host "==> OK: $Exe ($sizeMB MB)" -ForegroundColor Green
} else {
    Write-Host '==> ERROR: no se genero el ejecutable.' -ForegroundColor Red
    exit 1
}
