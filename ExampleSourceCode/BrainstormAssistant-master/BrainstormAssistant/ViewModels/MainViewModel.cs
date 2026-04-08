using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;
using BrainstormAssistant.Models;

namespace BrainstormAssistant.ViewModels;

public class MainViewModel : INotifyPropertyChanged
{
    public ObservableCollection<ChatMessage> Messages { get; } = new();

    private string _inputText = "";
    public string InputText
    {
        get => _inputText;
        set { _inputText = value; OnPropertyChanged(); }
    }

    private string _statusText = "Ready. Describe your idea to start brainstorming.";
    public string StatusText
    {
        get => _statusText;
        set { _statusText = value; OnPropertyChanged(); }
    }

    private bool _isListening;
    public bool IsListening
    {
        get => _isListening;
        set { _isListening = value; OnPropertyChanged(); }
    }

    private bool _isBusy;
    public bool IsBusy
    {
        get => _isBusy;
        set { _isBusy = value; OnPropertyChanged(); }
    }

    private string _sessionTitle = "New Session";
    public string SessionTitle
    {
        get => _sessionTitle;
        set { _sessionTitle = value; OnPropertyChanged(); }
    }

    private string _partialSpeech = "";
    public string PartialSpeech
    {
        get => _partialSpeech;
        set { _partialSpeech = value; OnPropertyChanged(); }
    }

    private string _boardVisible = "";
    public string BoardVisible
    {
        get => _boardVisible;
        set { _boardVisible = value; OnPropertyChanged(); }
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    protected void OnPropertyChanged([CallerMemberName] string? name = null)
    {
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }
}
