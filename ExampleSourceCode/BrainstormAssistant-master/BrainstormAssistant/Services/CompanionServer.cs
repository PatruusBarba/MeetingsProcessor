using System.IO;
using System.Net;
using System.Speech.Synthesis;
using System.Text;
using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

/// <summary>
/// Embedded HTTP server that allows a companion app (e.g. Android) to interact
/// with BrainstormAssistant over the local network.
/// </summary>
public class CompanionServer : IDisposable
{
    private HttpListener? _listener;
    private CancellationTokenSource? _cts;
    private Task? _listenTask;
    private readonly int _port;

    private ChatManager? _chatManager;
    private ParakeetSttService? _sttService;
    private readonly string? _ttsVoice;
    private readonly int _ttsRate;
    private readonly int _ttsVolume;

    public bool IsRunning => _listener?.IsListening == true;
    public string? Address => IsRunning ? $"http://{GetLocalIp()}:{_port}" : null;

    public event EventHandler<string>? LogMessage;
    public event EventHandler<CompanionChatResult>? ChatCompleted;

    /// <summary>Delegate to retrieve current board HTML from the main window.</summary>
    public Func<string?>? GetBoardHtml { get; set; }

    public CompanionServer(int port = 5225, string? ttsVoice = null, int ttsRate = 0, int ttsVolume = 100)
    {
        _port = port;
        _ttsVoice = ttsVoice;
        _ttsRate = ttsRate;
        _ttsVolume = ttsVolume;
    }

    public void SetChatManager(ChatManager chatManager)
    {
        _chatManager = chatManager;
    }

    public void SetSttService(ParakeetSttService stt)
    {
        _sttService = stt;
    }

    public void Start()
    {
        if (IsRunning) return;

        _cts = new CancellationTokenSource();

        // Try binding to all interfaces (requires admin or URL ACL)
        if (TryStartListener($"http://+:{_port}/"))
        {
            Log($"Companion server started on port {_port} (all interfaces)");
        }
        // Try binding to specific LAN IP
        else if (TryStartListener($"http://{GetLocalIp()}:{_port}/"))
        {
            Log($"Companion server started on {GetLocalIp()}:{_port}");
        }
        // Try binding to 0.0.0.0 via specific IPs
        else if (TryStartOnAllAddresses())
        {
            Log($"Companion server started on port {_port} (per-address binding)");
        }
        // Last resort: localhost only
        else
        {
            _listener = new HttpListener();
            _listener.Prefixes.Add($"http://localhost:{_port}/");
            _listener.Prefixes.Add($"http://127.0.0.1:{_port}/");
            _listener.Start();
            Log($"Companion server started on localhost:{_port} only (run as admin for LAN access)");
        }

        _listenTask = Task.Run(() => ListenLoop(_cts.Token));
        Log($"Companion server started on port {_port}");
    }

    public void Stop()
    {
        _cts?.Cancel();
        try { _listener?.Stop(); } catch { }
        _listener = null;
        Log("Companion server stopped");
    }

    private async Task ListenLoop(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested && _listener?.IsListening == true)
        {
            try
            {
                var context = await _listener.GetContextAsync().WaitAsync(ct);
                _ = Task.Run(() => HandleRequest(context), ct);
            }
            catch (OperationCanceledException) { break; }
            catch (HttpListenerException) { break; }
            catch (Exception ex) { Log($"Listener error: {ex.Message}"); }
        }
    }

    private async Task HandleRequest(HttpListenerContext context)
    {
        var req = context.Request;
        var resp = context.Response;

        // CORS headers for companion app
        resp.Headers.Add("Access-Control-Allow-Origin", "*");
        resp.Headers.Add("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
        resp.Headers.Add("Access-Control-Allow-Headers", "Content-Type");

        if (req.HttpMethod == "OPTIONS")
        {
            resp.StatusCode = 204;
            resp.Close();
            return;
        }

        try
        {
            var path = req.Url?.AbsolutePath?.TrimEnd('/') ?? "";

            switch (path)
            {
                case "/api/status":
                    await HandleStatus(resp);
                    break;
                case "/api/chat":
                    await HandleChat(req, resp);
                    break;
                case "/api/audio":
                    await HandleAudio(req, resp);
                    break;
                case "/api/board":
                    await HandleBoard(resp);
                    break;
                default:
                    await WriteJson(resp, 404, new { error = "Not found" });
                    break;
            }
        }
        catch (Exception ex)
        {
            Log($"Request error: {ex.Message}");
            try { await WriteJson(resp, 500, new { error = ex.Message }); }
            catch { resp.Close(); }
        }
    }

    /// <summary>GET /api/board — retrieve current board HTML content.</summary>
    private async Task HandleBoard(HttpListenerResponse resp)
    {
        var html = GetBoardHtml?.Invoke() ?? "";
        await WriteJson(resp, 200, new { html });
    }

    /// <summary>GET /api/status — health check + current model info.</summary>
    private async Task HandleStatus(HttpListenerResponse resp)
    {
        var status = new
        {
            ok = true,
            model = _chatManager?.GetCurrentModel() ?? "not configured",
            provider = _chatManager?.Provider ?? "unknown",
            session = _chatManager?.CurrentSession?.Title ?? "none",
            messageCount = _chatManager?.MessageCount ?? 0
        };
        await WriteJson(resp, 200, status);
    }

    /// <summary>POST /api/chat — send text, get LLM response + optional TTS audio.</summary>
    private async Task HandleChat(HttpListenerRequest req, HttpListenerResponse resp)
    {
        if (req.HttpMethod != "POST")
        {
            await WriteJson(resp, 405, new { error = "POST required" });
            return;
        }

        if (_chatManager == null)
        {
            await WriteJson(resp, 503, new { error = "Chat not initialized" });
            return;
        }

        string body;
        using (var reader = new StreamReader(req.InputStream, req.ContentEncoding))
            body = await reader.ReadToEndAsync();

        var input = JsonConvert.DeserializeObject<CompanionChatRequest>(body);
        if (string.IsNullOrWhiteSpace(input?.text))
        {
            await WriteJson(resp, 400, new { error = "Missing 'text' field" });
            return;
        }

        Log($"Companion chat: {input.text[..Math.Min(input.text.Length, 80)]}...");

        var response = await _chatManager.SendMessageAsync(input.text);

        // Generate TTS audio if requested
        string? audioBase64 = null;
        if (input.tts != false)
        {
            audioBase64 = await SynthesizeToBase64(response);
        }

        var result = new CompanionChatResult
        {
            response = response,
            audio = audioBase64,
            model = _chatManager.GetCurrentModel(),
            messageCount = _chatManager.MessageCount,
            board_html = GetBoardHtml?.Invoke()
        };

        ChatCompleted?.Invoke(this, result);
        await WriteJson(resp, 200, result);
    }

    /// <summary>POST /api/audio — send WAV audio, get STT transcription + LLM response + TTS audio.</summary>
    private async Task HandleAudio(HttpListenerRequest req, HttpListenerResponse resp)
    {
        if (req.HttpMethod != "POST")
        {
            await WriteJson(resp, 405, new { error = "POST required" });
            return;
        }

        if (_chatManager == null)
        {
            await WriteJson(resp, 503, new { error = "Chat not initialized" });
            return;
        }

        // Read raw audio bytes
        using var ms = new MemoryStream();
        await req.InputStream.CopyToAsync(ms);
        var audioBytes = ms.ToArray();

        if (audioBytes.Length == 0)
        {
            await WriteJson(resp, 400, new { error = "Empty audio data" });
            return;
        }

        // STT: transcribe audio using Parakeet
        string transcription;
        try
        {
            if (_sttService == null)
            {
                await WriteJson(resp, 503, new { error = "STT service not available" });
                return;
            }
            transcription = _sttService.TranscribeWav(audioBytes);

            if (string.IsNullOrWhiteSpace(transcription))
            {
                await WriteJson(resp, 200, new { transcription = "", response = "", error = "No speech detected" });
                return;
            }
        }
        catch (Exception ex)
        {
            await WriteJson(resp, 500, new { error = $"STT error: {ex.Message}" });
            return;
        }

        Log($"Companion audio transcribed: {transcription[..Math.Min(transcription.Length, 80)]}");

        var response = await _chatManager.SendMessageAsync(transcription);
        var audioBase64 = await SynthesizeToBase64(response);

        var result = new CompanionChatResult
        {
            transcription = transcription,
            response = response,
            audio = audioBase64,
            model = _chatManager.GetCurrentModel(),
            messageCount = _chatManager.MessageCount,
            board_html = GetBoardHtml?.Invoke()
        };

        ChatCompleted?.Invoke(this, result);
        await WriteJson(resp, 200, result);
    }

    /// <summary>Synthesizes text to a WAV byte array and returns as base64.</summary>
    private Task<string?> SynthesizeToBase64(string text)
    {
        return Task.Run(() =>
        {
            try
            {
                using var synth = new SpeechSynthesizer();
                if (!string.IsNullOrWhiteSpace(_ttsVoice))
                {
                    try { synth.SelectVoice(_ttsVoice); } catch { }
                }
                synth.Rate = _ttsRate;
                synth.Volume = _ttsVolume;

                using var ms = new MemoryStream();
                synth.SetOutputToWaveStream(ms);
                synth.Speak(text);
                return Convert.ToBase64String(ms.ToArray());
            }
            catch
            {
                return null;
            }
        });
    }

    private static async Task WriteJson(HttpListenerResponse resp, int statusCode, object data)
    {
        resp.StatusCode = statusCode;
        resp.ContentType = "application/json; charset=utf-8";
        var json = JsonConvert.SerializeObject(data);
        var bytes = Encoding.UTF8.GetBytes(json);
        resp.ContentLength64 = bytes.Length;
        await resp.OutputStream.WriteAsync(bytes);
        resp.Close();
    }

    private bool TryStartListener(string prefix)
    {
        try
        {
            var listener = new HttpListener();
            listener.Prefixes.Add(prefix);
            listener.Start();
            _listener = listener;
            return true;
        }
        catch (HttpListenerException)
        {
            return false;
        }
    }

    private bool TryStartOnAllAddresses()
    {
        try
        {
            var listener = new HttpListener();
            foreach (var ip in GetAllLocalIps())
            {
                listener.Prefixes.Add($"http://{ip}:{_port}/");
            }
            if (listener.Prefixes.Count == 0) return false;
            listener.Start();
            _listener = listener;
            return true;
        }
        catch (HttpListenerException)
        {
            return false;
        }
    }

    private static string GetLocalIp()
    {
        // Prefer 192.168.x.x and 10.x.x.x private LAN IPs,
        // prioritizing common home/office subnets over VPN adapters
        try
        {
            var candidates = new List<(IPAddress ip, int priority)>();
            foreach (var iface in System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces())
            {
                if (iface.OperationalStatus != System.Net.NetworkInformation.OperationalStatus.Up)
                    continue;
                // Skip virtual/loopback/tunnel adapters
                if (iface.NetworkInterfaceType == System.Net.NetworkInformation.NetworkInterfaceType.Loopback)
                    continue;

                foreach (var addr in iface.GetIPProperties().UnicastAddresses)
                {
                    if (addr.Address.AddressFamily != System.Net.Sockets.AddressFamily.InterNetwork)
                        continue;
                    if (IPAddress.IsLoopback(addr.Address))
                        continue;

                    var bytes = addr.Address.GetAddressBytes();
                    int priority;

                    // Wi-Fi and Ethernet adapters with 192.168.x.x get highest priority
                    if (bytes[0] == 192 && bytes[1] == 168)
                    {
                        priority = iface.NetworkInterfaceType switch
                        {
                            System.Net.NetworkInformation.NetworkInterfaceType.Wireless80211 => 1,
                            System.Net.NetworkInformation.NetworkInterfaceType.Ethernet => 2,
                            _ => 3
                        };
                    }
                    // 10.x.x.x — could be LAN or VPN, lower priority
                    else if (bytes[0] == 10)
                        priority = 10;
                    // 172.16-31.x.x
                    else if (bytes[0] == 172 && bytes[1] >= 16 && bytes[1] <= 31)
                        priority = 10;
                    else
                        priority = 20;

                    candidates.Add((addr.Address, priority));
                }
            }

            var best = candidates.OrderBy(c => c.priority).FirstOrDefault();
            if (best.ip != null) return best.ip.ToString();
        }
        catch { }
        return "localhost";
    }

    private static List<string> GetAllLocalIps()
    {
        var ips = new List<string>();
        try
        {
            foreach (var iface in System.Net.NetworkInformation.NetworkInterface.GetAllNetworkInterfaces())
            {
                if (iface.OperationalStatus != System.Net.NetworkInformation.OperationalStatus.Up)
                    continue;
                if (iface.NetworkInterfaceType == System.Net.NetworkInformation.NetworkInterfaceType.Loopback)
                    continue;

                foreach (var addr in iface.GetIPProperties().UnicastAddresses)
                {
                    if (addr.Address.AddressFamily == System.Net.Sockets.AddressFamily.InterNetwork
                        && !IPAddress.IsLoopback(addr.Address))
                    {
                        ips.Add(addr.Address.ToString());
                    }
                }
            }
        }
        catch { }
        return ips;
    }

    private void Log(string message) => LogMessage?.Invoke(this, message);

    public void Dispose()
    {
        Stop();
        _cts?.Dispose();
    }
}

public class CompanionChatRequest
{
    public string text { get; set; } = "";
    public bool? tts { get; set; }
}

public class CompanionChatResult
{
    public string? transcription { get; set; }
    public string response { get; set; } = "";
    public string? audio { get; set; }
    public string? model { get; set; }
    public int messageCount { get; set; }
    public string? board_html { get; set; }
}
