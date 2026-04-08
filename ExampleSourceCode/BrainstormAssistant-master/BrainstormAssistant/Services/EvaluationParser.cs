using System.Text.RegularExpressions;
using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

public static class EvaluationParser
{
    public static IdeaEvaluation? Parse(string jsonString)
    {
        try
        {
            // Try to extract JSON from the response (LLM might wrap it in markdown)
            var match = Regex.Match(jsonString, @"\{[\s\S]*\}");
            if (!match.Success) return null;

            var parsed = JsonConvert.DeserializeObject<IdeaEvaluation>(match.Value);
            if (parsed == null) return null;

            // Validate required fields
            if (string.IsNullOrEmpty(parsed.IdeaSummary) ||
                string.IsNullOrEmpty(parsed.Recommendation))
                return null;

            return parsed;
        }
        catch
        {
            return null;
        }
    }

    public static string Format(IdeaEvaluation eval)
    {
        var lines = new List<string>
        {
            "========== IDEA EVALUATION ==========",
            "",
            $"SUMMARY: {eval.IdeaSummary}",
            $"TARGET AUDIENCE: {eval.TargetAudience}",
            "",
            "TECHNICAL COMPONENTS:"
        };

        for (int i = 0; i < eval.Components.Count; i++)
            lines.Add($"  {i + 1}. {eval.Components[i]}");

        lines.Add($"\nRESOURCES: {eval.EstimatedResources}");
        lines.Add($"ESTIMATED COST: {eval.EstimatedCost}");
        lines.Add($"TIMELINE: {eval.EstimatedTimeline}");

        lines.Add("\nMONETIZATION OPTIONS:");
        for (int i = 0; i < eval.MonetizationOptions.Count; i++)
            lines.Add($"  {i + 1}. {eval.MonetizationOptions[i]}");

        lines.Add($"\nVIABILITY SCORE: {eval.ViabilityScore}/10");

        lines.Add("\nSTRENGTHS:");
        foreach (var s in eval.Strengths)
            lines.Add($"  + {s}");

        lines.Add("\nWEAKNESSES:");
        foreach (var w in eval.Weaknesses)
            lines.Add($"  - {w}");

        lines.Add("\nRISKS:");
        foreach (var r in eval.Risks)
            lines.Add($"  ! {r}");

        lines.Add($"\nRECOMMENDATION: {eval.Recommendation}");
        lines.Add("=====================================");

        return string.Join("\n", lines);
    }

    public static string FormatSessionExport(Session session)
    {
        var lines = new List<string>
        {
            $"# Brainstorm Session: {session.Title}",
            $"**Created:** {DateTimeOffset.FromUnixTimeMilliseconds(session.CreatedAt).LocalDateTime:g}",
            $"**Last Updated:** {DateTimeOffset.FromUnixTimeMilliseconds(session.UpdatedAt).LocalDateTime:g}",
            $"**Messages:** {session.Messages.Count}",
            "",
            "---",
            ""
        };

        foreach (var msg in session.Messages)
        {
            var time = DateTimeOffset.FromUnixTimeMilliseconds(msg.Timestamp).LocalDateTime;
            var role = msg.Role == "user" ? "You" : "Assistant";
            lines.Add($"### {role} ({time:t})");
            lines.Add("");
            lines.Add(msg.Content);
            lines.Add("");
        }

        if (!string.IsNullOrEmpty(session.Summary))
        {
            lines.Add("---");
            lines.Add("");
            lines.Add("## Session Summary");
            lines.Add("");
            lines.Add(session.Summary);
        }

        return string.Join("\n", lines);
    }
}
