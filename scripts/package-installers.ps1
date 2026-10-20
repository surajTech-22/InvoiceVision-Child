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
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (-not (Test-Path -LiteralPath $iscc)) { throw 'ISCC.exe missing' }
$project = Join-Path $root 'InvoiceVisionChild\InvoiceVisionChild.csproj'
[xml]$projectXml = Get-Content $project -Raw
$version = [string]$projectXml.Project.PropertyGroup.Version
if (-not $version -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Unable to resolve safe Child version' }
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
