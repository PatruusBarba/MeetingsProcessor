namespace BrainstormCompanion.Services;

/// <summary>
/// Records audio from the device microphone using Android AudioRecord API.
/// Produces 16kHz mono 16-bit PCM WAV data compatible with the PC-side Parakeet STT service.
/// </summary>
public class AudioRecorderService
{
#if ANDROID
    private Android.Media.AudioRecord? _audioRecord;
    private System.IO.MemoryStream? _buffer;
    private bool _isRecording;
    private Task? _recordingTask;

    private const int SampleRate = 16000;
    private const Android.Media.ChannelIn Channel = Android.Media.ChannelIn.Mono;
    private const Android.Media.Encoding Encoding = Android.Media.Encoding.Pcm16bit;

    /// <summary>Optional preferred input device (e.g. Bluetooth earpiece mic).</summary>
    public Android.Media.AudioDeviceInfo? PreferredInputDevice { get; set; }

    public async Task StartRecordingAsync()
    {
        // Request microphone permission at runtime
        var status = await Permissions.CheckStatusAsync<Permissions.Microphone>();
        if (status != PermissionStatus.Granted)
        {
            status = await Permissions.RequestAsync<Permissions.Microphone>();
            if (status != PermissionStatus.Granted)
                throw new InvalidOperationException("Microphone permission denied");
        }

        var bufferSize = Android.Media.AudioRecord.GetMinBufferSize(SampleRate, Channel, Encoding);
        if (bufferSize <= 0)
            bufferSize = 4096;

        // Use VoiceCommunication source for Bluetooth SCO, Mic for default
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
            throw new InvalidOperationException("Failed to initialize microphone. Check permissions in Android Settings.");
        }

        _buffer = new MemoryStream();
        _isRecording = true;

        _audioRecord.StartRecording();

        _recordingTask = Task.Run(() =>
        {
            var readBuffer = new byte[bufferSize];
            while (_isRecording)
            {
                int bytesRead = _audioRecord.Read(readBuffer, 0, readBuffer.Length);
                if (bytesRead > 0)
                    _buffer.Write(readBuffer, 0, bytesRead);
            }
        });
    }

    public async Task<byte[]> StopRecordingAsync()
    {
        _isRecording = false;

        if (_recordingTask != null)
            await _recordingTask;

        _audioRecord?.Stop();
        _audioRecord?.Release();
        _audioRecord = null;

        if (_buffer == null) return Array.Empty<byte>();

        var pcmData = _buffer.ToArray();
        _buffer.Dispose();
        _buffer = null;

        return CreateWav(pcmData);
    }

    private static byte[] CreateWav(byte[] pcmData)
    {
        using var ms = new MemoryStream();
        using var writer = new BinaryWriter(ms);

        int dataSize = pcmData.Length;
        int fileSize = 36 + dataSize;

        // RIFF header
        writer.Write(System.Text.Encoding.ASCII.GetBytes("RIFF"));
        writer.Write(fileSize);
        writer.Write(System.Text.Encoding.ASCII.GetBytes("WAVE"));

        // fmt sub-chunk
        writer.Write(System.Text.Encoding.ASCII.GetBytes("fmt "));
        writer.Write(16);           // Sub-chunk size
        writer.Write((short)1);     // PCM format
        writer.Write((short)1);     // Mono
        writer.Write(SampleRate);
        writer.Write(SampleRate * 2); // Byte rate (16-bit mono)
        writer.Write((short)2);     // Block align
        writer.Write((short)16);    // Bits per sample

        // data sub-chunk
        writer.Write(System.Text.Encoding.ASCII.GetBytes("data"));
        writer.Write(dataSize);
        writer.Write(pcmData);

        return ms.ToArray();
    }
#else
    public Task StartRecordingAsync() => Task.CompletedTask;
    public Task<byte[]> StopRecordingAsync() => Task.FromResult(Array.Empty<byte>());
#endif
}
