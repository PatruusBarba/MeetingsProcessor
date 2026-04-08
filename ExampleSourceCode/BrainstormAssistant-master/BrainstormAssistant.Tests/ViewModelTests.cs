using BrainstormAssistant.ViewModels;

namespace BrainstormAssistant.Tests;

public class MainViewModelTests
{
    [Fact]
    public void DefaultValues_AreCorrect()
    {
        var vm = new MainViewModel();

        Assert.Equal("", vm.InputText);
        Assert.Contains("Ready", vm.StatusText);
        Assert.False(vm.IsListening);
        Assert.False(vm.IsBusy);
        Assert.Equal("New Session", vm.SessionTitle);
        Assert.Equal("", vm.PartialSpeech);
        Assert.Empty(vm.Messages);
    }

    [Fact]
    public void PropertyChanged_FiresOnInputTextChange()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.InputText = "Hello";

        Assert.Equal("InputText", changedProperty);
        Assert.Equal("Hello", vm.InputText);
    }

    [Fact]
    public void PropertyChanged_FiresOnStatusTextChange()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.StatusText = "Thinking...";

        Assert.Equal("StatusText", changedProperty);
    }

    [Fact]
    public void PropertyChanged_FiresOnIsListeningChange()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.IsListening = true;

        Assert.Equal("IsListening", changedProperty);
        Assert.True(vm.IsListening);
    }

    [Fact]
    public void PropertyChanged_FiresOnIsBusyChange()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.IsBusy = true;

        Assert.Equal("IsBusy", changedProperty);
    }

    [Fact]
    public void Messages_IsObservableCollection()
    {
        var vm = new MainViewModel();
        int notifyCount = 0;
        vm.Messages.CollectionChanged += (_, _) => notifyCount++;

        vm.Messages.Add(new Models.ChatMessage("user", "test"));

        Assert.Equal(1, notifyCount);
        Assert.Single(vm.Messages);
    }

    [Fact]
    public void PartialSpeech_FiresPropertyChanged()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.PartialSpeech = "Hello wor...";

        Assert.Equal("PartialSpeech", changedProperty);
        Assert.Equal("Hello wor...", vm.PartialSpeech);
    }

    [Fact]
    public void SessionTitle_FiresPropertyChanged()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.SessionTitle = "My Brainstorm";

        Assert.Equal("SessionTitle", changedProperty);
        Assert.Equal("My Brainstorm", vm.SessionTitle);
    }

    [Fact]
    public void BoardVisible_DefaultIsEmpty()
    {
        var vm = new MainViewModel();

        Assert.Equal("", vm.BoardVisible);
    }

    [Fact]
    public void BoardVisible_FiresPropertyChanged()
    {
        var vm = new MainViewModel();
        string? changedProperty = null;
        vm.PropertyChanged += (_, e) => changedProperty = e.PropertyName;

        vm.BoardVisible = "visible";

        Assert.Equal("BoardVisible", changedProperty);
        Assert.Equal("visible", vm.BoardVisible);
    }

    [Fact]
    public void BoardVisible_CanToggleBetweenStates()
    {
        var vm = new MainViewModel();

        vm.BoardVisible = "visible";
        Assert.Equal("visible", vm.BoardVisible);

        vm.BoardVisible = "";
        Assert.Equal("", vm.BoardVisible);
    }
}
