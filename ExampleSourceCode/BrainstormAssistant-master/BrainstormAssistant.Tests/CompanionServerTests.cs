using System.Net;
using System.Net.Http;
using System.Text;
using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using Moq;
using Newtonsoft.Json;

namespace BrainstormAssistant.Tests;

public class CompanionServerTests : IDisposable
{
    private CompanionServer? _server;
    private readonly HttpClient _client;
    private readonly int _port;

    public CompanionServerTests()
    {
        // Use a random high port to avoid conflicts
        _port = new Random().Next(15000, 16000);
        _client = new HttpClient { BaseAddress = new Uri($"http://localhost:{_port}") };
    }

    public void Dispose()
    {
        _server?.Dispose();
        _client.Dispose();
    }

    private CompanionServer CreateServer()
    {
        _server = new CompanionServer(_port);
        return _server;
    }

    [Fact]
    public void Start_SetsIsRunning()
    {
        var server = CreateServer();
        server.Start();

        Assert.True(server.IsRunning);
        Assert.NotNull(server.Address);
    }

    [Fact]
    public void Stop_ClearsIsRunning()
    {
        var server = CreateServer();
        server.Start();
        server.Stop();

        Assert.False(server.IsRunning);
        Assert.Null(server.Address);
    }

    [Fact]
    public async Task StatusEndpoint_ReturnsOk()
    {
        var server = CreateServer();
        server.Start();

        var resp = await _client.GetAsync("/api/status");
        var body = await resp.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Contains("\"ok\":true", body);
    }

    [Fact]
    public async Task StatusEndpoint_ShowsModelInfo_WhenChatManagerSet()
    {
        var mockLlm = new Mock<ILlmService>();
        mockLlm.Setup(l => l.GetModel()).Returns("openai/gpt-4o");
        mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ChatCompletionResponse
            {
                choices = new List<Choice>
                {
                    new Choice { message = new ResponseMessage { content = "hi" } }
                }
            });

        var testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_server_test_{Guid.NewGuid():N}");
        var sessionManager = new SessionManager(testDir);
        var chatManager = new ChatManager(mockLlm.Object, sessionManager);

        try
        {
            var server = CreateServer();
            server.SetChatManager(chatManager);
            server.Start();

            var resp = await _client.GetAsync("/api/status");
            var body = await resp.Content.ReadAsStringAsync();

            Assert.Contains("openai/gpt-4o", body);
        }
        finally
        {
            if (Directory.Exists(testDir))
                Directory.Delete(testDir, true);
        }
    }

    [Fact]
    public async Task ChatEndpoint_RequiresPost()
    {
        var server = CreateServer();
        server.Start();

        var resp = await _client.GetAsync("/api/chat");

        Assert.Equal(HttpStatusCode.MethodNotAllowed, resp.StatusCode);
    }

    [Fact]
    public async Task ChatEndpoint_Returns503_WhenNoChatManager()
    {
        var server = CreateServer();
        server.Start();

        var content = new StringContent("{\"text\": \"hello\"}", Encoding.UTF8, "application/json");
        var resp = await _client.PostAsync("/api/chat", content);

        Assert.Equal(HttpStatusCode.ServiceUnavailable, resp.StatusCode);
    }

    [Fact]
    public async Task ChatEndpoint_ReturnsResponse_WhenChatManagerSet()
    {
        var mockLlm = new Mock<ILlmService>();
        mockLlm.Setup(l => l.ChatStreamAsync(
                It.IsAny<List<ChatMessage>>(),
                It.IsAny<List<ToolDefinition>?>(),
                It.IsAny<Action<string>?>(),
                It.IsAny<Action<int, string>?>(),
                It.IsAny<CancellationToken>()))
            .ReturnsAsync(new ChatCompletionResponse
            {
                choices = new List<Choice>
                {
                    new Choice { message = new ResponseMessage { content = "Great brainstorm idea!" } }
                }
            });
        mockLlm.Setup(l => l.GetModel()).Returns("test-model");

        var testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_server_test_{Guid.NewGuid():N}");
        var sessionManager = new SessionManager(testDir);
        var chatManager = new ChatManager(mockLlm.Object, sessionManager);

        try
        {
            var server = CreateServer();
            server.SetChatManager(chatManager);
            server.Start();

            var content = new StringContent(
                JsonConvert.SerializeObject(new { text = "I have an idea", tts = false }),
                Encoding.UTF8, "application/json");
            var resp = await _client.PostAsync("/api/chat", content);
            var body = await resp.Content.ReadAsStringAsync();

            Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
            Assert.Contains("Great brainstorm idea!", body);
        }
        finally
        {
            if (Directory.Exists(testDir))
                Directory.Delete(testDir, true);
        }
    }

    [Fact]
    public async Task ChatEndpoint_Returns400_WhenTextMissing()
    {
        var mockLlm = new Mock<ILlmService>();
        var testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_server_test_{Guid.NewGuid():N}");
        var sessionManager = new SessionManager(testDir);
        var chatManager = new ChatManager(mockLlm.Object, sessionManager);

        try
        {
            var server = CreateServer();
            server.SetChatManager(chatManager);
            server.Start();

            var content = new StringContent("{}", Encoding.UTF8, "application/json");
            var resp = await _client.PostAsync("/api/chat", content);

            Assert.Equal(HttpStatusCode.BadRequest, resp.StatusCode);
        }
        finally
        {
            if (Directory.Exists(testDir))
                Directory.Delete(testDir, true);
        }
    }

    [Fact]
    public async Task UnknownEndpoint_Returns404()
    {
        var server = CreateServer();
        server.Start();

        var resp = await _client.GetAsync("/api/nonexistent");

        Assert.Equal(HttpStatusCode.NotFound, resp.StatusCode);
    }

    [Fact]
    public void LogMessage_FiresOnStartStop()
    {
        var logs = new List<string>();
        var server = CreateServer();
        server.LogMessage += (_, msg) => logs.Add(msg);

        server.Start();
        server.Stop();

        Assert.Contains(logs, l => l.Contains("started"));
        Assert.Contains(logs, l => l.Contains("stopped"));
    }

    [Fact]
    public async Task BoardEndpoint_ReturnsHtml_WhenDelegateSet()
    {
        var server = CreateServer();
        server.GetBoardHtml = () => "<h1>My Board</h1>";
        server.Start();

        var resp = await _client.GetAsync("/api/board");
        var body = await resp.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Contains("<h1>My Board</h1>", body);
    }

    [Fact]
    public async Task BoardEndpoint_ReturnsEmpty_WhenNoDelegateSet()
    {
        var server = CreateServer();
        server.Start();

        var resp = await _client.GetAsync("/api/board");
        var body = await resp.Content.ReadAsStringAsync();

        Assert.Equal(HttpStatusCode.OK, resp.StatusCode);
        Assert.Contains("\"html\":\"\"", body);
    }
}
