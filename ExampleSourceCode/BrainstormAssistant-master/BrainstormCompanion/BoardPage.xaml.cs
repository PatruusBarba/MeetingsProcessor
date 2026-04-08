namespace BrainstormCompanion;

/// <summary>
/// Displays the HTML board content from the PC app in a WebView.
/// Fetches board HTML from the companion server's /api/board endpoint.
/// </summary>
public partial class BoardPage : ContentPage
{
    private readonly BrainstormApiClient _api;

    public BoardPage(BrainstormApiClient api)
    {
        InitializeComponent();
        _api = api;
        LoadBoard();
    }

    private async void LoadBoard()
    {
        try
        {
            var html = await _api.GetBoardHtmlAsync();

            if (string.IsNullOrWhiteSpace(html))
            {
                html = WrapHtml("<p style='color:#888'>No board content available.</p>");
            }
            else if (!html.TrimStart().StartsWith("<"))
            {
                // Wrap plain text in basic HTML
                html = WrapHtml($"<pre style='color:#e0e0e0;white-space:pre-wrap'>{html}</pre>");
            }
            else if (!html.Contains("<html", StringComparison.OrdinalIgnoreCase))
            {
                html = WrapHtml(html);
            }

            BoardWebView.Source = new HtmlWebViewSource { Html = html };
        }
        catch (Exception ex)
        {
            var errorHtml = WrapHtml($"<p style='color:#ff6b6b'>Failed to load board: {ex.Message}</p>");
            BoardWebView.Source = new HtmlWebViewSource { Html = errorHtml };
        }
    }

    private async void OnRefreshClicked(object sender, EventArgs e)
    {
        RefreshButton.IsEnabled = false;
        RefreshButton.Text = "⏳ Loading...";

        LoadBoard();
        await Task.Delay(500);

        RefreshButton.Text = "🔄 Refresh";
        RefreshButton.IsEnabled = true;
    }

    private static string WrapHtml(string body) =>
        $"<!DOCTYPE html><html><head><meta charset='utf-8'/>" +
        $"<meta name='viewport' content='width=device-width,initial-scale=1'/>" +
        $"<style>body{{background:#1e1e1e;color:#e0e0e0;font-family:sans-serif;padding:16px;margin:0}}</style>" +
        $"</head><body>{body}</body></html>";
}
