using System.IO;

namespace BrainstormAssistant.Services;

/// <summary>
/// Manages per-session artifact folders for saving MD and HTML files.
/// Each session gets its own folder: %AppData%/BrainstormAssistant/artifacts/{sessionId}/
/// </summary>
public class ArtifactManager
{
    private readonly string _artifactsBaseDir;

    public ArtifactManager(string? baseDir = null)
    {
        _artifactsBaseDir = baseDir ?? AppPaths.ArtifactsDir;

        if (!Directory.Exists(_artifactsBaseDir))
            Directory.CreateDirectory(_artifactsBaseDir);
    }

    /// <summary>
    /// Gets the artifact folder for a specific session, creating it if needed.
    /// </summary>
    public string GetSessionArtifactDir(string sessionId)
    {
        var dir = Path.Combine(_artifactsBaseDir, sessionId);
        if (!Directory.Exists(dir))
            Directory.CreateDirectory(dir);
        return dir;
    }

    /// <summary>
    /// Saves a Markdown artifact to the session's folder.
    /// Returns the full file path.
    /// </summary>
    public string SaveMarkdown(string sessionId, string content, string? fileName = null)
    {
        var dir = GetSessionArtifactDir(sessionId);
        fileName ??= $"document-{DateTime.Now:yyyyMMdd-HHmmss}.md";
        if (!fileName.EndsWith(".md", StringComparison.OrdinalIgnoreCase))
            fileName += ".md";

        var path = Path.Combine(dir, SanitizeFileName(fileName));
        File.WriteAllText(path, content);
        return path;
    }

    /// <summary>
    /// Saves an HTML artifact to the session's folder.
    /// Returns the full file path.
    /// </summary>
    public string SaveHtml(string sessionId, string content, string? fileName = null)
    {
        var dir = GetSessionArtifactDir(sessionId);
        fileName ??= $"page-{DateTime.Now:yyyyMMdd-HHmmss}.html";
        if (!fileName.EndsWith(".html", StringComparison.OrdinalIgnoreCase))
            fileName += ".html";

        var path = Path.Combine(dir, SanitizeFileName(fileName));
        File.WriteAllText(path, content);
        return path;
    }

    /// <summary>
    /// Lists all artifacts in a session's folder.
    /// </summary>
    public List<string> ListArtifacts(string sessionId)
    {
        var dir = GetSessionArtifactDir(sessionId);
        if (!Directory.Exists(dir))
            return new List<string>();

        return Directory.GetFiles(dir)
            .Select(Path.GetFileName)
            .Where(f => f != null)
            .Cast<string>()
            .OrderByDescending(f => f)
            .ToList();
    }

    /// <summary>
    /// Reads an artifact file's content.
    /// </summary>
    public string? ReadArtifact(string sessionId, string fileName)
    {
        var path = Path.Combine(GetSessionArtifactDir(sessionId), SanitizeFileName(fileName));
        return File.Exists(path) ? File.ReadAllText(path) : null;
    }

    /// <summary>
    /// Deletes all artifacts for a session.
    /// </summary>
    public void DeleteSessionArtifacts(string sessionId)
    {
        var dir = Path.Combine(_artifactsBaseDir, sessionId);
        if (Directory.Exists(dir))
            Directory.Delete(dir, true);
    }

    public string GetBaseDir() => _artifactsBaseDir;

    private static string SanitizeFileName(string name)
    {
        var invalid = Path.GetInvalidFileNameChars();
        var sanitized = new string(name.Select(c => invalid.Contains(c) ? '_' : c).ToArray());
        return sanitized;
    }
}
