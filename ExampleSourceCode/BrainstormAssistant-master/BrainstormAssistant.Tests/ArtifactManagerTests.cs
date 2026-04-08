using BrainstormAssistant.Services;

namespace BrainstormAssistant.Tests;

public class ArtifactManagerTests : IDisposable
{
    private readonly string _testDir;
    private readonly ArtifactManager _manager;

    public ArtifactManagerTests()
    {
        _testDir = Path.Combine(Path.GetTempPath(), $"brainstorm_artifact_test_{Guid.NewGuid():N}");
        _manager = new ArtifactManager(_testDir);
    }

    public void Dispose()
    {
        if (Directory.Exists(_testDir))
            Directory.Delete(_testDir, true);
    }

    [Fact]
    public void Constructor_CreatesBaseDirectory()
    {
        Assert.True(Directory.Exists(_testDir));
    }

    [Fact]
    public void GetBaseDir_ReturnsConfiguredPath()
    {
        Assert.Equal(_testDir, _manager.GetBaseDir());
    }

    [Fact]
    public void GetSessionArtifactDir_CreatesSessionFolder()
    {
        var dir = _manager.GetSessionArtifactDir("session-123");

        Assert.True(Directory.Exists(dir));
        Assert.Equal(Path.Combine(_testDir, "session-123"), dir);
    }

    [Fact]
    public void SaveMarkdown_CreatesFileWithContent()
    {
        var content = "# Test Document\n\nHello world.";
        var path = _manager.SaveMarkdown("session-1", content, "test-doc.md");

        Assert.True(File.Exists(path));
        Assert.Equal(content, File.ReadAllText(path));
        Assert.EndsWith(".md", path);
    }

    [Fact]
    public void SaveMarkdown_AutoGeneratesFileName()
    {
        var content = "# Auto named";
        var path = _manager.SaveMarkdown("session-1", content);

        Assert.True(File.Exists(path));
        Assert.EndsWith(".md", path);
        Assert.Contains("document-", Path.GetFileName(path));
    }

    [Fact]
    public void SaveMarkdown_AppendsMdExtension_IfMissing()
    {
        var path = _manager.SaveMarkdown("session-1", "content", "myfile");

        Assert.EndsWith(".md", path);
    }

    [Fact]
    public void SaveMarkdown_DoesNotDoubleExtension()
    {
        var path = _manager.SaveMarkdown("session-1", "content", "myfile.md");

        Assert.EndsWith(".md", path);
        Assert.DoesNotContain(".md.md", path);
    }

    [Fact]
    public void SaveHtml_CreatesFileWithContent()
    {
        var content = "<html><body><h1>Test</h1></body></html>";
        var path = _manager.SaveHtml("session-1", content, "test-page.html");

        Assert.True(File.Exists(path));
        Assert.Equal(content, File.ReadAllText(path));
        Assert.EndsWith(".html", path);
    }

    [Fact]
    public void SaveHtml_AutoGeneratesFileName()
    {
        var content = "<html><body>Auto</body></html>";
        var path = _manager.SaveHtml("session-1", content);

        Assert.True(File.Exists(path));
        Assert.EndsWith(".html", path);
        Assert.Contains("page-", Path.GetFileName(path));
    }

    [Fact]
    public void SaveHtml_AppendsHtmlExtension_IfMissing()
    {
        var path = _manager.SaveHtml("session-1", "content", "mypage");

        Assert.EndsWith(".html", path);
    }

    [Fact]
    public void SaveHtml_DoesNotDoubleExtension()
    {
        var path = _manager.SaveHtml("session-1", "content", "mypage.html");

        Assert.EndsWith(".html", path);
        Assert.DoesNotContain(".html.html", path);
    }

    [Fact]
    public void ListArtifacts_ReturnsAllFiles()
    {
        _manager.SaveMarkdown("session-1", "md content", "doc1.md");
        _manager.SaveHtml("session-1", "html content", "page1.html");

        var artifacts = _manager.ListArtifacts("session-1");

        Assert.Equal(2, artifacts.Count);
        Assert.Contains("doc1.md", artifacts);
        Assert.Contains("page1.html", artifacts);
    }

    [Fact]
    public void ListArtifacts_EmptySession_ReturnsEmptyList()
    {
        var artifacts = _manager.ListArtifacts("nonexistent-session");

        // GetSessionArtifactDir creates the dir, so it will exist but be empty
        Assert.Empty(artifacts);
    }

    [Fact]
    public void ReadArtifact_ReturnsContent()
    {
        var originalContent = "# My Document\n\nWith some content.";
        _manager.SaveMarkdown("session-1", originalContent, "doc.md");

        var readContent = _manager.ReadArtifact("session-1", "doc.md");

        Assert.Equal(originalContent, readContent);
    }

    [Fact]
    public void ReadArtifact_NonexistentFile_ReturnsNull()
    {
        var result = _manager.ReadArtifact("session-1", "does-not-exist.md");

        Assert.Null(result);
    }

    [Fact]
    public void DeleteSessionArtifacts_RemovesEntireFolder()
    {
        _manager.SaveMarkdown("session-del", "content1", "doc1.md");
        _manager.SaveHtml("session-del", "content2", "page1.html");

        var dir = _manager.GetSessionArtifactDir("session-del");
        Assert.True(Directory.Exists(dir));

        _manager.DeleteSessionArtifacts("session-del");

        Assert.False(Directory.Exists(dir));
    }

    [Fact]
    public void DeleteSessionArtifacts_NonexistentSession_DoesNotThrow()
    {
        // Should not throw
        _manager.DeleteSessionArtifacts("no-such-session");
    }

    [Fact]
    public void SaveMarkdown_SanitizesFileName()
    {
        // Characters like : and / are invalid in file names
        var path = _manager.SaveMarkdown("session-1", "content", "file:with/bad<chars>.md");

        Assert.True(File.Exists(path));
        var fileName = Path.GetFileName(path);
        Assert.DoesNotContain(":", fileName);
        Assert.DoesNotContain("/", fileName);
        Assert.DoesNotContain("<", fileName);
        Assert.DoesNotContain(">", fileName);
    }

    [Fact]
    public void MultipleSessionsHaveSeparateFolders()
    {
        _manager.SaveMarkdown("session-A", "content A", "doc.md");
        _manager.SaveMarkdown("session-B", "content B", "doc.md");

        var contentA = _manager.ReadArtifact("session-A", "doc.md");
        var contentB = _manager.ReadArtifact("session-B", "doc.md");

        Assert.Equal("content A", contentA);
        Assert.Equal("content B", contentB);
    }

    [Fact]
    public void SaveOverwritesExistingFile()
    {
        _manager.SaveMarkdown("session-1", "original", "doc.md");
        _manager.SaveMarkdown("session-1", "updated", "doc.md");

        var content = _manager.ReadArtifact("session-1", "doc.md");

        Assert.Equal("updated", content);
    }
}
