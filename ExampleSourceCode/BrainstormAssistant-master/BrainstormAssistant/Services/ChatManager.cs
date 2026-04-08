using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

public class ChatManager
{
    public static readonly string SystemPrompt =
@"You are a brainstorm assistant — a critical thinking partner who helps users develop raw ideas into structured, viable concepts.

Your core behavior:
1. LISTEN carefully to the user's idea and ask clarifying questions.
2. HELP structure the idea: identify the problem it solves, target audience, key features, and technical components.
3. CHALLENGE assumptions: point out gaps, risks, and potential issues honestly.
4. EVALUATE viability: assess business potential, monetization options, competition, and market fit.
5. BE HONEST: Never sugarcoat or be sycophantic. If an idea has serious flaws, say so directly and explain why. The user values truth over comfort.
6. SUGGEST improvements: offer concrete ways to strengthen the idea.
7. ESTIMATE resources: provide rough estimates on cost, time, team size, and technical stack needed.

## VISUALIZATION BOARD

You have a visual rendering board available in the application. The user can see it as a right panel next to the chat. You MUST use the provided tools to display content on the board:

### How to use the board:

1. **Markdown content** — Use the `set_board_markdown` tool to display formatted text, tables, lists, mermaid diagrams, etc. on the board. Example: call set_board_markdown with markdown content including headings, lists, tables, or ```mermaid blocks.

2. **HTML content** — Use the `set_board_html` tool to display rich interactive content with full HTML/CSS/JS. The board uses a dark theme (background: #1E1E1E, text: #E0E0E0).

### When to use the board:
- When the user asks you to visualize, draw, or diagram something
- When showing architecture diagrams, flowcharts, mind maps, or process flows
- When presenting structured comparisons, tables, or dashboards
- When the user asks to ""show on the board"" or ""display"" something
- When a visual representation would genuinely help explain the concept
- Use set_board_markdown for text-heavy content with optional mermaid diagrams
- Use set_board_html for rich layouts, interactive dashboards, styled visualizations

### Important:
- You ALWAYS have the board available. Do not say you cannot visualize or that you lack tools.
- ALWAYS use the set_board_markdown or set_board_html tools to put content on the board. Do NOT include raw ```html or ```mermaid code blocks in your response text — use the tools instead.
- You can include explanatory text in your normal response alongside the tool call.

Communication style:
- Be direct and concise. No fluff.
- Use structured responses when evaluating (bullet points, numbered lists).
- If the idea is bad, say it's bad and explain why. Then suggest how to pivot.
- If the idea is good, acknowledge it but still point out risks.
- Speak as an experienced product strategist and technical architect.
- Respond in the same language the user uses.

You are NOT a yes-man. You are a trusted advisor who gives real feedback.";

    private readonly ILlmService _llm;
    private readonly ISessionManager _sessionManager;
    private readonly ChatMessage _systemMessage;
    private List<string> _availableModels;

    /// <summary>Fired when the LLM switches the model via tool call.</summary>
    public event EventHandler<string>? ModelSwitched;

    /// <summary>Fired when the LLM sets markdown content on the board via tool call.</summary>
    public event EventHandler<string>? BoardMarkdownSet;

    /// <summary>Fired when the LLM sets HTML content on the board via tool call.</summary>
    public event EventHandler<string>? BoardHtmlSet;

    /// <summary>Fired when the LLM streams a content token (for real-time chat display).</summary>
    public event EventHandler<string>? StreamingToken;

    /// <summary>Fired when the board content is being built during streaming (partial render).</summary>
    public event EventHandler<(string toolName, string partialContent)>? PartialBoardContent;

    /// <summary>Returns the current provider name for tool responses.</summary>
    public string Provider { get; set; } = "openrouter";

    public Session CurrentSession { get; private set; }

    /// <summary>Updates the available models list (called when settings change).</summary>
    public void SetAvailableModels(List<string> models)
    {
        _availableModels = models ?? new List<string>();
        _chatTools = BuildChatTools();
    }

    private List<ToolDefinition> _chatTools;

    private List<ToolDefinition> BuildChatTools()
    {
        var modelListDesc = "Switch the LLM model. Use the model_id number from the available list. " +
            "Available models: " + string.Join(", ",
                _availableModels.Select((m, i) => $"{i + 1}={m}")) + ".";

        return new List<ToolDefinition>
    {
        new ToolDefinition
        {
            type = "function",
            function = new FunctionDefinition
            {
                name = "switch_model",
                description = modelListDesc,
                parameters = new
                {
                    type = "object",
                    properties = new
                    {
                        model_id = new
                        {
                            type = "integer",
                            description = "The numeric ID of the model to switch to (1-based index from the available models list)"
                        }
                    },
                    required = new[] { "model_id" }
                }
            }
        },
        new ToolDefinition
        {
            type = "function",
            function = new FunctionDefinition
            {
                name = "get_model_info",
                description = "Get information about the currently active LLM model and API provider. Call this when the user asks what model is being used, what models are available, or wants to know the current configuration.",
                parameters = new
                {
                    type = "object",
                    properties = new { },
                    required = Array.Empty<string>()
                }
            }
        },
        new ToolDefinition
        {
            type = "function",
            function = new FunctionDefinition
            {
                name = "set_board_markdown",
                description = "Display markdown content on the visualization board. Use this to show structured text, lists, tables, diagrams (mermaid), summaries, specs, or any formatted content. The content replaces whatever is currently on the board.",
                parameters = new
                {
                    type = "object",
                    properties = new
                    {
                        content = new
                        {
                            type = "string",
                            description = "The markdown content to display on the board. Supports headings, lists, tables, code blocks, and ```mermaid blocks for diagrams."
                        }
                    },
                    required = new[] { "content" }
                }
            }
        },
        new ToolDefinition
        {
            type = "function",
            function = new FunctionDefinition
            {
                name = "set_board_html",
                description = "Display rich HTML content on the visualization board. Use this for interactive visualizations, styled dashboards, charts, or any content that benefits from full HTML/CSS/JS. The content replaces whatever is currently on the board.",
                parameters = new
                {
                    type = "object",
                    properties = new
                    {
                        content = new
                        {
                            type = "string",
                            description = "The HTML content to display on the board. Can include CSS and JavaScript. The board has a dark background (#1E1E1E) with light text (#E0E0E0)."
                        }
                    },
                    required = new[] { "content" }
                }
            }
        }
    };
    }

    public ChatManager(ILlmService llm, ISessionManager sessionManager, Session? session = null, List<string>? availableModels = null)
    {
        _llm = llm;
        _sessionManager = sessionManager;
        CurrentSession = session ?? sessionManager.CreateSession();
        _availableModels = availableModels ?? new List<string>
        {
            "openai/gpt-4o",
            "anthropic/claude-3.5-sonnet",
            "google/gemini-pro"
        };
        _chatTools = BuildChatTools();

        _systemMessage = new ChatMessage("system", SystemPrompt);
    }

    public async Task<string> SendMessageAsync(string userInput, CancellationToken ct = default)
    {
        var userMessage = new ChatMessage("user", userInput);
        _sessionManager.AddMessage(CurrentSession, userMessage);

        var allMessages = new List<ChatMessage> { _systemMessage };
        allMessages.AddRange(CurrentSession.Messages);

        // Tool call loop: LLM may respond with tool calls instead of text
        const int maxToolRounds = 5;
        for (int round = 0; round < maxToolRounds; round++)
        {
            ChatCompletionResponse response;

            try
            {
                // Try streaming first for real-time UI updates
                var toolArgs = new Dictionary<int, string>();
                int lastBoardLen = 0;

                response = await _llm.ChatStreamAsync(
                    allMessages,
                    _chatTools,
                    token => StreamingToken?.Invoke(this, token),
                    (index, fragment) =>
                    {
                        if (!toolArgs.ContainsKey(index))
                            toolArgs[index] = "";
                        toolArgs[index] += fragment;

                        var accumulated = toolArgs[index];
                        if (accumulated.Length - lastBoardLen > 200)
                        {
                            lastBoardLen = accumulated.Length;
                            var partialContent = TryExtractPartialContent(accumulated);
                            if (partialContent != null)
                                PartialBoardContent?.Invoke(this, ("board", partialContent));
                        }
                    }
                );
            }
            catch (Exception ex1)
            {
                System.Diagnostics.Debug.WriteLine($"[ChatManager] Streaming+tools failed: {ex1.Message}");
                // Clean history for tool-less fallbacks (strip role=tool and tool_calls)
                var cleanMessages = StripToolMessages(allMessages);
                try
                {
                    // Fallback 1: streaming WITHOUT tools + clean history
                    await Task.Delay(100, ct);
                    response = await _llm.ChatStreamAsync(
                        cleanMessages,
                        null,
                        token => StreamingToken?.Invoke(this, token),
                        null);
                }
                catch (Exception ex1b)
                {
                    System.Diagnostics.Debug.WriteLine($"[ChatManager] Stream-no-tools failed: {ex1b.Message}");
                    try
                    {
                        // Fallback 2: non-streaming with tools (original history)
                        await Task.Delay(100, ct);
                        response = await _llm.ChatWithToolsAsync(allMessages, _chatTools, ct);
                    }
                    catch (Exception ex2)
                    {
                        System.Diagnostics.Debug.WriteLine($"[ChatManager] Non-stream+tools failed: {ex2.Message}");
                        try
                        {
                            // Fallback 3: non-streaming WITHOUT tools + clean history
                            await Task.Delay(100, ct);
                            response = await _llm.ChatWithToolsAsync(cleanMessages, null, ct);
                        }
                        catch (Exception ex3)
                        {
                            System.Diagnostics.Debug.WriteLine($"[ChatManager] All attempts failed: {ex3.Message}");
                            throw new InvalidOperationException(
                                $"All API call attempts failed.\n" +
                                $"Stream+tools: {ex1.Message}\n" +
                                $"Stream (no tools): {ex1b.Message}\n" +
                                $"Non-stream+tools: {ex2.Message}\n" +
                                $"Non-stream (no tools): {ex3.Message}");
                        }
                    }
                }
            }

            var choice = response.choices!.First();
            var msg = choice.message!;

            // If no tool calls, return the text response
            if (msg.tool_calls == null || msg.tool_calls.Count == 0)
            {
                var text = msg.content ?? "";
                var assistantMessage = new ChatMessage("assistant", text);
                _sessionManager.AddMessage(CurrentSession, assistantMessage);
                return text;
            }

            // Process tool calls (fires board events for final content)
            var assistantToolMsg = ChatMessage.AssistantWithToolCalls(msg.tool_calls);
            _sessionManager.AddMessage(CurrentSession, assistantToolMsg);
            allMessages.Add(assistantToolMsg);

            foreach (var toolCall in msg.tool_calls)
            {
                var result = ExecuteToolCall(toolCall);
                var toolResultMsg = ChatMessage.ToolResult(toolCall.id, result);
                _sessionManager.AddMessage(CurrentSession, toolResultMsg);
                allMessages.Add(toolResultMsg);
            }
        }

        throw new InvalidOperationException("Too many tool call rounds.");
    }

    /// <summary>
    /// Tries to extract the partial "content" value from an incomplete JSON arguments string.
    /// E.g., from {"content": "# Hello\nSome text... (still streaming)
    /// </summary>
    private static string? TryExtractPartialContent(string partialJson)
    {
        // Look for "content": " or "content":" pattern
        const string marker1 = "\"content\":\"";
        const string marker2 = "\"content\": \"";
        int startIdx = partialJson.IndexOf(marker2);
        int markerLen = marker2.Length;
        if (startIdx < 0)
        {
            startIdx = partialJson.IndexOf(marker1);
            markerLen = marker1.Length;
        }
        if (startIdx < 0) return null;

        var valueStart = startIdx + markerLen;
        if (valueStart >= partialJson.Length) return null;

        // Take everything after the opening quote, unescape basic JSON escapes
        var raw = partialJson.Substring(valueStart);
        // Remove trailing incomplete JSON (closing quote + brace)
        if (raw.EndsWith("\"}")) raw = raw.Substring(0, raw.Length - 2);
        else if (raw.EndsWith("\"")) raw = raw.Substring(0, raw.Length - 1);

        // Unescape common JSON sequences
        raw = raw.Replace("\\n", "\n")
                  .Replace("\\t", "\t")
                  .Replace("\\\"", "\"")
                  .Replace("\\\\", "\\");

        return raw.Length > 0 ? raw : null;
    }

    /// <summary>
    /// Creates a sanitized copy of the message list with all tool-related messages removed.
    /// Assistant messages with tool_calls are converted to plain text summaries.
    /// Used for fallback calls to servers that don't support function calling.
    /// </summary>
    private static List<ChatMessage> StripToolMessages(List<ChatMessage> messages)
    {
        var clean = new List<ChatMessage>();
        foreach (var msg in messages)
        {
            if (msg.Role == "tool") continue;

            if (msg.Role == "assistant" && msg.ToolCalls != null && msg.ToolCalls.Count > 0)
            {
                // Convert tool-calling assistant message to plain text
                var summary = string.IsNullOrEmpty(msg.Content)
                    ? "(tool call attempted)"
                    : msg.Content;
                clean.Add(new ChatMessage("assistant", summary));
                continue;
            }

            clean.Add(msg);
        }
        return clean;
    }

    private string ExecuteToolCall(ToolCall toolCall)
    {
        if (toolCall.function.name == "switch_model")
        {
            try
            {
                var args = JsonConvert.DeserializeObject<Dictionary<string, object>>(toolCall.function.arguments);
                int modelId;
                if (args != null && args.ContainsKey("model_id"))
                    modelId = Convert.ToInt32(args["model_id"]);
                else if (args != null && args.ContainsKey("model"))
                {
                    // Backward compat: AI might still send model name
                    var name = args["model"]?.ToString() ?? "";
                    var idx = _availableModels.FindIndex(m =>
                        m.Equals(name, StringComparison.OrdinalIgnoreCase));
                    if (idx < 0)
                        return $"Error: model '{name}' is not in the available models list. Use get_model_info to see available models.";
                    modelId = idx + 1;
                }
                else
                    return "Error: missing model_id parameter.";

                if (modelId < 1 || modelId > _availableModels.Count)
                    return $"Error: model_id must be between 1 and {_availableModels.Count}. Use get_model_info to see the list.";

                var newModel = _availableModels[modelId - 1];
                var oldModel = _llm.GetModel();
                _llm.SetModel(newModel);
                ModelSwitched?.Invoke(this, newModel);
                return $"Model switched from {oldModel} to {newModel} (id={modelId}).";
            }
            catch (Exception ex)
            {
                return $"Error switching model: {ex.Message}";
            }
        }

        if (toolCall.function.name == "get_model_info")
        {
            var currentModel = _llm.GetModel();
            var modelList = _availableModels.Select((m, i) => new { id = i + 1, name = m }).ToList();
            return JsonConvert.SerializeObject(new
            {
                current_model = currentModel,
                provider = Provider,
                available_models = modelList,
                note = "Use switch_model with the model_id number to switch."
            });
        }

        if (toolCall.function.name == "set_board_markdown")
        {
            try
            {
                var args = JsonConvert.DeserializeObject<Dictionary<string, string>>(toolCall.function.arguments);
                var content = args?["content"] ?? throw new ArgumentException("Missing content parameter.");
                BoardMarkdownSet?.Invoke(this, content);
                return "Markdown content displayed on the board.";
            }
            catch (Exception ex)
            {
                return $"Error setting board markdown: {ex.Message}";
            }
        }

        if (toolCall.function.name == "set_board_html")
        {
            try
            {
                var args = JsonConvert.DeserializeObject<Dictionary<string, string>>(toolCall.function.arguments);
                var content = args?["content"] ?? throw new ArgumentException("Missing content parameter.");
                BoardHtmlSet?.Invoke(this, content);
                return "HTML content displayed on the board.";
            }
            catch (Exception ex)
            {
                return $"Error setting board HTML: {ex.Message}";
            }
        }

        return $"Unknown tool: {toolCall.function.name}";
    }

    public async Task<string> EvaluateIdeaAsync()
    {
        var allMessages = new List<ChatMessage> { _systemMessage };
        allMessages.AddRange(CurrentSession.Messages);
        return await _llm.EvaluateIdeaAsync(allMessages);
    }

    public async Task<string> GenerateSummaryAsync()
    {
        var summaryPrompt = new ChatMessage("user",
@"Provide a concise summary of the brainstorm session so far. Include:
1. Main idea discussed
2. Key decisions made
3. Open questions remaining
4. Next steps recommended

Keep it brief and actionable.
Respond in the same language used in the conversation.");

        var allMessages = new List<ChatMessage> { _systemMessage };
        allMessages.AddRange(CurrentSession.Messages);
        allMessages.Add(summaryPrompt);

        var summary = await _llm.ChatAsync(allMessages);
        CurrentSession.Summary = summary;
        return summary;
    }

    public async Task<string> GenerateBusinessPlanAsync()
    {
        var allMessages = new List<ChatMessage> { _systemMessage };
        allMessages.AddRange(CurrentSession.Messages);
        return await _llm.GenerateBusinessPlanAsync(allMessages);
    }

    public async Task<string> GenerateSpecAsync()
    {
        var allMessages = new List<ChatMessage> { _systemMessage };
        allMessages.AddRange(CurrentSession.Messages);
        return await _llm.GenerateSpecAsync(allMessages);
    }

    public void SaveCurrentSession() => _sessionManager.SaveSession(CurrentSession);

    public void SetSessionTitle(string title) => CurrentSession.Title = title;

    public int MessageCount => CurrentSession.Messages.Count;

    public void StartNewSession(string? title = null)
    {
        SaveCurrentSession();
        CurrentSession = _sessionManager.CreateSession(title);
    }

    public void LoadSession(Session session)
    {
        CurrentSession = session;
    }

    public void SwitchModel(string model)
    {
        _llm.SetModel(model);
    }

    public string GetCurrentModel() => _llm.GetModel();
}
