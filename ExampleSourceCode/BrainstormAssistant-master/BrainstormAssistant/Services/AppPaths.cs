using System.IO;
using System.Reflection;

namespace BrainstormAssistant.Services;

/// <summary>
/// Centralises all data paths.  When the app runs from a local drive the
/// data lives next to the EXE (portable).  When running from a UNC/network
/// path it falls back to %LOCALAPPDATA% to avoid page-fault errors.
/// </summary>
public static class AppPaths
{
    private static readonly string AppDir =
        Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location) ?? "";

    private static readonly bool IsNetworkPath =
        AppDir.StartsWith(@"\\") || AppDir.StartsWith("//");

    public static readonly string DataDir = IsNetworkPath
        ? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BrainstormAssistant")
        : Path.Combine(AppDir, "data");

    public static readonly string ConfigPath = Path.Combine(DataDir, "config.json");
    public static readonly string SessionsDir = Path.Combine(DataDir, "sessions");
    public static readonly string ArtifactsDir = Path.Combine(DataDir, "artifacts");
    public static readonly string ModelsDir = Path.Combine(DataDir, "models", "parakeet-tdt-0.6b-v3");
    public static readonly string LogDir = Path.Combine(DataDir, "logs");

    /// <summary>True when data is stored next to the EXE (portable mode).</summary>
    public static bool IsPortable => !IsNetworkPath;

    /// <summary>Ensures all required directories exist.</summary>
    public static void EnsureDirectories()
    {
        Directory.CreateDirectory(DataDir);
        Directory.CreateDirectory(SessionsDir);
        Directory.CreateDirectory(ArtifactsDir);
        Directory.CreateDirectory(ModelsDir);
        Directory.CreateDirectory(LogDir);
    }

    /// <summary>
    /// One-time migration: copies data from legacy %AppData% to portable data dir.
    /// Only runs in portable mode. Skips model files (~670 MB).
    /// </summary>
    public static void MigrateFromAppData()
    {
        if (!IsPortable) return;   // nothing to migrate when already using AppData

        var legacyDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
            "BrainstormAssistant");

        if (!Directory.Exists(legacyDir)) return;

        EnsureDirectories();

        var legacyConfig = Path.Combine(legacyDir, "config.json");
        if (File.Exists(legacyConfig) && !File.Exists(ConfigPath))
            File.Copy(legacyConfig, ConfigPath);

        var legacySessions = Path.Combine(legacyDir, "sessions");
        if (Directory.Exists(legacySessions))
            CopyDirContents(legacySessions, SessionsDir);

        var legacyArtifacts = Path.Combine(legacyDir, "artifacts");
        if (Directory.Exists(legacyArtifacts))
            CopyDirContents(legacyArtifacts, ArtifactsDir);
    }

    private static void CopyDirContents(string src, string dest)
    {
        Directory.CreateDirectory(dest);
        foreach (var file in Directory.GetFiles(src))
        {
            var destFile = Path.Combine(dest, Path.GetFileName(file));
            if (!File.Exists(destFile))
                File.Copy(file, destFile);
        }
        foreach (var dir in Directory.GetDirectories(src))
        {
            CopyDirContents(dir, Path.Combine(dest, Path.GetFileName(dir)));
        }
    }
}
