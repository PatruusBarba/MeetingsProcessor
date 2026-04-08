using Microsoft.Maui.Hosting;

namespace BrainstormCompanion;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp()
    {
        var builder = MauiApp.CreateBuilder();
        builder
            .UseMauiApp<App>();

        builder.Services.AddSingleton<BrainstormApiClient>();

        return builder.Build();
    }
}
