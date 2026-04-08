using BrainstormAssistant.Models;

namespace BrainstormAssistant.Tests;

public class AppConfigTests
{
    [Fact]
    public void Validate_ValidConfig_ReturnsNoErrors()
    {
        var config = new AppConfig
        {
            Provider = "openrouter",
            ApiKey = "test-key",
            Model = "openai/gpt-4o"
        };

        var errors = config.Validate();

        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_MissingApiKey_ReturnsError()
    {
        var config = new AppConfig
        {
            Provider = "openrouter",
            ApiKey = "",
            Model = "gpt-4"
        };

        var errors = config.Validate();

        Assert.Contains(errors, e => e.Contains("API Key"));
    }

    [Fact]
    public void Validate_MissingModel_ReturnsError()
    {
        var config = new AppConfig
        {
            Provider = "openai",
            ApiKey = "key",
            Model = ""
        };

        var errors = config.Validate();

        Assert.Contains(errors, e => e.Contains("Model"));
    }

    [Fact]
    public void Validate_InvalidProvider_ReturnsError()
    {
        var config = new AppConfig
        {
            Provider = "azure",
            ApiKey = "key",
            Model = "gpt-4"
        };

        var errors = config.Validate();

        Assert.Contains(errors, e => e.Contains("Provider"));
    }

    [Fact]
    public void Validate_MultipleErrors_ReturnsAll()
    {
        var config = new AppConfig
        {
            Provider = "invalid",
            ApiKey = "",
            Model = ""
        };

        var errors = config.Validate();

        Assert.Equal(3, errors.Count);
    }

    [Fact]
    public void GetBaseUrl_OpenRouter_ReturnsOpenRouterUrl()
    {
        var config = new AppConfig { Provider = "openrouter" };

        Assert.Equal("https://openrouter.ai/api/v1", config.GetBaseUrl());
    }

    [Fact]
    public void GetBaseUrl_OpenAI_ReturnsOpenAIUrl()
    {
        var config = new AppConfig { Provider = "openai" };

        Assert.Equal("https://api.openai.com/v1", config.GetBaseUrl());
    }

    [Fact]
    public void GetBaseUrl_CustomUrl_ReturnsCustom()
    {
        var config = new AppConfig
        {
            Provider = "openrouter",
            BaseUrl = "https://custom.api.com/v1"
        };

        Assert.Equal("https://custom.api.com/v1", config.GetBaseUrl());
    }

    [Fact]
    public void DefaultValues_AreCorrect()
    {
        var config = new AppConfig();

        Assert.Equal("openrouter", config.Provider);
        Assert.Equal("openai/gpt-4o", config.Model);
        Assert.Equal(0.7, config.Temperature);
        Assert.Equal(6000, config.MaxTokens);
        Assert.True(config.TtsEnabled);
        Assert.True(config.SttEnabled);
        Assert.Equal(0, config.TtsRate);
        Assert.Equal(100, config.TtsVolume);
    }

    [Fact]
    public void Validate_CustomProvider_NoApiKey_NoError()
    {
        var config = new AppConfig
        {
            Provider = "custom",
            ApiKey = "",
            Model = "llama3",
            BaseUrl = "http://localhost:11434/v1"
        };

        var errors = config.Validate();

        Assert.Empty(errors);
    }

    [Fact]
    public void Validate_CustomProvider_MissingBaseUrl_ReturnsError()
    {
        var config = new AppConfig
        {
            Provider = "custom",
            ApiKey = "",
            Model = "llama3",
            BaseUrl = ""
        };

        var errors = config.Validate();

        Assert.Contains(errors, e => e.Contains("Base URL"));
    }

    [Fact]
    public void Validate_CustomProvider_WithBaseUrl_Valid()
    {
        var config = new AppConfig
        {
            Provider = "custom",
            ApiKey = "optional-key",
            Model = "mistral",
            BaseUrl = "http://192.168.1.100:1234/v1"
        };

        var errors = config.Validate();

        Assert.Empty(errors);
    }

    [Fact]
    public void GetBaseUrl_CustomProvider_NoBaseUrl_ReturnsOpenAIDefault()
    {
        // custom provider without BaseUrl falls through to default logic
        var config = new AppConfig { Provider = "custom" };

        // GetBaseUrl returns OpenAI default since custom != openrouter
        Assert.Equal("https://api.openai.com/v1", config.GetBaseUrl());
    }

    [Fact]
    public void GetBaseUrl_CustomProvider_WithBaseUrl_ReturnsCustom()
    {
        var config = new AppConfig
        {
            Provider = "custom",
            BaseUrl = "http://localhost:11434/v1"
        };

        Assert.Equal("http://localhost:11434/v1", config.GetBaseUrl());
    }
}
