using System.Net;
using System.Net.Http;
using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using Moq;
using Moq.Protected;
using Newtonsoft.Json;

namespace BrainstormAssistant.Tests;

public class LlmServiceTests
{
    private LlmService CreateServiceWithMockHttp(HttpResponseMessage response)
    {
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .ReturnsAsync(response);

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openrouter",
            ApiKey = "test-key",
            Model = "openai/gpt-4o"
        };

        return new LlmService(config, httpClient);
    }

    [Fact]
    public async Task ChatAsync_SuccessfulResponse_ReturnsContent()
    {
        var apiResponse = new ChatCompletionResponse
        {
            choices = new List<Choice>
            {
                new Choice
                {
                    message = new ResponseMessage { content = "Test response" }
                }
            }
        };

        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(JsonConvert.SerializeObject(apiResponse))
        };

        var service = CreateServiceWithMockHttp(response);
        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "Hello")
        };

        var result = await service.ChatAsync(messages);

        Assert.Equal("Test response", result);
    }

    [Fact]
    public async Task ChatAsync_OpenRouter_SendsToCorrectUrl()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openrouter",
            ApiKey = "test-key",
            Model = "openai/gpt-4o"
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("user", "Hi")
        });

        Assert.NotNull(capturedRequest);
        Assert.Equal("https://openrouter.ai/api/v1/chat/completions", capturedRequest!.RequestUri!.ToString());
    }

    [Fact]
    public async Task ChatAsync_OpenAI_SendsToCorrectUrl()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4o"
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("user", "Hi")
        });

        Assert.NotNull(capturedRequest);
        Assert.Equal("https://api.openai.com/v1/chat/completions", capturedRequest!.RequestUri!.ToString());
    }

    [Fact]
    public async Task ChatAsync_CustomBaseUrl_SendsToCorrectUrl()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4o",
            BaseUrl = "http://localhost:11434/v1"
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("user", "Hi")
        });

        Assert.NotNull(capturedRequest);
        Assert.Equal("http://localhost:11434/v1/chat/completions", capturedRequest!.RequestUri!.ToString());
    }

    [Fact]
    public async Task ChatAsync_SendsAuthHeader()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openrouter",
            ApiKey = "sk-test-12345",
            Model = "openai/gpt-4o"
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("user", "Hi")
        });

        Assert.NotNull(capturedRequest);
        Assert.Equal("Bearer", capturedRequest!.Headers.Authorization!.Scheme);
        Assert.Equal("sk-test-12345", capturedRequest!.Headers.Authorization!.Parameter);
    }

    [Fact]
    public async Task ChatAsync_SendsCorrectRequestBody()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4o",
            Temperature = 0.5,
            MaxTokens = 1024
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("system", "You are helpful."),
            new ChatMessage("user", "Hello world")
        });

        Assert.NotNull(capturedRequest);
        var body = await capturedRequest!.Content!.ReadAsStringAsync();
        var parsed = JsonConvert.DeserializeObject<ChatCompletionRequest>(body);
        Assert.Equal("gpt-4o", parsed!.model);
        Assert.Equal(0.5, parsed.temperature);
        Assert.Equal(1024, parsed.max_tokens);
        Assert.Equal(2, parsed.messages.Count);
        Assert.Equal("system", parsed.messages[0].role);
        Assert.Equal("You are helpful.", parsed.messages[0].content);
        Assert.Equal("user", parsed.messages[1].role);
        Assert.Equal("Hello world", parsed.messages[1].content);
    }

    [Fact]
    public async Task ChatAsync_EmptyResponse_ThrowsException()
    {
        var apiResponse = new ChatCompletionResponse
        {
            choices = new List<Choice>
            {
                new Choice
                {
                    message = new ResponseMessage { content = null }
                }
            }
        };

        var response = new HttpResponseMessage(HttpStatusCode.OK)
        {
            Content = new StringContent(JsonConvert.SerializeObject(apiResponse))
        };

        var service = CreateServiceWithMockHttp(response);
        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "Hello")
        };

        await Assert.ThrowsAsync<InvalidOperationException>(() => service.ChatAsync(messages));
    }

    [Fact]
    public async Task ChatAsync_ApiError_ThrowsHttpRequestException()
    {
        var response = new HttpResponseMessage(HttpStatusCode.Unauthorized)
        {
            Content = new StringContent("Unauthorized")
        };

        var service = CreateServiceWithMockHttp(response);
        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "Hello")
        };

        await Assert.ThrowsAsync<HttpRequestException>(() => service.ChatAsync(messages));
    }

    [Fact]
    public void GetModel_ReturnsConfiguredModel()
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK);
        var service = CreateServiceWithMockHttp(response);

        Assert.Equal("openai/gpt-4o", service.GetModel());
    }

    [Fact]
    public void SetModel_ChangesActiveModel()
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK);
        var service = CreateServiceWithMockHttp(response);

        service.SetModel("anthropic/claude-3.5-sonnet");

        Assert.Equal("anthropic/claude-3.5-sonnet", service.GetModel());
    }

    [Fact]
    public void SetModel_EmptyName_Throws()
    {
        var response = new HttpResponseMessage(HttpStatusCode.OK);
        var service = CreateServiceWithMockHttp(response);

        Assert.Throws<ArgumentException>(() => service.SetModel(""));
        Assert.Throws<ArgumentException>(() => service.SetModel("  "));
    }

    [Fact]
    public async Task EvaluateIdeaAsync_AppendsEvaluationPrompt()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "{\"ideaSummary\":\"test\"}" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4"
        };
        var service = new LlmService(config, httpClient);

        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "My idea")
        };

        var result = await service.EvaluateIdeaAsync(messages);

        Assert.NotNull(capturedRequest);
        var body = await capturedRequest!.Content!.ReadAsStringAsync();
        Assert.Contains("critical evaluation", body);
        Assert.Contains("My idea", body);
    }

    [Fact]
    public async Task GenerateBusinessPlanAsync_AppendsBusinessPlanPrompt()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "# Business Plan\n\n## Executive Summary" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4"
        };
        var service = new LlmService(config, httpClient);

        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "My startup idea")
        };

        var result = await service.GenerateBusinessPlanAsync(messages);

        Assert.NotNull(capturedRequest);
        var body = await capturedRequest!.Content!.ReadAsStringAsync();
        Assert.Contains("business plan", body.ToLower());
        Assert.Contains("Executive Summary", body);
        Assert.Contains("Revenue Model", body);
        Assert.Contains("My startup idea", body);
        Assert.Contains("Business Plan", result);
    }

    [Fact]
    public async Task GenerateSpecAsync_AppendsSpecPrompt()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "# PRD\n\n## Product Overview" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "test-key",
            Model = "gpt-4"
        };
        var service = new LlmService(config, httpClient);

        var messages = new List<ChatMessage>
        {
            new ChatMessage("user", "My product idea")
        };

        var result = await service.GenerateSpecAsync(messages);

        Assert.NotNull(capturedRequest);
        var body = await capturedRequest!.Content!.ReadAsStringAsync();
        Assert.Contains("Product Requirements Document", body);
        Assert.Contains("Functional Requirements", body);
        Assert.Contains("Technical Architecture", body);
        Assert.Contains("My product idea", body);
        Assert.Contains("PRD", result);
    }

    [Fact]
    public async Task ChatAsync_CustomProvider_NoApiKey_NoAuthHeader()
    {
        HttpRequestMessage? capturedRequest = null;
        var handlerMock = new Mock<HttpMessageHandler>();
        handlerMock
            .Protected()
            .Setup<Task<HttpResponseMessage>>(
                "SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .Callback<HttpRequestMessage, CancellationToken>((req, _) => capturedRequest = req)
            .ReturnsAsync(new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(JsonConvert.SerializeObject(new ChatCompletionResponse
                {
                    choices = new List<Choice>
                    {
                        new Choice { message = new ResponseMessage { content = "ok" } }
                    }
                }))
            });

        var httpClient = new HttpClient(handlerMock.Object);
        var config = new AppConfig
        {
            Provider = "custom",
            ApiKey = "",
            Model = "llama3",
            BaseUrl = "http://localhost:11434/v1"
        };
        var service = new LlmService(config, httpClient);

        await service.ChatAsync(new List<ChatMessage>
        {
            new ChatMessage("user", "Hi")
        });

        Assert.NotNull(capturedRequest);
        Assert.Null(capturedRequest!.Headers.Authorization);
    }
}
