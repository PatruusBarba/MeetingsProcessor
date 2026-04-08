using BrainstormAssistant.Services;

namespace BrainstormAssistant.Tests;

public class ParakeetSttServiceTests : IDisposable
{
    private readonly ParakeetSttService _service;

    public ParakeetSttServiceTests()
    {
        _service = new ParakeetSttService(enabled: false);
    }

    public void Dispose()
    {
        _service.Dispose();
    }

    // --- ISttService interface compliance ---

    [Fact]
    public void ImplementsISttService()
    {
        Assert.IsAssignableFrom<ISttService>(_service);
    }

    [Fact]
    public void ImplementsIDisposable()
    {
        Assert.IsAssignableFrom<IDisposable>(_service);
    }

    // --- Constructor and initial state ---

    [Fact]
    public void Constructor_Disabled_IsEnabledFalse()
    {
        using var svc = new ParakeetSttService(enabled: false);

        Assert.False(svc.IsEnabled);
    }

    [Fact]
    public void Constructor_Enabled_IsEnabledTrue()
    {
        using var svc = new ParakeetSttService(enabled: true);

        Assert.True(svc.IsEnabled);
    }

    [Fact]
    public void Constructor_InitialState_NotListening()
    {
        Assert.False(_service.IsListening);
    }

    [Fact]
    public void IsEnabled_CanBeToggled()
    {
        _service.IsEnabled = true;
        Assert.True(_service.IsEnabled);

        _service.IsEnabled = false;
        Assert.False(_service.IsEnabled);
    }

    // --- StartListening / StopListening state ---

    [Fact]
    public void StartListening_WhenDisabled_DoesNotListen()
    {
        _service.IsEnabled = false;

        _service.StartListening();

        Assert.False(_service.IsListening);
    }

    [Fact]
    public void StopListening_WhenNotListening_DoesNotThrow()
    {
        // Should be a no-op, no exceptions
        var ex = Record.Exception(() => _service.StopListening());

        Assert.Null(ex);
    }

    // --- Event wiring ---

    [Fact]
    public void SpeechRecognized_CanSubscribeAndUnsubscribe()
    {
        var handler = new EventHandler<string>((s, e) => { });

        _service.SpeechRecognized += handler;
        _service.SpeechRecognized -= handler;
    }

    [Fact]
    public void PartialResult_CanSubscribeAndUnsubscribe()
    {
        var handler = new EventHandler<string>((s, e) => { });

        _service.PartialResult += handler;
        _service.PartialResult -= handler;
    }

    [Fact]
    public void ListeningStarted_CanSubscribeAndUnsubscribe()
    {
        var handler = new EventHandler((s, e) => { });

        _service.ListeningStarted += handler;
        _service.ListeningStarted -= handler;
    }

    [Fact]
    public void ListeningStopped_CanSubscribeAndUnsubscribe()
    {
        var handler = new EventHandler((s, e) => { });

        _service.ListeningStopped += handler;
        _service.ListeningStopped -= handler;
    }

    // --- Dispose ---

    [Fact]
    public void Dispose_MultipleCalls_DoesNotThrow()
    {
        using var svc = new ParakeetSttService(enabled: false);

        var ex = Record.Exception(() =>
        {
            svc.Dispose();
            svc.Dispose();
        });

        Assert.Null(ex);
    }

    // --- DecodeTokens logic ---

    [Fact]
    public void DecodeTokens_EmptyList_ReturnsEmpty()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, " hello" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int>());

        Assert.Equal("", result);
    }

    [Fact]
    public void DecodeTokens_SingleToken_ReturnsText()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, "hello" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 1 });

        Assert.Equal("hello", result);
    }

    [Fact]
    public void DecodeTokens_MultipleTokens_ConcatenatesCorrectly()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, " hello" },
            { 2, " world" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 1, 2 });

        Assert.Equal("hello world", result);
    }

    [Fact]
    public void DecodeTokens_SkipsBlankToken()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, "hello" },
            { 2, " world" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 0, 1, 0, 2 });

        Assert.Equal("hello world", result);
    }

    [Fact]
    public void DecodeTokens_SkipsSpecialTokens()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, "<|endoftext|>" },
            { 2, "hello" },
            { 3, "<|startoftranscript|>" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 3, 2, 1 });

        Assert.Equal("hello", result);
    }

    [Fact]
    public void DecodeTokens_HandlesWordBoundaryReplacement()
    {
        // The vocab loader replaces ▁ (U+2581) with space
        // By the time DecodeTokens sees the vocab, spaces are already there
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, " hello" },  // was "▁hello" before loading
            { 2, " world" }   // was "▁world" before loading
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 1, 2 });

        Assert.Equal("hello world", result);
    }

    [Fact]
    public void DecodeTokens_UnknownTokenId_Skipped()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, "hello" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        // Token ID 999 does not exist in vocab
        var result = _service.DecodeTokens(new List<int> { 1, 999 });

        Assert.Equal("hello", result);
    }

    [Fact]
    public void DecodeTokens_OnlyBlanks_ReturnsEmpty()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, "hello" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 0, 0, 0 });

        Assert.Equal("", result);
    }

    [Fact]
    public void DecodeTokens_TrimsLeadingAndTrailingWhitespace()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, " hello " }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 1 });

        Assert.Equal("hello", result);
    }

    [Fact]
    public void DecodeTokens_CollapsesMultipleSpaces()
    {
        var vocab = new Dictionary<int, string>
        {
            { 0, "<blk>" },
            { 1, " hello " },
            { 2, "  world" }
        };
        _service.SetVocabForTesting(vocab, blankIdx: 0);

        var result = _service.DecodeTokens(new List<int> { 1, 2 });

        Assert.Equal("hello world", result);
    }

    // --- StartListening with models missing ---

    [Fact]
    public void StartListening_WhenEnabled_ModelsNotPresent_ThrowsInvalidOperationException()
    {
        using var svc = new ParakeetSttService(enabled: true);

        // Models are not downloaded in test env, so this should throw
        // (unless models happen to be present, which is unlikely)
        if (!ModelDownloader.AllModelsPresent())
        {
            var ex = Assert.Throws<InvalidOperationException>(() => svc.StartListening());
            Assert.Contains("models", ex.Message, StringComparison.OrdinalIgnoreCase);
        }
    }
}
