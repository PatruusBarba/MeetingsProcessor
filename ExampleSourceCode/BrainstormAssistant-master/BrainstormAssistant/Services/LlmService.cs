using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

public interface ILlmService
{
    Task<string> ChatAsync(List<ChatMessage> messages);
    Task<ChatCompletionResponse> ChatWithToolsAsync(List<ChatMessage> messages, List<ToolDefinition>? tools, CancellationToken ct = default);
    Task<ChatCompletionResponse> ChatStreamAsync(
        List<ChatMessage> messages,
        List<ToolDefinition>? tools,
        Action<string>? onContentToken,
        Action<int, string>? onToolArgFragment,
        CancellationToken ct = default);
    Task<string> EvaluateIdeaAsync(List<ChatMessage> messages);
    Task<string> GenerateBusinessPlanAsync(List<ChatMessage> messages);
    Task<string> GenerateSpecAsync(List<ChatMessage> messages);
    string GetModel();
    void SetModel(string model);
}

public class LlmService : ILlmService
{
    private readonly HttpClient _httpClient;
    private string _model;
    private readonly double _temperature;
    private readonly int _maxTokens;

    public LlmService(AppConfig config) : this(config, new HttpClient()) { }

    public LlmService(AppConfig config, HttpClient httpClient)
    {
        _httpClient = httpClient;
        _model = config.Model;
        _temperature = config.Temperature;
        _maxTokens = config.MaxTokens;

        var baseUrl = config.GetBaseUrl().TrimEnd('/') + "/";
        _httpClient.BaseAddress = new Uri(baseUrl);

        if (!string.IsNullOrWhiteSpace(config.ApiKey))
        {
            _httpClient.DefaultRequestHeaders.Authorization =
                new AuthenticationHeaderValue("Bearer", config.ApiKey);
        }

        if (config.Provider == "openrouter")
        {
            _httpClient.DefaultRequestHeaders.Add("HTTP-Referer", "https://brainstorm-assistant.local");
            _httpClient.DefaultRequestHeaders.Add("X-Title", "Brainstorm Voice Assistant");
        }
    }

    public async Task<string> ChatAsync(List<ChatMessage> messages)
    {
        var response = await ChatWithToolsAsync(messages, null);
        var text = response?.choices?.FirstOrDefault()?.message?.content;

        if (string.IsNullOrEmpty(text))
            throw new InvalidOperationException("No response content from LLM.");

        return text;
    }

    public async Task<ChatCompletionResponse> ChatWithToolsAsync(List<ChatMessage> messages, List<ToolDefinition>? tools, CancellationToken ct = default)
    {
        var request = new ChatCompletionRequest
        {
            model = _model,
            temperature = _temperature,
            max_tokens = _maxTokens,
            tools = tools,
            messages = messages.Select(m =>
            {
                var apiMsg = new ApiMessage
                {
                    role = m.Role,
                    content = m.Content,
                    tool_call_id = m.ToolCallId,
                    tool_calls = m.ToolCalls
                };
                return apiMsg;
            }).ToList()
        };

        var json = JsonConvert.SerializeObject(request,
            new JsonSerializerSettings { NullValueHandling = NullValueHandling.Ignore });
        var content = new StringContent(json, Encoding.UTF8, "application/json");

        var fullUrl = new Uri(_httpClient.BaseAddress!, "chat/completions");
        DebugLog($"POST {fullUrl} (non-stream) payload={json.Length}b");
        try
        {
            AppPaths.EnsureDirectories();
            System.IO.File.WriteAllText(System.IO.Path.Combine(AppPaths.LogDir, "last_request.json"), json);
        }
        catch { }

        var response = await _httpClient.PostAsync("chat/completions", content, ct);
        var responseBody = await response.Content.ReadAsStringAsync(ct);

        DebugLog($"Response: {response.StatusCode} body={responseBody.Length}b");

        if (!response.IsSuccessStatusCode)
        {
            DebugLog($"ERROR body: {responseBody.Substring(0, Math.Min(500, responseBody.Length))}");
            throw new HttpRequestException(
                $"LLM API error ({response.StatusCode}): {CleanErrorBody(responseBody)}");
        }

        var result = JsonConvert.DeserializeObject<ChatCompletionResponse>(responseBody);
        if (result?.choices == null || result.choices.Count == 0)
            throw new InvalidOperationException("No response from LLM.");

        return result;
    }

    /// <summary>
    /// Streams a chat completion using SSE. Invokes onContentToken for each text fragment,
    /// and onToolArgFragment(index, fragment) for each tool-call argument chunk.
    /// Returns a synthesized ChatCompletionResponse with the fully accumulated content and tool calls.
    /// </summary>
    public async Task<ChatCompletionResponse> ChatStreamAsync(
        List<ChatMessage> messages,
        List<ToolDefinition>? tools,
        Action<string>? onContentToken,
        Action<int, string>? onToolArgFragment,
        CancellationToken ct = default)
    {
        var request = new ChatCompletionRequest
        {
            model = _model,
            temperature = _temperature,
            max_tokens = _maxTokens,
            tools = tools,
            stream = true,
            messages = messages.Select(m => new ApiMessage
            {
                role = m.Role,
                content = m.Content,
                tool_call_id = m.ToolCallId,
                tool_calls = m.ToolCalls
            }).ToList()
        };

        var json = JsonConvert.SerializeObject(request,
            new JsonSerializerSettings { NullValueHandling = NullValueHandling.Ignore });
        var httpContent = new StringContent(json, Encoding.UTF8, "application/json");

        var httpRequest = new HttpRequestMessage(HttpMethod.Post, "chat/completions")
        {
            Content = httpContent
        };

        var fullUrl = new Uri(_httpClient.BaseAddress!, "chat/completions");
        DebugLog($"POST {fullUrl} (stream) payload={json.Length}b");
        try
        {
            AppPaths.EnsureDirectories();
            System.IO.File.WriteAllText(System.IO.Path.Combine(AppPaths.LogDir, "last_stream_request.json"), json);
        }
        catch { }

        using var response = await _httpClient.SendAsync(httpRequest, HttpCompletionOption.ResponseHeadersRead, ct);

        DebugLog($"Stream response: {response.StatusCode}");

        if (!response.IsSuccessStatusCode)
        {
            var errorBody = await response.Content.ReadAsStringAsync();
            DebugLog($"Stream ERROR body: {errorBody.Substring(0, Math.Min(500, errorBody.Length))}");
            response.Dispose();
            throw new HttpRequestException($"LLM API error ({response.StatusCode}): {CleanErrorBody(errorBody)}");
        }

        // Read SSE stream
        var contentBuilder = new StringBuilder();
        var toolCalls = new Dictionary<int, ToolCall>();
        string? finishReason = null;

        using var stream = await response.Content.ReadAsStreamAsync(ct);
        using var reader = new System.IO.StreamReader(stream);

        while (!reader.EndOfStream)
        {
            ct.ThrowIfCancellationRequested();
            var line = await reader.ReadLineAsync();
            if (line == null) break;

            if (!line.StartsWith("data: ")) continue;
            var data = line.Substring(6).Trim();

            if (data == "[DONE]") break;

            StreamChunk? chunk;
            try
            {
                chunk = JsonConvert.DeserializeObject<StreamChunk>(data);
            }
            catch { continue; }

            if (chunk?.choices == null || chunk.choices.Count == 0) continue;

            var choice = chunk.choices[0];
            finishReason = choice.finish_reason ?? finishReason;

            var delta = choice.delta;
            if (delta == null) continue;

            // Content token
            if (!string.IsNullOrEmpty(delta.content))
            {
                contentBuilder.Append(delta.content);
                onContentToken?.Invoke(delta.content);
            }

            // Tool call fragments
            if (delta.tool_calls != null)
            {
                foreach (var tc in delta.tool_calls)
                {
                    if (!toolCalls.ContainsKey(tc.index))
                    {
                        toolCalls[tc.index] = new ToolCall
                        {
                            id = tc.id ?? "",
                            type = tc.type ?? "function",
                            function = new FunctionCall
                            {
                                name = tc.function?.name ?? "",
                                arguments = ""
                            }
                        };
                    }

                    var existing = toolCalls[tc.index];

                    if (!string.IsNullOrEmpty(tc.id))
                        existing.id = tc.id;
                    if (!string.IsNullOrEmpty(tc.function?.name))
                        existing.function.name = tc.function.name;
                    if (!string.IsNullOrEmpty(tc.function?.arguments))
                    {
                        existing.function.arguments += tc.function.arguments;
                        onToolArgFragment?.Invoke(tc.index, tc.function.arguments);
                    }
                }
            }
        }

        // Build synthesized response
        var toolCallList = toolCalls.Count > 0
            ? toolCalls.OrderBy(kv => kv.Key).Select(kv => kv.Value).ToList()
            : null;

        return new ChatCompletionResponse
        {
            choices = new List<Choice>
            {
                new Choice
                {
                    finish_reason = finishReason ?? "stop",
                    message = new ResponseMessage
                    {
                        content = contentBuilder.Length > 0 ? contentBuilder.ToString() : null,
                        tool_calls = toolCallList
                    }
                }
            }
        };
    }

    public async Task<string> EvaluateIdeaAsync(List<ChatMessage> messages)
    {
        var evaluationMessage = new ChatMessage("user",
            @"Based on our entire conversation so far, provide a structured critical evaluation of the idea we discussed. Use this exact JSON format:

{
  ""ideaSummary"": ""brief summary of the idea"",
  ""targetAudience"": ""who this is for"",
  ""components"": [""list"", ""of"", ""technical"", ""components""],
  ""estimatedResources"": ""what resources are needed"",
  ""estimatedCost"": ""rough cost estimate"",
  ""estimatedTimeline"": ""development timeline estimate"",
  ""monetizationOptions"": [""option1"", ""option2""],
  ""viabilityScore"": 7,
  ""risks"": [""risk1"", ""risk2""],
  ""strengths"": [""strength1"", ""strength2""],
  ""weaknesses"": [""weakness1"", ""weakness2""],
  ""recommendation"": ""honest final recommendation""
}

Be brutally honest. Do not sugarcoat. Give a real assessment.");

        var allMessages = new List<ChatMessage>(messages) { evaluationMessage };
        return await ChatAsync(allMessages);
    }

    public async Task<string> GenerateBusinessPlanAsync(List<ChatMessage> messages)
    {
        var planMessage = new ChatMessage("user",
            @"Based on our entire conversation so far, generate a comprehensive business plan for the idea we discussed. Write it in Markdown format. The business plan must include:

1. **Executive Summary** — what the product is, who it's for, and why it matters
2. **Problem & Solution** — the problem being solved and how the product solves it
3. **Target Market** — target audience, market size estimates, segments
4. **Competitive Analysis** — existing competitors, our differentiation
5. **Revenue Model** — how this will make money, pricing strategy, monetization options
6. **Go-to-Market Strategy** — launch plan, marketing channels, customer acquisition
7. **Development Roadmap** — phases, milestones, timeline
8. **Team & Resources** — what roles/skills are needed, estimated team size
9. **Financial Projections** — rough cost estimates, break-even analysis, revenue projections
10. **Risks & Mitigation** — key risks and how to address them
11. **Conclusion & Recommendation** — honest final assessment

Be critical and realistic. No sugarcoating. If parts of the plan are weak, say so.
Respond in the same language the user has been using in the conversation.");

        var allMessages = new List<ChatMessage>(messages) { planMessage };
        return await ChatAsync(allMessages);
    }

    public async Task<string> GenerateSpecAsync(List<ChatMessage> messages)
    {
        var specMessage = new ChatMessage("user",
            @"Based on our entire conversation so far, generate a detailed Product Requirements Document (PRD) / Technical Specification for the idea we discussed. Write it in Markdown format. The spec must include:

1. **Product Overview** — what the product is and its core purpose
2. **Goals & Success Metrics** — measurable goals and KPIs
3. **User Stories / Use Cases** — key user scenarios
4. **Functional Requirements** — detailed feature list with descriptions
5. **Non-Functional Requirements** — performance, security, scalability, accessibility
6. **Technical Architecture** — high-level system design, components, data flow
7. **Technology Stack** — recommended languages, frameworks, services, infrastructure
8. **API Design** — key API endpoints or interfaces (if applicable)
9. **Data Model** — key entities, relationships, storage approach
10. **UI/UX Considerations** — key screens, user flow, design principles
11. **Development Phases** — breakdown into MVP and future iterations
12. **Dependencies & Constraints** — external dependencies, limitations
13. **Open Questions** — unresolved items that need further discussion

Be thorough and technical. This document should be usable by a development team to start building.
Respond in the same language the user has been using in the conversation.");

        var allMessages = new List<ChatMessage>(messages) { specMessage };
        return await ChatAsync(allMessages);
    }

    public string GetModel() => _model;

    public void SetModel(string model)
    {
        if (string.IsNullOrWhiteSpace(model))
            throw new ArgumentException("Model name cannot be empty.", nameof(model));
        _model = model;
    }

    /// <summary>Strips HTML tags from error bodies so error dialogs show clean text.</summary>
    private static string CleanErrorBody(string body)
    {
        if (string.IsNullOrWhiteSpace(body)) return "No details.";
        if (body.TrimStart().StartsWith("<"))
        {
            var text = System.Text.RegularExpressions.Regex.Replace(body, "<[^>]+>", " ");
            text = System.Text.RegularExpressions.Regex.Replace(text, @"\s+", " ").Trim();
            return string.IsNullOrWhiteSpace(text) ? "Server returned HTML error page." : text;
        }
        return body.Length > 500 ? body.Substring(0, 500) + "..." : body;
    }

    private static void DebugLog(string message)
    {
        try
        {
            AppPaths.EnsureDirectories();
            var logPath = System.IO.Path.Combine(AppPaths.LogDir, "llm_debug.log");
            var timestamp = DateTime.Now.ToString("HH:mm:ss.fff");
            System.IO.File.AppendAllText(logPath, $"[{timestamp}] {message}\n");
        }
        catch { }
    }
}
