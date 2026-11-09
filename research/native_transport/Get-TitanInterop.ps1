param(
    [Parameter(Mandatory)][string]$InstallDirectory,
    [Parameter(Mandatory)][string]$CecilDll
)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Resolve-Path -LiteralPath $CecilDll).Path
$readMemberRefs = [Mono.Cecil.ModuleDefinition].GetMethod('GetMemberReferences')

foreach ($name in 'Imo.DataCore.dll', 'Imo.ChannelNetwork.dll') {
    $assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $InstallDirectory $name))
    try {
        "assembly $name"
        $readMemberRefs.Invoke($assembly.MainModule, @()) | Where-Object {
            $_.DeclaringType.Namespace -eq 'cppcli_titancpp' -and
            $_.DeclaringType.Name -in 'Titancpp', 'Nerv', 'NervTask', 'MediaProtoX', 'Antiban', 'AntibanHttpClient'
        } | ForEach-Object { "  ref $_" } | Sort-Object -Unique
    }
    finally { $assembly.Dispose() }
}

$assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly((Join-Path $InstallDirectory 'libtitancpp.dll'))
try {
    $module = $assembly.MainModule
    "assembly libtitancpp.dll architecture=$($module.Architecture) flags=$($module.Attributes)"
    $publicNames = 'Titancpp', 'MediaProtoX', 'Antiban', 'AntibanHttpClient', 'Nerv', 'NervTask',
        'JSONDelegate', 'MediaAuthInfoProvider', 'MediaEventListener', 'MediaStateListener'
    foreach ($type in $module.Types | Where-Object { $_.Namespace -eq 'cppcli_titancpp' -and $_.Name -in $publicNames }) {
        "type $($type.FullName)"
        $type.Methods | Where-Object { $_.IsPublic -and -not $_.IsConstructor } |
            ForEach-Object { "  api $($_.FullName)" }
    }

    $nativeNames = 'bp_titancpp.Titancpp.init', 'titancpp.TitancppImpl.initMediaProtoX',
        'titancpp.TitancppImpl.initNerv', 'titancpp.MediaProtoXImpl.init',
        'titancpp.MediaProtoXImpl.sendJSONWithParams', 'titancpp.MediaProtoXImpl.registerPush',
        'titancpp.MediaProtoXImpl.startAndKeepConnected', 'titancpp.MediaProtoXImpl.getState',
        'bp_titancpp.Antiban.createHttpClient', 'bp_titancpp.AntibanHttpClientImpl.{ctor}',
        'bp_titancpp.AntibanHttpClientImpl.send', 'bp_proxy.Proxy.createHttpClient', 'bp_proxy.Proxy.init',
        'bigo_protox_djinni.YYProtoX.globalInitialize'
    $module.Types[0].Methods | Where-Object { $_.Name -match '^titancpp\.MediaProtoXImpl\.' -and $_.Name -notmatch 'lambda' } |
        ForEach-Object { "  methoddef 0x{0:x8} rva=0x{1:x} {2}" -f $_.MetadataToken.ToUInt32(), $_.RVA, $_.Name }

    $proxyMethods = @(
        $module.Types | Where-Object {
            $_.Namespace -eq 'cppcli_titancpp' -and $_.Name -in
                'TitancppCppProxy', 'MediaProtoXCppProxy', 'AntibanHttpClientCppProxy', 'NervCppProxy'
        } | ForEach-Object { $_.Methods } | Where-Object {
            $_.Name -match '^(InitMediaProtoX|InitNerv|SendJSONWithParams|CancelJSONRequest|RegisterPush|StartAndKeepConnected|GetState|Send|NewTask)$'
        }
    )
    $methods = @($module.Types[0].Methods | Where-Object { $_.Name -in $nativeNames }) + $proxyMethods
    foreach ($method in $methods) {
        "method 0x{0:x} {1} {2}::{3}" -f $method.RVA, $method.ImplAttributes,
            $method.DeclaringType.FullName, $method.Name
        if (-not $method.HasBody) { continue }
        foreach ($insn in $method.Body.Instructions) {
            if ($insn.OpCode.Name -eq 'calli') {
                "  il_{0:x4} calli {1}" -f $insn.Offset, $insn.Operand
            }
            elseif ($insn.OpCode.Name -in 'call', 'callvirt', 'newobj' -and
                    $insn.Operand -is [Mono.Cecil.MethodReference] -and
                    $insn.Operand.Name -notmatch '^std\.(?!make_shared)|___Cxx|_Decref') {
                "  il_{0:x4} {1} {2}" -f $insn.Offset, $insn.OpCode.Name, $insn.Operand.Name
            }
        }
    }
}
finally { $assembly.Dispose() }
