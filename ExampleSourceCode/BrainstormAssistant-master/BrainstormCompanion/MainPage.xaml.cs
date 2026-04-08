using BrainstormCompanion.Services;

namespace BrainstormCompanion;

public partial class MainPage : ContentPage
{
    private BrainstormApiClient? _api;
    private AudioRecorderService? _recorder;
    private VadService? _vad;
    private AudioRoutingService _audioRouting = new();
    private List<AudioRoutingService.AudioRoute> _audioRoutes = new();
    private bool _isRecording;
    private bool _handsFreeMode;
    private TaskCompletionSource<bool>? _playerTcs;
#if ANDROID
    private Android.Media.MediaPlayer? _currentPlayer;
#endif

    public MainPage()
    {
        InitializeComponent();
        // Restore saved server address
        var saved = Preferences.Default.Get("server_address", "");
        if (!string.IsNullOrEmpty(saved))
            ServerEntry.Text = saved;
    }

    private async void OnConnectClicked(object sender, EventArgs e)
    {
        var address = ServerEntry.Text?.Trim();
        if (string.IsNullOrEmpty(address)) return;

        if (!address.StartsWith("http"))
            address = $"http://{address}";

        _api = new BrainstormApiClient(address);
        StatusLabel.Text = "Connecting...";

        try
        {
            var status = await _api.GetStatusAsync();
            StatusDot.TextColor = Colors.LimeGreen;
            StatusLabel.Text = $"Connected — Model: {status.model}";
            PttButton.IsEnabled = true;
            HandsFreeButton.IsEnabled = true;
            ConnectButton.Text = "Reconnect";

            // Save address for next launch
            Preferences.Default.Set("server_address", ServerEntry.Text?.Trim() ?? "");

            _recorder = new AudioRecorderService();

            // Populate audio device picker
            RefreshAudioDevices();
        }
        catch (Exception ex)
        {
            StatusDot.TextColor = Colors.Red;
            StatusLabel.Text = $"Failed: {ex.Message}";
            PttButton.IsEnabled = false;
        }
    }

    private async void OnPttPressed(object sender, EventArgs e)
    {
        if (_recorder == null || _isRecording || _handsFreeMode) return;

        _isRecording = true;
        PttButton.BackgroundColor = Color.FromArgb("#CC3333");
        PttButton.Text = "🔴  Recording...";
        TranscriptionLabel.Text = "";

        try
        {
            await _recorder.StartRecordingAsync();
        }
        catch (Exception ex)
        {
            TranscriptionLabel.Text = $"Mic error: {ex.Message}";
            _isRecording = false;
            ResetPttButton();
        }
    }

    private async void OnPttReleased(object sender, EventArgs e)
    {
        if (!_isRecording || _recorder == null || _api == null) return;

        _isRecording = false;
        PttButton.Text = "⏳  Processing...";
        PttButton.IsEnabled = false;

        try
        {
            var audioData = await _recorder.StopRecordingAsync();
            await ProcessAudioResponse(audioData);
        }
        catch (Exception ex)
        {
            ResponseLabel.Text = $"Error: {ex.Message}";
        }
        finally
        {
            ResetPttButton();
        }
    }

    private void OnHandsFreeClicked(object sender, EventArgs e)
    {
        if (_api == null) return;

        _handsFreeMode = !_handsFreeMode;

        if (_handsFreeMode)
        {
            HandsFreeButton.Text = "🙌  Hands-Free: ON";
            HandsFreeButton.BackgroundColor = Color.FromArgb("#2E7D32");
            HandsFreeButton.TextColor = Colors.White;
            PttButton.IsEnabled = false;
            PttButton.Text = "🎤  VAD Active — listening...";

            _vad = new VadService();
#if ANDROID
            _vad.PreferredInputDevice = _audioRouting.PreferredInputDevice;
#endif
            _vad.SpeechStarted += OnVadSpeechStarted;
            _vad.SpeechEnded += OnVadSpeechEnded;
            _vad.Error += OnVadError;
            _vad.Start();
        }
        else
        {
            StopHandsFree();
        }
    }

    private void OnVadError(string message)
    {
        MainThread.BeginInvokeOnMainThread(() =>
        {
            TranscriptionLabel.Text = $"VAD error: {message}";
            StopHandsFree();
        });
    }

    private void StopHandsFree()
    {
        _handsFreeMode = false;
        _vad?.Stop();
        _vad = null;

        MainThread.BeginInvokeOnMainThread(() =>
        {
            HandsFreeButton.Text = "🙌  Hands-Free: OFF";
            HandsFreeButton.BackgroundColor = Color.FromArgb("#2D2D2D");
            HandsFreeButton.TextColor = Color.FromArgb("#AAAAAA");
            ResetPttButton();
        });
    }

    private void OnVadSpeechStarted()
    {
        MainThread.BeginInvokeOnMainThread(() =>
        {
            PttButton.BackgroundColor = Color.FromArgb("#CC3333");
            PttButton.Text = "🔴  Listening...";
            TranscriptionLabel.Text = "";
        });
    }

    private void OnVadSpeechEnded(byte[] wavData)
    {
        MainThread.BeginInvokeOnMainThread(async () =>
        {
            PttButton.Text = "⏳  Processing...";
            try
            {
                await ProcessAudioResponse(wavData);
            }
            catch (Exception ex)
            {
                ResponseLabel.Text = $"Error: {ex.Message}";
            }
            finally
            {
                if (_handsFreeMode)
                    PttButton.Text = "🎤  VAD Active — listening...";
            }
        });
    }

    private async Task ProcessAudioResponse(byte[] audioData)
    {
        if (_api == null) return;

        if (audioData.Length == 0)
        {
            TranscriptionLabel.Text = "No audio captured.";
            return;
        }

        // Pause VAD for the entire processing + playback cycle
        if (_vad != null)
            _vad.IsPaused = true;

        try
        {
            // Suspend SCO so audio plays through A2DP (Music stream)
            _audioRouting.SuspendScoForPlayback();

            // "Thinking" beep
            await PlayBeepAsync(880, 100);

            var result = await _api.SendAudioAsync(audioData);

            TranscriptionLabel.Text = $"You: {result.transcription}";
            ResponseLabel.Text = result.response;

            // Update board if content was returned
            if (!string.IsNullOrEmpty(result.board_html))
            {
                UpdateBoard(result.board_html);
            }

            if (!string.IsNullOrEmpty(result.audio))
            {
                await PlayAudioBase64(result.audio);
            }

            // "Done" beep
            await PlayBeepAsync(440, 150);
        }
        finally
        {
            // Resume SCO for BT mic recording
            await _audioRouting.ResumeScoAfterPlayback();

            // Resume VAD
            if (_vad != null)
                _vad.IsPaused = false;
        }
    }

    private void UpdateBoard(string html)
    {
        if (!html.Contains("<html", StringComparison.OrdinalIgnoreCase))
        {
            html = "<!DOCTYPE html><html><head><meta charset='utf-8'/>" +
                   "<meta name='viewport' content='width=device-width,initial-scale=1'/>" +
                   "<style>body{background:#1e1e1e;color:#e0e0e0;font-family:sans-serif;padding:16px;margin:0}</style>" +
                   "</head><body>" + html + "</body></html>";
        }
        BoardWebView.Source = new HtmlWebViewSource { Html = html };
    }

    private void OnStopTtsClicked(object sender, EventArgs e)
    {
#if ANDROID
        try
        {
            if (_currentPlayer != null)
            {
                if (_currentPlayer.IsPlaying)
                    _currentPlayer.Stop();
                _currentPlayer.Release();
                _currentPlayer = null;
            }
        }
        catch { }
#endif
        // Resolve pending playback task so ProcessAudioResponse can continue
        _playerTcs?.TrySetResult(false);
        StopTtsButton.IsVisible = false;
    }

    private void ResetPttButton()
    {
        PttButton.BackgroundColor = Color.FromArgb("#3A3A3A");
        PttButton.Text = "🎤  Hold to Talk";
        PttButton.IsEnabled = true;
    }

    private async Task PlayAudioBase64(string base64Audio)
    {
        try
        {
            StopTtsButton.IsVisible = true;

            var audioBytes = Convert.FromBase64String(base64Audio);
            var tempPath = Path.Combine(FileSystem.CacheDirectory, "response.wav");
            await File.WriteAllBytesAsync(tempPath, audioBytes);

#if ANDROID
            _playerTcs = new TaskCompletionSource<bool>();
            var player = new Android.Media.MediaPlayer();
            _currentPlayer = player;

            // Always use Music stream — routes through A2DP to BT earphones
            // SCO is already suspended by ProcessAudioResponse
#pragma warning disable CA1422
            player.SetAudioStreamType(Android.Media.Stream.Music);
#pragma warning restore CA1422

            player.SetDataSource(tempPath);
            player.Prepare();
            player.Completion += (_, _) =>
            {
                _currentPlayer = null;
                player.Release();
                try { File.Delete(tempPath); } catch { }
                _playerTcs?.TrySetResult(true);
            };
            player.Error += (_, _) =>
            {
                _currentPlayer = null;
                player.Release();
                try { File.Delete(tempPath); } catch { }
                _playerTcs?.TrySetResult(false);
            };
            player.Start();
            await _playerTcs.Task;
            _playerTcs = null;
#endif
        }
        catch
        {
            // Audio playback failure is non-critical
        }
        finally
        {
            StopTtsButton.IsVisible = false;
        }
    }

#if ANDROID
    /// <summary>Generates and plays a short sine-wave beep through the Music stream.</summary>
    private async Task PlayBeepAsync(int frequencyHz, int durationMs)
    {
        try
        {
            const int sampleRate = 16000;
            int sampleCount = sampleRate * durationMs / 1000;
            var pcm = new short[sampleCount];

            for (int i = 0; i < sampleCount; i++)
            {
                double t = (double)i / sampleRate;
                // Fade in/out envelope to avoid click artifacts
                double envelope = 1.0;
                int fade = sampleCount / 5;
                if (i < fade) envelope = (double)i / fade;
                else if (i > sampleCount - fade) envelope = (double)(sampleCount - i) / fade;
                pcm[i] = (short)(short.MaxValue * 0.25 * envelope * Math.Sin(2 * Math.PI * frequencyHz * t));
            }

            var bytes = new byte[pcm.Length * 2];
            Buffer.BlockCopy(pcm, 0, bytes, 0, bytes.Length);

            int bufSize = Android.Media.AudioTrack.GetMinBufferSize(
                sampleRate, Android.Media.ChannelOut.Mono, Android.Media.Encoding.Pcm16bit);
            if (bufSize < bytes.Length) bufSize = bytes.Length;

#pragma warning disable CA1422
            var track = new Android.Media.AudioTrack(
                Android.Media.Stream.Music, sampleRate,
                Android.Media.ChannelOut.Mono, Android.Media.Encoding.Pcm16bit,
                bufSize, Android.Media.AudioTrackMode.Static);
#pragma warning restore CA1422

            track.Write(bytes, 0, bytes.Length);
            track.Play();
            await Task.Delay(durationMs + 50);
            track.Stop();
            track.Release();
        }
        catch { }
    }
#else
    private Task PlayBeepAsync(int frequencyHz, int durationMs) => Task.CompletedTask;
#endif

    private async void RefreshAudioDevices()
    {
        _audioRoutes = await _audioRouting.GetAvailableRoutesAsync();
        AudioDevicePicker.Items.Clear();
        foreach (var route in _audioRoutes)
            AudioDevicePicker.Items.Add(route.Name);
        AudioDevicePicker.SelectedIndex = 0;

        // Show device count for feedback
        var btCount = _audioRoutes.Count(r => r.IsBluetooth);
        TranscriptionLabel.Text = btCount > 0
            ? $"Found {btCount} Bluetooth device(s)"
            : "No Bluetooth devices found. Check pairing & permissions.";
    }

    private async void OnRefreshDevicesClicked(object sender, EventArgs e)
    {
        TranscriptionLabel.Text = "Scanning audio devices...";
        _audioRoutes = await _audioRouting.GetAvailableRoutesAsync();
        AudioDevicePicker.Items.Clear();
        foreach (var route in _audioRoutes)
            AudioDevicePicker.Items.Add(route.Name);
        AudioDevicePicker.SelectedIndex = 0;

        var btCount = _audioRoutes.Count(r => r.IsBluetooth);
        TranscriptionLabel.Text = btCount > 0
            ? $"Found {btCount} Bluetooth device(s)"
            : $"No BT devices. Log:\n{_audioRouting.LastLog}";
    }

    private async void OnAudioDeviceChanged(object? sender, EventArgs e)
    {
        if (AudioDevicePicker.SelectedIndex < 0 ||
            AudioDevicePicker.SelectedIndex >= _audioRoutes.Count) return;

        var route = _audioRoutes[AudioDevicePicker.SelectedIndex];
        await _audioRouting.ApplyRouteAsync(route);

#if ANDROID
        // Propagate preferred device to recorder and VAD
        if (_recorder != null)
            _recorder.PreferredInputDevice = _audioRouting.PreferredInputDevice;
        if (_vad != null)
            _vad.PreferredInputDevice = _audioRouting.PreferredInputDevice;
#endif

        StatusLabel.Text = route.IsBluetooth
            ? $"Audio: {route.Name}"
            : StatusLabel.Text;
    }

    protected override void OnDisappearing()
    {
        base.OnDisappearing();
        StopHandsFree();
        _audioRouting.Cleanup();
    }
}
