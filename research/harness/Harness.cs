using System;
using System.Collections.Generic;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Runtime.InteropServices;
using System.Text;

[assembly: System.Runtime.Versioning.TargetFramework(".NETFramework,Version=v4.6.1")]

internal static partial class Harness
{
    private const BindingFlags Declared = BindingFlags.Public | BindingFlags.NonPublic |
        BindingFlags.Instance | BindingFlags.Static | BindingFlags.DeclaredOnly;

    private static readonly string[] Targets = {
        "ImoDesktopApp.exe", "Imo.Dispatcher.dll", "Imo.DataModel.dll", "Imo.DataCommon.dll",
        "Imo.ChannelNetwork.dll", "Imo.DataCore.dll", "Imo.DB.dll",
        @"Plugs\Imo.Contact.dll", @"Plugs\Imo.Message.dll"
    };

    private static string installDirectory;

    private static int Main(string[] args)
    {
        if (args.Length < 1 || args.Length > 2 || (args.Length == 2 && args[1] != "--activation" && args[1] != "--cold-core" && args[1] != "--lifecycle" && args[1] != "--native-probe"))
        {
            Console.Error.WriteLine("Usage: Harness.exe <IMO install directory> [--activation|--cold-core|--lifecycle|--native-probe]");
            return 2;
        }

        try
        {
            Check(IntPtr.Size == 4, "x86");
            Console.WriteLine("process=x86 clr={0} pid={1}", Environment.Version,
                System.Diagnostics.Process.GetCurrentProcess().Id);
            installDirectory = Path.GetFullPath(args[0]);
            AppDomain.CurrentDomain.AssemblyResolve += Resolve;

            if (args.Length == 2 && args[1] == "--activation")
                ProbeActivation();
            else if (args.Length == 2 && args[1] == "--lifecycle")
                ProbeLifecycle();
            else if (args.Length == 2 && args[1] == "--native-probe")
                ProbeNativeHandles();
            else if (args.Length == 2)
                ProbeColdCore();
            else
                ProbeAssemblies();
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.GetBaseException());
            return 1;
        }
    }

    private static Assembly Resolve(object sender, ResolveEventArgs args)
    {
        string name = new AssemblyName(args.Name).Name + ".dll";
        string path = Path.Combine(installDirectory, name);
        return File.Exists(path) ? Assembly.LoadFrom(path) : null;
    }

    private static void ProbeAssemblies()
    {
        var loaded = new Dictionary<string, Assembly>();
        foreach (string file in Targets)
        {
            var assembly = Assembly.LoadFrom(Path.Combine(installDirectory, file));
            loaded.Add(assembly.GetName().Name, assembly);
            Console.WriteLine("loaded {0} version={1}", file, assembly.GetName().Version);
        }

        Assembly models = loaded["Imo.DataModel"];
        Type origin = Find(models, "Imo.DataModel.Enums.MessageOrigin");
        Type text = Find(models, "Imo.DataModel.Models.Messages.TextMessage");
        object message = Activator.CreateInstance(text, Enum.Parse(origin, "RECV"));
        Check(text.GetProperty("MessageContentType").GetValue(message).ToString() == "Text", "TextMessage type");
        Check(text.GetProperty("Origin").GetValue(message).ToString() == "RECV", "TextMessage origin");
        foreach (string name in new[] { "MessageModel", "ChaterModel", "UserModel" })
            Check(Activator.CreateInstance(Find(models, "Imo.DataModel.Models." + name)) != null, name);
        Console.WriteLine("models: synthetic TextMessage, MessageModel, ChaterModel, UserModel");

        Type market = Find(loaded["Imo.DataCore"], "Imo.DataCore.Market");
        Type network = Find(loaded["Imo.ChannelNetwork"], "Imo.ChannelNetwork.NetMarket");
        PrintMethods(market, "Initialize", "InitConnect", "RunTask", "get_Instance",
            "get_SSID", "add_ReceivedData", "add_ReceivedDevData");
        PrintMethods(network, "InitConnect", "Reconnect", "add_ReceiveMessageHandler");
        PrintMethods(Find(loaded["Imo.DataCore"], "Imo.DataCore.Message.DevMessageManager"),
            "GetReceivedMessages", "GetSentMessages", "GetProcessedMessages");
        PrintMethods(Find(loaded["Imo.DataCore"], "Imo.DataCore.Message.MessageManager"),
            "HandleRecvIm", "HandleRecvUnreadMsgs");
        ProbeLocalEvent(Find(loaded["Imo.Dispatcher"], "Imo.Dispatcher.Manager"));
    }

    private static Type Find(Assembly assembly, string name)
    {
        return assembly.GetType(name, true);
    }

    private static void PrintMethods(Type type, params string[] names)
    {
        foreach (string name in names)
        {
            var methods = type.GetMethods(Declared).Where(method => method.Name == name).ToArray();
            Check(methods.Length > 0, type.FullName + "." + name);
            foreach (var method in methods)
            {
                string il;
                try
                {
                    var body = method.GetMethodBody();
                    il = body == null ? "none" : body.GetILAsByteArray().Length.ToString();
                }
                catch (BadImageFormatException)
                {
                    il = "invalid-on-disk";
                }
                Console.WriteLine("method {0} {1}::{2} IL={3}", method.IsPublic ? "public" : "nonpublic",
                    type.FullName, method, il);
            }
        }
    }

    private sealed class Counter
    {
        public int Value;
        public void Increment() { Value++; }
    }

    private static void ProbeLocalEvent(Type type)
    {
        // Manager's ordinary constructor just creates its empty plug list. Initialize and
        // InitConnect are deliberately omitted. The only raised action is synthetic.
        object singleton = type.GetProperty("Instance").GetValue(null);
        object other = Activator.CreateInstance(type, true);
        Check(ReferenceEquals(singleton, type.GetProperty("Instance").GetValue(null)), "local singleton");
        var received = type.GetEvent("ReceivedData");
        var count = new Counter();
        var parameters = received.EventHandlerType.GetMethod("Invoke").GetParameters()
            .Select(parameter => Expression.Parameter(parameter.ParameterType)).ToArray();
        var body = Expression.Call(Expression.Constant(count), typeof(Counter).GetMethod("Increment"));
        var handler = Expression.Lambda(received.EventHandlerType, body, parameters).Compile();
        received.AddEventHandler(singleton, handler);
        try
        {
            var forward = type.GetMethod("Instance_ReceivedData", Declared);
            var arguments = new[] { Enum.Parse(parameters[0].Type, "DevToolsMessage"),
                Activator.CreateInstance(parameters[1].Type) };
            forward.Invoke(other, arguments);
            Check(count.Value == 0, "separate dispatcher instance must not deliver callback");
            forward.Invoke(singleton, arguments);
            Check(count.Value == 1, "local dispatcher must deliver callback");
        }
        finally
        {
            received.RemoveEventHandler(singleton, handler);
        }
        Console.WriteLine("dispatcher callback: other instance=0, local synthetic dispatch=1");
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(IntPtr token, int informationClass,
        byte[] value, int length, out int returnedLength);

    private static void RequireIsolatedToken()
    {
        // Require a capability-free AppContainer before executing the protected module.
        using (var identity = System.Security.Principal.WindowsIdentity.GetCurrent())
        {
            int returnedLength;
            var value = new byte[32];
            Check(GetTokenInformation(identity.Token, 29, value, value.Length, out returnedLength)
                && BitConverter.ToInt32(value, 0) == 1, "cold core requires AppContainer");
            Check(GetTokenInformation(identity.Token, 30, value, value.Length, out returnedLength)
                && BitConverter.ToInt32(value, 0) == 0, "cold core requires zero capabilities");
        }
    }

    private static void ProbeColdCore()
    {
        RequireIsolatedToken();
        var assembly = Assembly.LoadFrom(Path.Combine(installDirectory, "Imo.DataCore.dll"));
        var type = Find(assembly, "Imo.DataCore.Market");
        object market = type.GetProperty("Instance").GetValue(null);
        Console.WriteLine("cold_market_instance={0}", market == null ? "null" : "non-null");
        TraceCalls(type, "get_Instance", "Initialize", "InitializeTaskList", "RunTask",
            "InitConnect", "ReceiveMessageHandler", "OnReceivedData", "DevMessage");
        TraceCalls(type.GetNestedType("<>c", BindingFlags.NonPublic), "<InitConnect>b__15_0");
        TraceCalls(Find(assembly, "Imo.DataCore.Tasks.ForMessagesTask"), "MessageSend",
            "SendNormalMessage", "SetOwner", "MessageReceived", "HandleMessageReceive");
        TraceCalls(Find(assembly, "Imo.DataCore.Message.MessageManager"), "HandleMessage", "HandleRecvIm");
        TraceCalls(Find(assembly, "Imo.DataCore.Tasks.ForChatersTask"), "GetAllBuddies",
            "SyncBuddyList", "GetChaters", "OpenChat");
        TraceCalls(Find(assembly, "Imo.DataCore.Message.ContactsManager"), "HandleMessage");

        var network = Assembly.LoadFrom(Path.Combine(installDirectory, "Imo.ChannelNetwork.dll"));
        RuntimeHelpers.RunModuleConstructor(network.ManifestModule.ModuleHandle);
        TraceCalls(Find(network, "Imo.ChannelNetwork.NetMarket"), "InitConnect", "Reconnect",
            "RegisterEvent", "Instance_ReceiveMessageHandler", "Work");
        TraceCalls(Find(network, "Imo.ChannelNetwork.Connection.Network"), "Reconnect", "ReconnectInner",
            "RunConnectThread", "HandleMessageReceived");
        TraceCalls(Find(network, "Imo.ChannelNetwork.Connection.Dispatcher"), "OnReceiveMessage");

        var executable = Assembly.LoadFrom(Path.Combine(installDirectory, Targets[0]));
        RuntimeHelpers.RunModuleConstructor(executable.ManifestModule.ModuleHandle);
        TraceCalls(Find(executable, "Imo.Main.EntryPoint"), "Main");
        TraceCalls(Find(executable, "Imo.Main.SingleInstanceAppWrpper"), ".ctor", "OnStartup", "OnStartupNextInstance");
        TraceCalls(Find(executable, "Imo.Main.Helper.AppHelper"), "Activate", "ActivateMainWindow");
        var diagnostics = Find(assembly, "Imo.DataCore.Message.DevMessageManager");
        object manager = diagnostics.GetProperty("Instance", Declared).GetValue(null);
        foreach (string name in new[] { "GetReceivedMessages", "GetSentMessages", "GetProcessedMessages" })
        {
            var queue = (System.Collections.IEnumerable)diagnostics.GetMethod(name).Invoke(manager, null);
            Console.WriteLine("cold_{0}_empty={1}", name, !queue.Cast<object>().Any());
        }
    }

    private static void TraceCalls(Type type, params string[] names)
    {
        var opcodes = typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(field => field.FieldType == typeof(OpCode))
            .Select(field => (OpCode)field.GetValue(null)).ToDictionary(code => code.Value);

        foreach (string name in names)
        {
            IEnumerable<MethodBase> methods = name == ".ctor"
                ? type.GetConstructors(Declared).Cast<MethodBase>()
                : type.GetMethods(Declared).Where(method => method.Name == name).Cast<MethodBase>();
            var selected = methods.ToArray();
            Check(selected.Length > 0, type.FullName + "." + name);
            foreach (var method in selected)
            {
                var il = method.GetMethodBody().GetILAsByteArray();
                Console.WriteLine("calls {0}::{1} IL={2}", type.FullName, method.Name, il.Length);
                for (int offset = 0; offset < il.Length;)
                {
                    short value = il[offset++];
                    if (value == 0xfe)
                        value = unchecked((short)(0xfe00 | il[offset++]));
                    var opcode = opcodes[value];
                    if (opcode.OperandType == OperandType.InlineMethod)
                    {
                        var target = method.Module.ResolveMethod(BitConverter.ToInt32(il, offset));
                        Console.WriteLine("  {0} {1}::{2}", opcode.Name, target.DeclaringType, target.Name);
                    }
                    else if (opcode.OperandType == OperandType.InlineField &&
                        (name == "get_Instance" || name == "Instance_ReceiveMessageHandler" || name == "OnReceivedData"))
                    {
                        var field = method.Module.ResolveField(BitConverter.ToInt32(il, offset));
                        Console.WriteLine("  {0} {1}::{2}", opcode.Name, field.DeclaringType, field.Name);
                    }
                    offset += OperandSize(opcode.OperandType, il, offset);
                }
            }
        }
    }

    private static int OperandSize(OperandType type, byte[] il, int offset)
    {
        switch (type)
        {
            case OperandType.InlineNone:
                return 0;
            case OperandType.ShortInlineBrTarget:
            case OperandType.ShortInlineI:
            case OperandType.ShortInlineVar:
                return 1;
            case OperandType.InlineVar:
                return 2;
            case OperandType.InlineI8:
            case OperandType.InlineR:
                return 8;
            case OperandType.InlineSwitch:
                return checked(4 + 4 * BitConverter.ToInt32(il, offset));
            default:
                return 4;
        }
    }

    private static void ProbeActivation()
    {
        // Match WindowsFormsApplicationBase.GetApplicationInstanceID on .NET Framework.
        // Read its activation URL mapping without loading IMO for execution or calling Remoting.
        var executable = Assembly.ReflectionOnlyLoadFrom(Path.Combine(installDirectory, Targets[0]));
        var version = executable.GetName().Version;
        string id = Marshal.GetTypeLibGuidForAssembly(executable).ToString() + version.Major + "." + version.Minor;
        using (var mapping = MemoryMappedFile.OpenExisting(id + "Map", MemoryMappedFileRights.Read))
        using (var view = mapping.CreateViewAccessor(0, 0, MemoryMappedFileAccess.Read))
        {
            const string prefix = "tcp://127.0.0.1:";
            string suffix = "/" + id + ".rem";
            var url = new StringBuilder();
            for (long offset = 0; offset + 2 <= view.Capacity && url.Length <= prefix.Length + 5 + suffix.Length; offset += 2)
            {
                char character = (char)view.ReadUInt16(offset);
                if (character == '\0')
                    break;
                url.Append(character);
            }
            string address = url.ToString();
            Check(address.StartsWith(prefix, StringComparison.Ordinal) &&
                address.EndsWith(suffix, StringComparison.Ordinal) &&
                address.Length > prefix.Length + suffix.Length, "framework activation mapping format");
            string port = address.Substring(prefix.Length, address.Length - prefix.Length - suffix.Length);
            ushort portNumber;
            Check(ushort.TryParse(port, System.Globalization.NumberStyles.None,
                System.Globalization.CultureInfo.InvariantCulture, out portNumber) && portNumber > 0,
                "activation port");
            Console.WriteLine("activation_port={0}", portNumber);
        }
    }

    private static void Check(bool condition, string name)
    {
        if (!condition)
            throw new InvalidOperationException("Probe failed: " + name);
    }
}
