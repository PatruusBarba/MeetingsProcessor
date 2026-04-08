using System.IO;
using System.Net.Http;

namespace BrainstormAssistant.Services;

public class ModelDownloader
{
    private static readonly string HfBaseUrl =
        "https://huggingface.co/istupakov/parakeet-tdt-0.6b-v3-onnx/resolve/main/";

    public static readonly string[] RequiredFiles = new[]
    {
        "nemo128.onnx",             // ~140KB preprocessor
        "encoder-model.int8.onnx",  // ~652MB encoder
        "decoder_joint-model.int8.onnx", // ~18MB decoder+joint
        "vocab.txt"                 // ~94KB vocabulary
    };

    public static string GetModelDir() => AppPaths.ModelsDir;

    public static string GetModelPath(string filename) =>
        Path.Combine(AppPaths.ModelsDir, filename);

    public static bool AllModelsPresent()
    {
        return RequiredFiles.All(f => File.Exists(GetModelPath(f)));
    }

    public static List<string> GetMissingFiles()
    {
        return RequiredFiles.Where(f => !File.Exists(GetModelPath(f))).ToList();
    }

    public static async Task DownloadModelsAsync(
        IProgress<(string file, double percent)>? progress = null,
        CancellationToken ct = default)
    {
        Directory.CreateDirectory(AppPaths.ModelsDir);

        using var http = new HttpClient();
        http.Timeout = TimeSpan.FromHours(2);

        var missing = GetMissingFiles();
        for (int i = 0; i < missing.Count; i++)
        {
            var file = missing[i];
            var url = HfBaseUrl + file;
            var destPath = GetModelPath(file);
            var tempPath = destPath + ".tmp";

            progress?.Report((file, 0));

            using var response = await http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct);
            response.EnsureSuccessStatusCode();

            var totalBytes = response.Content.Headers.ContentLength ?? -1;
            long downloaded = 0;

            using (var stream = await response.Content.ReadAsStreamAsync(ct))
            using (var fs = new FileStream(tempPath, FileMode.Create, FileAccess.Write, FileShare.None, 81920))
            {
                var buffer = new byte[81920];
                int bytesRead;
                while ((bytesRead = await stream.ReadAsync(buffer, 0, buffer.Length, ct)) > 0)
                {
                    await fs.WriteAsync(buffer, 0, bytesRead, ct);
                    downloaded += bytesRead;

                    if (totalBytes > 0)
                    {
                        var pct = (double)downloaded / totalBytes * 100;
                        progress?.Report((file, pct));
                    }
                }
            }

            // Rename temp to final
            if (File.Exists(destPath))
                File.Delete(destPath);
            File.Move(tempPath, destPath);

            progress?.Report((file, 100));
        }
    }
    public static long GetModelSizeOnDisk()
    {
        if (!Directory.Exists(AppPaths.ModelsDir)) return 0;
        return RequiredFiles
            .Select(f => GetModelPath(f))
            .Where(File.Exists)
            .Sum(p => new FileInfo(p).Length);
    }

    public static void DeleteModels()
    {
        if (!Directory.Exists(AppPaths.ModelsDir)) return;
        foreach (var file in RequiredFiles)
        {
            var path = GetModelPath(file);
            if (File.Exists(path))
                File.Delete(path);
        }
        if (Directory.Exists(AppPaths.ModelsDir) && !Directory.EnumerateFileSystemEntries(AppPaths.ModelsDir).Any())
            Directory.Delete(AppPaths.ModelsDir);
    }
}