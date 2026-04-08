using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using Newtonsoft.Json;

namespace BrainstormAssistant.Tests;

public class EvaluationParserTests
{
    [Fact]
    public void Parse_ValidJson_ReturnsEvaluation()
    {
        var eval = new IdeaEvaluation
        {
            IdeaSummary = "A mobile app",
            TargetAudience = "Developers",
            Components = new List<string> { "React Native", "Node.js" },
            EstimatedResources = "2 devs",
            EstimatedCost = "$10k",
            EstimatedTimeline = "3 months",
            MonetizationOptions = new List<string> { "Freemium" },
            ViabilityScore = 7,
            Risks = new List<string> { "Competition" },
            Strengths = new List<string> { "Novel approach" },
            Weaknesses = new List<string> { "Small market" },
            Recommendation = "Worth trying"
        };
        var json = JsonConvert.SerializeObject(eval);

        var result = EvaluationParser.Parse(json);

        Assert.NotNull(result);
        Assert.Equal("A mobile app", result!.IdeaSummary);
        Assert.Equal(7, result.ViabilityScore);
        Assert.Equal(2, result.Components.Count);
    }

    [Fact]
    public void Parse_JsonInMarkdownCodeBlock_ExtractsCorrectly()
    {
        var json = "```json\n" + JsonConvert.SerializeObject(new IdeaEvaluation
        {
            IdeaSummary = "Test",
            Recommendation = "OK",
            Risks = new List<string> { "risk" },
            Strengths = new List<string> { "str" },
            Weaknesses = new List<string> { "w" }
        }) + "\n```";

        var result = EvaluationParser.Parse(json);

        Assert.NotNull(result);
        Assert.Equal("Test", result!.IdeaSummary);
    }

    [Fact]
    public void Parse_InvalidJson_ReturnsNull()
    {
        var result = EvaluationParser.Parse("not json at all");

        Assert.Null(result);
    }

    [Fact]
    public void Parse_MissingRequiredFields_ReturnsNull()
    {
        var json = JsonConvert.SerializeObject(new { someField = "value" });

        var result = EvaluationParser.Parse(json);

        Assert.Null(result);
    }

    [Fact]
    public void Format_ProducesReadableOutput()
    {
        var eval = new IdeaEvaluation
        {
            IdeaSummary = "Test app",
            TargetAudience = "Everyone",
            Components = new List<string> { "Frontend", "Backend" },
            EstimatedResources = "3 devs",
            EstimatedCost = "$20k",
            EstimatedTimeline = "6 months",
            MonetizationOptions = new List<string> { "SaaS" },
            ViabilityScore = 8,
            Risks = new List<string> { "Market risk" },
            Strengths = new List<string> { "Good UX" },
            Weaknesses = new List<string> { "No moat" },
            Recommendation = "Go for it"
        };

        var result = EvaluationParser.Format(eval);

        Assert.Contains("IDEA EVALUATION", result);
        Assert.Contains("SUMMARY: Test app", result);
        Assert.Contains("TARGET AUDIENCE: Everyone", result);
        Assert.Contains("1. Frontend", result);
        Assert.Contains("2. Backend", result);
        Assert.Contains("VIABILITY SCORE: 8/10", result);
        Assert.Contains("+ Good UX", result);
        Assert.Contains("- No moat", result);
        Assert.Contains("! Market risk", result);
        Assert.Contains("RECOMMENDATION: Go for it", result);
    }

    [Fact]
    public void FormatSessionExport_ProducesMarkdown()
    {
        var session = new Session
        {
            Id = "test-id",
            Title = "Test Session",
            CreatedAt = 1700000000000,
            UpdatedAt = 1700000100000,
            Messages = new List<ChatMessage>
            {
                new ChatMessage("user", "My idea"),
                new ChatMessage("assistant", "Interesting!")
            }
        };

        var result = EvaluationParser.FormatSessionExport(session);

        Assert.Contains("# Brainstorm Session: Test Session", result);
        Assert.Contains("**Messages:** 2", result);
        Assert.Contains("### You", result);
        Assert.Contains("My idea", result);
        Assert.Contains("### Assistant", result);
        Assert.Contains("Interesting!", result);
    }

    [Fact]
    public void FormatSessionExport_IncludesSummaryWhenPresent()
    {
        var session = new Session
        {
            Title = "Test",
            Summary = "This is the summary",
            Messages = new List<ChatMessage>()
        };

        var result = EvaluationParser.FormatSessionExport(session);

        Assert.Contains("## Session Summary", result);
        Assert.Contains("This is the summary", result);
    }

    [Fact]
    public void FormatSessionExport_OmitsSummaryWhenNull()
    {
        var session = new Session
        {
            Title = "Test",
            Messages = new List<ChatMessage>()
        };

        var result = EvaluationParser.FormatSessionExport(session);

        Assert.DoesNotContain("## Session Summary", result);
    }
}
