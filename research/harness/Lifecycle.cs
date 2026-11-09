using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Linq.Expressions;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Runtime.Serialization;
using System.Text.RegularExpressions;

internal static partial class Harness
{
    // Labels from public metadata and selected static field names. Everything else is redacted.
    private static readonly HashSet<string> LifecycleLabels = new HashSet<string>(StringComparer.Ordinal) {
        "qr_link", "code_ttl", "result", "rcode", "status", "qr_code", "qrcode", "qr_login",
        "qr_code_scanned", "qrcode_scanned", "qr_code_login_completed", "qr_code_login_cancelled",
        "qr_code_login_canceled", "request_qr_code", "invalidate_qr_code", "signed_on", "sign_off",
        "signed_off", "signon", "signoff", "uid", "cookie_uid", "cookie", "account", "user", "name",
        "alias", "icon", "profile", "data", "action", "type", "name", "imdata", "recv_im",
        "reflect", "recv_unread_msgs", "signal", "connected", "disconnected", "reason", "login_type",
        "im", "ttl", "link", "err", "error", "ssid", "token", "qr_token", "qr_id", "request_id",
        "confirm", "cancel", "scan", "success", "expired", "login_mode", "scan_version", "State"
    };

    private static readonly IDictionary<short, OpCode> LifecycleOpcodes =
        typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Where(field => field.FieldType == typeof(OpCode))
            .Select(field => (OpCode)field.GetValue(null)).ToDictionary(code => code.Value);

    private static void ProbeLifecycle()
    {
        RequireIsolatedToken();
        var app = LoadLifecycleAssembly(Targets[0]);
        var core = LoadLifecycleAssembly("Imo.DataCore.dll");
        var network = LoadLifecycleAssembly("Imo.ChannelNetwork.dll");
        var common = LoadLifecycleAssembly("Imo.DataCommon.dll");
        var model = LoadLifecycleAssembly("Imo.DataModel.dll");
        var bridge = LoadLifecycleAssembly("Imo.Dispatcher.dll");
        var message = LoadLifecycleAssembly(@"Plugs\Imo.Message.dll");
        TraceLifecycle(app, "Imo.Main.EntryPoint", "Main|WaitForRestartParentExit|TryGetRestartParentPid");
        TraceLifecycle(app, "Imo.Main.SingleInstanceAppWrpper", ".*");
        TraceLifecycle(app, "Imo.Main.App", "OnStartup");
        TraceLifecycle(app, "Imo.Main.MainWindow", @"\.ctor|OnShutdown|PerformExit|MainWindow_Closing|MainWindow_Activated|HandleActivated.*|MinimizeToTray");
        TraceLifecycle(app, "Imo.Main.MainEntry", "OnAction|InitializeView|Dispose");
        TraceLifecycle(app, "Imo.Main.Helper.AppHelper", "StartInit|StartTasks|AppExit|ReStart|InitEvents|HandleSSIDResetted|SystemEvents_.*");
        TraceLifecycle(app, "Imo.Main.ViewModels.MainWindowViewModel", @"\.ctor|Instance_PropertyChanged|ShowLoginPage|HandleSignedOn|HandleSignOff|set_CurrentContent|NavigateTo.*");
        TraceLifecycle(app, "Imo.Main.ViewModels.NewSignIn.SignInWithScanPageViewModel", @".*QRcode.*|\.ctor|Dispose|Instance_ReceivedData|User_PropertyChanged|UpdateNetStatus|Reset|get_Ttl|get_TryAgainCommand|set_ShowBeginScanCode", true);
        TraceLifecycle(app, "Imo.Main.Views.NewSignIn.SignInWithScanPageView", @"\.ctor|ConGuide_IsVisibleChanged");

        TraceLifecycle(core, "Imo.DataCore.Market", @"\.ctor|Initialize|InitializeTaskList|RunTask|InitConnect|ReceiveMessageHandler|OnSignalConnectChanged|OnReceivedData|Exit|SSIDResetted");
        TraceLifecycle(core, "Imo.DataCore.Tasks.LoginTask", "StartTask|SignOff|CookieLogin|GetMyProfile|ReconnectSignal|DisconnectSignal", true);
        TraceLifecycle(core, "Imo.DataCore.Tasks.QRcodeTask", ".*");
        TraceLifecycle(core, "Imo.DataCore.Message.AccountMessageManager", ".*");
        TraceLifecycle(core, "Imo.DataCore.Message.MessageManager", "HandleMessage|HandleRecvIm|HandleRecvUnreadMsgs|HandleReflect");
        TraceLifecycle(core, "Imo.DataCore.Tasks.ForMessagesTask", "MessageReceived|HandleMessageReceive|HandleUnreadMessageCache|RegisterTaskType|StartTask");
        TraceLifecycle(core, "Imo.DataCore.Tasks.ForChatersTask", "GetChaters|GetAccountData|RegisterTaskType");

        TraceLifecycle(network, "Imo.ChannelNetwork.NetMarket", @"\.ctor|\.cctor|Init|RegisterEvent|InitNetServices|InitConnect|Work|Reconnect|DisConnect|Instance_Connected|Instance_Disconnected|Instance_ReceiveMessageHandler");
        TraceLifecycle(network, "Imo.ChannelNetwork.Services.LoginService", "DoRequest|RequestQRcode|InvalidateQRcode|CookieLogin|GetMyProfile", true);
        TraceLifecycle(network, "Imo.ChannelNetwork.Managers.Session", ".*");
        TraceLifecycle(network, "Imo.ChannelNetwork.Connection.Network", @"\.ctor|Reconnect|ReconnectInner|RunConnectThread|HandleConnected|HandleDisconnected|Disconnect|DisconnectInner|HandleMessageReceived|ConnectedChannel_MessageReceived|NetworkChange_NetworkAvailabilityChanged|CheckConnectionInner|ScheduleReconnect.*");
        TraceLifecycle(network, "Imo.ChannelNetwork.Connection.Dispatcher", "ProcessServerMessage|ProcessIncommingMessages|OnReceiveMessage|EnqueueIncommingMessage|Reset");
        TraceLifecycle(network, "Imo.ChannelNetwork.Connection.ConnectionData", "CreateFromApplicationSettings|CreatePatchFromApplicationSettings");
        TraceLifecycle(network, "Imo.ChannelNetwork.Managers.NetManager", "Send");

        TraceLifecycle(common, "Imo.DataCommon.ApplicationSettings", @"\.ctor|InitFromStorage|UpdateQRCodeScannedInfo|set_IsCookieSignedOn|ClearCookieData|EnsureCookieGenerated");
        TraceLifecycle(common, "Imo.DataCommon.IMO", @"\.ctor|_user_PropertyChanged");
        TraceLifecycle(common, "Imo.DataCommon.Storage.ApplicationStorage", @"\.ctor|TryLoadData.*|GetDataDir");
        TraceLifecycle(common, "Imo.DataCommon.Storage.UserStorage", "Init|ClearUser|Dispose");
        TraceLifecycle(model, "Imo.DataModel.Models.User", @"\.ctor|UpdateFromSignedOnData|InitFromStorage|InitFromJObject|SetCurrentState|Clear");
        TraceLifecycle(bridge, "Imo.Dispatcher.Manager", "Initialize|LoadPlugModule|InitConnect|Instance_ReceivedData|Dispose");
        TraceLifecycle(bridge, "Imo.Dispatcher.Base.BasePlug", "StartAction");
        TraceLifecycle(message, "Imo.Message.MessagePlugEntry", "OnAction");
        TraceLifecycle(message, "Imo.Message.ViewModels.ChatsListViewModel", "HandleSignedOn|InitNetData|HandleResetConnected|HandleDisconnectedd|HandleOnlineMessage|HandleGetChatersLocal|HandleGetChatersNet");

        ProbeSyntheticQrResponse(app, model);
        ProbeSyntheticReceive(core, network, model);
    }

    private static Assembly LoadLifecycleAssembly(string file)
    {
        var assembly = Assembly.LoadFrom(Path.Combine(installDirectory, file));
        RuntimeHelpers.RunModuleConstructor(assembly.ManifestModule.ModuleHandle);
        Console.WriteLine("module {0}", file);
        return assembly;
    }

    private static void TraceLifecycle(Assembly assembly, string typeName, string names, bool allNested = false)
    {
        Type type = Find(assembly, typeName);
        var selector = new Regex("^(?:" + names + ")$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
        var methods = LifecycleMethods(type).Where(method => selector.IsMatch(method.Name)).ToArray();
        Check(methods.Length > 0, typeName + " lifecycle selection");
        foreach (var method in methods)
            PrintLifecycleIL(method);

        var parentNames = new HashSet<string>(methods.Select(method => method.Name), StringComparer.Ordinal);
        foreach (MethodBase generated in LifecycleMethods(type).Except(methods))
        {
            if (parentNames.Any(name => generated.Name.StartsWith("<" + name + ">", StringComparison.Ordinal)))
                PrintLifecycleIL(generated);
        }
        foreach (Type nested in NestedTypes(type))
        {
            foreach (MethodBase method in LifecycleMethods(nested))
            {
                if (method.Name == ".ctor" || method.Name == ".cctor")
                    continue;
                if (allNested || parentNames.Any(name => method.Name.StartsWith("<" + name + ">", StringComparison.Ordinal)
                    || nested.Name.StartsWith("<" + name + ">", StringComparison.Ordinal)))
                    PrintLifecycleIL(method);
            }
        }
    }

    private static IEnumerable<MethodBase> LifecycleMethods(Type type)
    {
        return type.GetMethods(Declared).Cast<MethodBase>().Concat(type.GetConstructors(Declared));
    }

    private static IEnumerable<Type> NestedTypes(Type type)
    {
        foreach (Type nested in type.GetNestedTypes(BindingFlags.Public | BindingFlags.NonPublic))
        {
            yield return nested;
            foreach (Type child in NestedTypes(nested))
                yield return child;
        }
    }

    private static void PrintLifecycleIL(MethodBase method)
    {
        var body = method.GetMethodBody();
        if (body == null)
            return;
        var il = body.GetILAsByteArray();
        Console.WriteLine("\nmethod {0}::{1} {2}", method.DeclaringType.FullName, method.Name, method);
        for (int offset = 0; offset < il.Length;)
        {
            int instruction = offset;
            short value = il[offset++];
            if (value == 0xfe)
                value = unchecked((short)(0xfe00 | il[offset++]));
            var opcode = LifecycleOpcodes[value];
            int size = OperandSize(opcode.OperandType, il, offset);
            string operand = LifecycleOperand(method, opcode.OperandType, il, offset, size);
            Console.WriteLine("  {0:x4} {1} {2}", instruction, opcode.Name, operand);
            offset += size;
        }
    }

    private static string LifecycleOperand(MethodBase method, OperandType type, byte[] il, int offset, int size)
    {
        int next = offset + size;
        if (type == OperandType.InlineNone)
            return "";
        if (type == OperandType.ShortInlineBrTarget)
            return (next + (sbyte)il[offset]).ToString("x4");
        if (type == OperandType.ShortInlineI)
            return ((sbyte)il[offset]).ToString(CultureInfo.InvariantCulture);
        if (type == OperandType.ShortInlineVar)
            return il[offset].ToString(CultureInfo.InvariantCulture);
        if (type == OperandType.InlineVar)
            return BitConverter.ToUInt16(il, offset).ToString(CultureInfo.InvariantCulture);
        if (type == OperandType.InlineSwitch)
        {
            int count = BitConverter.ToInt32(il, offset);
            return string.Join(",", Enumerable.Range(0, count)
                .Select(i => (next + BitConverter.ToInt32(il, offset + 4 + 4 * i)).ToString("x4")));
        }
        if (size != 4 || type == OperandType.ShortInlineR)
            return "";
        int token = BitConverter.ToInt32(il, offset);
        if (type == OperandType.InlineBrTarget)
            return (next + token).ToString("x4");
        if (type == OperandType.InlineI)
            return token.ToString(CultureInfo.InvariantCulture);
        if (type == OperandType.InlineString)
        {
            string text = method.Module.ResolveString(token);
            if (LifecycleLabels.Contains(text))
                return text;
            bool isAccountRoute = method.Name == "MoveNext"
                && method.DeclaringType.FullName.EndsWith("AccountMessageManager+<HandleMessage>d__7", StringComparison.Ordinal)
                && Regex.IsMatch(text, @"^(?:account|cookie|sign|log|qr|kick|im|phone|auth|delete|sync|session|force)[a-z_]{2,36}$")
                && next + 5 <= il.Length && il[next] == 0x28
                && method.Module.ResolveMethod(BitConverter.ToInt32(il, next + 1)).Name == "op_Equality";
            return isAccountRoute ? text : "<redacted>";
        }
        if (type == OperandType.InlineField || type == OperandType.InlineMethod
            || type == OperandType.InlineTok || type == OperandType.InlineType)
        {
            try
            {
                var declaringArgs = method.DeclaringType.GetGenericArguments();
                var methodArgs = method.IsGenericMethod ? method.GetGenericArguments() : Type.EmptyTypes;
                var member = method.Module.ResolveMember(token, declaringArgs, methodArgs);
                return member.DeclaringType == null ? member.ToString() : member.DeclaringType.FullName + "::" + member;
            }
            catch (Exception error)
            {
                if (!(error is ArgumentException || error is TypeLoadException || error is FileNotFoundException))
                    throw;
                return "<unresolved:" + error.GetType().Name + ">";
            }
        }
        return "";
    }

    private static void ProbeSyntheticQrResponse(Assembly app, Assembly model)
    {
        var response = Find(model, "Imo.DataModel.Models.ResponseModel.ResRequestQRcode");
        var json = Assembly.LoadFrom(Path.Combine(installDirectory, "Newtonsoft.Json.dll"));
        var convert = Find(json, "Newtonsoft.Json.JsonConvert");
        var deserialize = convert.GetMethod("DeserializeObject", new[] { typeof(string), typeof(Type) });
        const string fixture = "{\"result\":{\"qr_link\":\"fixture-only\",\"code_ttl\":45}}";
        object value = deserialize.Invoke(null, new object[] { fixture, response });
        object result = response.GetProperty("Result").GetValue(value);
        Check((string)result.GetType().GetProperty("QrLink").GetValue(result) == "fixture-only", "QR response link mapping");
        Check((int)result.GetType().GetProperty("CodeTtl").GetValue(result) == 45, "QR response TTL mapping");
        Console.WriteLine("synthetic_qr_response_mapping=pass");

        // Pure TTL getter on a throwaway object. No view or login manager is initialized.
        var viewModel = Find(app, "Imo.Main.ViewModels.NewSignIn.SignInWithScanPageViewModel");
        object vm = FormatterServices.GetUninitializedObject(viewModel);
        var ttl = viewModel.GetProperty("Ttl", Declared);
        Check((double)ttl.GetValue(vm) == 60, "default QR TTL");
        viewModel.GetField("codeTtl", Declared).SetValue(vm, 45);
        Check((double)ttl.GetValue(vm) == 45, "positive QR TTL");
        Console.WriteLine("synthetic_qr_ttl=default:60,positive:45");
    }

    private sealed class SyntheticReceiveProbe
    {
        public readonly List<string> Steps = new List<string>();
        public object Market;
        public MethodInfo Deliver;
        public object Action;
        public object Result;
        public object Message;

        public void OnNetwork(object value)
        {
            Check(value != null, "synthetic JObject");
            Steps.Add("NetMarket.ReceiveMessageHandler");
            // Stand-in for parsing and persistence. The real handlers are only traced.
            Deliver.Invoke(Market, new[] { Action, Result });
        }

        public void OnMessage(object action, object result)
        {
            Check(action.Equals(Action), "synthetic MessageReceive");
            Check(ReferenceEquals(result.GetType().GetProperty("Data").GetValue(result), Message),
                "synthetic MessageModel identity");
            Steps.Add("Market.ReceivedData");
        }
    }

    private static Delegate BindSyntheticHandler(Type delegateType, object receiver, string name)
    {
        var parameters = delegateType.GetMethod("Invoke").GetParameters()
            .Select(parameter => Expression.Parameter(parameter.ParameterType)).ToArray();
        var body = Expression.Call(Expression.Constant(receiver), receiver.GetType().GetMethod(name),
            parameters.Select(parameter => Expression.Convert(parameter, typeof(object))));
        return Expression.Lambda(delegateType, body, parameters).Compile();
    }

    private static void ProbeSyntheticReceive(Assembly core, Assembly network, Assembly model)
    {
        var market = Find(core, "Imo.DataCore.Market");
        var netMarket = Find(network, "Imo.ChannelNetwork.NetMarket");
        var result = Find(model, "Imo.DataModel.Structs.TaskResult");
        var action = Find(model, "Imo.DataModel.Enums.ActionTypes");
        var probe = new SyntheticReceiveProbe {
            Market = FormatterServices.GetUninitializedObject(market),
            Deliver = market.GetMethod("OnReceivedData", Declared),
            Action = Enum.Parse(action, "MessageReceive"),
            Result = Activator.CreateInstance(result),
            Message = Activator.CreateInstance(Find(model, "Imo.DataModel.Models.MessageModel"))
        };
        result.GetProperty("Data").SetValue(probe.Result, probe.Message);
        object networkObject = FormatterServices.GetUninitializedObject(netMarket);
        var networkEvent = netMarket.GetEvent("ReceiveMessageHandler", Declared);
        var marketEvent = market.GetEvent("ReceivedData", Declared);
        var onNetwork = BindSyntheticHandler(networkEvent.EventHandlerType, probe, "OnNetwork");
        var onMessage = BindSyntheticHandler(marketEvent.EventHandlerType, probe, "OnMessage");
        networkEvent.AddEventHandler(networkObject, onNetwork);
        marketEvent.AddEventHandler(probe.Market, onMessage);
        try
        {
            Type payload = networkEvent.EventHandlerType.GetMethod("Invoke").GetParameters()[0].ParameterType;
            netMarket.GetMethod("Instance_ReceiveMessageHandler", Declared)
                .Invoke(networkObject, new[] { Activator.CreateInstance(payload) });
            Check(probe.Steps.SequenceEqual(new[] { "NetMarket.ReceiveMessageHandler", "Market.ReceivedData" }),
                "synthetic boundary order");
            Console.WriteLine("synthetic_receive_boundaries={0}", string.Join(" -> fixture -> ", probe.Steps));
        }
        finally
        {
            networkEvent.RemoveEventHandler(networkObject, onNetwork);
            marketEvent.RemoveEventHandler(probe.Market, onMessage);
        }
    }
}
