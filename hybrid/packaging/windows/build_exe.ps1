#Requires -Version 5.1
<#
.SYNOPSIS
    Construye el ejecutable HIBRIDO (web + escritorio) de RPA Step Recorder.

.DESCRIPTION
    - Usa el entorno virtual hybrid\.venv si existe (si no, el python del PATH).
    - Instala las dependencias de hybrid\requirements.txt y PyInstaller.
    - Genera un icono .ico desde extension/icons/icon128.png.
    - Ejecuta pyinstaller con packaging/windows/rpa-step-recorder-hibrido.spec.
    - Deja el binario en hybrid/dist/RPAStepRecorderHibrido.exe y lo copia a
      hybrid/releases/windows/RPAStepRecorderHibrido.exe (la copia versionada).

    Se puede ejecutar desde cualquier carpeta; por ejemplo, desde hybrid/:
        .\packaging\windows\build_exe.ps1
#>

$ErrorActionPreference = 'Stop'

# pip y PyInstaller escriben su registro en stderr: en PowerShell 5.1, con la
# salida redirigida, eso cuenta como error. Se juzgan por su código de salida.
function Invoke-Native([scriptblock]$Block) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block } finally { $ErrorActionPreference = $prev }
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$HibridoDir = (Resolve-Path (Join-Path $ScriptDir '..\..')).Path
Set-Location $HibridoDir

Write-Host '==> RPA Step Recorder HIBRIDO - build del ejecutable' -ForegroundColor Cyan

# 1. Python y dependencias -----------------------------------------------------
$Python = Join-Path $HibridoDir '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    $Python = 'python'
    Write-Host '    Sin .venv: se usa el python del PATH.' -ForegroundColor Yellow
}
Write-Host '--> Instalando dependencias...'
Invoke-Native { & $Python -m pip install --disable-pip-version-check -q -r requirements.txt pyinstaller }
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar las dependencias.' }

# 2. Icono .ico desde el PNG de la extension -----------------------------------
$IconPng = Join-Path $HibridoDir '..\extension\icons\icon128.png'
$BuildDir = Join-Path $HibridoDir 'build'
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null
$IconIco = Join-Path $BuildDir 'RPAStepRecorderHibrido.ico'
if (Test-Path $IconPng) {
    Write-Host '--> Generando icono .ico...'
    $gen = @"
from PIL import Image
img = Image.open(r'$IconPng').convert('RGBA')
img.save(r'$IconIco', format='ICO', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('ok')
"@
    $res = $gen | & $Python -
    Write-Host "    $res"
}

# 3. Build --------------------------------------------------------------------
Write-Host '--> Ejecutando PyInstaller...' -ForegroundColor Cyan
Invoke-Native { & $Python -m PyInstaller --noconfirm --log-level WARN --workpath build --distpath dist packaging\windows\rpa-step-recorder-hibrido.spec }
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller fallo.' }

# 4. Resultado ----------------------------------------------------------------
$Exe = Join-Path $HibridoDir 'dist\RPAStepRecorderHibrido.exe'
if (Test-Path $Exe) {
    $sizeMB = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
    $ReleaseDir = Join-Path $HibridoDir 'releases\windows'
    New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
    Copy-Item -Path $Exe -Destination (Join-Path $ReleaseDir 'RPAStepRecorderHibrido.exe') -Force
    Write-Host ''
    Write-Host "==> OK: $Exe ($sizeMB MB)" -ForegroundColor Green
    Write-Host '    Copiado a releases\windows\RPAStepRecorderHibrido.exe' -ForegroundColor Green
} else {
    Write-Host '==> ERROR: no se genero el ejecutable.' -ForegroundColor Red
    exit 1
}
