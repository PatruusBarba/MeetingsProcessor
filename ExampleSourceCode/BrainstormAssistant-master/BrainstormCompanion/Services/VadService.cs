namespace BrainstormCompanion.Services;

/// <summary>
/// Voice Activity Detection (VAD) using energy-based speech detection.
/// Monitors the microphone continuously and raises events when speech starts/stops.
/// Uses RMS energy threshold with adaptive noise floor estimation.
/// </summary>
public class VadService
{
    /// <summary>Raised when speech is detected (transition from silence → speech).</summary>
    public event Action? SpeechStarted;

    /// <summary>Raised when speech ends (silence exceeds timeout after speech).</summary>
    public event Action<byte[]>? SpeechEnded;

    /// <summary>RMS energy threshold multiplier above noise floor to trigger speech detection.</summary>
    public double ThresholdMultiplier { get; set; } = 3.0;

    /// <summary>How long silence must persist after speech to consider utterance complete (ms).</summary>
    public int SilenceTimeoutMs { get; set; } = 1500;

    /// <summary>Minimum speech duration to count as valid utterance (ms).</summary>
    public int MinSpeechDurationMs { get; set; } = 300;

    /// <summary>Raised when VAD fails to start (e.g. permission denied).</summary>
    public event Action<string>? Error;

    private bool _isListening;

    /// <summary>When true, VAD ignores all audio (used to prevent feedback from TTS playback).</summary>
    public bool IsPaused { get; set; }

#if ANDROID
    private Android.Media.AudioRecord? _audioRecord;
    private Task? _listenTask;

    private const int SampleRate = 16000;
    private const Android.Media.ChannelIn Channel = Android.Media.ChannelIn.Mono;
    private const Android.Media.Encoding Encoding = Android.Media.Encoding.Pcm16bit;

    /// <summary>Optional preferred input device (e.g. Bluetooth earpiece mic).</summary>
    public Android.Media.AudioDeviceInfo? PreferredInputDevice { get; set; }

    public async void Start()
    {
        if (_isListening) return;

        // Request microphone permission at runtime
        var status = await Permissions.CheckStatusAsync<Permissions.Microphone>();
        if (status != PermissionStatus.Granted)
        {
            status = await Permissions.RequestAsync<Permissions.Microphone>();
            if (status != PermissionStatus.Granted)
            {
                Error?.Invoke("Microphone permission denied");
                return;
            }
        }

        var bufferSize = Android.Media.AudioRecord.GetMinBufferSize(SampleRate, Channel, Encoding);
        if (bufferSize <= 0)
            bufferSize = 4096;

        var source = PreferredInputDevice?.Type == Android.Media.AudioDeviceType.BluetoothSco
            ? Android.Media.AudioSource.VoiceCommunication
            : Android.Media.AudioSource.Mic;

        _audioRecord = new Android.Media.AudioRecord(
            source, SampleRate, Channel, Encoding, bufferSize);

        if (PreferredInputDevice != null)
            _audioRecord.SetPreferredDevice(PreferredInputDevice);

        if (_audioRecord.State != Android.Media.State.Initialized)
        {
            _audioRecord.Release();
            _audioRecord = null;
            Error?.Invoke("Failed to initialize microphone");
            return;
        }

        _isListening = true;
        _audioRecord.StartRecording();
        _listenTask = Task.Run(() => ListenLoop(bufferSize));
    }

    public void Stop()
    {
        _isListening = false;
        _listenTask?.Wait(2000);
        _audioRecord?.Stop();
        _audioRecord?.Release();
        _audioRecord = null;
    }

    private void ListenLoop(int bufferSize)
    {
        var readBuffer = new byte[bufferSize];
        var speechBuffer = new MemoryStream();
        double noiseFloor = 0;
        int noiseFrames = 0;
        bool inSpeech = false;
        long lastSpeechTime = 0;
        long speechStartTime = 0;

        // Calibrate noise floor from first ~0.5s
        const int calibrationFrames = 8;

        while (_isListening)
        {
            int bytesRead = _audioRecord!.Read(readBuffer, 0, readBuffer.Length);
            if (bytesRead <= 0) continue;

            // Skip processing while TTS is playing to avoid feedback loop
            if (IsPaused)
            {
                // Reset speech state so TTS audio doesn't merge with next utterance
                if (inSpeech)
                {
                    inSpeech = false;
                    speechBuffer.Dispose();
                    speechBuffer = new MemoryStream();
                }
                continue;
            }

            double rms = CalculateRms(readBuffer, bytesRead);
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

            // Noise floor calibration
            if (noiseFrames < calibrationFrames)
            {
                noiseFloor = (noiseFloor * noiseFrames + rms) / (noiseFrames + 1);
                noiseFrames++;
                continue;
            }

            // Adaptive noise floor (slow decay towards current level when not speaking)
            double threshold = Math.Max(noiseFloor * ThresholdMultiplier, 300);
            bool isSpeech = rms > threshold;

            if (isSpeech)
            {
                lastSpeechTime = now;

                if (!inSpeech)
                {
                    inSpeech = true;
                    speechStartTime = now;
                    speechBuffer = new MemoryStream();
                    SpeechStarted?.Invoke();
                }

                speechBuffer.Write(readBuffer, 0, bytesRead);
            }
            else if (inSpeech)
            {
                speechBuffer.Write(readBuffer, 0, bytesRead);

                if (now - lastSpeechTime > SilenceTimeoutMs)
                {
                    inSpeech = false;
                    long duration = now - speechStartTime;

                    if (duration >= MinSpeechDurationMs)
                    {
                        var pcm = speechBuffer.ToArray();
                        var wav = CreateWav(pcm);
                        SpeechEnded?.Invoke(wav);
                    }

                    speechBuffer.Dispose();
                    speechBuffer = new MemoryStream();
                }

                // Update noise floor slowly during silence
                noiseFloor = noiseFloor * 0.95 + rms * 0.05;
            }
            else
            {
                // Pure silence — adapt noise floor
                noiseFloor = noiseFloor * 0.95 + rms * 0.05;
            }
        }

        speechBuffer.Dispose();
    }

    private static double CalculateRms(byte[] buffer, int length)
    {
        double sum = 0;
        int samples = length / 2;
        for (int i = 0; i < length - 1; i += 2)
        {
            short sample = (short)(buffer[i] | (buffer[i + 1] << 8));
            sum += sample * sample;
        }
        return samples > 0 ? Math.Sqrt(sum / samples) : 0;
    }

    private static byte[] CreateWav(byte[] pcmData)
    {
        using var ms = new MemoryStream();
        using var writer = new BinaryWriter(ms);

        int dataSize = pcmData.Length;
        int fileSize = 36 + dataSize;

        writer.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));
        writer.Write(fileSize);
        writer.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"));
        writer.Write(System.Text.Encoding.ASCII.GetBytes("fmt "));
        writer.Write(16);
        writer.Write((short)1);
        writer.Write((short)1);
        writer.Write(SampleRate);
        writer.Write(SampleRate * 2);
        writer.Write((short)2);
        writer.Write((short)16);
        writer.Write(System.Text.Encoding.ASCII.GetBytes("data"));
        writer.Write(dataSize);
        writer.Write(pcmData);

        return ms.ToArray();
    }
#else
    public void Start() { }
    public void Stop() { }
#endif
}
