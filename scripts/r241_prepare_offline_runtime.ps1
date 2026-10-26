#requires -Version 7.2
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
param(
  [Parameter(Mandatory=$true)][string]$Destination,
  [Parameter(Mandatory=$true)][string]$TesseractSource
)
# R241: build an ISOLATED TEST COPY from preinstalled, toolchain-managed binaries.
# Never install software or modify an existing AAH / Child / bank OCR directory.
$source=$env:pythonLocation
if ([string]::IsNullOrWhiteSpace($source) -or
    -not (Test-Path -LiteralPath (Join-Path $source 'python.exe') -PathType Leaf)) {
  throw 'Trusted GitHub runner Python toolcache location unavailable'
}
if (-not (Test-Path -LiteralPath (Join-Path $TesseractSource 'tesseract.exe') -PathType Leaf) -or
    -not (Test-Path -LiteralPath (Join-Path $TesseractSource 'tessdata/eng.traineddata') -PathType Leaf)) {
  throw 'Local Tesseract binary and trained data must both be present'
}
$destination=[IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $destination) {
  throw 'Refusing to overwrite an existing OCR runtime directory'
}
New-Item -ItemType Directory -Path "$destination/Python","$destination/Tesseract" -Force | Out-Null
Copy-Item -Path (Join-Path $source '*') -Destination "$destination/Python" -Recurse -Force
Copy-Item -Path (Join-Path $TesseractSource '*') -Destination "$destination/Tesseract" -Recurse -Force
$python=Join-Path $destination 'Python/python.exe'
$tesseract=Join-Path $destination 'Tesseract/tesseract.exe'
$data=Join-Path $destination 'Tesseract/tessdata'
& $python -I -c "import cv2,numpy,sys;print('R241_RELOCATED_PYTHON_READY',sys.version,cv2.__version__,numpy.__version__)"
if ($LASTEXITCODE -ne 0) { throw 'Relocated Python cannot import OCR libraries without the runner interpreter' }
$old=$env:TESSDATA_PREFIX
try {
  $env:TESSDATA_PREFIX=$data
  $languages=& $tesseract --list-langs 2>&1
  if ($LASTEXITCODE -ne 0 -or -not ($languages -match '\beng\b')) {
    throw 'Relocated Tesseract cannot find its English traineddata'
  }
} finally {
  $env:TESSDATA_PREFIX=$old
}
$required=@(
  (Join-Path $destination 'Python/python.exe'),
  (Join-Path $destination 'Tesseract/tesseract.exe'),
  (Join-Path $destination 'Tesseract/tessdata/eng.traineddata')
)
$files=@()
foreach($file in $required) {
  $files+=@{ path=[IO.Path]::GetRelativePath($destination,$file)
             ; sha256=(Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
             ; size_bytes=(Get-Item -LiteralPath $file).Length }
}
$manifest=@{
  schema_version=1
  status='ISOLATED_WINDOWS_CPU_RUNTIME_VERIFIED_NO_PADDLE_MODELS'
  python_runtime='Windows toolcache Python 3.11'
  required_packages=@('numpy','opencv-python-headless')
  tesseract_engine='Offline CPU Tesseract + eng traineddata'
  source='Trusted GitHub Windows runner toolcache and locally installed Tesseract'
  includes_paddleocr_models=$false
  customer_files_embedded=$false
  tests=@('relocated_python_cv2_numpy','relocated_tesseract_eng')
  executables=$files
  production_installation_authorized=$false
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $destination 'R241_RUNTIME_VERIFICATION.json') -Encoding utf8
Write-Host 'R241_RELOCATED_OFFLINE_CPU_OCR_RUNTIME_PROVEN'
