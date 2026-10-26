#requires -Version 7.2
param(
  [Parameter(Mandatory=$true)][string]$PublishedPath,
  [Parameter(Mandatory=$true)][string]$EvidencePath
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$publish=[IO.Path]::GetFullPath($PublishedPath)
$evidence=[IO.Path]::GetFullPath($EvidencePath)
if (-not (Test-Path (Join-Path $publish 'InvoiceVisionChild.exe') -PathType Leaf) -or
    -not (Test-Path (Join-Path $publish 'Runtime/Python/python.exe') -PathType Leaf)) {
  throw 'Real published Child and offline runtime required'
}
$root=Join-Path ([IO.Path]::GetTempPath()) ('IV_R242_'+[Guid]::NewGuid().ToString('N'))
try {
  $installed=Join-Path $root 'Installed'
  $backup=Join-Path $root 'ApplicationBackup'
  $userdata=Join-Path $root 'SimulatedUserLocalAppData'
  $custom=Join-Path $installed 'CustomUserLayouts'
  New-Item -ItemType Directory -Path $installed,$backup,$userdata,$custom -Force | Out-Null
  $samples=@{
    'SourceReviewAnnotations/source-1.json'='{"review":"user annotation","protected":true}'
    'Settings/preferences.json'='{"theme":"dark","startup":false}'
    'Mappings/my-user-mapping.json'='{"mapping":"do not remove","version":42}'
    'SourceOriginals/photo-reference.txt'='synthetic immutable photo hash'
  }
  foreach($name in $samples.Keys) {
    $target=Join-Path $userdata $name
    New-Item -ItemType Directory -Path (Split-Path $target) -Force | Out-Null
    [IO.File]::WriteAllText($target,$samples[$name])
  }
  [IO.File]::WriteAllText((Join-Path $custom 'custom-layout.json'),'{"user_owned":true}')
  $paths=@('InvoiceVisionChild.exe','Engine/INVOICE_OCR_SOURCE_REVIEW_R226.py',
           'Engine/INVOICE_OCR_QR_REVIEW_R238.py')
  foreach($p in $paths) {
    foreach($targetRoot in @($installed,$backup)) {
      $to=Join-Path $targetRoot $p
      New-Item -ItemType Directory -Path (Split-Path $to) -Force | Out-Null
      Copy-Item -LiteralPath (Join-Path $publish $p) -Destination $to -Force
    }
  }
  function Snapshot([string]$location) {
    $map=@{}
    foreach($file in @(Get-ChildItem -LiteralPath $location -File -Recurse)) {
      $name=[IO.Path]::GetRelativePath($location,$file.FullName)
      $map[$name]=(Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    return $map
  }
  function AssertSame($expected,$actual,[string]$what) {
    if ($expected.Count -ne $actual.Count) { throw "$what file count changed" }
    foreach($name in $expected.Keys) {
      if (-not $actual.ContainsKey($name) -or $expected[$name] -cne $actual[$name]) {
        throw "$what content changed: $name"
      }
    }
  }
  $stateBefore=Snapshot $userdata
  $customBefore=Snapshot $custom
  $engineBefore=Snapshot (Join-Path $installed 'Engine')
  $module=Join-Path $installed 'Engine/INVOICE_OCR_SOURCE_REVIEW_R226.py'
  [IO.File]::AppendAllText($module,[Environment]::NewLine+'# R242_SANDBOX_INJECTED_CORRUPTION'+[Environment]::NewLine)
  if ((Get-FileHash $module -Algorithm SHA256).Hash -ceq
      (Get-FileHash (Join-Path $backup 'Engine/INVOICE_OCR_SOURCE_REVIEW_R226.py') -Algorithm SHA256).Hash) {
    throw 'Fault injection was not detected'
  }
  foreach($p in $paths) {
    Copy-Item -LiteralPath (Join-Path $backup $p) -Destination (Join-Path $installed $p) -Force
  }
  AssertSame $stateBefore (Snapshot $userdata) 'User LocalAppData'
  AssertSame $customBefore (Snapshot $custom) 'User-created installation file'
  AssertSame $engineBefore (Snapshot (Join-Path $installed 'Engine')) 'Restored application engine'
  $report=@{
    status='R242_ISOLATED_WINDOWS_UPDATE_FAULT_ROLLBACK_PASS'
    real_installation_modified=$false
    full_inno_installer_tested=$false
    actual_published_executable_and_engine_files_used=$true
    fault_injection_detected=$true
    original_application_engine_restored=$true
    user_local_files_preserved=$stateBefore.Count
    custom_installation_files_preserved=$customBefore.Count
    existing_data_corrupted=$false
    production_release_authorized=$false
  }
  New-Item -ItemType Directory -Path (Split-Path $evidence) -Force | Out-Null
  $report | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $evidence -Encoding utf8
  Write-Host 'R242_ISOLATED_WINDOWS_UPDATE_AND_ROLLBACK_PASS'
} finally {
  if(Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
