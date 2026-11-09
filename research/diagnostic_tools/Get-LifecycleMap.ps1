param(
    [Parameter(Mandatory)][string]$InstallDirectory,
    [Parameter(Mandatory)][string]$CecilDll,
    [Parameter(Mandatory)][string]$OutputFile
)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Resolve-Path -LiteralPath $CecilDll).Path

$files = 'ImoDesktopApp.exe', 'Imo.DataCore.dll', 'Imo.ChannelNetwork.dll', 'Imo.DataCommon.dll',
    'Imo.DataModel.dll', 'Imo.Dispatcher.dll', 'Imo.DB.dll', 'Plugs\Imo.Message.dll', 'Plugs\Imo.Contact.dll'
$typeNames = 'EntryPoint|App|MainEntry|MainWindow|MainWindowViewModel|SingleInstanceAppWrpper|AppHelper|' +
    'SignInWithScanPageView|SignInWithScanPageViewModel|Market|NetMarket|QRcodeTask|LoginTask|LoginService|' +
    'NetManager|Session|AccountMessageManager|MessageManager|ForMessagesTask|ForChatersTask|' +
    'Network|Dispatcher|ConnectionData|ComplexConnector|ConnectData|ReceivedDataHandler|Manager|BasePlug|' +
    'ApplicationStorage|UserStorage|PersistentStorage|IMO|User|UserSettings|ApplicationSettings|ApplicationProperties|' +
    'MessageModel|SignOnData|ResRequestQRcode|ResBaseModel|ResResult|QRCodeStatus|EnumStartupMode|ActionTypes|' +
    'NetActionTypes|DataType|MessageOrigin|DBActionTypes|TaskResult|ActionParamer|MessagePlugEntry|ContactPlugEntry|ChatsListViewModel'

function Get-TypeTree($items) {
    foreach ($type in $items) {
        if ($type.Name -match ('^(?:' + $typeNames + ')$')) { $type }
        Get-TypeTree $type.NestedTypes
    }
}

$records = foreach ($file in $files) {
    $path = Join-Path $InstallDirectory $file
    $assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($path)
    try {
        $module = $assembly.MainModule
        $target = $assembly.CustomAttributes | Where-Object {
            $_.AttributeType.FullName -eq 'System.Runtime.Versioning.TargetFrameworkAttribute'
        } | Select-Object -First 1
        [pscustomobject]@{
            file = $file
            sha256 = (Get-FileHash -LiteralPath $path).Hash
            version = $assembly.Name.Version.ToString()
            framework = if ($target) { $target.ConstructorArguments[0].Value }
            architecture = $module.Architecture.ToString()
            flags = $module.Attributes.ToString()
            dependencies = @($module.AssemblyReferences.Name | Sort-Object)
            types = @(Get-TypeTree $module.Types | ForEach-Object {
                $type = $_
                [pscustomobject]@{
                    name = $type.FullName
                    base = $type.BaseType.FullName
                    events = @($type.Events | ForEach-Object { $_.FullName })
                    enum_values = if ($type.IsEnum) {
                        [ordered]@{} + (& {
                            $values = [ordered]@{}
                            foreach ($field in $type.Fields | Where-Object HasConstant) {
                                $values[$field.Name] = $field.Constant
                            }
                            $values
                        })
                    }
                    methods = @($type.Methods | Where-Object { $_.Name -notmatch '^<' } | ForEach-Object {
                        [pscustomobject]@{
                            signature = $_.FullName
                            access = ($_.Attributes -band [Mono.Cecil.MethodAttributes]::MemberAccessMask).ToString()
                            static = $_.IsStatic
                        }
                    })
                }
            })
        }
    }
    finally {
        $assembly.Dispose()
    }
}
ConvertTo-Json -InputObject @($records) -Depth 10 | Set-Content -LiteralPath $OutputFile -Encoding utf8
