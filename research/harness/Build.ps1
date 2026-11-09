param(
    [Parameter(Mandatory)][string]$ReferenceAssemblies,
    [Parameter(Mandatory)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$compiler = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319\csc.exe'
$refs = @('mscorlib.dll', 'System.dll', 'System.Core.dll') | ForEach-Object {
    '/reference:' + (Resolve-Path -LiteralPath (Join-Path $ReferenceAssemblies $_)).Path
}
$destination = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$exe = Join-Path $destination 'Harness.exe'
$sources = @(Join-Path $PSScriptRoot 'Harness.cs'; Join-Path $PSScriptRoot 'Lifecycle.cs'; Join-Path $PSScriptRoot 'NativeProbe.cs')
& $compiler /nologo /noconfig /nostdlib+ /platform:x86 /target:exe "/out:$exe" @refs @sources
if ($LASTEXITCODE -ne 0) { throw "csc exited with $LASTEXITCODE" }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'Harness.exe.config') -Destination $destination
$exe
