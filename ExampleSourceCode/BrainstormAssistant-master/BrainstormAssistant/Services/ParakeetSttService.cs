using System.IO;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using NAudio.Wave;

namespace BrainstormAssistant.Services;

/// <summary>
/// Speech-to-text using NVIDIA Parakeet TDT v3 ONNX model with NAudio mic capture.
/// Pipeline: NAudio mic (16kHz mono) -> silence detection -> nemo128.onnx preprocessor 
///           -> encoder -> TDT decoder -> vocab lookup -> text
/// </summary>
public class ParakeetSttService : ISttService, IDisposable
{
    private const int SampleRate = 16000;
    private const int BitsPerSample = 16;
    private const int Channels = 1;

    // Silence detection parameters
    private const float SilenceThreshold = 0.01f;
    private const int MinSpeechMs = 500;       // min speech before we consider it valid
    private const int SilenceAfterSpeechMs = 1200; // silence after speech to trigger recognition
    private const int MaxRecordingMs = 25000;  // max single utterance (model limit ~30s)

    private WaveInEvent? _waveIn;
    private MemoryStream? _audioBuffer;
    private BinaryWriter? _audioWriter;
    private bool _isListening;
    private bool _disposed;
    private bool _isPaused;
    private bool _isSpeaking;
    private int _silenceSamples;
    private int _speechSamples;
    private readonly object _lock = new();

    // ONNX sessions
    private InferenceSession? _preprocessor;
    private InferenceSession? _encoder;
    private InferenceSession? _decoderJoint;

    // Vocab
    private Dictionary<int, string>? _vocab;
    private int _vocabSize;
    private int _blankIdx = -1;

    public event EventHandler<string>? SpeechRecognized;
    public event EventHandler<string>? PartialResult;
    public event EventHandler? ListeningStarted;
    public event EventHandler? ListeningStopped;

    public bool IsListening => _isListening;
    public bool IsEnabled { get; set; }

    public int DeviceNumber { get; set; }

    public ParakeetSttService(bool enabled, string? microphoneDevice = null)
    {
        IsEnabled = enabled;
        DeviceNumber = ResolveDeviceNumber(microphoneDevice);
    }

    private static int ResolveDeviceNumber(string? deviceName)
    {
        if (string.IsNullOrWhiteSpace(deviceName)) return 0;
        for (int i = 0; i < WaveInEvent.DeviceCount; i++)
        {
            var caps = WaveInEvent.GetCapabilities(i);
            if (caps.ProductName == deviceName) return i;
        }
        return 0;
    }

    /// <summary>
    /// Sets vocab dictionary for testing DecodeTokens without loading ONNX models.
    /// </summary>
    internal void SetVocabForTesting(Dictionary<int, string> vocab, int blankIdx)
    {
        _vocab = vocab;
        _blankIdx = blankIdx;
        _vocabSize = vocab.Count;
    }

    private void EnsureModelsLoaded()
    {
        if (_preprocessor != null) return;

        if (!ModelDownloader.AllModelsPresent())
            throw new InvalidOperationException(
                "Parakeet ONNX models not downloaded. Go to Settings to download them.");

        var opts = new SessionOptions();
        opts.InterOpNumThreads = 1;
        opts.IntraOpNumThreads = Environment.ProcessorCount;
        opts.GraphOptimizationLevel = GraphOptimizationLevel.ORT_ENABLE_ALL;

        _preprocessor = new InferenceSession(
            ModelDownloader.GetModelPath("nemo128.onnx"), opts);

        _encoder = new InferenceSession(
            ModelDownloader.GetModelPath("encoder-model.int8.onnx"), opts);

        _decoderJoint = new InferenceSession(
            ModelDownloader.GetModelPath("decoder_joint-model.int8.onnx"), opts);

        LoadVocab();
    }

    private void LoadVocab()
    {
        var vocabPath = ModelDownloader.GetModelPath("vocab.txt");
        _vocab = new Dictionary<int, string>();
        foreach (var line in File.ReadAllLines(vocabPath))
        {
            var parts = line.Trim().Split(' ', 2);
            if (parts.Length == 2 && int.TryParse(parts[1], out var id))
            {
                var token = parts[0].Replace("\u2581", " ");
                _vocab[id] = token;
                if (token == "<blk>")
                    _blankIdx = id;
            }
        }
        _vocabSize = _vocab.Count;
    }

    public void StartListening()
    {
        if (_isListening || !IsEnabled) return;

        try
        {
            EnsureModelsLoaded();

            _waveIn = new WaveInEvent
            {
                DeviceNumber = DeviceNumber,
                WaveFormat = new WaveFormat(SampleRate, BitsPerSample, Channels),
                BufferMilliseconds = 100
            };

            ResetAudioBuffer();

            _waveIn.DataAvailable += OnDataAvailable;
            _waveIn.RecordingStopped += OnRecordingStopped;
            _waveIn.StartRecording();

            _isListening = true;
            ListeningStarted?.Invoke(this, EventArgs.Empty);
        }
        catch (Exception ex)
        {
            _isListening = false;
            throw new InvalidOperationException(
                $"Failed to start speech recognition: {ex.Message}", ex);
        }
    }

    public void StopListening()
    {
        if (!_isListening) return;

        _isListening = false;

        try
        {
            _waveIn?.StopRecording();
        }
        catch { }

        // Process any remaining audio
        ProcessBufferedAudio();

        CleanupWaveIn();
        ListeningStopped?.Invoke(this, EventArgs.Empty);
    }

    /// <summary>
    /// Temporarily pause audio capture (e.g. while TTS is speaking to avoid feedback).
    /// </summary>
    public void PauseListening()
    {
        if (!_isListening || _isPaused) return;
        _isPaused = true;
        ResetAudioBuffer();
    }

    /// <summary>
    /// Resume audio capture after pause.
    /// </summary>
    public void ResumeListening()
    {
        if (!_isListening || !_isPaused) return;
        _isPaused = false;
        ResetAudioBuffer();
    }

    private void ResetAudioBuffer()
    {
        lock (_lock)
        {
            _audioBuffer = new MemoryStream();
            _audioWriter = new BinaryWriter(_audioBuffer);
            _isSpeaking = false;
            _silenceSamples = 0;
            _speechSamples = 0;
        }
    }

    private void OnDataAvailable(object? sender, WaveInEventArgs e)
    {
        if (!_isListening || _disposed || _isPaused) return;

        lock (_lock)
        {
            if (_audioBuffer == null || _audioWriter == null) return;

            // Convert bytes to float samples and check for speech
            int sampleCount = e.BytesRecorded / 2; // 16-bit samples
            float maxAmp = 0;
            for (int i = 0; i < e.BytesRecorded; i += 2)
            {
                if (i + 1 < e.BytesRecorded)
                {
                    short sample = (short)(e.Buffer[i] | (e.Buffer[i + 1] << 8));
                    float normalized = Math.Abs(sample / 32768f);
                    if (normalized > maxAmp) maxAmp = normalized;
                }
            }

            bool hasSpeech = maxAmp > SilenceThreshold;

            if (hasSpeech)
            {
                _isSpeaking = true;
                _silenceSamples = 0;
                _speechSamples += sampleCount;
                _audioWriter.Write(e.Buffer, 0, e.BytesRecorded);

                // Partial feedback
                PartialResult?.Invoke(this, "[speaking...]");
            }
            else if (_isSpeaking)
            {
                // Still write silence to buffer (for natural speech gaps)
                _audioWriter.Write(e.Buffer, 0, e.BytesRecorded);
                _silenceSamples += sampleCount;

                int silenceMs = _silenceSamples * 1000 / SampleRate;
                int totalMs = (int)(_audioBuffer.Length / 2) * 1000 / SampleRate;

                if (silenceMs >= SilenceAfterSpeechMs || totalMs >= MaxRecordingMs)
                {
                    // End of utterance detected
                    if (_speechSamples * 1000 / SampleRate >= MinSpeechMs)
                    {
                        ProcessBufferedAudio();
                    }
                    ResetAudioBuffer();
                }
            }
        }
    }

    public event EventHandler<string>? RecognitionError;

    /// <summary>
    /// Transcribes a WAV byte array (16kHz 16-bit mono PCM) to text.
    /// Used by CompanionServer for one-shot transcription.
    /// </summary>
    public string TranscribeWav(byte[] wavData)
    {
        EnsureModelsLoaded();

        // Strip WAV header (44 bytes for standard RIFF/PCM)
        byte[] pcmData;
        if (wavData.Length > 44
            && wavData[0] == 'R' && wavData[1] == 'I'
            && wavData[2] == 'F' && wavData[3] == 'F')
        {
            // Find "data" chunk
            int dataOffset = 12;
            while (dataOffset + 8 < wavData.Length)
            {
                var chunkId = System.Text.Encoding.ASCII.GetString(wavData, dataOffset, 4);
                int chunkSize = BitConverter.ToInt32(wavData, dataOffset + 4);
                if (chunkId == "data")
                {
                    dataOffset += 8;
                    pcmData = new byte[chunkSize];
                    Array.Copy(wavData, dataOffset, pcmData, 0, Math.Min(chunkSize, wavData.Length - dataOffset));
                    return RecognizeAudio(pcmData);
                }
                dataOffset += 8 + chunkSize;
            }
            // Fallback: skip first 44 bytes
            pcmData = new byte[wavData.Length - 44];
            Array.Copy(wavData, 44, pcmData, 0, pcmData.Length);
        }
        else
        {
            // Assume raw PCM
            pcmData = wavData;
        }

        return RecognizeAudio(pcmData);
    }

    private void ProcessBufferedAudio()
    {
        byte[] audioData;
        lock (_lock)
        {
            if (_audioBuffer == null || _audioBuffer.Length < SampleRate) // at least 0.5s
                return;

            audioData = _audioBuffer.ToArray();
        }

        // Run recognition in background to not block audio capture
        Task.Run(() =>
        {
            try
            {
                PartialResult?.Invoke(this, "[recognizing...]");
                var text = RecognizeAudio(audioData);
                if (!string.IsNullOrWhiteSpace(text))
                {
                    SpeechRecognized?.Invoke(this, text.Trim());
                }
                else
                {
                    PartialResult?.Invoke(this, "");
                }
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine($"Recognition error: {ex}");
                RecognitionError?.Invoke(this, ex.Message);
            }
        });
    }

    private string RecognizeAudio(byte[] pcmData)
    {
        if (_preprocessor == null || _encoder == null || _decoderJoint == null || _vocab == null)
            return "";

        // Convert 16-bit PCM to float32 normalized
        int sampleCount = pcmData.Length / 2;
        var waveform = new float[sampleCount];
        for (int i = 0; i < sampleCount; i++)
        {
            short sample = (short)(pcmData[i * 2] | (pcmData[i * 2 + 1] << 8));
            waveform[i] = sample / 32768f;
        }

        // Step 1: Preprocessor - compute log-mel spectrogram
        var waveformTensor = new DenseTensor<float>(waveform, new[] { 1, sampleCount });
        var waveformLensTensor = new DenseTensor<long>(new[] { (long)sampleCount }, new[] { 1 });

        var prepInputs = new List<NamedOnnxValue>
        {
            NamedOnnxValue.CreateFromTensor("waveforms", waveformTensor),
            NamedOnnxValue.CreateFromTensor("waveforms_lens", waveformLensTensor)
        };

        float[] features;
        int[] featuresShape;
        long featuresLen;

        using (var prepResults = _preprocessor.Run(prepInputs))
        {
            var featuresTensor = prepResults.First(r => r.Name == "features").AsTensor<float>();
            var featuresLensTensor = prepResults.First(r => r.Name == "features_lens").AsTensor<long>();

            featuresShape = featuresTensor.Dimensions.ToArray();
            features = featuresTensor.ToArray();
            featuresLen = featuresLensTensor.ToArray()[0];
        }

        // Step 2: Encoder
        var audioSignalTensor = new DenseTensor<float>(features, featuresShape);
        var lengthTensor = new DenseTensor<long>(new[] { featuresLen }, new[] { 1 });

        var encInputs = new List<NamedOnnxValue>
        {
            NamedOnnxValue.CreateFromTensor("audio_signal", audioSignalTensor),
            NamedOnnxValue.CreateFromTensor("length", lengthTensor)
        };

        float[] encoderOut;
        int[] encoderOutShape;
        long encoderOutLen;

        using (var encResults = _encoder.Run(encInputs))
        {
            var outputsTensor = encResults.First(r => r.Name == "outputs").AsTensor<float>();
            var encodedLenTensor = encResults.First(r => r.Name == "encoded_lengths").AsTensor<long>();

            encoderOutShape = outputsTensor.Dimensions.ToArray();
            encoderOut = outputsTensor.ToArray();
            encoderOutLen = encodedLenTensor.ToArray()[0];
        }

        // Step 3: TDT Greedy Decoding
        return TdtGreedyDecode(encoderOut, encoderOutShape, encoderOutLen);
    }

    private string TdtGreedyDecode(float[] encoderOut, int[] shape, long encoderOutLen)
    {
        if (_decoderJoint == null || _vocab == null)
            return "";

        // encoderOut shape: [batch=1, dim, time] - we need [batch, time, dim] for indexing
        // Actually NeMo encoder outputs [batch, dim, time], and onnx-asr transposes to [batch, time, dim]
        int batch = shape[0];
        int dim = shape[1];
        int timeSteps = shape[2];

        // Transpose to [time, dim] for easy indexing
        var encoderOutTransposed = new float[timeSteps * dim];
        for (int t = 0; t < timeSteps; t++)
        {
            for (int d = 0; d < dim; d++)
            {
                encoderOutTransposed[t * dim + d] = encoderOut[d * timeSteps + t];
            }
        }

        // Get decoder state shape from model inputs
        var decoderInputs = _decoderJoint.InputMetadata;
        var state1Shape = decoderInputs["input_states_1"].Dimensions;
        var state2Shape = decoderInputs["input_states_2"].Dimensions;

        // Initialize decoder states with zeros
        var state1 = new float[state1Shape[0] * 1 * state1Shape[2]];
        var state1Dims = new[] { state1Shape[0], 1, state1Shape[2] };

        var state2 = new float[state2Shape[0] * 1 * state2Shape[2]];
        var state2Dims = new[] { state2Shape[0], 1, state2Shape[2] };

        var tokens = new List<int>();
        int maxTokensPerStep = 10;

        int t_pos = 0;
        int emittedTokens = 0;

        while (t_pos < encoderOutLen)
        {
            // Extract encoder output at time t: shape [1, dim, 1]
            var encSlice = new float[dim];
            Array.Copy(encoderOutTransposed, t_pos * dim, encSlice, 0, dim);

            var encoderOutputTensor = new DenseTensor<float>(
                encSlice.Select((v, i) => v).ToArray(),
                new[] { 1, dim, 1 });

            int prevToken = tokens.Count > 0 ? tokens[^1] : _blankIdx;
            var targetsTensor = new DenseTensor<int>(new[] { prevToken }, new[] { 1, 1 });
            var targetLenTensor = new DenseTensor<int>(new[] { 1 }, new[] { 1 });
            var state1Tensor = new DenseTensor<float>((float[])state1.Clone(), state1Dims);
            var state2Tensor = new DenseTensor<float>((float[])state2.Clone(), state2Dims);

            var decInputs = new List<NamedOnnxValue>
            {
                NamedOnnxValue.CreateFromTensor("encoder_outputs", encoderOutputTensor),
                NamedOnnxValue.CreateFromTensor("targets", targetsTensor),
                NamedOnnxValue.CreateFromTensor("target_length", targetLenTensor),
                NamedOnnxValue.CreateFromTensor("input_states_1", state1Tensor),
                NamedOnnxValue.CreateFromTensor("input_states_2", state2Tensor)
            };

            using var decResults = _decoderJoint.Run(decInputs);

            var outputTensor = decResults.First(r => r.Name == "outputs").AsTensor<float>();
            var outState1 = decResults.First(r => r.Name == "output_states_1").AsTensor<float>();
            var outState2 = decResults.First(r => r.Name == "output_states_2").AsTensor<float>();

            // Output shape is [B, 1, 1, vocab_size+duration_size] — use last dim size
            var output = outputTensor.ToArray();
            int jointSize = outputTensor.Dimensions[^1];

            // TDT: first vocab_size elements are token logits, 
            // remaining elements are duration logits
            var tokenLogits = new float[_vocabSize];
            Array.Copy(output, 0, tokenLogits, 0, _vocabSize);

            int durationSize = jointSize - _vocabSize;
            var durationLogits = new float[durationSize];
            Array.Copy(output, _vocabSize, durationLogits, 0, durationSize);

            // Find best token
            int bestToken = 0;
            float bestScore = tokenLogits[0];
            for (int i = 1; i < _vocabSize; i++)
            {
                if (tokenLogits[i] > bestScore)
                {
                    bestScore = tokenLogits[i];
                    bestToken = i;
                }
            }

            // Find best duration
            int bestDuration = 0;
            float bestDurScore = durationLogits[0];
            for (int i = 1; i < durationSize; i++)
            {
                if (durationLogits[i] > bestDurScore)
                {
                    bestDurScore = durationLogits[i];
                    bestDuration = i;
                }
            }

            if (bestToken != _blankIdx)
            {
                // Update state
                state1 = outState1.ToArray();
                state2 = outState2.ToArray();
                tokens.Add(bestToken);
                emittedTokens++;
            }

            // Advance time
            if (bestDuration > 0)
            {
                t_pos += bestDuration;
                emittedTokens = 0;
            }
            else if (bestToken == _blankIdx || emittedTokens >= maxTokensPerStep)
            {
                t_pos += 1;
                emittedTokens = 0;
            }
        }

        // Decode tokens to text
        return DecodeTokens(tokens);
    }

    internal string DecodeTokens(List<int> tokenIds)
    {
        if (_vocab == null) return "";

        var parts = new List<string>();
        foreach (var id in tokenIds)
        {
            if (_vocab.TryGetValue(id, out var token))
            {
                if (!token.StartsWith("<|") && token != "<blk>")
                    parts.Add(token);
            }
        }

        var text = string.Join("", parts);
        // Clean up extra spaces
        text = System.Text.RegularExpressions.Regex.Replace(text, @"^\s+", "");
        text = System.Text.RegularExpressions.Regex.Replace(text, @"\s+", " ");
        return text.Trim();
    }

    private void OnRecordingStopped(object? sender, StoppedEventArgs e)
    {
        if (_isListening && !_disposed)
        {
            // Unexpected stop - try to restart
            try
            {
                _waveIn?.StartRecording();
            }
            catch
            {
                _isListening = false;
                ListeningStopped?.Invoke(this, EventArgs.Empty);
            }
        }
    }

    private void CleanupWaveIn()
    {
        if (_waveIn != null)
        {
            _waveIn.DataAvailable -= OnDataAvailable;
            _waveIn.RecordingStopped -= OnRecordingStopped;
            try { _waveIn.Dispose(); }
            catch { }
            _waveIn = null;
        }

        lock (_lock)
        {
            _audioWriter?.Dispose();
            _audioBuffer?.Dispose();
            _audioWriter = null;
            _audioBuffer = null;
        }
    }

    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        StopListening();
        _preprocessor?.Dispose();
        _encoder?.Dispose();
        _decoderJoint?.Dispose();
    }
}
