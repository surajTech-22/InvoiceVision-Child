#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$report = Join-Path $root 'release\BUILD_VERIFICATION.json'
$publish = Join-Path $root 'build\publish'
$iss = Join-Path $root 'installer\InvoiceVisionChild.iss'
$release = Join-Path $root 'release'
if (-not (Test-Path $report -PathType Leaf)) { throw 'Source, compilation and startup gates have NOT passed.' }
if (-not (Test-Path (Join-Path $publish 'InvoiceVisionChild.exe'))) { throw 'Missing real compiled Child.' }
if (-not (Test-Path $iss -PathType Leaf)) { throw 'Missing Inno Setup definition.' }
# Startup/compilation alone never authorize Setup.exe or Update.exe creation.
# Acceptance must describe this exact build and provide checksummed evidence.
$acceptancePath = Join-Path $release 'ACCEPTANCE_VERIFICATION.json'
if (-not (Test-Path -LiteralPath $acceptancePath -PathType Leaf)) {
    throw 'Full invoice and Windows acceptance evidence missing; installers withheld.'
}
$acceptance = Get-Content -LiteralPath $acceptancePath -Raw -Encoding UTF8 | ConvertFrom-Json
$required = @('ocr_accuracy','physical_boxes','recursive_zones','field_mapping',
    'cpu_gpu_fallback','offline_runtime','windows_child_end_to_end',
    'install_update_rollback','existing_data_preservation','visual_comparisons')
if ($acceptance.schema_version -ne 1 -or $acceptance.release_authorized -isnot [bool] -or -not $acceptance.release_authorized) {
    throw 'Acceptance does not authorize installers.'
}
$actualBuildHash = (Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant()
if ($acceptance.build_report_sha256 -cne $actualBuildHash) { throw 'Acceptance belongs to a different build.' }
if ($acceptance.unresolved_failures -ne 0 -or $acceptance.total_cases -lt 51 -or $acceptance.passed_cases -ne $acceptance.total_cases) {
    throw 'Complete source corpus has not passed acceptance.'
}
foreach ($name in $required) {
    $gate = $acceptance.gates.$name
    if ($gate.passed -isnot [bool] -or -not $gate.passed) { throw "Acceptance gate failed: $name" }
    $relative = [string]$gate.evidence_path
    if (-not $relative -or [IO.Path]::IsPathRooted($relative) -or ($relative -split '[\\/]') -contains '..') {
        throw "Unsafe acceptance evidence path: $name"
    }
    $evidence = Join-Path $release $relative
    if (-not (Test-Path -LiteralPath $evidence -PathType Leaf)) { throw "Missing acceptance evidence: $name" }
    $actual = (Get-FileHash -LiteralPath $evidence -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($gate.evidence_sha256 -cne $actual) { throw "Acceptance evidence checksum mismatch: $name" }
}
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) { throw 'ISCC.exe missing' }
$project = Join-Path $root 'InvoiceVisionChild\InvoiceVisionChild.csproj'
[xml]$projectXml = Get-Content $project -Raw
$version = [string]$projectXml.Project.PropertyGroup.Version
if (-not $version -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Unable to resolve safe Child version' }
$obj = (Get-Content $report -Raw -Encoding UTF8 | ConvertFrom-Json)
if (-not $obj.source_sha256_pass -or -not $obj.child_startup_smoke_pass -or -not $obj.self_contained_dotnet) { throw 'Build verification failed' }
& $iscc "/DAppVersion=$version" $iss
if ($LASTEXITCODE -ne 0) { throw 'Setup.exe compilation failed' }
& $iscc "/DAppVersion=$version" "/DUpdateMode=1" $iss
if ($LASTEXITCODE -ne 0) { throw 'Update.exe compilation failed' }
$exes = @('InvoiceVisionChild_Setup.exe','InvoiceVisionChild_Update.exe')
$hashes = @()
foreach ($name in $exes) {
    $f = Join-Path $release $name
    if (-not (Test-Path $f -PathType Leaf)) { throw "Missing actual installer $name" }
    $bytes = [IO.File]::ReadAllBytes($f)
    if ($bytes.Length -lt 5000000 -or $bytes[0] -ne 77 -or $bytes[1] -ne 90) {
        throw "Invalid or implausibly small Windows installer: $name"
    }
    $sha = (Get-FileHash $f -Algorithm SHA256).Hash.ToLowerInvariant()
    "$sha  $name" | Set-Content -LiteralPath (Join-Path $release ($name + '.sha256.txt')) -Encoding Ascii
    $hashes += @{name=$name;sha256=$sha;size_bytes=$bytes.Length}
}
$obj = (Get-Content $report -Raw -Encoding UTF8 | ConvertFrom-Json)
if (-not $obj.source_sha256_pass -or -not $obj.child_startup_smoke_pass -or -not $obj.self_contained_dotnet) {
    throw 'Verification report does not authorize release'
}
$obj | Add-Member -NotePropertyName windows_installers -NotePropertyValue $hashes
$obj | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $report -Encoding UTF8
Write-Host 'SETUP_AND_UPDATE_EXECUTABLES_BUILT_AND_HASHED'
Write-Host 'NOTE: Real installation and rollback still require a Windows test before end-user release.'

