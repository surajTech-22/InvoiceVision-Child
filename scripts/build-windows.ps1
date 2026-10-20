#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$project = Join-Path $root 'InvoiceVisionChild\InvoiceVisionChild.csproj'
$manifest = Join-Path $root 'CHILD_SOURCE_SHA256.json'
$publish = Join-Path $root 'build\publish'
$release = Join-Path $root 'release'

if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
    throw 'Child source has not been imported. Refusing to create a fake or incomplete installer.'
}
if (-not (Test-Path -LiteralPath $manifest -PathType Leaf)) {
    throw 'Missing Child SHA-256 source manifest. Stopping.'
}
$items = @((Get-Content -LiteralPath $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).files)
if ($items.Count -lt 70) { throw "Child source manifest incomplete: $($items.Count)" }
$paths = @{}
foreach ($item in $items) {
    $rel = [string]$item.path
    if (-not $rel.StartsWith('InvoiceVisionChild/') -or $rel.Contains('..') -or $paths.ContainsKey($rel)) {
        throw "Unsafe, duplicate or unexpected source entry: $rel"
    }
    $paths[$rel] = $true
    $file = Join-Path $root ($rel.Replace('/', '\'))
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "Missing source: $rel" }
    $sha = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -ne [string]$item.sha256) { throw "Source hash mismatch: $rel" }
}
Write-Host "SOURCE_SHA256_PASS $($items.Count) files"
if (Test-Path $publish) { Remove-Item $publish -Recurse -Force }
New-Item -ItemType Directory -Path $publish,$release -Force | Out-Null
& dotnet publish $project -c Release -r win-x64 --self-contained true -p:UseAppHost=true -p:PublishSingleFile=false -o $publish
if ($LASTEXITCODE -ne 0) { throw "Windows .NET 10 publish failed ($LASTEXITCODE)" }
Copy-Item -Path (Join-Path $root 'InvoiceVisionChild\Engine\*') -Destination (Join-Path $publish 'Engine') -Recurse -Force
foreach ($item in $items) {
    $rel = [string]$item.path
    if (-not $rel.StartsWith('InvoiceVisionChild/Engine/')) { continue }
    $sub = $rel.Substring('InvoiceVisionChild/'.Length)
    $file = Join-Path $publish ($sub.Replace('/', '\'))
    if (-not (Test-Path $file -PathType Leaf)) { throw "Published engine file missing: $sub" }
    $sha = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($sha -ne [string]$item.sha256) { throw "Published engine checksum mismatch: $sub" }
}
$exe = Join-Path $publish 'InvoiceVisionChild.exe'
if (-not (Test-Path $exe -PathType Leaf)) { throw 'Real Child executable missing' }
$bytes = [IO.File]::ReadAllBytes($exe)
if ($bytes.Length -lt 100000 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90) { throw 'Invalid Windows executable' }

# Run the app's REAL startup smoke test. A headless GitHub runner may not
# provide an interactive desktop; in that case fail instead of certifying.
$smoke = Join-Path $root 'build\startup-smoke.txt'
if (Test-Path $smoke) { Remove-Item $smoke -Force }
$p = Start-Process -FilePath $exe -WorkingDirectory $publish -ArgumentList @('--self-test','--self-test-output',('"' + $smoke + '"')) -PassThru
try {
    if (-not $p.WaitForExit(90000)) {
        try { $p.Kill() } catch {}
        throw 'Child startup smoke timed out. No installer may be released.'
    }
    if ($p.ExitCode -ne 0 -or -not (Test-Path $smoke -PathType Leaf)) { throw "Child startup failed ($($p.ExitCode))" }
    $marker = (Get-Content -LiteralPath $smoke -Raw).Trim()
    if ($marker -ne 'SMOKE_OK|R95_R3|VISIBLE_WINDOW|STAGE1_ENGINE_PRESENT|R109_RECURSIVE_EDITOR_PRESENT') {
        throw "Unexpected Child startup marker: $marker"
    }
} finally { $p.Dispose() }
Write-Host 'WINDOWS_SELF_CONTAINED_PUBLISH_AND_STARTUP_PASS'
$report = @{
    generated_utc = (Get-Date).ToUniversalTime().ToString('o')
    source_sha256_pass = $true
    manifest_file_count = $items.Count
    self_contained_dotnet = $true
    engine_hash_check_pass = $true
    windows_executable_valid = $true
    child_startup_smoke_pass = $true
    source_version = 'R113_R4_R2_VERIFIED_BASELINE'
    field_accuracy_certified = $false
    note = 'Packaging validation only. Full invoice recognition remains provisional.'
}
$report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $release 'BUILD_VERIFICATION.json') -Encoding UTF8
