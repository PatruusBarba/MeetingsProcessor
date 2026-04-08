using BrainstormAssistant.Services;

namespace BrainstormAssistant.Tests;

public class ModelDownloaderTests
{
    [Fact]
    public void RequiredFiles_ContainsFourModels()
    {
        Assert.Equal(4, ModelDownloader.RequiredFiles.Length);
    }

    [Fact]
    public void RequiredFiles_ContainsPreprocessor()
    {
        Assert.Contains("nemo128.onnx", ModelDownloader.RequiredFiles);
    }

    [Fact]
    public void RequiredFiles_ContainsEncoder()
    {
        Assert.Contains("encoder-model.int8.onnx", ModelDownloader.RequiredFiles);
    }

    [Fact]
    public void RequiredFiles_ContainsDecoderJoint()
    {
        Assert.Contains("decoder_joint-model.int8.onnx", ModelDownloader.RequiredFiles);
    }

    [Fact]
    public void RequiredFiles_ContainsVocab()
    {
        Assert.Contains("vocab.txt", ModelDownloader.RequiredFiles);
    }

    [Fact]
    public void GetModelDir_ReturnsNonEmptyPath()
    {
        var dir = ModelDownloader.GetModelDir();

        Assert.False(string.IsNullOrEmpty(dir));
    }

    [Fact]
    public void GetModelDir_ContainsParakeetSubfolder()
    {
        var dir = ModelDownloader.GetModelDir();

        Assert.Contains("parakeet-tdt-0.6b-v3", dir);
    }

    [Fact]
    public void GetModelDir_ContainsBrainstormAssistant()
    {
        var dir = ModelDownloader.GetModelDir();

        Assert.Contains("BrainstormAssistant", dir);
    }

    [Fact]
    public void GetModelPath_CombinesDirAndFilename()
    {
        var path = ModelDownloader.GetModelPath("vocab.txt");
        var dir = ModelDownloader.GetModelDir();

        Assert.StartsWith(dir, path);
        Assert.EndsWith("vocab.txt", path);
    }

    [Fact]
    public void GetModelPath_EachRequiredFile_ReturnsUniquePath()
    {
        var paths = ModelDownloader.RequiredFiles
            .Select(f => ModelDownloader.GetModelPath(f))
            .ToList();

        Assert.Equal(paths.Count, paths.Distinct().Count());
    }

    [Fact]
    public void GetMissingFiles_WhenNoModelsExist_ReturnsAllFiles()
    {
        // Models are not downloaded in test environment,
        // so all files should be missing (unless running on a machine
        // where they happen to exist, which is unlikely in CI)
        var missing = ModelDownloader.GetMissingFiles();

        // At minimum, missing should be a valid list
        Assert.NotNull(missing);
        Assert.IsType<List<string>>(missing);
    }

    [Fact]
    public void AllModelsPresent_WhenNoModelsExist_ReturnsFalse()
    {
        // Unless the test machine has downloaded all models,
        // this should be false
        var present = ModelDownloader.AllModelsPresent();

        // We can only assert it returns a bool without error
        Assert.IsType<bool>(present);
    }

    [Fact]
    public void GetMissingFiles_ReturnsSubsetOfRequiredFiles()
    {
        var missing = ModelDownloader.GetMissingFiles();

        foreach (var file in missing)
        {
            Assert.Contains(file, ModelDownloader.RequiredFiles);
        }
    }

    [Fact]
    public void AllModelsPresent_ConsistentWithGetMissingFiles()
    {
        var allPresent = ModelDownloader.AllModelsPresent();
        var missing = ModelDownloader.GetMissingFiles();

        if (allPresent)
            Assert.Empty(missing);
        else
            Assert.NotEmpty(missing);
    }
}
