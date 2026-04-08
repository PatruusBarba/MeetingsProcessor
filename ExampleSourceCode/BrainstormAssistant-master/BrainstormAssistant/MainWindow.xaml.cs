using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using BrainstormAssistant.ViewModels;
using BrainstormAssistant.Views;
using Microsoft.Win32;
using Microsoft.Web.WebView2.Core;

namespace BrainstormAssistant;

public partial class MainWindow : Window
{
    private readonly MainViewModel _vm;
    private ChatManager? _chat;
    private TtsService? _tts;
    private ParakeetSttService? _stt;
    private CompanionServer? _companionServer;
    private SessionManager _sessionManager;
    private ArtifactManager _artifactManager;
    private AppConfig _config;

    // Current board content for saving
    private string _currentMdContent = "";
    private bool _webView2Ready;
    private string _currentHtmlContent = "";
    private bool _isMdTab = true;
    private CancellationTokenSource? _cts;

    public MainWindow()
    {
        InitializeComponent();

        // Ensure portable data directories exist and migrate legacy data
        AppPaths.EnsureDirectories();
        AppPaths.MigrateFromAppData();

        _vm = new MainViewModel();
        DataContext = _vm;

        _config = ConfigService.Load();
        _sessionManager = new SessionManager();
        _artifactManager = new ArtifactManager();

        InitializeServices();
    }

    private void InitializeServices()
    {
        var errors = _config.Validate();
        if (errors.Count > 0)
        {
            _vm.StatusText = "Configure your API key in Settings to get started.";
        }
        else
        {
            try
            {
                var llm = new LlmService(_config);
                _chat = new ChatManager(llm, _sessionManager, availableModels: _config.AvailableModels);
                _chat.ModelSwitched += OnModelSwitched;
                _chat.BoardMarkdownSet += OnBoardMarkdownSet;
                _chat.BoardHtmlSet += OnBoardHtmlSet;
                _chat.PartialBoardContent += OnPartialBoardContent;
                _chat.Provider = _config.Provider;
                _vm.SessionTitle = _chat.CurrentSession.Title;
                _vm.StatusText = $"Ready. Model: {_config.Model}";
            }
            catch (Exception ex)
            {
                _vm.StatusText = $"LLM init error: {ex.Message}";
            }
        }

        // TTS
        _tts = new TtsService(_config.TtsEnabled, _config.TtsVoice, _config.TtsRate, _config.TtsVolume);

        // STT - Parakeet ONNX continuous listening
        _stt = new ParakeetSttService(_config.SttEnabled, _config.MicrophoneDevice);
        _stt.SpeechRecognized += OnSpeechRecognized;
        _stt.PartialResult += OnPartialResult;
        _stt.RecognitionError += (_, err) => Dispatcher.Invoke(() =>
        {
            _vm.PartialSpeech = "";
            _vm.StatusText = $"Recognition error: {err}";
        });
        _stt.ListeningStarted += (_, _) => Dispatcher.Invoke(() =>
        {
            _vm.IsListening = true;
            _vm.StatusText = "Listening...";
        });
        _stt.ListeningStopped += (_, _) => Dispatcher.Invoke(() =>
        {
            _vm.IsListening = false;
            _vm.PartialSpeech = "";
            _vm.StatusText = "Microphone off.";
        });

        InitWebView2();
    }

    private async void InitWebView2()
    {
        try
        {
            await BoardBrowser.EnsureCoreWebView2Async(null);
            _webView2Ready = true;
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"WebView2 init error: {ex.Message}";
        }
    }

    private async void NavigateBoard(string html)
    {
        try
        {
            if (!_webView2Ready)
                await BoardBrowser.EnsureCoreWebView2Async(null);
            BoardBrowser.NavigateToString(html);
        }
        catch (Exception ex)
        {
            BoardStatusText.Text = $"Render error: {ex.Message}";
        }
    }

    private void OnModelSwitched(object? sender, string newModel)
    {
        Dispatcher.Invoke(() =>
        {
            _config.Model = newModel;
            ConfigService.Save(_config);
            _vm.StatusText = $"Ready. Model: {newModel}";
        });
    }

    private void OnBoardMarkdownSet(object? sender, string content)
    {
        Dispatcher.BeginInvoke(() => RenderMarkdownOnBoard(content));
    }

    private void OnBoardHtmlSet(object? sender, string content)
    {
        Dispatcher.BeginInvoke(() => RenderHtmlOnBoard(content));
    }

    private void OnPartialBoardContent(object? sender, (string toolName, string partialContent) e)
    {
        Dispatcher.Invoke(() =>
        {
            // Render partial board content as markdown (most common for streaming)
            RenderMarkdownOnBoard(e.partialContent);
        });
    }

    private void OnSpeechRecognized(object? sender, string text)
    {
        Dispatcher.Invoke(() =>
        {
            _vm.PartialSpeech = "";
            _vm.InputText = text;
            // Auto-send on voice recognition
            _ = SendMessageAsync();
        });
    }

    private void OnPartialResult(object? sender, string text)
    {
        Dispatcher.Invoke(() =>
        {
            _vm.PartialSpeech = text;
        });
    }

    private async Task SendMessageAsync()
    {
        var input = _vm.InputText.Trim();
        if (string.IsNullOrEmpty(input) || _chat == null)
            return;

        _vm.InputText = "";
        _vm.IsBusy = true;
        _vm.StatusText = "Thinking...";

        _cts?.Dispose();
        _cts = new CancellationTokenSource();
        var ct = _cts.Token;
        StopTtsButton.Visibility = Visibility.Visible;

        // Pause STT during entire LLM processing + TTS to avoid picking up stray audio
        _stt?.PauseListening();

        try
        {
            // Show user message immediately
            _vm.Messages.Add(new ChatMessage("user", input));
            ScrollToBottom();

            // Add a placeholder assistant message for streaming
            var assistantMsg = new ChatMessage("assistant", "");
            _vm.Messages.Add(assistantMsg);
            ScrollToBottom();

            // Wire up streaming token handler to update the placeholder message
            void OnToken(object? sender, string token)
            {
                Dispatcher.Invoke(() =>
                {
                    assistantMsg.Content += token;
                    ScrollToBottom();
                });
            }

            _chat.StreamingToken += OnToken;

            try
            {
                var response = await _chat.SendMessageAsync(input, ct);

                // Update final content
                Dispatcher.Invoke(() =>
                {
                    assistantMsg.Content = response;
                    ScrollToBottom();
                });
            }
            finally
            {
                _chat.StreamingToken -= OnToken;
            }

            _vm.StatusText = $"Ready. {_chat.MessageCount} messages in session.";

            var response2 = assistantMsg.Content ?? "";

            // TTS
            if (_tts != null && _tts.IsEnabled)
            {
                try
                {
                    StopTtsButton.Visibility = Visibility.Visible;
                    await _tts.SpeakAsync(response2);
                }
                catch { /* TTS failure is non-critical */ }
                finally
                {
                    StopTtsButton.Visibility = Visibility.Collapsed;
                }
            }
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Error: {ex.Message}";
            MessageBox.Show(ex.Message, "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            _vm.IsBusy = false;
            _stt?.ResumeListening();
        }
    }

    private void ScrollToBottom()
    {
        ChatScrollViewer.ScrollToEnd();
    }

    // ===================== Board Rendering =====================

    /// <summary>
    /// Renders Markdown content on the board using a lightweight HTML conversion
    /// with Mermaid support via CDN.
    /// </summary>
    private void RenderMarkdownOnBoard(string markdown)
    {
        _currentMdContent = markdown;
        _isMdTab = true;
        MdTabButton.IsChecked = true;

        // Convert markdown to HTML with marked.js + mermaid.js via CDN
        var html = WrapMarkdownInHtml(markdown);
        ShowBoard();
        NavigateBoard(html);
        BoardStatusText.Text = $"Markdown rendered | {markdown.Length} chars";
    }

    /// <summary>
    /// Renders raw HTML content on the board.
    /// </summary>
    private void RenderHtmlOnBoard(string htmlContent)
    {
        _currentHtmlContent = htmlContent;
        _isMdTab = false;
        HtmlTabButton.IsChecked = true;

        // Wrap in a full HTML document if it's just a fragment
        var fullHtml = htmlContent.TrimStart();
        if (!fullHtml.StartsWith("<!DOCTYPE", StringComparison.OrdinalIgnoreCase) &&
            !fullHtml.StartsWith("<html", StringComparison.OrdinalIgnoreCase))
        {
            fullHtml = $@"<!DOCTYPE html>
<html>
<head>
<meta charset=""utf-8"">
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #1E1E1E; color: #E0E0E0; padding: 20px; margin: 0; }}
a {{ color: #4FC3F7; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #555; padding: 8px; text-align: left; }}
th {{ background: #333; }}
</style>
</head>
<body>
{htmlContent}
</body>
</html>";
        }

        ShowBoard();
        NavigateBoard(fullHtml);
        BoardStatusText.Text = $"HTML rendered | {htmlContent.Length} chars";
    }

    /// <summary>
    /// Converts markdown to HTML in C# and wraps in a styled HTML page.
    /// Server-side conversion keeps rendering fast.
    /// </summary>
    internal static string WrapMarkdownInHtml(string markdown)
    {
        var bodyHtml = ConvertMarkdownToHtml(markdown);

        return $@"<!DOCTYPE html>
<html>
<head>
<meta charset=""utf-8"">
<style>
body {{
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #1E1E1E;
    color: #E0E0E0;
    padding: 20px;
    margin: 0;
    line-height: 1.6;
}}
h1, h2, h3, h4, h5, h6 {{ color: #4FC3F7; margin-top: 1.2em; }}
h1 {{ border-bottom: 1px solid #444; padding-bottom: 0.3em; }}
h2 {{ border-bottom: 1px solid #333; padding-bottom: 0.2em; }}
a {{ color: #4FC3F7; }}
code {{
    background: #2D2D2D;
    padding: 2px 6px;
    border-radius: 3px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 0.9em;
}}
pre {{
    background: #2D2D2D;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
    border: 1px solid #444;
}}
pre code {{
    background: none;
    padding: 0;
}}
blockquote {{
    border-left: 3px solid #4FC3F7;
    margin-left: 0;
    padding-left: 16px;
    color: #AAAAAA;
}}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #555; padding: 8px 12px; text-align: left; }}
th {{ background: #333; color: #4FC3F7; }}
tr:nth-child(even) {{ background: #252525; }}
ul, ol {{ padding-left: 24px; }}
li {{ margin: 4px 0; }}
hr {{ border: none; border-top: 1px solid #444; margin: 1.5em 0; }}
strong {{ color: #FFD54F; }}
.mermaid-block {{
    background: #2D2D2D;
    padding: 16px;
    border-radius: 6px;
    font-family: 'Consolas', 'Courier New', monospace;
    white-space: pre;
    border: 1px solid #444;
    color: #A5D6A7;
}}
.mermaid-label {{ color: #4FC3F7; font-weight: bold; margin-bottom: 8px; }}
</style>
</head>
<body>
{bodyHtml}
</body>
</html>";
    }

    /// <summary>
    /// Converts markdown text to HTML using C# string processing.
    /// Handles code blocks, mermaid blocks, headers, lists, blockquotes, tables, and inline formatting.
    /// </summary>
    internal static string ConvertMarkdownToHtml(string markdown)
    {
        var lines = markdown.Split('\n');
        var result = new System.Text.StringBuilder();
        bool inCode = false;
        bool inList = false;
        string listType = "";
        bool inTable = false;
        bool tableHeaderDone = false;

        for (int i = 0; i < lines.Length; i++)
        {
            var line = lines[i].TrimEnd('\r');

            // Code block toggle
            if (line.TrimStart().StartsWith("```"))
            {
                if (inCode)
                {
                    // Close code block
                    result.AppendLine("</code></pre>");
                    inCode = false;
                    continue;
                }
                else
                {
                    // Close any open list/table
                    if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                    if (inTable) { result.AppendLine("</table>"); inTable = false; tableHeaderDone = false; }

                    var lang = line.TrimStart().Substring(3).Trim();
                    if (string.Equals(lang, "mermaid", StringComparison.OrdinalIgnoreCase))
                    {
                        // Collect mermaid content and render as styled pre block
                        var mermaidLines = new System.Collections.Generic.List<string>();
                        i++;
                        while (i < lines.Length && !lines[i].TrimStart().StartsWith("```"))
                        {
                            mermaidLines.Add(lines[i].TrimEnd('\r'));
                            i++;
                        }
                        result.AppendLine("<div class=\"mermaid-label\">Mermaid Diagram:</div>");
                        result.Append("<div class=\"mermaid-block\">");
                        result.Append(EscapeHtml(string.Join("\n", mermaidLines)));
                        result.AppendLine("</div>");
                    }
                    else
                    {
                        result.AppendLine("<pre><code>");
                        inCode = true;
                    }
                    continue;
                }
            }

            // Inside code block — output escaped, no formatting
            if (inCode)
            {
                result.AppendLine(EscapeHtml(line));
                continue;
            }

            // Table detection: line contains | and is not a list
            if (line.TrimStart().StartsWith("|") && line.TrimEnd().EndsWith("|"))
            {
                // Check if this is a separator row (e.g., |---|---|)
                var stripped = line.Trim().Trim('|').Trim();
                if (System.Text.RegularExpressions.Regex.IsMatch(stripped, @"^[\s\-\|:]+$") && stripped.Contains("-"))
                {
                    // Separator row — skip, but mark header as done
                    tableHeaderDone = true;
                    continue;
                }

                if (!inTable)
                {
                    // Close any open list
                    if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                    result.AppendLine("<table>");
                    inTable = true;
                    tableHeaderDone = false;
                }

                // Parse cells
                var cells = line.Trim().Trim('|').Split('|');
                var cellTag = !tableHeaderDone ? "th" : "td";
                result.Append("<tr>");
                foreach (var cell in cells)
                {
                    result.Append($"<{cellTag}>{InlineFormat(cell.Trim())}</{cellTag}>");
                }
                result.AppendLine("</tr>");
                continue;
            }

            // Close table if we're no longer in table rows
            if (inTable)
            {
                result.AppendLine("</table>");
                inTable = false;
                tableHeaderDone = false;
            }

            // Empty line — close list
            if (string.IsNullOrWhiteSpace(line))
            {
                if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                result.AppendLine("");
                continue;
            }

            // Headers
            var headerMatch = System.Text.RegularExpressions.Regex.Match(line, @"^(#{1,6})\s+(.+)$");
            if (headerMatch.Success)
            {
                if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                int level = headerMatch.Groups[1].Value.Length;
                result.AppendLine($"<h{level}>{InlineFormat(headerMatch.Groups[2].Value)}</h{level}>");
                continue;
            }

            // HR
            if (System.Text.RegularExpressions.Regex.IsMatch(line, @"^---+\s*$"))
            {
                if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                result.AppendLine("<hr>");
                continue;
            }

            // Blockquote
            if (line.StartsWith("> "))
            {
                if (inList) { result.AppendLine(listType == "ul" ? "</ul>" : "</ol>"); inList = false; }
                result.AppendLine($"<blockquote>{InlineFormat(line.Substring(2))}</blockquote>");
                continue;
            }

            // Unordered list (- item or * item)
            var ulMatch = System.Text.RegularExpressions.Regex.Match(line, @"^(\s*)[*\-]\s+(.+)$");
            if (ulMatch.Success)
            {
                if (!inList || listType != "ul")
                {
                    if (inList) result.AppendLine(listType == "ul" ? "</ul>" : "</ol>");
                    result.AppendLine("<ul>");
                    inList = true;
                    listType = "ul";
                }
                result.AppendLine($"<li>{InlineFormat(ulMatch.Groups[2].Value)}</li>");
                continue;
            }

            // Ordered list (1. item)
            var olMatch = System.Text.RegularExpressions.Regex.Match(line, @"^(\s*)\d+\.\s+(.+)$");
            if (olMatch.Success)
            {
                if (!inList || listType != "ol")
                {
                    if (inList) result.AppendLine(listType == "ul" ? "</ul>" : "</ol>");
                    result.AppendLine("<ol>");
                    inList = true;
                    listType = "ol";
                }
                result.AppendLine($"<li>{InlineFormat(olMatch.Groups[2].Value)}</li>");
                continue;
            }

            // Paragraph
            result.AppendLine($"<p>{InlineFormat(line)}</p>");
        }

        // Close any open blocks
        if (inCode) result.AppendLine("</code></pre>");
        if (inList) result.AppendLine(listType == "ul" ? "</ul>" : "</ol>");
        if (inTable) result.AppendLine("</table>");

        return result.ToString();
    }

    /// <summary>
    /// Applies inline markdown formatting: bold, italic, inline code, links.
    /// </summary>
    internal static string InlineFormat(string text)
    {
        // Escape HTML first
        text = EscapeHtml(text);

        // Inline code (must be before bold/italic to avoid formatting inside code)
        text = System.Text.RegularExpressions.Regex.Replace(text, @"`(.+?)`", "<code>$1</code>");

        // Bold: **text** or __text__
        text = System.Text.RegularExpressions.Regex.Replace(text, @"\*\*(.+?)\*\*", "<strong>$1</strong>");
        text = System.Text.RegularExpressions.Regex.Replace(text, @"__(.+?)__", "<strong>$1</strong>");

        // Italic: *text* or _text_ (but not inside words for underscore)
        text = System.Text.RegularExpressions.Regex.Replace(text, @"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", "<em>$1</em>");
        text = System.Text.RegularExpressions.Regex.Replace(text, @"(?<!\w)_(?!_)(.+?)(?<!_)_(?!\w)", "<em>$1</em>");

        // Links: [text](url)
        text = System.Text.RegularExpressions.Regex.Replace(text, @"\[(.+?)\]\((.+?)\)", "<a href=\"$2\">$1</a>");

        return text;
    }

    /// <summary>
    /// Escapes HTML special characters.
    /// </summary>
    internal static string EscapeHtml(string text)
    {
        return text
            .Replace("&", "&amp;")
            .Replace("<", "&lt;")
            .Replace(">", "&gt;")
            .Replace("\"", "&quot;");
    }

    private void ShowBoard()
    {
        BoardColumn.Width = new GridLength(500);
        _vm.BoardVisible = "visible";
        BoardToggle.IsChecked = true;
    }

    private void HideBoard()
    {
        BoardColumn.Width = new GridLength(0);
        _vm.BoardVisible = "";
        BoardToggle.IsChecked = false;
    }

    // ===================== Event Handlers =====================

    private void InputTextBox_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Enter && !_vm.IsBusy)
        {
            _ = SendMessageAsync();
            e.Handled = true;
        }
    }

    private async void Send_Click(object sender, RoutedEventArgs e)
    {
        await SendMessageAsync();
    }

    private async void ToggleVoice_Click(object sender, RoutedEventArgs e)
    {
        if (_stt == null) return;

        if (_stt.IsListening)
        {
            _stt.StopListening();
        }
        else
        {
            // Check if models are downloaded
            if (!ModelDownloader.AllModelsPresent())
            {
                var result = MessageBox.Show(
                    "Parakeet STT models need to be downloaded (~670MB).\n" +
                    "This is required for voice recognition.\n\nDownload now?",
                    "Download STT Models",
                    MessageBoxButton.YesNo, MessageBoxImage.Question);

                if (result != MessageBoxResult.Yes) return;

                await DownloadModelsWithProgress();

                if (!ModelDownloader.AllModelsPresent()) return;
            }

            try
            {
                _stt.IsEnabled = true;
                _stt.StartListening();
            }
            catch (Exception ex)
            {
                _vm.StatusText = $"Mic error: {ex.Message}";
                MessageBox.Show(
                    $"Could not start speech recognition:\n{ex.Message}",
                    "Voice Error", MessageBoxButton.OK, MessageBoxImage.Warning);
            }
        }
    }

    private async Task DownloadModelsWithProgress()
    {
        _vm.IsBusy = true;
        _vm.StatusText = "Downloading STT models...";
        DownloadProgressPanel.Visibility = Visibility.Visible;
        DownloadProgressBar.Value = 0;

        try
        {
            var missing = ModelDownloader.GetMissingFiles();
            int fileIndex = 0;

            var progress = new Progress<(string file, double percent)>(p =>
            {
                Dispatcher.Invoke(() =>
                {
                    DownloadFileText.Text = $"[{fileIndex + 1}/{missing.Count}] {p.file}";
                    DownloadProgressBar.Value = p.percent;
                    DownloadPercentText.Text = $"{p.percent:F0}%";
                    _vm.StatusText = $"Downloading {p.file}... {p.percent:F0}%";
                    if (p.percent >= 100) fileIndex++;
                });
            });

            await ModelDownloader.DownloadModelsAsync(progress);
            _vm.StatusText = "STT models downloaded successfully.";
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Download failed: {ex.Message}";
            MessageBox.Show(
                $"Failed to download models:\n{ex.Message}",
                "Download Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
        finally
        {
            DownloadProgressPanel.Visibility = Visibility.Collapsed;
            _vm.IsBusy = false;
        }
    }

    private void TtsToggle_Changed(object sender, RoutedEventArgs e)
    {
        if (_tts != null)
            _tts.IsEnabled = TtsToggle.IsChecked == true;
    }

    private void StopTts_Click(object sender, RoutedEventArgs e)
    {
        _tts?.Stop();
        StopTtsButton.Visibility = Visibility.Collapsed;
    }

    private void BoardToggle_Changed(object sender, RoutedEventArgs e)
    {
        // Guard: BoardColumn may not be initialized during XAML parsing
        if (BoardColumn == null) return;

        if (BoardToggle.IsChecked == true)
            ShowBoard();
        else
            HideBoard();
    }

    private void ServerToggle_Changed(object sender, RoutedEventArgs e)
    {
        if (ServerToggle.IsChecked == true)
        {
            try
            {
                _companionServer = new CompanionServer(
                    ttsVoice: _config.TtsVoice,
                    ttsRate: _config.TtsRate,
                    ttsVolume: _config.TtsVolume);
                if (_chat != null) _companionServer.SetChatManager(_chat);
                if (_stt != null) _companionServer.SetSttService(_stt);
                _companionServer.GetBoardHtml = () =>
                {
                    string? html = null;
                    Dispatcher.Invoke(() =>
                    {
                        // Use _isMdTab to determine which content was last set
                        if (_isMdTab && !string.IsNullOrEmpty(_currentMdContent))
                        {
                            html = WrapMarkdownInHtml(_currentMdContent);
                        }
                        else if (!_isMdTab && !string.IsNullOrEmpty(_currentHtmlContent))
                        {
                            var content = _currentHtmlContent.TrimStart();
                            if (!content.StartsWith("<!DOCTYPE", StringComparison.OrdinalIgnoreCase) &&
                                !content.StartsWith("<html", StringComparison.OrdinalIgnoreCase))
                            {
                                html = $"<!DOCTYPE html><html><head><meta charset='utf-8'/>" +
                                       "<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#1E1E1E;color:#E0E0E0;padding:20px;margin:0}}" +
                                       "a{{color:#4FC3F7}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #555;padding:8px;text-align:left}}th{{background:#333}}</style>" +
                                       $"</head><body>{_currentHtmlContent}</body></html>";
                            }
                            else
                            {
                                html = _currentHtmlContent;
                            }
                        }
                        else if (!string.IsNullOrEmpty(_currentMdContent))
                        {
                            html = WrapMarkdownInHtml(_currentMdContent);
                        }
                        else if (!string.IsNullOrEmpty(_currentHtmlContent))
                        {
                            html = _currentHtmlContent;
                        }
                    });
                    return html;
                };
                _companionServer.LogMessage += (_, msg) =>
                    Dispatcher.Invoke(() => _vm.StatusText = $"[Server] {msg}");
                _companionServer.ChatCompleted += (_, result) =>
                    Dispatcher.Invoke(() =>
                    {
                        // Sync companion messages into the UI
                        if (_chat != null)
                        {
                            _vm.Messages.Clear();
                            foreach (var msg in _chat.CurrentSession.Messages)
                            {
                                if (msg.Role == "user" || (msg.Role == "assistant" && msg.ToolCalls == null))
                                    _vm.Messages.Add(msg);
                            }
                            ScrollToBottom();
                        }
                    });
                _companionServer.Start();
                _vm.StatusText = $"Companion server running at {_companionServer.Address}";
            }
            catch (Exception ex)
            {
                _vm.StatusText = $"Server error: {ex.Message}";
                ServerToggle.IsChecked = false;
            }
        }
        else
        {
            _companionServer?.Stop();
            _companionServer?.Dispose();
            _companionServer = null;
            _vm.StatusText = "Companion server stopped.";
        }
    }

    private void BoardTab_Changed(object sender, RoutedEventArgs e)
    {
        if (MdTabButton == null || BoardStatusText == null) return;
        _isMdTab = MdTabButton.IsChecked == true;

        if (_isMdTab)
        {
            // Markdown tab selected
            if (!string.IsNullOrEmpty(_currentMdContent))
            {
                var html = WrapMarkdownInHtml(_currentMdContent);
                NavigateBoard(html);
                BoardStatusText.Text = $"Markdown rendered | {_currentMdContent.Length} chars";
            }
            else if (!string.IsNullOrEmpty(_currentHtmlContent))
            {
                // No markdown content — show HTML content rendered as-is
                BoardStatusText.Text = "No markdown content. Showing HTML content.";
            }
            else
            {
                BoardStatusText.Text = "No content. Send a message that uses the board.";
            }
        }
        else
        {
            // HTML tab selected
            if (!string.IsNullOrEmpty(_currentHtmlContent))
            {
                var fullHtml = _currentHtmlContent.TrimStart();
                if (!fullHtml.StartsWith("<!DOCTYPE", StringComparison.OrdinalIgnoreCase) &&
                    !fullHtml.StartsWith("<html", StringComparison.OrdinalIgnoreCase))
                {
                    fullHtml = $@"<!DOCTYPE html>
<html><head><meta charset=""utf-8"">
<style>body {{ font-family: 'Segoe UI', Arial, sans-serif; background: #1E1E1E; color: #E0E0E0; padding: 20px; margin: 0; }}
a {{ color: #4FC3F7; }} table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #555; padding: 8px; text-align: left; }} th {{ background: #333; }}</style>
</head><body>{_currentHtmlContent}</body></html>";
                }
                NavigateBoard(fullHtml);
                BoardStatusText.Text = $"HTML rendered | {_currentHtmlContent.Length} chars";
            }
            else if (!string.IsNullOrEmpty(_currentMdContent))
            {
                // No HTML content — render the markdown content as HTML
                var html = WrapMarkdownInHtml(_currentMdContent);
                NavigateBoard(html);
                BoardStatusText.Text = $"Markdown as HTML | {_currentMdContent.Length} chars";
            }
            else
            {
                BoardStatusText.Text = "No content. Send a message that uses the board.";
            }
        }
    }

    private void CloseBoard_Click(object sender, RoutedEventArgs e)
    {
        HideBoard();
    }

    private void SaveArtifact_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null) return;

        var sessionId = _chat.CurrentSession.Id;
        try
        {
            if (_isMdTab && !string.IsNullOrEmpty(_currentMdContent))
            {
                var path = _artifactManager.SaveMarkdown(sessionId, _currentMdContent);
                _vm.StatusText = $"Markdown saved: {Path.GetFileName(path)}";
                BoardStatusText.Text = $"Saved: {Path.GetFileName(path)}";
            }
            else if (!_isMdTab && !string.IsNullOrEmpty(_currentHtmlContent))
            {
                var path = _artifactManager.SaveHtml(sessionId, _currentHtmlContent);
                _vm.StatusText = $"HTML saved: {Path.GetFileName(path)}";
                BoardStatusText.Text = $"Saved: {Path.GetFileName(path)}";
            }
            else
            {
                _vm.StatusText = "No content to save.";
            }
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Save error: {ex.Message}";
        }
    }

    private void NewSession_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null) return;

        _chat.SaveCurrentSession();
        _chat.StartNewSession();
        _vm.Messages.Clear();
        _vm.SessionTitle = _chat.CurrentSession.Title;
        _vm.StatusText = "New session started.";
        _currentMdContent = "";
        _currentHtmlContent = "";
    }

    private void LoadSession_Click(object sender, RoutedEventArgs e)
    {
        var sessions = _sessionManager.ListSessions();
        if (sessions.Count == 0)
        {
            MessageBox.Show("No saved sessions.", "Load", MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        var loadWindow = new SessionListWindow(sessions);
        loadWindow.Owner = this;
        if (loadWindow.ShowDialog() == true && loadWindow.SelectedSession != null)
        {
            var loaded = _sessionManager.LoadSession(loadWindow.SelectedSession.Id);
            if (loaded != null && _chat != null)
            {
                _chat.LoadSession(loaded);
                _vm.Messages.Clear();
                foreach (var msg in loaded.Messages)
                    _vm.Messages.Add(msg);
                _vm.SessionTitle = loaded.Title;
                _vm.StatusText = $"Loaded: {loaded.Title} ({loaded.Messages.Count} messages)";
                ScrollToBottom();
            }
        }
    }

    private void SaveSession_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null) return;
        _chat.SaveCurrentSession();
        _vm.StatusText = "Session saved.";
    }

    private void ExportSession_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null) return;

        var dlg = new SaveFileDialog
        {
            Filter = "Markdown|*.md|Text|*.txt",
            FileName = $"brainstorm-{_chat.CurrentSession.Id[..8]}.md"
        };

        if (dlg.ShowDialog() == true)
        {
            var content = EvaluationParser.FormatSessionExport(_chat.CurrentSession);
            File.WriteAllText(dlg.FileName, content);
            _vm.StatusText = $"Exported to {dlg.FileName}";
        }
    }

    private async void Summary_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null || _chat.MessageCount == 0)
        {
            MessageBox.Show("Start a conversation first before generating a summary.", "Summary",
                MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _vm.IsBusy = true;
        _vm.StatusText = "Generating summary...";
        _stt?.PauseListening();

        try
        {
            var summary = await _chat.GenerateSummaryAsync();
            _vm.Messages.Add(new ChatMessage("assistant", summary));
            ScrollToBottom();

            // Also render on the board
            RenderMarkdownOnBoard(summary);

            _vm.StatusText = "Summary generated.";
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Summary error: {ex.Message}";
        }
        finally
        {
            _vm.IsBusy = false;
            _stt?.ResumeListening();
        }
    }

    private async void Evaluate_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null || _chat.MessageCount == 0)
        {
            MessageBox.Show("Start a conversation first before evaluating.", "Evaluate",
                MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _vm.IsBusy = true;
        _vm.StatusText = "Evaluating idea...";
        _stt?.PauseListening();

        try
        {
            var result = await _chat.EvaluateIdeaAsync();
            var evaluation = EvaluationParser.Parse(result);

            if (evaluation != null)
            {
                var formatted = EvaluationParser.Format(evaluation);
                _vm.Messages.Add(new ChatMessage("assistant", formatted));
            }
            else
            {
                _vm.Messages.Add(new ChatMessage("assistant", result));
            }

            ScrollToBottom();
            _vm.StatusText = "Evaluation complete.";
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Evaluation error: {ex.Message}";
        }
        finally
        {
            _vm.IsBusy = false;
            _stt?.ResumeListening();
        }
    }

    private async void BusinessPlan_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null || _chat.MessageCount == 0)
        {
            MessageBox.Show("Start a conversation first before generating a business plan.", "Business Plan",
                MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _vm.IsBusy = true;
        _vm.StatusText = "Generating business plan...";
        _stt?.PauseListening();

        try
        {
            var plan = await _chat.GenerateBusinessPlanAsync();

            _vm.Messages.Add(new ChatMessage("assistant", "Business plan generated. See the board for the formatted version."));
            ScrollToBottom();

            // Render on MD board and auto-save as artifact
            RenderMarkdownOnBoard(plan);
            _currentMdContent = plan;

            var path = _artifactManager.SaveMarkdown(
                _chat.CurrentSession.Id, plan, "business-plan.md");
            BoardStatusText.Text = $"Business plan saved: {Path.GetFileName(path)}";

            _vm.StatusText = "Business plan generated and saved.";
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Business plan error: {ex.Message}";
        }
        finally
        {
            _vm.IsBusy = false;
            _stt?.ResumeListening();
        }
    }

    private async void Spec_Click(object sender, RoutedEventArgs e)
    {
        if (_chat == null || _chat.MessageCount == 0)
        {
            MessageBox.Show("Start a conversation first before generating a spec.", "Spec/PRD",
                MessageBoxButton.OK, MessageBoxImage.Information);
            return;
        }

        _vm.IsBusy = true;
        _vm.StatusText = "Generating spec/PRD...";
        _stt?.PauseListening();

        try
        {
            var spec = await _chat.GenerateSpecAsync();

            _vm.Messages.Add(new ChatMessage("assistant", "Spec/PRD generated. See the board for the formatted version."));
            ScrollToBottom();

            // Render on MD board and auto-save as artifact
            RenderMarkdownOnBoard(spec);
            _currentMdContent = spec;

            var path = _artifactManager.SaveMarkdown(
                _chat.CurrentSession.Id, spec, "spec-prd.md");
            BoardStatusText.Text = $"Spec saved: {Path.GetFileName(path)}";

            _vm.StatusText = "Spec/PRD generated and saved.";
        }
        catch (Exception ex)
        {
            _vm.StatusText = $"Spec error: {ex.Message}";
        }
        finally
        {
            _vm.IsBusy = false;
            _stt?.ResumeListening();
        }
    }

    private void Settings_Click(object sender, RoutedEventArgs e)
    {
        var settingsWindow = new SettingsWindow(_config);
        settingsWindow.Owner = this;
        if (settingsWindow.ShowDialog() == true)
        {
            _config = settingsWindow.Config;
            ConfigService.Save(_config);

            // Reinitialize services with new config
            _stt?.Dispose();
            _tts?.Dispose();
            _vm.Messages.Clear();
            InitializeServices();
        }
    }

    protected override void OnClosed(EventArgs e)
    {
        _chat?.SaveCurrentSession();
        _companionServer?.Dispose();
        _stt?.Dispose();
        _tts?.Dispose();
        base.OnClosed(e);
    }
}
