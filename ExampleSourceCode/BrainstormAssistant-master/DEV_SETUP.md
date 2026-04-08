# BrainstormAssistant — Dev Setup (Windows 11)

## Automated Setup (Recommended)

Right-click `setup_dev.ps1` → **Run with PowerShell**, or from an admin terminal:

```powershell
powershell -ExecutionPolicy Bypass -File setup_dev.ps1
```

The script installs Git, .NET 8.0 SDK, VS2022, MAUI workload, restores packages, builds, and runs tests — all automatically. No package managers needed (downloads installers directly).

**Flags:**

| Flag | Effect |
|------|--------|
| `-SkipVS` | Skip Visual Studio install (not required — dotnet CLI is enough) |
| `-SkipCompanion` | Skip MAUI workload (only needed for Android companion app) |
| `-SkipBuild` | Skip build and tests |

After setup, configure your LLM provider and API key in the app's **Settings** window, then run `.\run.bat`.

## Manual Setup

If you prefer to set things up manually:

1. Install [.NET 8.0 SDK](https://dotnet.microsoft.com/download/dotnet/8.0)
2. Install [Microsoft OpenJDK 17](https://learn.microsoft.com/java/openjdk/download)
3. Install [Android SDK command-line tools](https://developer.android.com/studio#command-line-tools-only) to `C:\Android\Sdk`
4. Clone the repo
5. `dotnet workload install maui-android`
6. `dotnet restore BrainstormAssistant.sln`
7. `.\build.bat` → `.\run.bat`
8. Configure LLM provider & API key in the app's Settings window
9. For Android companion: `.\build_apk.bat`
