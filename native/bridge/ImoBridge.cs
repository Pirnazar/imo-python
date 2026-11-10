// ImoBridge — headless host for the installed IMO Windows client's managed core.
//
// Runs from a private copy of the IMO binaries (see Build.ps1), so its profile (`data`)
// is separate from the desktop client's. Talks JSON lines over stdin/stdout:
//
//   -> {"id": 1, "cmd": "request_qr"}
//   <- {"id": 1, "ok": true, "result": {...}}
//   <- {"event": "action", "type": "SignedOn", ...}        (unsolicited)
//
// Nothing here re-implements the protocol: every network operation goes through the
// client's own Market.RunTask, exactly as its UI layer does.
using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Imo.DataCommon;
using Imo.DataCore;
using Imo.DataModel.Enums;
using Imo.DataModel.Models;
using Imo.DataModel.Structs;
using Microsoft.Win32;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

internal static class ImoBridge
{
    private const string RunKey = @"SOFTWARE\Microsoft\Windows\CurrentVersion\Run";
    private const string RunValue = "Imo Messenger";

    private static TextWriter output;
    private static readonly object OutputLock = new object();
    private static bool autoLogin = true;

    [STAThread]
    private static int Main(string[] args)
    {
        bool verbose = args.Contains("--log");
        // The protocol owns stdout. Anything the client prints goes to stderr.
        output = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true };
        Console.SetOut(Console.Error);
        if (!verbose)
            NLog.LogManager.DisableLogging();

        AppDomain.CurrentDomain.UnhandledException += (s, e) =>
            Emit(new JObject { { "event", "fatal" }, { "error", Convert.ToString(e.ExceptionObject) } });
        TaskScheduler.UnobservedTaskException += (s, e) => e.SetObserved();

        try
        {
            Startup();
        }
        catch (Exception error)
        {
            Emit(new JObject { { "event", "fatal" }, { "error", error.ToString() } });
            return 1;
        }

        var reader = new Thread(ReadCommands) { IsBackground = true, Name = "bridge-stdin" };
        reader.Start();

        // The core marshals some callbacks through Application.Current.Dispatcher.
        var app = new System.Windows.Application { ShutdownMode = System.Windows.ShutdownMode.OnExplicitShutdown };
        app.DispatcherUnhandledException += (s, e) =>
        {
            Emit(new JObject { { "event", "error" }, { "error", e.Exception.ToString() } });
            e.Handled = true;
        };
        Emit(new JObject { { "event", "ready" }, { "version", ApplicationProperties.Instance.Version.ToString() },
            { "signed_on_before", ApplicationSettings.Instance.IsCookieSignedOn } });
        app.Run();
        return 0;
    }

    private static void Startup()
    {
        // ApplicationSettings rewrites the user's "Imo Messenger" autostart entry to point at
        // the current executable. Put the original value back straight away.
        object autostart = ReadAutostart();
        try
        {
            GC.KeepAlive(ApplicationSettings.Instance);
        }
        finally
        {
            RestoreAutostart(autostart);
        }

        // Same as AppHelper.InitVersion, with the version taken from the copied client.
        string exe = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "ImoDesktopApp.exe");
        Version v = AssemblyName.GetAssemblyName(exe).Version;
        ApplicationProperties.Instance.Version = new ImoVersion(v.Major, v.Minor, v.Build, v.Revision);

        if (!Market.Initialize())
            throw new InvalidOperationException("Market.Initialize returned false");
        Market.Instance.ReceivedData += OnReceivedData;
    }

    private static object ReadAutostart()
    {
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKey))
            return key == null ? null : key.GetValue(RunValue);
    }

    private static void RestoreAutostart(object original)
    {
        using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RunKey, true))
        {
            if (key == null)
                return;
            object current = key.GetValue(RunValue);
            if (original == null && current != null)
                key.DeleteValue(RunValue, false);
            else if (original != null && !original.Equals(current))
                key.SetValue(RunValue, original);
        }
    }

    // ------------------------------------------------------------------ events

    private static void OnReceivedData(ActionTypes type, TaskResult result)
    {
        try
        {
            if (type == ActionTypes.DevToolsMessage)
                return;
            var message = new JObject { { "event", "action" }, { "type", type.ToString() } };
            message["result_type"] = result.ResultType.ToString();
            AddIf(message, "code", result.ResultCode);
            AddIf(message, "info", result.Info);
            AddIf(message, "info1", result.Info1);
            AddIf(message, "error", result.Error);
            AddIf(message, "async_key", result.AsyncKey);
            if (result.Flag != 0) message["flag"] = result.Flag;
            if (result.BoolValue0) message["bool0"] = true;
            if (result.TimeStamp != 0) message["ts"] = result.TimeStamp;
            if (result.Data != null) message["data"] = ToJson(result.Data, 0);
            if (result.Data1 != null) message["data1"] = ToJson(result.Data1, 0);
            if (result.Model != null) message["model"] = ToJson(result.Model, 0);
            if (result.Models != null) message["models"] = ToJson(result.Models, 0);
            if (result.JObjectData != null) message["json"] = result.JObjectData;
            Emit(message);

            // What SignInWithScanPageViewModel does when the phone confirms the QR login.
            if (type == ActionTypes.QrCodeLoginCompleted && autoLogin)
                Task.Run(() => Market.Instance.RunTask(ActionTypes.CookieLogin, new ActionParamer { Str0 = "qr_login" }));
        }
        catch (Exception error)
        {
            Emit(new JObject { { "event", "error" }, { "error", error.ToString() } });
        }
    }

    private static void AddIf(JObject target, string name, string value)
    {
        if (!string.IsNullOrEmpty(value))
            target[name] = value;
    }

    // ---------------------------------------------------------------- commands

    private static void ReadCommands()
    {
        var input = new StreamReader(Console.OpenStandardInput(), new UTF8Encoding(false));
        string line;
        while ((line = input.ReadLine()) != null)
        {
            if (line.Trim().Length == 0)
                continue;
            JObject command;
            try
            {
                command = JObject.Parse(line);
            }
            catch (JsonException error)
            {
                Emit(new JObject { { "event", "error" }, { "error", "bad command: " + error.Message } });
                continue;
            }
            JObject captured = command;
            Task.Run(() => Execute(captured));
        }
        Shutdown();
    }

    private static void Execute(JObject command)
    {
        JToken id = command["id"];
        try
        {
            JToken result = Dispatch(command, id);
            if (result != null)
                Reply(id, result);
        }
        catch (Exception error)
        {
            Exception inner = error is TargetInvocationException && error.InnerException != null ? error.InnerException : error;
            Emit(new JObject { { "id", id }, { "ok", false }, { "error", Describe(inner) } });
        }
    }

    private static string Describe(Exception error)
    {
        var text = new StringBuilder();
        for (Exception e = error; e != null; e = e.InnerException)
            text.Append(text.Length == 0 ? "" : " <- ").Append(e.GetType().Name).Append(": ").Append(e.Message);
        return text.ToString();
    }

    private static void Reply(JToken id, JToken result)
    {
        Emit(new JObject { { "id", id }, { "ok", true }, { "result", result } });
    }

    /// Returns the reply, or null when the reply is sent later from a callback.
    private static JToken Dispatch(JObject command, JToken id)
    {
        switch ((string)command["cmd"])
        {
            case "status":
                return Status();
            case "connect":
                autoLogin = (bool?)command["auto_login"] ?? true;
                Market.Instance.InitConnect();
                return true;
            case "request_qr":
                Market.Instance.RunTask(ActionTypes.RequestQRcode, new ActionParamer {
                    SuccessCallback = token => Reply(id, token ?? JValue.CreateNull()) });
                return null;
            case "send":
                return Send(command);
            case "run":
                return Run(command, id);
            case "exit":
                Reply(id, true);
                Shutdown();
                return null;
            default:
                throw new ArgumentException("unknown cmd: " + command["cmd"]);
        }
    }

    private static JToken Status()
    {
        var user = IMO.Instance.User;
        return new JObject {
            { "signed_on", ApplicationProperties.Instance.IsSignedOn },
            { "cookie_signed_on", ApplicationSettings.Instance.IsCookieSignedOn },
            { "cookie_sign_on_failed", ApplicationProperties.Instance.CookieSignOnFailed },
            { "signal_connected", user.State == 1 },
            { "uid", user.Uid },
            { "user", ToJson(user, 0) } };
    }

    private static JToken Send(JObject command)
    {
        string buid = (string)command["buid"];
        string text = (string)command["text"];
        if (string.IsNullOrEmpty(buid) || string.IsNullOrEmpty(text))
            throw new ArgumentException("send needs buid and text");
        if (!ApplicationProperties.Instance.IsSignedOn)
            throw new InvalidOperationException("not signed on");
        // Mirrors ConversationViewModel.SendNormalMessage.
        var model = new MsgSendModel {
            Content = text,
            Imdata = command["imdata"] as JObject ?? new JObject(),
            Buid = buid,
            SendMessageType = MessageContentType.Text,
        };
        JToken id = command["id"];
        object returned = Market.Instance.RunTask(ActionTypes.MessageSend, new ActionParamer {
            SendModel = model,
            BoolValue2 = (bool?)command["online"] ?? false,
            onDispatcherAckCallback = () => Emit(new JObject { { "event", "send_ack" }, { "send_id", id }, { "buid", buid } }),
        });
        return new JObject { { "queued", true }, { "returned", ToJson(returned, 0) } };
    }

    /// Generic RunTask: {"cmd":"run","action":"GetChaters","params":{"BoolValue0":true},"callback":true}
    private static JToken Run(JObject command, JToken id)
    {
        var action = (ActionTypes)Enum.Parse(typeof(ActionTypes), (string)command["action"], false);
        object parameters = new ActionParamer();
        var values = command["params"] as JObject;
        if (values != null)
        {
            foreach (var pair in values)
            {
                PropertyInfo property = typeof(ActionParamer).GetProperty(pair.Key);
                if (property == null)
                    throw new ArgumentException("ActionParamer has no property " + pair.Key);
                property.SetValue(parameters, pair.Value.ToObject(property.PropertyType));
            }
        }
        bool callback = (bool?)command["callback"] ?? false;
        if (callback)
        {
            Action<JToken> reply = token => Reply(id, token ?? JValue.CreateNull());
            typeof(ActionParamer).GetProperty("SuccessCallback").SetValue(parameters, reply);
        }
        object returned = Market.Instance.RunTask(action, (ActionParamer)parameters);
        return callback ? null : ToJson(returned, 0);
    }

    private static int shuttingDown;

    private static void Shutdown()
    {
        if (Interlocked.Exchange(ref shuttingDown, 1) != 0)
            return;
        try
        {
            var closing = Task.Run(() => Market.Exit());
            closing.Wait(3000);
        }
        catch (Exception)
        {
        }
        Environment.Exit(0);
    }

    // ----------------------------------------------------------- serialization

    private static void Emit(JObject message)
    {
        lock (OutputLock)
            output.WriteLine(message.ToString(Formatting.None));
    }

    /// Plain-data view of a client model: scalars, enums, JSON and nested Imo.DataModel objects.
    private static JToken ToJson(object value, int depth)
    {
        if (value == null)
            return JValue.CreateNull();
        var token = value as JToken;
        if (token != null)
            return token;
        Type type = value.GetType();
        if (value is string || type.IsPrimitive || value is decimal)
            return JToken.FromObject(value);
        if (type.IsEnum)
            return value.ToString();
        if (value is DateTime)
            return ((DateTime)value).ToString("o");
        if (value is TimeSpan)
            return ((TimeSpan)value).TotalSeconds;
        if (depth > 4)
            return JValue.CreateNull();
        var dictionary = value as IDictionary;
        if (dictionary != null)
        {
            var map = new JObject();
            foreach (DictionaryEntry entry in dictionary)
                map[Convert.ToString(entry.Key)] = ToJson(entry.Value, depth + 1);
            return map;
        }
        var sequence = value as IEnumerable;
        if (sequence != null)
        {
            var array = new JArray();
            foreach (object item in sequence)
                array.Add(ToJson(item, depth + 1));
            return array;
        }
        if (type.Namespace == null || !type.Namespace.StartsWith("Imo.DataModel", StringComparison.Ordinal))
            return type.Name;

        var result = new JObject { { "_type", type.Name } };
        foreach (PropertyInfo property in type.GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (!property.CanRead || property.GetIndexParameters().Length != 0 || !IsData(property.PropertyType))
                continue;
            try
            {
                object item = property.GetValue(value);
                if (item != null)
                    result[property.Name] = ToJson(item, depth + 1);
            }
            catch (Exception)
            {
            }
        }
        foreach (FieldInfo field in type.GetFields(BindingFlags.Public | BindingFlags.Instance))
        {
            if (!IsData(field.FieldType))
                continue;
            object item = field.GetValue(value);
            if (item != null)
                result[field.Name] = ToJson(item, depth + 1);
        }
        return result;
    }

    private static bool IsData(Type type)
    {
        type = Nullable.GetUnderlyingType(type) ?? type;
        if (type.IsPrimitive || type.IsEnum || type == typeof(string) || type == typeof(decimal)
            || type == typeof(DateTime) || type == typeof(TimeSpan) || typeof(JToken).IsAssignableFrom(type))
            return true;
        if (typeof(Delegate).IsAssignableFrom(type))
            return false;
        if (type.IsArray)
            return IsData(type.GetElementType());
        if (type.IsGenericType && typeof(IEnumerable).IsAssignableFrom(type))
            return type.GetGenericArguments().All(IsData);
        return type.Namespace != null && type.Namespace.StartsWith("Imo.DataModel", StringComparison.Ordinal);
    }
}
