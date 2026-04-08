using BrainstormAssistant.Models;
using BrainstormAssistant.Services;

namespace BrainstormAssistant.Tests;

public class SessionManagerTests : IDisposable
{
    private readonly string _testDir;
    private readonly SessionManager _manager;

    public SessionManagerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_test_{Guid.NewGuid():N}");
        _manager = new SessionManager(_testDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_testDir))
            Directory.Delete(_testDir, true);
    }

    [Fact]
    public void CreateSession_DefaultTitle_ContainsBrainstorm()
    {
        var session = _manager.CreateSession();

        Assert.Contains("Brainstorm", session.Title);
        Assert.NotEmpty(session.Id);
        Assert.Empty(session.Messages);
    }

    [Fact]
    public void CreateSession_CustomTitle_SetsTitle()
    {
        var session = _manager.CreateSession("My Idea");

        Assert.Equal("My Idea", session.Title);
    }

    [Fact]
    public void SaveAndLoad_RoundTrip_PreservesData()
    {
        var session = _manager.CreateSession("Test Session");
        session.Messages.Add(new ChatMessage("user", "Hello"));
        session.Messages.Add(new ChatMessage("assistant", "Hi there!"));
        session.Summary = "Test summary";

        _manager.SaveSession(session);
        var loaded = _manager.LoadSession(session.Id);

        Assert.NotNull(loaded);
        Assert.Equal(session.Id, loaded!.Id);
        Assert.Equal("Test Session", loaded.Title);
        Assert.Equal(2, loaded.Messages.Count);
        Assert.Equal("Hello", loaded.Messages[0].Content);
        Assert.Equal("assistant", loaded.Messages[1].Role);
        Assert.Equal("Test summary", loaded.Summary);
    }

    [Fact]
    public void LoadSession_NonExistent_ReturnsNull()
    {
        var loaded = _manager.LoadSession("non-existent-id");

        Assert.Null(loaded);
    }

    [Fact]
    public void SaveSession_UpdatesTimestamp()
    {
        var session = _manager.CreateSession();
        var originalTimestamp = session.UpdatedAt;

        // Small delay
        Thread.Sleep(10);
        _manager.SaveSession(session);

        Assert.True(session.UpdatedAt >= originalTimestamp);
    }

    [Fact]
    public void ListSessions_Empty_ReturnsEmptyList()
    {
        var sessions = _manager.ListSessions();

        Assert.Empty(sessions);
    }

    [Fact]
    public void ListSessions_MultipleSessions_ReturnsSortedByUpdatedAt()
    {
        // Save sessions first, then overwrite UpdatedAt in the files
        // because SaveSession sets UpdatedAt to current time
        var s1 = _manager.CreateSession("First");
        _manager.SaveSession(s1);
        s1.UpdatedAt = 1000;
        File.WriteAllText(_manager.GetSessionPath(s1.Id),
            Newtonsoft.Json.JsonConvert.SerializeObject(s1));

        var s2 = _manager.CreateSession("Second");
        _manager.SaveSession(s2);
        s2.UpdatedAt = 3000;
        File.WriteAllText(_manager.GetSessionPath(s2.Id),
            Newtonsoft.Json.JsonConvert.SerializeObject(s2));

        var s3 = _manager.CreateSession("Third");
        _manager.SaveSession(s3);
        s3.UpdatedAt = 2000;
        File.WriteAllText(_manager.GetSessionPath(s3.Id),
            Newtonsoft.Json.JsonConvert.SerializeObject(s3));

        var sessions = _manager.ListSessions();

        Assert.Equal(3, sessions.Count);
        Assert.Equal("Second", sessions[0].Title);
        Assert.Equal("Third", sessions[1].Title);
        Assert.Equal("First", sessions[2].Title);
    }

    [Fact]
    public void DeleteSession_Existing_ReturnsTrue()
    {
        var session = _manager.CreateSession("To Delete");
        _manager.SaveSession(session);

        var result = _manager.DeleteSession(session.Id);

        Assert.True(result);
        Assert.Null(_manager.LoadSession(session.Id));
    }

    [Fact]
    public void DeleteSession_NonExistent_ReturnsFalse()
    {
        var result = _manager.DeleteSession("non-existent");

        Assert.False(result);
    }

    [Fact]
    public void AddMessage_AddsToSessionAndUpdatesTimestamp()
    {
        var session = _manager.CreateSession();
        var before = session.UpdatedAt;

        Thread.Sleep(10);
        var msg = new ChatMessage("user", "Test message");
        _manager.AddMessage(session, msg);

        Assert.Single(session.Messages);
        Assert.Equal("Test message", session.Messages[0].Content);
        Assert.True(session.UpdatedAt >= before);
    }

    [Fact]
    public void GetSessionPath_ReturnsCorrectPath()
    {
        var path = _manager.GetSessionPath("test-id");

        Assert.EndsWith("test-id.json", path);
        Assert.StartsWith(_testDir, path);
    }
}
