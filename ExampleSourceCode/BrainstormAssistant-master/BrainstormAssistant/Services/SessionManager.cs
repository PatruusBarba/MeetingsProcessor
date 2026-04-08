using System.IO;
using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

public interface ISessionManager
{
    Session CreateSession(string? title = null);
    void SaveSession(Session session);
    Session? LoadSession(string sessionId);
    List<Session> ListSessions();
    bool DeleteSession(string sessionId);
    void AddMessage(Session session, ChatMessage message);
    string GetSessionPath(string sessionId);
}

public class SessionManager : ISessionManager
{
    private readonly string _sessionsDir;

    public SessionManager(string? sessionsDir = null)
    {
        _sessionsDir = sessionsDir ?? AppPaths.SessionsDir;
        EnsureDir();
    }

    private void EnsureDir()
    {
        if (!Directory.Exists(_sessionsDir))
            Directory.CreateDirectory(_sessionsDir);
    }

    public Session CreateSession(string? title = null)
    {
        return new Session
        {
            Title = title ?? $"Brainstorm {DateTime.Now:g}"
        };
    }

    public void SaveSession(Session session)
    {
        session.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        var path = GetSessionPath(session.Id);
        var json = JsonConvert.SerializeObject(session, Formatting.Indented);
        File.WriteAllText(path, json);
    }

    public Session? LoadSession(string sessionId)
    {
        var path = GetSessionPath(sessionId);
        if (!File.Exists(path))
            return null;

        var json = File.ReadAllText(path);
        return JsonConvert.DeserializeObject<Session>(json);
    }

    public List<Session> ListSessions()
    {
        EnsureDir();
        var sessions = new List<Session>();

        foreach (var file in Directory.GetFiles(_sessionsDir, "*.json"))
        {
            try
            {
                var json = File.ReadAllText(file);
                var session = JsonConvert.DeserializeObject<Session>(json);
                if (session != null)
                    sessions.Add(session);
            }
            catch { /* skip corrupt files */ }
        }

        return sessions.OrderByDescending(s => s.UpdatedAt).ToList();
    }

    public bool DeleteSession(string sessionId)
    {
        var path = GetSessionPath(sessionId);
        if (File.Exists(path))
        {
            File.Delete(path);
            return true;
        }
        return false;
    }

    public void AddMessage(Session session, ChatMessage message)
    {
        session.Messages.Add(message);
        session.UpdatedAt = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
    }

    public string GetSessionPath(string sessionId)
        => Path.Combine(_sessionsDir, $"{sessionId}.json");

    public string GetSessionsDir() => _sessionsDir;
}
