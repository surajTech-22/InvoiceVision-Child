$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Join-Path ([IO.Path]::GetTempPath()) ('InvoiceVision-Gate-' + [Guid]::NewGuid().ToString('N'))
try {
    New-Item -ItemType Directory -Path "$root/scripts","$root/release","$root/build/publish","$root/installer" -Force | Out-Null
    Copy-Item (Join-Path $PSScriptRoot 'package-installers.ps1') "$root/scripts/package-installers.ps1"
    # Deliberately non-executable fixtures: rejection must precede compiler use.
    'fixture' | Set-Content "$root/build/publish/InvoiceVisionChild.exe"
    'fixture' | Set-Content "$root/installer/InvoiceVisionChild.iss"
    @{source_sha256_pass=$true;child_startup_smoke_pass=$true;self_contained_dotnet=$true;field_accuracy_certified=$false} | ConvertTo-Json | Set-Content "$root/release/BUILD_VERIFICATION.json"
    function Reject([string]$expected) {
        $caught = $false
        try { & "$root/scripts/package-installers.ps1" } catch {
            if ($_.Exception.Message -notmatch $expected) { throw "Wrong rejection: $($_.Exception.Message)" }
            $caught = $true
        }
        if (-not $caught) { throw 'Unverified installer creation was allowed' }
        if (Get-ChildItem "$root/release" -Filter '*.exe') { throw 'Installer created before acceptance' }
    }
    Reject 'acceptance evidence missing'
    'source-backed verification fixture' | Set-Content "$root/release/evidence.txt"
    $gates = @{}
    foreach ($name in @('ocr_accuracy','physical_boxes','recursive_zones','field_mapping','cpu_gpu_fallback','offline_runtime','windows_child_end_to_end','install_update_rollback','existing_data_preservation','visual_comparisons')) {
        $gates[$name]=@{passed=$true;evidence_path='evidence.txt';evidence_sha256=(Get-FileHash "$root/release/evidence.txt").Hash.ToLowerInvariant()}
    }
    $acceptance=@{schema_version=1;release_authorized=$true;build_report_sha256=(Get-FileHash "$root/release/BUILD_VERIFICATION.json").Hash.ToLowerInvariant();unresolved_failures=0;total_cases=51;passed_cases=51;gates=$gates}
    function Save { $acceptance | ConvertTo-Json -Depth 8 | Set-Content "$root/release/ACCEPTANCE_VERIFICATION.json" }
    $acceptance.release_authorized=$false;Save;Reject 'does not authorize'
    $acceptance.release_authorized=$true;$acceptance.passed_cases=50;Save;Reject 'corpus has not passed'
    $acceptance.passed_cases=51;$gates.physical_boxes.passed=$false;Save;Reject 'gate failed: physical_boxes'
    $gates.physical_boxes.passed=$true;$gates.physical_boxes.evidence_sha256='wrong';Save;Reject 'checksum mismatch'
    $gates.physical_boxes.evidence_path='../outside';Save;Reject 'Unsafe acceptance evidence path'
    Write-Host 'PASS_R146_NO_INSTALLERS_BEFORE_ACCEPTANCE_6_REJECTIONS'
} finally {
    # Only the GUID-named test fixture tree is removed; no installed data is used.
    if (Test-Path -LiteralPath $root) { Remove-Item -LiteralPath $root -Recurse -Force }
}
