using System.Net.Http.Headers;
using Newtonsoft.Json;

namespace BrainstormCompanion;

public class BrainstormApiClient
{
    private readonly HttpClient _http;
    private readonly string _baseUrl;

    public BrainstormApiClient(string baseUrl)
    {
        _baseUrl = baseUrl.TrimEnd('/');
        _http = new HttpClient { Timeout = TimeSpan.FromSeconds(60) };
    }

    public async Task<StatusResponse> GetStatusAsync()
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/status");
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        return JsonConvert.DeserializeObject<StatusResponse>(json)!;
    }

    public async Task<ChatResponse> SendChatAsync(string message)
    {
        var content = new StringContent(
            JsonConvert.SerializeObject(new { message }),
            System.Text.Encoding.UTF8, "application/json");
        var response = await _http.PostAsync($"{_baseUrl}/api/chat", content);
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        return JsonConvert.DeserializeObject<ChatResponse>(json)!;
    }

    public async Task<AudioResponse> SendAudioAsync(byte[] wavData)
    {
        var content = new ByteArrayContent(wavData);
        content.Headers.ContentType = new MediaTypeHeaderValue("audio/wav");
        var response = await _http.PostAsync($"{_baseUrl}/api/audio", content);
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        return JsonConvert.DeserializeObject<AudioResponse>(json)!;
    }
    public async Task<string> GetBoardHtmlAsync()
    {
        var response = await _http.GetAsync($"{_baseUrl}/api/board");
        response.EnsureSuccessStatusCode();
        var json = await response.Content.ReadAsStringAsync();
        var result = JsonConvert.DeserializeObject<BoardResponse>(json)!;
        return result.html;
    }
}

public class StatusResponse
{
    public string status { get; set; } = "";
    public string model { get; set; } = "";
}

public class ChatResponse
{
    public string response { get; set; } = "";
    public string? audio { get; set; }
}

public class AudioResponse
{
    public string transcription { get; set; } = "";
    public string response { get; set; } = "";
    public string? audio { get; set; }
    public string? board_html { get; set; }
}

public class BoardResponse
{
    public string html { get; set; } = "";
}
