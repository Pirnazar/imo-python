param(
    [Parameter(Mandatory)][string]$InstallDirectory,
    [Parameter(Mandatory)][string]$CecilDll,
    [Parameter(Mandatory)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Add-Type -Path (Resolve-Path -LiteralPath $CecilDll).Path

function Get-Types($Types) {
    foreach ($type in $Types) {
        $type
        Get-Types $type.NestedTypes
    }
}

function Get-ComVisible($Attributes) {
    foreach ($attribute in $Attributes) {
        if ($attribute.AttributeType.FullName -eq 'System.Runtime.InteropServices.ComVisibleAttribute') {
            return $attribute.ConstructorArguments[0].Value
        }
    }
}

$installation = (Resolve-Path -LiteralPath $InstallDirectory).Path
$destination = (New-Item -ItemType Directory -Path $OutputDirectory -Force).FullName
$files = Get-ChildItem -File -Path (Join-Path $installation 'Imo*.dll'),
    (Join-Path $installation 'ImoDesktopApp.exe'), (Join-Path $installation 'Plugs\Imo*.dll')
$readRefs = [Mono.Cecil.ModuleDefinition].GetMethod('GetTypeReferences')

$metadata = foreach ($file in ($files | Sort-Object Name)) {
    $assembly = [Mono.Cecil.AssemblyDefinition]::ReadAssembly($file.FullName)
    try {
        $module = $assembly.MainModule
        $types = @(Get-Types $module.Types)
        $publicTypes = @($types | Where-Object { $_.IsPublic -or $_.IsNestedPublic })
        $framework = $assembly.CustomAttributes | Where-Object {
            $_.AttributeType.FullName -eq 'System.Runtime.Versioning.TargetFrameworkAttribute'
        } | Select-Object -First 1
        [pscustomobject]@{
            File = $file.FullName.Substring($installation.Length + 1)
            Assembly = $assembly.Name.Name
            Version = $assembly.Name.Version.ToString()
            Framework = if ($framework) { $framework.ConstructorArguments[0].Value }
            Architecture = $module.Architecture.ToString()
            Flags = $module.Attributes.ToString()
            Sha256 = (Get-FileHash -LiteralPath $file.FullName).Hash
            References = @($module.AssemblyReferences.Name | Sort-Object)
            ComVisible = Get-ComVisible $assembly.CustomAttributes
            ComVisibleTypes = @($publicTypes | Where-Object {
                (Get-ComVisible $_.CustomAttributes) -eq $true
            } | ForEach-Object { $_.FullName })
            PublicInterfaces = @($publicTypes | Where-Object IsInterface | ForEach-Object {
                [pscustomobject]@{ Type = $_.FullName; Methods = @($_.Methods | ForEach-Object { $_.FullName }) }
            })
            IpcTypeReferences = @($readRefs.Invoke($module, @()) | Where-Object {
                $_.FullName -match 'Remoting|MarshalByRef|ServiceModel|NamedPipe|PipeStream|TcpListener|HttpListener|Socket|MemoryMapped|WindowsFormsApplicationBase'
            } | ForEach-Object { $_.FullName } | Sort-Object -Unique)
            PInvokeModules = @($module.ModuleReferences.Name | Sort-Object -Unique)
            Surface = @($types | Where-Object {
                $_.Name -match '^(SingleInstanceAppWrpper|Manager|BasePlug|Market|NetMarket|DevMessageManager|MessageManager|ContactsManager|ForChatersTask|ForMessagesTask|ReceivedDataHandler|MessagePlugEntry|ContactPlugEntry|ComplexConnector)$'
            } | ForEach-Object {
                [pscustomobject]@{
                    Type = $_.FullName
                    Base = $_.BaseType.FullName
                    Interfaces = @($_.Interfaces | ForEach-Object { $_.InterfaceType.FullName })
                    Events = @($_.Events | ForEach-Object { $_.FullName })
                    Methods = @($_.Methods | ForEach-Object {
                        [pscustomobject]@{ Public = $_.IsPublic; Signature = $_.FullName; Rva = $_.RVA }
                    })
                }
            })
        }
    }
    finally { $assembly.Dispose() }
}
ConvertTo-Json -InputObject @($metadata) -Depth 10 |
    Set-Content -LiteralPath (Join-Path $destination 'managed.json') -Encoding utf8

# Full IMO assembly-to-assembly reference graph, with selected platform/native boundaries.
$included = @($metadata.Assembly) + @('PresentationFramework', 'Microsoft.VisualBasic',
    'libtitancpp', 'System.Data.SQLite')
$edges = foreach ($row in $metadata) {
    foreach ($reference in $row.References) {
        if ($reference -in $included) { '  "{0}" -> "{1}";' -f $row.Assembly, $reference }
    }
}
@('digraph IMO {', '  rankdir=LR;', '  node [shape=box];') + @($edges) + '}' |
    Set-Content -LiteralPath (Join-Path $destination 'dependencies.dot') -Encoding utf8
