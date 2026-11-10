<#
Builds ImoBridge.exe into a private runtime folder next to a copy of the installed IMO
binaries. The copy leaves out the client's profile (data, data1), logs and crash dumps,
so the bridge keeps its own sign-in and never touches the desktop client's.

    .\Build.ps1                       # auto-detect %APPDATA%\imo\<version>
    .\Build.ps1 -InstallDirectory C:\path\to\imo\1.5.9.3
#>
param(
    [string]$InstallDirectory,
    [string]$RuntimeRoot = (Join-Path $env:LOCALAPPDATA 'imo-python\runtime')
)
$ErrorActionPreference = 'Stop'

if (-not $InstallDirectory) {
    $candidate = Get-ChildItem -Directory (Join-Path $env:APPDATA 'imo') -ErrorAction SilentlyContinue |
        Where-Object { Test-Path (Join-Path $_.FullName 'ImoDesktopApp.exe') } |
        Sort-Object { [version]$_.Name } | Select-Object -Last 1
    if (-not $candidate) { throw 'IMO install not found; pass -InstallDirectory' }
    $InstallDirectory = $candidate.FullName
}
$exe = Join-Path $InstallDirectory 'ImoDesktopApp.exe'
if (-not (Test-Path $exe)) { throw "ImoDesktopApp.exe not found in $InstallDirectory" }
$version = (Get-Item $exe).VersionInfo.FileVersion
$runtime = Join-Path $RuntimeRoot $version
New-Item -ItemType Directory -Force $runtime | Out-Null

# /XD: never copy the desktop client's profile. /XO keeps an existing bridge profile intact.
robocopy $InstallDirectory $runtime /E /XO /XD data data1 Logs nativeCrash /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with $LASTEXITCODE" }

$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework\v4.0.30319'
$refs = @(
    (Join-Path $framework 'WPF\PresentationFramework.dll'),
    (Join-Path $framework 'WPF\PresentationCore.dll'),
    (Join-Path $framework 'WPF\WindowsBase.dll'),
    (Join-Path $framework 'System.Xaml.dll'),
    (Join-Path $runtime 'Newtonsoft.Json.dll'),
    (Join-Path $runtime 'NLog.dll'),
    (Join-Path $runtime 'Imo.DataModel.dll'),
    (Join-Path $runtime 'Imo.DataCommon.dll'),
    (Join-Path $runtime 'Imo.DataCore.dll')
) | ForEach-Object { "/reference:$_" }

$out = Join-Path $runtime 'ImoBridge.exe'
& (Join-Path $framework 'csc.exe') /nologo /platform:x86 /target:exe /optimize+ "/out:$out" @refs (Join-Path $PSScriptRoot 'ImoBridge.cs')
if ($LASTEXITCODE -ne 0) { throw "csc exited with $LASTEXITCODE" }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'ImoBridge.exe.config') -Destination $runtime -Force
$out
