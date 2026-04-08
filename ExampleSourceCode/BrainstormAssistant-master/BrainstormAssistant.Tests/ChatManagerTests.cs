using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using Moq;

namespace BrainstormAssistant.Tests;

public class ChatManagerTests : IDisposable
{
    private readonly Mock<ILlmService> _mockLlm;
    private readonly SessionManager _sessionManager;
    private readonly string _testDir;
    private readonly ChatManager _chatManager;

    public ChatManagerTests()
    {
        _mockLlm = new Mock<ILlmService>();
        _testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_chat_test_{Guid.NewGuid():N}");
        _sessionManager = new SessionManager(_testDir);
        _chatManager = new ChatManager(_mockLlm.Object, _sessionManager);
    }

    public void Dispose()
    {
        if (Directory.Exists(_testDir))
            Directory.Delete(_testDir, true);
    }

    /// <summary>Helper to create a ChatCompletionResponse with text content.</summary>
    private static ChatCompletionResponse TextResponse(string content) => new()
    {
        choices = new List<Choice>
        {
            new Choice { message = new ResponseMessage { content = content } }
        }
    };

    /// <summary>Sets up ChatStreamAsync mock to return a simple text response.</summary>
    private void SetupChatWithTools(string response)
    {
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(TextResponse(response));
    }

    [Fact]
    public async Task SendMessageAsync_StoresUserAndAssistantMessages()
    {
        SetupChatWithTools("Great idea!");

        var response = await _chatManager.SendMessageAsync("I want to build an app");

        Assert.Equal("Great idea!", response);
        // user + assistant (tool call/result messages are internal)
        var visibleMessages = _chatManager.CurrentSession.Messages
            .Where(m => m.Role == "user" || (m.Role == "assistant" && m.ToolCalls == null)).ToList();
        Assert.Equal(2, visibleMessages.Count);
        Assert.Equal("user", visibleMessages[0].Role);
        Assert.Equal("I want to build an app", visibleMessages[0].Content);
        Assert.Equal("assistant", visibleMessages[1].Role);
    }

    [Fact]
    public async Task SendMessageAsync_IncludesSystemPromptInLlmCall()
    {
        List<ChatMessage>? capturedMessages = null;
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .Callback<List<ChatMessage>, List<ToolDefinition>?, Action<string>?, Action<int, string>?, CancellationToken>(
                (msgs, _, _, _, _) => capturedMessages = msgs)
            .ReturnsAsync(TextResponse("Response"));

        await _chatManager.SendMessageAsync("Hello");

        Assert.NotNull(capturedMessages);
        Assert.Equal("system", capturedMessages![0].Role);
        Assert.Contains("brainstorm", capturedMessages[0].Content.ToLower());
    }

    [Fact]
    public async Task SendMessageAsync_IncludesConversationHistory()
    {
        SetupChatWithTools("Response");

        await _chatManager.SendMessageAsync("Message 1");

        List<ChatMessage>? secondCallMessages = null;
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .Callback<List<ChatMessage>, List<ToolDefinition>?, Action<string>?, Action<int, string>?, CancellationToken>(
                (msgs, _, _, _, _) => secondCallMessages = msgs)
            .ReturnsAsync(TextResponse("Response 2"));

        await _chatManager.SendMessageAsync("Message 2");

        // system + msg1 + resp1 + msg2
        Assert.NotNull(secondCallMessages);
        Assert.Equal(4, secondCallMessages!.Count);
    }

    [Fact]
    public async Task EvaluateIdeaAsync_CallsLlmEvaluate()
    {
        SetupChatWithTools("OK");
        _mockLlm.Setup(l => l.EvaluateIdeaAsync(It.IsAny<List<ChatMessage>>()))
            .ReturnsAsync("{\"viabilityScore\": 7}");

        await _chatManager.SendMessageAsync("My idea");
        var result = await _chatManager.EvaluateIdeaAsync();

        Assert.Contains("viabilityScore", result);
        _mockLlm.Verify(l => l.EvaluateIdeaAsync(It.IsAny<List<ChatMessage>>()), Times.Once);
    }

    [Fact]
    public async Task GenerateSummaryAsync_SetsSummaryOnSession()
    {
        SetupChatWithTools("Summary of the session");

        await _chatManager.SendMessageAsync("Test idea");

        _mockLlm.Setup(l => l.ChatAsync(It.IsAny<List<ChatMessage>>()))
            .ReturnsAsync("Session summary here");

        var summary = await _chatManager.GenerateSummaryAsync();

        Assert.Equal("Session summary here", summary);
        Assert.Equal("Session summary here", _chatManager.CurrentSession.Summary);
    }

    [Fact]
    public void SaveCurrentSession_PersistsToDisk()
    {
        _chatManager.CurrentSession.Messages.Add(new ChatMessage("user", "Test"));
        _chatManager.SaveCurrentSession();

        var loaded = _sessionManager.LoadSession(_chatManager.CurrentSession.Id);

        Assert.NotNull(loaded);
        Assert.Single(loaded!.Messages);
    }

    [Fact]
    public void SetSessionTitle_UpdatesTitle()
    {
        _chatManager.SetSessionTitle("New Title");

        Assert.Equal("New Title", _chatManager.CurrentSession.Title);
    }

    [Fact]
    public void MessageCount_ReturnsCorrectCount()
    {
        Assert.Equal(0, _chatManager.MessageCount);

        _chatManager.CurrentSession.Messages.Add(new ChatMessage("user", "msg"));

        Assert.Equal(1, _chatManager.MessageCount);
    }

    [Fact]
    public void Constructor_WithExistingSession_UsesIt()
    {
        var existing = new Session { Id = "existing-id", Title = "Existing" };
        existing.Messages.Add(new ChatMessage("user", "Previous"));

        var cm = new ChatManager(_mockLlm.Object, _sessionManager, existing);

        Assert.Equal("existing-id", cm.CurrentSession.Id);
        Assert.Equal(1, cm.MessageCount);
    }

    [Fact]
    public void StartNewSession_SavesCurrentAndCreatesNew()
    {
        _chatManager.CurrentSession.Messages.Add(new ChatMessage("user", "Old message"));
        var oldId = _chatManager.CurrentSession.Id;

        _chatManager.StartNewSession("Fresh Start");

        Assert.NotEqual(oldId, _chatManager.CurrentSession.Id);
        Assert.Equal("Fresh Start", _chatManager.CurrentSession.Title);
        Assert.Empty(_chatManager.CurrentSession.Messages);

        // Old session was saved
        var oldSession = _sessionManager.LoadSession(oldId);
        Assert.NotNull(oldSession);
    }

    [Fact]
    public void SystemPrompt_ContainsKeyBehaviors()
    {
        var prompt = ChatManager.SystemPrompt;

        Assert.Contains("brainstorm", prompt.ToLower());
        Assert.Contains("honest", prompt.ToLower());
        Assert.Contains("monetization", prompt.ToLower());
        Assert.Contains("yes-man", prompt.ToLower());
        Assert.Contains("viability", prompt.ToLower());
    }

    [Fact]
    public void SystemPrompt_MentionsVisualizationCapabilities()
    {
        var prompt = ChatManager.SystemPrompt.ToLower();

        Assert.Contains("markdown", prompt);
        Assert.Contains("mermaid", prompt);
        Assert.Contains("html", prompt);
    }

    [Fact]
    public void SystemPrompt_ExplainsHowToUseBoard()
    {
        var prompt = ChatManager.SystemPrompt;

        Assert.Contains("set_board_markdown", prompt);
        Assert.Contains("set_board_html", prompt);
        Assert.Contains("board", prompt.ToLower());
        Assert.Contains("tool", prompt.ToLower());
    }

    [Fact]
    public async Task GenerateBusinessPlanAsync_CallsLlmGenerateBusinessPlan()
    {
        SetupChatWithTools("OK");
        _mockLlm.Setup(l => l.GenerateBusinessPlanAsync(It.IsAny<List<ChatMessage>>()))
            .ReturnsAsync("# Business Plan\n\n## Executive Summary");

        await _chatManager.SendMessageAsync("My startup idea");
        var result = await _chatManager.GenerateBusinessPlanAsync();

        Assert.Contains("Business Plan", result);
        _mockLlm.Verify(l => l.GenerateBusinessPlanAsync(It.IsAny<List<ChatMessage>>()), Times.Once);
    }

    [Fact]
    public async Task GenerateBusinessPlanAsync_IncludesSystemPromptAndHistory()
    {
        List<ChatMessage>? capturedMessages = null;
        SetupChatWithTools("OK");
        _mockLlm.Setup(l => l.GenerateBusinessPlanAsync(It.IsAny<List<ChatMessage>>()))
            .Callback<List<ChatMessage>>(msgs => capturedMessages = msgs)
            .ReturnsAsync("plan");

        await _chatManager.SendMessageAsync("Idea about X");
        await _chatManager.GenerateBusinessPlanAsync();

        Assert.NotNull(capturedMessages);
        Assert.Equal("system", capturedMessages![0].Role);
        Assert.True(capturedMessages.Count >= 3); // system + user + assistant
    }

    [Fact]
    public async Task GenerateSpecAsync_CallsLlmGenerateSpec()
    {
        SetupChatWithTools("OK");
        _mockLlm.Setup(l => l.GenerateSpecAsync(It.IsAny<List<ChatMessage>>()))
            .ReturnsAsync("# PRD\n\n## Product Overview");

        await _chatManager.SendMessageAsync("My product idea");
        var result = await _chatManager.GenerateSpecAsync();

        Assert.Contains("PRD", result);
        _mockLlm.Verify(l => l.GenerateSpecAsync(It.IsAny<List<ChatMessage>>()), Times.Once);
    }

    [Fact]
    public async Task GenerateSpecAsync_IncludesSystemPromptAndHistory()
    {
        List<ChatMessage>? capturedMessages = null;
        SetupChatWithTools("OK");
        _mockLlm.Setup(l => l.GenerateSpecAsync(It.IsAny<List<ChatMessage>>()))
            .Callback<List<ChatMessage>>(msgs => capturedMessages = msgs)
            .ReturnsAsync("spec");

        await _chatManager.SendMessageAsync("Build a platform for X");
        await _chatManager.GenerateSpecAsync();

        Assert.NotNull(capturedMessages);
        Assert.Equal("system", capturedMessages![0].Role);
        Assert.True(capturedMessages.Count >= 3); // system + user + assistant
    }

    [Fact]
    public async Task SendMessageAsync_ToolCall_SwitchModel_ExecutesAndReturnsResponse()
    {
        var callCount = 0;
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                callCount++;
                if (callCount == 1)
                {
                    // First call: LLM returns a tool call
                    return new ChatCompletionResponse
                    {
                        choices = new List<Choice>
                        {
                            new Choice
                            {
                                message = new ResponseMessage
                                {
                                    content = null,
                                    tool_calls = new List<ToolCall>
                                    {
                                        new ToolCall
                                        {
                                            id = "call_123",
                                            type = "function",
                                            function = new FunctionCall
                                            {
                                                name = "switch_model",
                                                arguments = "{\"model\": \"anthropic/claude-3.5-sonnet\"}"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    };
                }
                // Second call: LLM responds with text after tool execution
                return TextResponse("Done! I've switched to Claude 3.5 Sonnet.");
            });

        _mockLlm.Setup(l => l.GetModel()).Returns("openai/gpt-4o");

        string? switchedTo = null;
        _chatManager.ModelSwitched += (_, model) => switchedTo = model;

        var result = await _chatManager.SendMessageAsync("Switch to claude 3.5 sonnet");

        Assert.Equal("Done! I've switched to Claude 3.5 Sonnet.", result);
        Assert.Equal("anthropic/claude-3.5-sonnet", switchedTo);
        _mockLlm.Verify(l => l.SetModel("anthropic/claude-3.5-sonnet"), Times.Once);
    }

    [Fact]
    public async Task SendMessageAsync_PassesToolDefinitions()
    {
        List<ToolDefinition>? capturedTools = null;
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .Callback<List<ChatMessage>, List<ToolDefinition>?, Action<string>?, Action<int, string>?, CancellationToken>(
                (_, tools, _, _, _) => capturedTools = tools)
            .ReturnsAsync(TextResponse("Hello"));

        await _chatManager.SendMessageAsync("Hi");

        Assert.NotNull(capturedTools);
        Assert.Equal(4, capturedTools!.Count);
        Assert.Equal("switch_model", capturedTools[0].function.name);
        Assert.Equal("get_model_info", capturedTools[1].function.name);
        Assert.Equal("set_board_markdown", capturedTools[2].function.name);
        Assert.Equal("set_board_html", capturedTools[3].function.name);
    }

    [Fact]
    public async Task SendMessageAsync_ToolCall_GetModelInfo_ReturnsCurrentModel()
    {
        var callCount = 0;
        _mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(() =>
            {
                callCount++;
                if (callCount == 1)
                {
                    return new ChatCompletionResponse
                    {
                        choices = new List<Choice>
                        {
                            new Choice
                            {
                                message = new ResponseMessage
                                {
                                    content = null,
                                    tool_calls = new List<ToolCall>
                                    {
                                        new ToolCall
                                        {
                                            id = "call_info",
                                            type = "function",
                                            function = new FunctionCall
                                            {
                                                name = "get_model_info",
                                                arguments = "{}"
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    };
                }
                return TextResponse("You're using openai/gpt-4o on openrouter.");
            });

        _mockLlm.Setup(l => l.GetModel()).Returns("openai/gpt-4o");
        _chatManager.Provider = "openrouter";

        var result = await _chatManager.SendMessageAsync("What model am I using?");

        Assert.Contains("openai/gpt-4o", result);
    }
}
