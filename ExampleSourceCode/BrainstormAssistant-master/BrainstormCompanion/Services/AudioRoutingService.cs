namespace BrainstormCompanion.Services;

/// <summary>
/// Manages audio routing between phone speaker/mic and Bluetooth devices.
/// Enumerates available audio devices via both AudioManager and BluetoothAdapter,
/// and handles SCO connection for BT earpieces.
/// </summary>
public class AudioRoutingService
{
#if ANDROID
    private Android.Media.AudioManager? _audioManager;
    private bool _scoActive;
    private bool _scoSuspended;

    public Android.Media.AudioDeviceInfo? PreferredInputDevice { get; private set; }
    public Android.Media.AudioDeviceInfo? PreferredOutputDevice { get; private set; }
    public bool IsBluetoothActive => _scoActive;
    /// <summary>Debug log of last device enumeration for troubleshooting.</summary>
    public string LastLog { get; private set; } = "";

    public class AudioRoute
    {
        public string Name { get; set; } = "";
        public bool IsBluetooth { get; set; }
        public Android.Media.AudioDeviceInfo? InputDevice { get; set; }
        public Android.Media.AudioDeviceInfo? OutputDevice { get; set; }

        public override string ToString() => Name;
    }

    /// <summary>Custom MAUI permission for BLUETOOTH_CONNECT (Android 12+).</summary>
    private class BluetoothConnectPermission : Permissions.BasePlatformPermission
    {
        public override (string androidPermission, bool isRuntime)[] RequiredPermissions =>
            new[]
            {
                (Android.Manifest.Permission.BluetoothConnect, true),
                (Android.Manifest.Permission.BluetoothScan, true)
            };
    }

    private Android.Media.AudioManager GetAudioManager()
    {
        if (_audioManager == null)
        {
            var context = Android.App.Application.Context;
            _audioManager = (Android.Media.AudioManager?)context.GetSystemService(
                Android.Content.Context.AudioService)
                ?? throw new InvalidOperationException("AudioManager unavailable");
        }
        return _audioManager;
    }

    private static bool IsBtDeviceType(Android.Media.AudioDeviceType type)
    {
        if (type == Android.Media.AudioDeviceType.BluetoothSco ||
            type == Android.Media.AudioDeviceType.BluetoothA2dp)
            return true;

        // BLE Audio types added in API 31 (BleHeadset=26, BleSpeaker=27)
        if (OperatingSystem.IsAndroidVersionAtLeast(31) &&
            ((int)type == 26 || (int)type == 27))
            return true;

        return false;
    }

    /// <summary>
    /// Requests BLUETOOTH_CONNECT + BLUETOOTH_SCAN runtime permissions using MAUI API.
    /// Returns true if granted.
    /// </summary>
    public static async Task<bool> RequestBluetoothPermissionsAsync()
    {
        if (!OperatingSystem.IsAndroidVersionAtLeast(31))
            return true; // Pre-Android 12 doesn't need runtime BT permissions

        var status = await Permissions.CheckStatusAsync<BluetoothConnectPermission>();
        if (status == PermissionStatus.Granted)
            return true;

        status = await Permissions.RequestAsync<BluetoothConnectPermission>();
        return status == PermissionStatus.Granted;
    }

    /// <summary>
    /// Returns list of available audio routes (phone + Bluetooth devices).
    /// Requests BT permissions first, then combines AudioManager + BluetoothAdapter.
    /// </summary>
    public async Task<List<AudioRoute>> GetAvailableRoutesAsync()
    {
        var log = new System.Text.StringBuilder();
        log.AppendLine("--- Audio Device Scan ---");

        bool btPermGranted = await RequestBluetoothPermissionsAsync();
        log.AppendLine($"BT permission: {(btPermGranted ? "granted" : "DENIED")}");

        var am = GetAudioManager();
        var routes = new List<AudioRoute>
        {
            new() { Name = "📱 Phone (Default)", IsBluetooth = false }
        };

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        // 1. Check AudioManager for active Bluetooth audio devices
        var inputs = am.GetDevices(Android.Media.GetDevicesTargets.Inputs) ?? [];
        var outputs = am.GetDevices(Android.Media.GetDevicesTargets.Outputs) ?? [];

        log.AppendLine($"AudioManager: {inputs.Length} inputs, {outputs.Length} outputs");
        foreach (var d in inputs)
            log.AppendLine($"  IN: type={d.Type} name={d.ProductName}");
        foreach (var d in outputs)
            log.AppendLine($"  OUT: type={d.Type} name={d.ProductName}");

        var btInputs = inputs.Where(d => IsBtDeviceType(d.Type)).ToList();
        var btOutputs = outputs.Where(d => IsBtDeviceType(d.Type)).ToList();

        foreach (var dev in btInputs.Cast<Android.Media.AudioDeviceInfo>().Concat(btOutputs))
        {
            var name = dev.ProductName?.ToString();
            if (string.IsNullOrWhiteSpace(name)) name = $"BT-{dev.Id}";
            if (!seen.Add(name)) continue;

            routes.Add(new AudioRoute
            {
                Name = $"🎧 {name}",
                IsBluetooth = true,
                InputDevice = btInputs.FirstOrDefault(d =>
                    (d.ProductName?.ToString() ?? $"BT-{d.Id}") == name),
                OutputDevice = btOutputs.FirstOrDefault(d =>
                    (d.ProductName?.ToString() ?? $"BT-{d.Id}") == name)
            });
        }

        // 2. Check BluetoothAdapter bonded (paired) devices
        if (btPermGranted)
        {
            try
            {
                var btAdapter = Android.Bluetooth.BluetoothAdapter.DefaultAdapter;
                log.AppendLine($"BT adapter: {(btAdapter == null ? "null" : btAdapter.IsEnabled ? "enabled" : "disabled")}");

                if (btAdapter?.IsEnabled == true && btAdapter.BondedDevices != null)
                {
                    log.AppendLine($"Bonded devices: {btAdapter.BondedDevices.Count}");
                    foreach (var device in btAdapter.BondedDevices)
                    {
                        var name = device.Name;
                        var major = device.BluetoothClass?.MajorDeviceClass;
                        log.AppendLine($"  Bonded: {name} class={major}");

                        if (string.IsNullOrWhiteSpace(name)) continue;
                        if (seen.Contains(name)) continue;

                        // Include audio devices + uncategorized (some earbuds report Misc)
                        if (major != Android.Bluetooth.MajorDeviceClass.AudioVideo &&
                            major != Android.Bluetooth.MajorDeviceClass.Wearable &&
                            major != Android.Bluetooth.MajorDeviceClass.Uncategorized &&
                            major != Android.Bluetooth.MajorDeviceClass.Peripheral)
                            continue;

                        seen.Add(name);
                        routes.Add(new AudioRoute
                        {
                            Name = $"🎧 {name}",
                            IsBluetooth = true
                        });
                    }
                }
            }
            catch (Exception ex)
            {
                log.AppendLine($"BT error: {ex.Message}");
            }
        }

        log.AppendLine($"Total routes: {routes.Count}");
        LastLog = log.ToString();
        return routes;
    }

    /// <summary>
    /// Applies the selected audio route — starts/stops Bluetooth SCO as needed.
    /// </summary>
    public async Task ApplyRouteAsync(AudioRoute route)
    {
        var am = GetAudioManager();

        if (route.IsBluetooth)
        {
            // Start SCO first — this opens the bidirectional audio link
#pragma warning disable CA1422
            am.StartBluetoothSco();
            am.BluetoothScoOn = true;
#pragma warning restore CA1422
            am.Mode = Android.Media.Mode.InCommunication;

            // Wait for SCO to connect
            await Task.Delay(2000);

            // Now resolve AudioDeviceInfo if we don't have it yet
            if (route.InputDevice == null || route.OutputDevice == null)
                RefreshDeviceInfo(route, am);

            // On API 31+ use SetCommunicationDevice for precise routing
            if (OperatingSystem.IsAndroidVersionAtLeast(31))
            {
                var commDevice = route.OutputDevice ?? route.InputDevice;
                if (commDevice != null)
                    am.SetCommunicationDevice(commDevice);
            }

            PreferredInputDevice = route.InputDevice;
            PreferredOutputDevice = route.OutputDevice;
            _scoActive = true;
        }
        else
        {
            PreferredInputDevice = null;
            PreferredOutputDevice = null;

            if (_scoActive)
            {
                if (OperatingSystem.IsAndroidVersionAtLeast(31))
                    am.ClearCommunicationDevice();

#pragma warning disable CA1422
                am.StopBluetoothSco();
                am.BluetoothScoOn = false;
#pragma warning restore CA1422
                _scoActive = false;
            }

            am.Mode = Android.Media.Mode.Normal;
        }
    }

    /// <summary>
    /// Temporarily stops SCO so TTS audio plays through A2DP (Music stream).
    /// Call before any audio playback. No-op if Bluetooth is not active.
    /// </summary>
    public void SuspendScoForPlayback()
    {
        if (!_scoActive || _scoSuspended || _audioManager == null) return;

        if (OperatingSystem.IsAndroidVersionAtLeast(31))
            _audioManager.ClearCommunicationDevice();

#pragma warning disable CA1422
        _audioManager.StopBluetoothSco();
        _audioManager.BluetoothScoOn = false;
#pragma warning restore CA1422
        _audioManager.Mode = Android.Media.Mode.Normal;
        _scoSuspended = true;
    }

    /// <summary>
    /// Restarts SCO after playback so BT mic recording works again.
    /// No-op if SCO was not suspended.
    /// </summary>
    public async Task ResumeScoAfterPlayback()
    {
        if (!_scoActive || !_scoSuspended || _audioManager == null) return;

#pragma warning disable CA1422
        _audioManager.StartBluetoothSco();
        _audioManager.BluetoothScoOn = true;
#pragma warning restore CA1422
        _audioManager.Mode = Android.Media.Mode.InCommunication;

        await Task.Delay(1500);

        if (OperatingSystem.IsAndroidVersionAtLeast(31))
        {
            var commDevice = PreferredOutputDevice ?? PreferredInputDevice;
            if (commDevice != null)
                _audioManager.SetCommunicationDevice(commDevice);
        }

        _scoSuspended = false;
    }

    private static void RefreshDeviceInfo(AudioRoute route, Android.Media.AudioManager am)
    {
        var routeName = route.Name.Replace("🎧 ", "");

        var inputs = am.GetDevices(Android.Media.GetDevicesTargets.Inputs) ?? [];
        var outputs = am.GetDevices(Android.Media.GetDevicesTargets.Outputs) ?? [];

        if (route.InputDevice == null)
        {
            // Try name match first, then any BT SCO input
            route.InputDevice = inputs.FirstOrDefault(d =>
                IsBtDeviceType(d.Type) &&
                d.ProductName?.ToString()?.Contains(routeName, StringComparison.OrdinalIgnoreCase) == true);
            route.InputDevice ??= inputs.FirstOrDefault(d =>
                d.Type == Android.Media.AudioDeviceType.BluetoothSco);
        }

        if (route.OutputDevice == null)
        {
            route.OutputDevice = outputs.FirstOrDefault(d =>
                IsBtDeviceType(d.Type) &&
                d.ProductName?.ToString()?.Contains(routeName, StringComparison.OrdinalIgnoreCase) == true);
            route.OutputDevice ??= outputs.FirstOrDefault(d =>
                d.Type == Android.Media.AudioDeviceType.BluetoothSco);
        }
    }

    /// <summary>
    /// Cleans up SCO connection when app closes.
    /// </summary>
    public void Cleanup()
    {
        if (!_scoActive || _audioManager == null) return;

        if (OperatingSystem.IsAndroidVersionAtLeast(31))
            _audioManager.ClearCommunicationDevice();

#pragma warning disable CA1422
        _audioManager.StopBluetoothSco();
        _audioManager.BluetoothScoOn = false;
#pragma warning restore CA1422

        _audioManager.Mode = Android.Media.Mode.Normal;
        _scoActive = false;
        PreferredInputDevice = null;
        PreferredOutputDevice = null;
    }
#else
    public string LastLog { get; private set; } = "";
    public bool IsBluetoothActive => false;

    public class AudioRoute
    {
        public string Name { get; set; } = "";
        public bool IsBluetooth { get; set; }
        public override string ToString() => Name;
    }

    public Task<List<AudioRoute>> GetAvailableRoutesAsync() =>
        Task.FromResult(new List<AudioRoute> { new() { Name = "📱 Phone (Default)" } });

    public Task ApplyRouteAsync(AudioRoute route) => Task.CompletedTask;
    public void SuspendScoForPlayback() { }
    public Task ResumeScoAfterPlayback() => Task.CompletedTask;
    public void Cleanup() { }
#endif
}
