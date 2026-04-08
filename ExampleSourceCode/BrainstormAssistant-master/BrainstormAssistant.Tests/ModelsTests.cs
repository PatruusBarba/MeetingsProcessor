using BrainstormAssistant.Models;

namespace BrainstormAssistant.Tests;

public class ChatMessageTests
{
    [Fact]
    public void DefaultConstructor_SetsDefaults()
    {
        var msg = new ChatMessage();

        Assert.Equal("user", msg.Role);
        Assert.Equal("", msg.Content);
        Assert.True(msg.Timestamp > 0);
    }

    [Fact]
    public void ParameterizedConstructor_SetsValues()
    {
        var msg = new ChatMessage("assistant", "Hello!");

        Assert.Equal("assistant", msg.Role);
        Assert.Equal("Hello!", msg.Content);
        Assert.True(msg.Timestamp > 0);
    }

    [Fact]
    public void Timestamp_IsRecentUnixMs()
    {
        var before = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var msg = new ChatMessage("user", "test");
        var after = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        Assert.InRange(msg.Timestamp, before, after);
    }
}

public class SessionTests
{
    [Fact]
    public void DefaultConstructor_CreatesValidSession()
    {
        var session = new Session();

        Assert.NotNull(session.Id);
        Assert.NotEmpty(session.Id);
        Assert.Contains("Brainstorm", session.Title);
        Assert.True(session.CreatedAt > 0);
        Assert.True(session.UpdatedAt > 0);
        Assert.Empty(session.Messages);
        Assert.Null(session.Summary);
    }

    [Fact]
    public void Id_IsUniquePerInstance()
    {
        var s1 = new Session();
        var s2 = new Session();

        Assert.NotEqual(s1.Id, s2.Id);
    }
}

public class IdeaEvaluationTests
{
    [Fact]
    public void DefaultConstructor_InitializesLists()
    {
        var eval = new IdeaEvaluation();

        Assert.NotNull(eval.Components);
        Assert.NotNull(eval.MonetizationOptions);
        Assert.NotNull(eval.Risks);
        Assert.NotNull(eval.Strengths);
        Assert.NotNull(eval.Weaknesses);
        Assert.Empty(eval.Components);
        Assert.Equal(0, eval.ViabilityScore);
    }
}
