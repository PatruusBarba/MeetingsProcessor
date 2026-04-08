using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Input;
using BrainstormAssistant.Models;

namespace BrainstormAssistant.Views;

public class SessionTimestampConverter : IValueConverter
{
    public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
    {
        if (value is long ts)
            return DateTimeOffset.FromUnixTimeMilliseconds(ts).LocalDateTime.ToString("g");
        return "";
    }

    public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
        => throw new NotImplementedException();
}

public partial class SessionListWindow : Window
{
    private readonly List<Session> _sessions;

    public Session? SelectedSession { get; private set; }

    public SessionListWindow(List<Session> sessions)
    {
        InitializeComponent();
        _sessions = sessions;
        SessionList.ItemsSource = _sessions;
    }

    private void Load_Click(object sender, RoutedEventArgs e)
    {
        if (SessionList.SelectedItem is Session session)
        {
            SelectedSession = session;
            DialogResult = true;
            Close();
        }
        else
        {
            MessageBox.Show("Select a session first.", "Load", MessageBoxButton.OK, MessageBoxImage.Information);
        }
    }

    private void Cancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
        Close();
    }

    private void Delete_Click(object sender, RoutedEventArgs e)
    {
        if (SessionList.SelectedItem is Session session)
        {
            var result = MessageBox.Show(
                $"Delete session \"{session.Title}\"?",
                "Delete", MessageBoxButton.YesNo, MessageBoxImage.Warning);

            if (result == MessageBoxResult.Yes)
            {
                var manager = new Services.SessionManager();
                manager.DeleteSession(session.Id);
                _sessions.Remove(session);
                SessionList.ItemsSource = null;
                SessionList.ItemsSource = _sessions;
            }
        }
    }

    private void SessionList_DoubleClick(object sender, MouseButtonEventArgs e)
    {
        if (SessionList.SelectedItem is Session session)
        {
            SelectedSession = session;
            DialogResult = true;
            Close();
        }
    }
}
