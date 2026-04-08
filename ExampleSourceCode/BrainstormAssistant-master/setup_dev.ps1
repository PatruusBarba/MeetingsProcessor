<#
.SYNOPSIS
    Automated dev environment setup for BrainstormAssistant on Windows 11.
.DESCRIPTION
    Downloads and installs all required tools, configures the project,
    builds, and runs tests. Run as Administrator.
.EXAMPLE
    Right-click setup_dev.ps1 > "Run with PowerShell"
    Or from an admin terminal: powershell -ExecutionPolicy Bypass -File setup_dev.ps1
#>

param(
    [switch]$SkipVS,
    [switch]$SkipCompanion,
    [switch]$SkipBuild
)

# -- Config -------------------------------------------------------------------
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"   # speeds up Invoke-WebRequest
$ProjectRoot           = $PSScriptRoot
$TempDir               = Join-Path $env:TEMP "BrainstormSetup"

$DotnetInstallerUrl    = "https://dot.net/v1/dotnet-install.ps1"
$GitInstallerUrl       = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.2/Git-2.47.1.2-64-bit.exe"
$VSInstallerUrl        = "https://aka.ms/vs/17/release/vs_community.exe"
$AndroidCmdlineUrl     = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"
$AndroidSdkRoot        = "C:\Android\Sdk"
$JdkInstallerUrl       = "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.msi"

# -- Helpers ------------------------------------------------------------------
function Write-Step  { param($n,$total,$msg) Write-Host "`n[$n/$total] $msg" -ForegroundColor Yellow }
function Write-Ok    { param($msg) Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Skip  { param($msg) Write-Host "  [--] Skipped: $msg" -ForegroundColor DarkGray }
function Write-Info  { param($msg) Write-Host "  $msg" -ForegroundColor White }

function Test-Command { param($cmd) [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path", "User")
}

function Ensure-TempDir {
    if (-not (Test-Path $TempDir)) { New-Item -ItemType Directory -Path $TempDir -Force | Out-Null }
}

# -- Admin check --------------------------------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "`n[!] This script needs Administrator privileges for installing tools." -ForegroundColor Red
    Write-Host "   Restarting as Administrator...`n" -ForegroundColor Yellow
    Start-Process powershell.exe -Verb RunAs -ArgumentList (
        "-ExecutionPolicy Bypass -File `"$PSCommandPath`"" +
        $(if ($SkipVS)        { " -SkipVS" }        else { "" }) +
        $(if ($SkipCompanion) { " -SkipCompanion" } else { "" }) +
        $(if ($SkipBuild)     { " -SkipBuild" }     else { "" })
    )
    exit
}

$totalSteps = 8
Write-Host "`n==========================================" -ForegroundColor Cyan
Write-Host "  BrainstormAssistant - Dev Environment"     -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Project : $ProjectRoot"
Write-Host "  Flags   : SkipVS=$SkipVS  SkipCompanion=$SkipCompanion  SkipBuild=$SkipBuild"

# -- 1. Git -------------------------------------------------------------------
Write-Step 1 $totalSteps "Git"

if (Test-Command "git") {
    Write-Ok "Git already installed: $(git --version)"
} else {
    Ensure-TempDir
    $gitExe = Join-Path $TempDir "git-installer.exe"
    Write-Info "Downloading Git..."
    Invoke-WebRequest -Uri $GitInstallerUrl -OutFile $gitExe -UseBasicParsing
    Write-Info "Installing Git (silent)..."
    Start-Process -FilePath $gitExe -ArgumentList "/VERYSILENT /NORESTART /NOCANCEL /SP- /CLOSEAPPLICATIONS /RESTARTAPPLICATIONS /COMPONENTS=`"icons,ext\reg\shellhere,assoc,assoc_sh`"" -Wait
    Refresh-Path
    if (Test-Command "git") { Write-Ok "Git installed." } else { Write-Host "  [!] Git installed but not in PATH yet. Restart terminal after setup." -ForegroundColor DarkYellow }
}

# -- 2. .NET 8.0 SDK ----------------------------------------------------------
Write-Step 2 $totalSteps ".NET 8.0 SDK"

$dotnetFound = $false
if (Test-Command "dotnet") {
    $sdks = & dotnet --list-sdks 2>$null
    if ($sdks -match "8\.0\.\d+") {
        Write-Ok ".NET 8.0 SDK already installed."
        $dotnetFound = $true
    }
}

if (-not $dotnetFound) {
    Ensure-TempDir
    $installScript = Join-Path $TempDir "dotnet-install.ps1"
    Write-Info "Downloading .NET install script..."
    Invoke-WebRequest -Uri $DotnetInstallerUrl -OutFile $installScript -UseBasicParsing
    Write-Info "Installing .NET 8.0 SDK (this may take a few minutes)..."
    & $installScript -Channel 8.0 -InstallDir "$env:ProgramFiles\dotnet"
    Refresh-Path

    # Ensure dotnet is in PATH permanently
    $machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $dotnetDir   = "$env:ProgramFiles\dotnet"
    if ($machinePath -notlike "*$dotnetDir*") {
        [System.Environment]::SetEnvironmentVariable("Path", "$machinePath;$dotnetDir", "Machine")
        Refresh-Path
    }
    Write-Ok ".NET 8.0 SDK installed."
}

# -- 3. Visual Studio 2022 Community (optional) -------------------------------
Write-Step 3 $totalSteps "Visual Studio 2022"

if ($SkipVS) {
    Write-Skip "Use -SkipVS to skip. Not required - dotnet CLI is enough to build."
} else {
    $vswherePath = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsInstalled = $false
    if (Test-Path $vswherePath) {
        $vsPath = & $vswherePath -latest -property installationPath 2>$null
        if ($vsPath) { $vsInstalled = $true }
    }

    if ($vsInstalled) {
        Write-Ok "Visual Studio found at: $vsPath"
    } else {
        Ensure-TempDir
        $vsExe = Join-Path $TempDir "vs_community.exe"
        Write-Info "Downloading Visual Studio 2022 Community installer..."
        Invoke-WebRequest -Uri $VSInstallerUrl -OutFile $vsExe -UseBasicParsing
        Write-Info "Installing VS2022 with .NET Desktop + MAUI workloads..."
        Write-Info "(This takes 15-30 min. A progress window will appear.)"
        $vsArgs = @(
            "--add", "Microsoft.VisualStudio.Workload.ManagedDesktop",
            "--add", "Microsoft.VisualStudio.Workload.NetCrossPlat",
            "--passive", "--norestart", "--wait"
        )
        Start-Process -FilePath $vsExe -ArgumentList $vsArgs -Wait
        Write-Ok "Visual Studio 2022 installed."
    }
}

# -- 4. JDK 17 (required for Android SDK build tools) ------------------------
Write-Step 4 $totalSteps "JDK 17 (for Android)"

if ($SkipCompanion) {
    Write-Skip "Companion skipped. JDK not needed."
} else {
    $javaFound = $false
    if (Test-Command "java") {
        $javaVer = & { $ErrorActionPreference = 'SilentlyContinue'; java -version 2>&1 } | Select-Object -First 1
        if ($javaVer -match '"(1[7-9]|[2-9]\d)') {
            Write-Ok "JDK found: $javaVer"
            $javaFound = $true
        }
    }
    # Also check JAVA_HOME
    if (-not $javaFound -and $env:JAVA_HOME -and (Test-Path "$env:JAVA_HOME\bin\java.exe")) {
        Write-Ok "JDK found at JAVA_HOME: $env:JAVA_HOME"
        $javaFound = $true
    }

    if (-not $javaFound) {
        Ensure-TempDir
        $jdkMsi = Join-Path $TempDir "microsoft-jdk-17.msi"
        Write-Info "Downloading Microsoft OpenJDK 17..."
        Invoke-WebRequest -Uri $JdkInstallerUrl -OutFile $jdkMsi -UseBasicParsing
        Write-Info "Installing JDK 17 (silent)..."
        Start-Process msiexec.exe -ArgumentList "/i `"$jdkMsi`" /quiet /norestart ADDLOCAL=FeatureMain,FeatureEnvironment,FeatureJarFileRunWith,FeatureJavaHome" -Wait
        Refresh-Path
        Write-Ok "JDK 17 installed."
    }
}

# -- 5. Android SDK -----------------------------------------------------------
Write-Step 5 $totalSteps "Android SDK"

if ($SkipCompanion) {
    Write-Skip "Companion skipped. Android SDK not needed."
} else {
    if (Test-Path "$AndroidSdkRoot\platform-tools") {
        Write-Ok "Android SDK found at: $AndroidSdkRoot"
    } else {
        Ensure-TempDir
        $cmdlineZip = Join-Path $TempDir "android-cmdline-tools.zip"
        $cmdlineDir = Join-Path $AndroidSdkRoot "cmdline-tools\latest"

        Write-Info "Downloading Android command-line tools..."
        Invoke-WebRequest -Uri $AndroidCmdlineUrl -OutFile $cmdlineZip -UseBasicParsing

        Write-Info "Extracting to $AndroidSdkRoot..."
        if (-not (Test-Path $AndroidSdkRoot)) { New-Item -ItemType Directory -Path $AndroidSdkRoot -Force | Out-Null }
        Expand-Archive -Path $cmdlineZip -DestinationPath $TempDir -Force
        if (-not (Test-Path (Split-Path $cmdlineDir))) { New-Item -ItemType Directory -Path (Split-Path $cmdlineDir) -Force | Out-Null }
        if (Test-Path $cmdlineDir) { Remove-Item $cmdlineDir -Recurse -Force }
        Move-Item -Path (Join-Path $TempDir "cmdline-tools") -Destination $cmdlineDir -Force

        $sdkmanager = Join-Path $cmdlineDir "bin\sdkmanager.bat"

        Write-Info "Accepting licenses..."
        $yeses = ("y`n" * 20)
        $yeses | & $sdkmanager --sdk_root="$AndroidSdkRoot" --licenses 2>$null

        Write-Info "Installing platform-tools, build-tools, platform API 34..."
        & $sdkmanager --sdk_root="$AndroidSdkRoot" "platform-tools" "build-tools;34.0.0" "platforms;android-34" 2>$null
        Write-Ok "Android SDK installed at $AndroidSdkRoot"
    }

    # Set ANDROID_HOME if not set
    $currentHome = [System.Environment]::GetEnvironmentVariable("ANDROID_HOME", "Machine")
    if (-not $currentHome) {
        [System.Environment]::SetEnvironmentVariable("ANDROID_HOME", $AndroidSdkRoot, "Machine")
        $env:ANDROID_HOME = $AndroidSdkRoot
        Write-Ok "ANDROID_HOME set to $AndroidSdkRoot"
    }
}

# -- 6. .NET MAUI Workload ----------------------------------------------------
Write-Step 6 $totalSteps ".NET MAUI Workload"

if ($SkipCompanion) {
    Write-Skip "Companion skipped. MAUI workload not needed."
} else {
    Write-Info "Installing MAUI Android workload..."
    & dotnet workload install maui-android 2>$null
    Write-Ok "MAUI workload ready."
}

# -- 7. NuGet Restore + Build -------------------------------------------------
Write-Step 7 $totalSteps "Restore & Build"

if ($SkipBuild) {
    Write-Skip "Build skipped."
} else {
    Write-Info "Restoring NuGet packages..."
    & dotnet restore "$ProjectRoot\BrainstormAssistant.sln" --verbosity quiet
    Write-Ok "Packages restored."

    Write-Info "Building desktop app (Release)..."
    & dotnet build "$ProjectRoot\BrainstormAssistant\BrainstormAssistant.csproj" -c Release --verbosity quiet
    Write-Ok "Desktop app built."

    Write-Info "Publishing to .\publish\ ..."
    & dotnet publish "$ProjectRoot\BrainstormAssistant\BrainstormAssistant.csproj" -c Release -o "$ProjectRoot\publish" --self-contained false --verbosity quiet
    Write-Ok "Published to $ProjectRoot\publish\"
}

# -- 8. Tests -----------------------------------------------------------------
Write-Step 8 $totalSteps "Tests"

if ($SkipBuild) {
    Write-Skip "Tests skipped (build was skipped)."
} else {
    Write-Info "Running tests..."
    & dotnet test "$ProjectRoot\BrainstormAssistant.Tests\BrainstormAssistant.Tests.csproj" -c Release --verbosity quiet
    Write-Ok "All tests passed."
}

# -- Cleanup ------------------------------------------------------------------
if (Test-Path $TempDir) {
    Remove-Item $TempDir -Recurse -Force -ErrorAction SilentlyContinue
}

# -- Done ---------------------------------------------------------------------
Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "  Setup Complete!" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Run the app:" -ForegroundColor White
Write-Host "    .\run.bat" -ForegroundColor White
Write-Host "    (Configure LLM provider & API key in the Settings window)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Build Android companion:" -ForegroundColor White
Write-Host "    .\build_apk.bat" -ForegroundColor White
Write-Host ""
