using System;
using System.IO;
using System.Runtime.InteropServices;

internal static partial class Harness
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr LoadLibrary(string path);

    [DllImport("kernel32.dll", CharSet = CharSet.Ansi, ExactSpelling = true, SetLastError = true)]
    private static extern IntPtr GetProcAddress(IntPtr library, string name);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate uint NewHttp();

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate void Destroy(uint handle);

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int Write(uint handle, IntPtr data, uint length);

    private static void ProbeNativeHandles()
    {
        RequireIsolatedToken();
        // The inspected cgo stubs use an empty input plus one four-byte result for new,
        // and one four-byte input for destroy. No HTTP client initialization is performed.
        IntPtr module = LoadLibrary(Path.Combine(installDirectory, "libgonet.dll"));
        Check(module != IntPtr.Zero, "load Go DLL, Win32=" + Marshal.GetLastWin32Error());
        var create = (NewHttp)NativeExport(module, "gonet_new_http", typeof(NewHttp));
        var destroy = (Destroy)NativeExport(module, "gonet_destroy", typeof(Destroy));
        var write = (Write)NativeExport(module, "gonet_conn_write", typeof(Write));
        int invalidResult = write(0, IntPtr.Zero, 0);
        Check(invalidResult == -2, "write rejects unregistered handle");
        Console.WriteLine("gonet_write_unregistered_handle={0}", invalidResult);
        uint first = create();
        uint second = create();
        try
        {
            Check(first != 0 && second != 0 && first != second, "distinct local Go handles");
            Console.WriteLine("gonet_local_handles=2 distinct,nonzero");
        }
        finally
        {
            // Deliberately exercise the missing-http-init path and capture Go recovery diagnostics.
            if (first != 0)
                destroy(first);
            if (second != 0 && second != first)
                destroy(second);
        }
        Console.WriteLine("gonet_destroy_returned=2");
        // The following steps read IL from copied modules without invoking their network methods.
        var core = LoadLifecycleAssembly("Imo.DataCore.dll");
        TraceLifecycle(core, "Imo.DataCore.Downloader.BigoNervServices",
            @"\.ctor|InitMediaProtoX|RegisterPush|SendJSON|UploadFile|DownloadFile|Dispose");
        TraceLifecycle(core, "Imo.DataCore.Downloader.AVSignalProtoX",
            @"\.ctor|startAndKeepConnectedIfUidNotEmpty|disconnect|sendJSON|registerPush");
        var network = LoadLifecycleAssembly("Imo.ChannelNetwork.dll");
        TraceLifecycle(network, "Imo.ChannelNetwork.Connection.Channel.HttplpProxyChannel",
            "EnsureHttpClient|SendDataAndRecv|Disconnect");
        // Let the isolated process own Go runtime shutdown.
    }

    private static Delegate NativeExport(IntPtr module, string name, Type type)
    {
        IntPtr address = GetProcAddress(module, name);
        Check(address != IntPtr.Zero, name);
        return Marshal.GetDelegateForFunctionPointer(address, type);
    }
}
