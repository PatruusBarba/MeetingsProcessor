using System.Windows;
using BrainstormAssistant.Models;
using BrainstormAssistant.Services;
using NAudio.Wave;

namespace BrainstormAssistant.Views;

public partial class SettingsWindow : Window
{
    public AppConfig Config { get; private set; }

    public SettingsWindow(AppConfig config)
    {
        InitializeComponent();
        Config = config;
        LoadConfig();
    }
    private void PopulateMicrophones()
    {
        MicCombo.Items.Clear();
        MicCombo.Items.Add("(System Default)");

        int selectedIndex = 0;
        for (int i = 0; i < WaveInEvent.DeviceCount; i++)
        {
            var caps = WaveInEvent.GetCapabilities(i);
            MicCombo.Items.Add(caps.ProductName);
            if (caps.ProductName == Config.MicrophoneDevice)
                selectedIndex = i + 1;
        }

        MicCombo.SelectedIndex = selectedIndex;
    }

    private void UpdateModelStatus()
    {
        if (ModelDownloader.AllModelsPresent())
        {
            var sizeBytes = ModelDownloader.GetModelSizeOnDisk();
            var sizeMb = sizeBytes / (1024.0 * 1024.0);
            SttModelStatus.Text = $"Downloaded ({sizeMb:F0} MB)";
            SttModelStatus.Foreground = new System.Windows.Media.SolidColorBrush(
                (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#88CC88"));
            DeleteModelBtn.IsEnabled = true;
            DeleteModelBtn.Visibility = Visibility.Visible;
        }
        else
        {
            SttModelStatus.Text = "Not downloaded";
            SttModelStatus.Foreground = new System.Windows.Media.SolidColorBrush(
                (System.Windows.Media.Color)System.Windows.Media.ColorConverter.ConvertFromString("#AAAAAA"));
            DeleteModelBtn.IsEnabled = false;
            DeleteModelBtn.Visibility = Visibility.Collapsed;
        }
    }

    private void DeleteModel_Click(object sender, RoutedEventArgs e)
    {
        var result = MessageBox.Show(
            "Delete the speech-to-text model files (~670 MB)?\nYou can re-download them later when needed.",
            "Delete STT Model",
            MessageBoxButton.YesNo, MessageBoxImage.Question);

        if (result != MessageBoxResult.Yes) return;

        try
        {
            ModelDownloader.DeleteModels();
            UpdateModelStatus();
        }
        catch (System.Exception ex)
        {
            MessageBox.Show($"Failed to delete model:\n{ex.Message}",
                "Error", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void LoadConfig()
    {
        // Provider
        foreach (System.Windows.Controls.ComboBoxItem item in ProviderCombo.Items)
        {
            if (item.Content?.ToString() == Config.Provider)
            {
                item.IsSelected = true;
                break;
            }
        }

        ApiKeyBox.Password = Config.ApiKey;
        ModelBox.Text = Config.Model;
        BaseUrlBox.Text = Config.BaseUrl ?? "";
        MaxTokensBox.Text = Config.MaxTokens.ToString();
        TtsVoiceBox.Text = Config.TtsVoice ?? "";
        TtsEnabledCheck.IsChecked = Config.TtsEnabled;
        SttEnabledCheck.IsChecked = Config.SttEnabled;
        ModelListBox.Text = string.Join("\n", Config.AvailableModels);

        PopulateMicrophones();
        UpdateModelStatus();
    }

    private void Save_Click(object sender, RoutedEventArgs e)
    {
        var modelList = ModelListBox.Text
            .Split('\n', '\r')
            .Select(l => l.Trim())
            .Where(l => !string.IsNullOrWhiteSpace(l))
            .ToList();

        Config = new AppConfig
        {
            Provider = (ProviderCombo.SelectedItem as System.Windows.Controls.ComboBoxItem)?.Content?.ToString() ?? "openrouter",
            ApiKey = ApiKeyBox.Password,
            Model = ModelBox.Text.Trim(),
            BaseUrl = string.IsNullOrWhiteSpace(BaseUrlBox.Text) ? null : BaseUrlBox.Text.Trim(),
            TtsVoice = string.IsNullOrWhiteSpace(TtsVoiceBox.Text) ? null : TtsVoiceBox.Text.Trim(),
            TtsEnabled = TtsEnabledCheck.IsChecked == true,
            SttEnabled = SttEnabledCheck.IsChecked == true,
            MicrophoneDevice = MicCombo.SelectedIndex > 0 ? MicCombo.SelectedItem?.ToString() : null,
            Temperature = 0.7,
            MaxTokens = int.TryParse(MaxTokensBox.Text.Trim(), out var mt) && mt > 0 ? mt : 6000,
            TtsRate = 0,
            TtsVolume = 100,
            AvailableModels = modelList.Count > 0 ? modelList : new List<string> { "openai/gpt-4o" },
        };

        var errors = Config.Validate();
        if (errors.Count > 0)
        {
            MessageBox.Show(string.Join("\n", errors), "Validation Error",
                MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        DialogResult = true;
        Close();
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }
}
