using System.IO;
using BrainstormAssistant.Models;
using Newtonsoft.Json;

namespace BrainstormAssistant.Services;

public static class ConfigService
{
    public static AppConfig Load()
    {
        var path = AppPaths.ConfigPath;
        if (!File.Exists(path))
            return new AppConfig();

        try
        {
            var json = File.ReadAllText(path);
            return JsonConvert.DeserializeObject<AppConfig>(json) ?? new AppConfig();
        }
        catch
        {
            return new AppConfig();
        }
    }

    public static void Save(AppConfig config)
    {
        AppPaths.EnsureDirectories();
        var json = JsonConvert.SerializeObject(config, Formatting.Indented);
        File.WriteAllText(AppPaths.ConfigPath, json);
    }

    public static string GetConfigPath() => AppPaths.ConfigPath;
}
