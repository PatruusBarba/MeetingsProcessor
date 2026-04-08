using System.Speech.Synthesis;
using System.Text.RegularExpressions;

namespace BrainstormAssistant.Services;

public interface ITtsService
{
    Task SpeakAsync(string text);
    void Stop();
    bool IsEnabled { get; set; }
}

public class TtsService : ITtsService, IDisposable
{
    private SpeechSynthesizer? _synthesizer;
    private readonly string? _voice;
    private readonly int _rate;
    private readonly int _volume;
    private CancellationTokenSource? _cts;

    public bool IsEnabled { get; set; }

    public TtsService(bool enabled, string? voice = null, int rate = 0, int volume = 100)
    {
        IsEnabled = enabled;
        _voice = voice;
        _rate = rate;
        _volume = volume;
    }

    public async Task SpeakAsync(string text)
    {
        if (!IsEnabled || string.IsNullOrWhiteSpace(text))
            return;

        Stop();

        _cts = new CancellationTokenSource();
        var token = _cts.Token;

        await Task.Run(() =>
        {
            try
            {
                _synthesizer = new SpeechSynthesizer();

                if (!string.IsNullOrWhiteSpace(_voice))
                {
                    try { _synthesizer.SelectVoice(_voice); }
                    catch { /* fallback to default voice */ }
                }

                _synthesizer.Rate = _rate;
                _synthesizer.Volume = _volume;

                if (token.IsCancellationRequested) return;

                _synthesizer.Speak(SanitizeForSpeech(text));
            }
            catch (OperationCanceledException) { }
            finally
            {
                _synthesizer?.Dispose();
                _synthesizer = null;
            }
        }, token);
    }

    public void Stop()
    {
        _cts?.Cancel();
        try
        {
            _synthesizer?.SpeakAsyncCancelAll();
            _synthesizer?.Dispose();
        }
        catch { }
        _synthesizer = null;
    }

    private static string SanitizeForSpeech(string text)
    {
        // Strip markdown: bold/italic markers, code blocks, headers, links
        text = Regex.Replace(text, @"```[\s\S]*?```", " ");  // fenced code blocks
        text = Regex.Replace(text, @"`[^`]+`", " ");          // inline code
        text = Regex.Replace(text, @"\[([^\]]+)\]\([^)]+\)", "$1"); // [text](url) → text
        text = Regex.Replace(text, @"[*_#~`>|]", "");         // *, _, #, ~, `, >, |
        text = Regex.Replace(text, @"-{2,}", " ");            // --- separators
        text = Regex.Replace(text, @"\s{2,}", " ");           // collapse whitespace
        return text.Trim();
    }

    public void Dispose()
    {
        Stop();
        _cts?.Dispose();
    }
}
