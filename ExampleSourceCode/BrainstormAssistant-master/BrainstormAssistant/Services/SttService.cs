namespace BrainstormAssistant.Services;

public interface ISttService
{
    event EventHandler<string>? SpeechRecognized;
    event EventHandler<string>? PartialResult;
    event EventHandler? ListeningStarted;
    event EventHandler? ListeningStopped;
    void StartListening();
    void StopListening();
    bool IsListening { get; }
    bool IsEnabled { get; set; }
}
