param(
    [Parameter(Mandatory)][int]$ProcessId
)
$ErrorActionPreference = 'Stop'
$app = Get-Process -Id $ProcessId
if ($app.ProcessName -ne 'ImoDesktopApp') { throw 'The PID must be ImoDesktopApp' }
$modules = @($app.Modules | Where-Object {
    $_.ModuleName -match '^(ImoDesktopApp\.exe|clr\.dll|mscoree\.dll|mscoreei\.dll|libtitancpp\.dll|proxy\.dll|libgonet\.dll|SQLite\.Interop\.dll)$'
} | Select-Object -ExpandProperty ModuleName | Sort-Object -Unique)

# The final output contains only socket counts and module basenames.
$owned = @(netstat.exe -ano | ForEach-Object {
    $parts = $_.Trim() -split '\s+'
    if ($parts.Count -eq 5 -and $parts[0] -eq 'TCP' -and $parts[4] -eq "$ProcessId") {
        [pscustomobject]@{
            Listener = $parts[2] -in @('0.0.0.0:0', '[::]:0')
            Loopback = $parts[1] -match '^(127\.|\[::1\]:)'
            Established = $parts[3] -eq 'ESTABLISHED'
        }
    }
})
$stillRunning = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
if (-not $stillRunning -or $stillRunning.StartTime -ne $app.StartTime) { throw 'PID changed during sampling' }

[pscustomobject]@{
    captured_at_utc = [DateTime]::UtcNow.ToString('o')
    pid = $ProcessId
    file_version = (Get-Item -LiteralPath $app.Path).VersionInfo.FileVersion
    native_modules = $modules
    tcp_listeners = @($owned | Where-Object Listener).Count
    tcp_loopback_listeners = @($owned | Where-Object { $_.Listener -and $_.Loopback }).Count
    tcp_established = @($owned | Where-Object Established).Count
} | ConvertTo-Json
