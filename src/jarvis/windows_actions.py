from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tempfile
import webbrowser
from urllib.parse import quote_plus

from .app_database import AppDatabase
from .models import CommandResult
from .processes import background_process_options, powershell_command
from .process_control import ProcessControl
from .local_file_actions import LocalFileActions
from .folder_windows import FolderWindows
from .rollback import RollbackManager
from .user_settings import JarvisSettings


class WindowsActions:
    def __init__(self, dry_run: bool = False, settings: JarvisSettings | None = None) -> None:
        self.dry_run = dry_run
        self.settings = settings
        self._record_rollback = True
        self.process_control = ProcessControl(dry_run=dry_run)
        self.local_files = LocalFileActions(dry_run=dry_run)
        self.folder_windows = FolderWindows(dry_run=dry_run)

    def open_task_manager(self) -> CommandResult:
        return self.open_app(str(Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32" / "Taskmgr.exe"), "Task Manager")

    def open_application(self, command: str, display_name: str | None = None) -> CommandResult:
        from .config import APP_ALIASES

        value = command.strip().strip('"')
        aliases = {**APP_ALIASES, **self._settings().app_aliases}
        value = aliases.get(value.casefold(), value)
        if value == "ms-settings:":
            return self.open_app(value, display_name or "Settings")
        if value in APP_ALIASES.values():
            return self.open_app(value, display_name)
        path = Path(value)
        if path.is_absolute() or value.startswith(("\\\\", "//")):
            if value.startswith(("\\\\", "//")) or ":" in value[2:] or path.suffix.casefold() != ".exe" or not path.is_file():
                return CommandResult(False, "Choose an existing local .exe without arguments, or an installed app name.")
            if self.dry_run:
                return CommandResult(True, f"Would open application: {path}")
            try:
                subprocess.Popen([str(path)], shell=False)
                return CommandResult(True, f"Windows accepted the launch request for {path.name}.",
                                     metadata={"path": str(path), "window_verified": False})
            except OSError as exc:
                return CommandResult(False, f"Could not launch application: {exc}")
        return self.launch_installed_app(value)

    def launch_installed_app(self, query: str) -> CommandResult:
        try:
            database = AppDatabase()
            entries = database.load() or database.refresh()
            key = query.strip().casefold()
            if not key:
                return CommandResult(False, "Specify the installed application name.")
            matches = [entry for entry in entries if entry.name.casefold() == key]
            if not matches:
                matches = [entry for entry in entries if key in entry.name.casefold()]
            if len(matches) != 1:
                names = [entry.name for entry in matches[:20]]
                return CommandResult(False, "Choose one exact installed application name: " + (", ".join(names) or "no match"),
                                     metadata={"matches": names, "launched": False})
            entry = matches[0]
            if self.dry_run:
                return CommandResult(True, f"Would launch installed application: {entry.name}")
            return self._start_app_id(entry.app_id, entry.name)
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return CommandResult(False, f"Could not resolve the installed application: {exc}")

    def list_processes(self, query: str = "", include_background: bool = False) -> CommandResult:
        return self.process_control.list_processes(query, include_background)

    def end_process(self, selection_id: str) -> CommandResult:
        return self.process_control.end_process(selection_id)

    def close_app(self, selection_id: str) -> CommandResult:
        return self.process_control.close_app(selection_id)

    def open_url(self, url: str) -> CommandResult:
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        if self.dry_run:
            browser = self._preferred_browser_display()
            suffix = f" in {browser}" if browser else ""
            return CommandResult(True, f"Would open {url}{suffix}")
        browser_command = self._preferred_browser_command()
        if browser_command:
            try:
                subprocess.Popen([browser_command, url], shell=False)
                return CommandResult(True, f"Opening {url} in {self._preferred_browser_display()}")
            except OSError:
                pass
        webbrowser.open(url)
        return CommandResult(True, f"Opening {url}")

    def search_web(self, query: str) -> CommandResult:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        if self.dry_run:
            browser = self._preferred_browser_display()
            suffix = f" in {browser}" if browser else ""
            return CommandResult(True, f"Would search the web for '{query}'{suffix}: {url}")
        return self.open_url(url).with_metadata(metadata={"query": query})

    def open_app(self, command: str, display_name: str | None = None) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, f"Would open {display_name or command}")
        try:
            if command.startswith("ms-settings:"):
                os.startfile(command)
            else:
                subprocess.Popen(command, shell=False)
        except FileNotFoundError:
            return CommandResult(
                False,
                f"I could not find {display_name or command}. Add its full path in src/jarvis/config.py.",
            )
        except OSError as exc:
            return CommandResult(False, f"Could not open {display_name or command}: {exc}")
        return CommandResult(True, f"Opening {display_name or command}")

    def open_discovered_app(self, query: str) -> CommandResult:
        query = query.strip()
        if not query:
            return CommandResult(False, "No app name provided.")
        cached = AppDatabase().find(query)
        if cached is not None:
            if self.dry_run:
                return CommandResult(True, f"Would open installed app from cache: {cached.name}")
            return self._start_app_id(cached.app_id, cached.name)

        escaped_query = self._powershell_string(query)
        if self.dry_run:
            lookup_script = f"""
$query = "{escaped_query}"
$app = Get-StartApps | Where-Object {{ $_.Name -like "*$query*" }} | Sort-Object Name | Select-Object -First 1
if ($null -eq $app) {{
    "No installed Start app matched '$query'."
    exit 1
}}
"Would open installed app: $($app.Name)"
""".strip()
            return self._run_readonly_powershell("Discover installed app", lookup_script)

        script = f"""
$query = "{escaped_query}"
$apps = Get-StartApps | Where-Object {{ $_.Name -like "*$query*" }} | Sort-Object Name
$app = $apps | Select-Object -First 1
if ($null -eq $app) {{
    "No installed Start app matched '$query'."
    exit 1
}}
Start-Process "shell:AppsFolder\\$($app.AppID)"
"Opening installed app: $($app.Name)"
""".strip()
        return self._run_powershell(f"Open discovered app {query}", script, capture=True)

    def refresh_app_database(self) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, "Would refresh installed app database from Start Menu.")
        try:
            entries = AppDatabase().refresh()
        except Exception as exc:
            return CommandResult(False, f"App database refresh failed: {exc}")
        return CommandResult(True, f"Indexed {len(entries)} installed Start apps.")

    def list_app_database(self) -> CommandResult:
        entries = AppDatabase().load()
        if not entries:
            return CommandResult(False, "App database is empty. Run: jarvis refresh app database")
        names = "\n".join(f"- {entry.name}" for entry in entries[:80])
        suffix = "" if len(entries) <= 80 else f"\n...and {len(entries) - 80} more."
        return CommandResult(True, f"Installed app database ({len(entries)} apps):\n{names}{suffix}")

    def _start_app_id(self, app_id: str, display_name: str) -> CommandResult:
        script = f"""
$appId = "{self._powershell_string(app_id)}"
Start-Process "shell:AppsFolder\\$appId"
"Opening installed app: {self._powershell_string(display_name)}"
""".strip()
        return self._run_powershell(f"Open installed app {display_name}", script, capture=True)

    def volume_up(self) -> CommandResult:
        return self._run_powershell(
            "Volume up",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]175)",
        )

    def volume_down(self) -> CommandResult:
        return self._run_powershell(
            "Volume down",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]174)",
        )

    def toggle_mute(self) -> CommandResult:
        return self._run_powershell(
            "Toggle mute",
            "(New-Object -ComObject WScript.Shell).SendKeys([char]173)",
        )

    def set_volume(self, percent: int) -> CommandResult:
        percent = max(0, min(100, percent))
        if self.dry_run:
            return CommandResult(True, f"Would set volume to {percent}%")
        try:
            from .volume import get_master_volume_percent, set_master_volume_percent
        except ImportError as exc:
            return CommandResult(False, f"Volume control dependency is missing: {exc}")
        try:
            previous = get_master_volume_percent()
            set_master_volume_percent(percent)
            if self._record_rollback:
                RollbackManager().push("Restore previous volume", "volume", {"percent": previous})
            observed = get_master_volume_percent()
            if abs(observed - percent) > 1:
                return CommandResult(False, f"Requested volume {percent}%, but Windows reports {observed}%.",
                                     metadata={"verification": "mismatch", "requested": percent, "observed": observed})
        except Exception as exc:
            return CommandResult(False, f"Set volume failed: {exc}")
        return CommandResult(True, f"Volume set to {observed}%.",
                             metadata={"verification": "read_back", "requested": percent, "observed": observed})

    def open_windows_update(self) -> CommandResult:
        return self.open_app("ms-settings:windowsupdate", "Windows Update")

    def check_windows_updates(self) -> CommandResult:
        script = """
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0 and Type='Software'")
if ($result.Updates.Count -eq 0) {
    "No pending Windows software updates found."
} else {
    "Pending Windows updates: $($result.Updates.Count)"
    for ($i = 0; $i -lt $result.Updates.Count; $i++) {
        $update = $result.Updates.Item($i)
        "- $($update.Title)"
    }
}
""".strip()
        return self._run_powershell("Windows Update check", script, capture=True)

    def check_driver_updates(self) -> CommandResult:
        script = """
$session = New-Object -ComObject Microsoft.Update.Session
$searcher = $session.CreateUpdateSearcher()
$result = $searcher.Search("IsInstalled=0 and Type='Driver'")
if ($result.Updates.Count -eq 0) {
    "No pending driver updates found through Windows Update."
} else {
    "Pending driver updates: $($result.Updates.Count)"
    for ($i = 0; $i -lt $result.Updates.Count; $i++) {
        $update = $result.Updates.Item($i)
        "- $($update.Title)"
    }
}
""".strip()
        return self._run_powershell("Driver update check", script, capture=True)

    def driver_info(self, category: str = "all") -> CommandResult:
        from .device_inventory import installed_drivers, DRIVER_CATEGORIES
        if not isinstance(category, str) or category not in DRIVER_CATEGORIES:
            return CommandResult(False, "Unknown driver category.")
        if self.dry_run:
            return CommandResult(True, f"Would read installed {category} drivers; no update check or installation.")
        return installed_drivers(category)

    def device_info(self) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, "Would read laptop model, CPU, GPUs, motherboard, BIOS and Windows version.")
        from .device_inventory import device_info
        return device_info()

    def nvidia_driver_info(self) -> CommandResult:
        return self.driver_info("nvidia")

    def open_nvidia_driver_page(self) -> CommandResult:
        return self.open_url("https://www.nvidia.com/Download/index.aspx")

    def disable_internet(self) -> CommandResult:
        if not self.dry_run and self._record_rollback:
            RollbackManager().push("Re-enable internet adapters", "enable_internet", {})
        script = """
Get-NetAdapter -Physical |
Where-Object { $_.Status -eq 'Up' -and $_.HardwareInterface -eq $true } |
Disable-NetAdapter -Confirm:$false
""".strip()
        return self._run_powershell("Disable internet adapters", script)

    def enable_internet(self) -> CommandResult:
        if not self.dry_run and self._record_rollback:
            RollbackManager().push("Disable internet adapters again", "disable_internet", {})
        script = """
Get-NetAdapter -Physical |
Where-Object { $_.Status -eq 'Disabled' -and $_.HardwareInterface -eq $true } |
Enable-NetAdapter -Confirm:$false
""".strip()
        return self._run_powershell("Enable internet adapters", script)

    def disable_bluetooth(self) -> CommandResult:
        if not self.dry_run and self._record_rollback:
            RollbackManager().push("Re-enable Bluetooth devices", "enable_bluetooth", {})
        script = """
Get-PnpDevice -Class Bluetooth |
Where-Object { $_.Status -eq 'OK' } |
Disable-PnpDevice -Confirm:$false
""".strip()
        return self._run_powershell("Disable Bluetooth devices", script)

    def enable_bluetooth(self) -> CommandResult:
        if not self.dry_run and self._record_rollback:
            RollbackManager().push("Disable Bluetooth devices again", "disable_bluetooth", {})
        script = """
Get-PnpDevice -Class Bluetooth |
Where-Object { $_.Status -ne 'OK' } |
Enable-PnpDevice -Confirm:$false
""".strip()
        return self._run_powershell("Enable Bluetooth devices", script)

    def open_nitrosense(self) -> CommandResult:
        script = """
$app = Get-StartApps | Where-Object { $_.Name -match 'NitroSense|Nitro Sense' } | Select-Object -First 1
if ($null -eq $app) {
    "NitroSense was not found in Start apps."
    exit 1
}
Start-Process "shell:AppsFolder\\$($app.AppID)"
"Opening $($app.Name)"
""".strip()
        return self._run_powershell("Open NitroSense", script, capture=True)

    def open_acer_support(self) -> CommandResult:
        return self.open_url("https://www.acer.com/support")

    def system_temperatures(self) -> CommandResult:
        return self.system_hardware_status()

    def system_hardware_status(self) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, "Would read CPU/GPU usage, temperatures and RAM usage.", metadata={"dry_run": True})
        from .monitoring.hardware import hardware_status
        return hardware_status()

    def temperature_warning(self, threshold: int = 85) -> CommandResult:
        threshold = max(40, min(110, threshold))
        if self.dry_run:
            return CommandResult(True, f"Would check CPU/GPU temperatures against {threshold} C.")
        snapshot = self.system_hardware_status()
        warnings, missing = [], []
        for name, key in (("CPU", "cpu_temperature"), ("GPU", "gpu")):
            value = snapshot.metadata.get(key, {}).get("temperature_c")
            if value is None:
                missing.append(name)
            elif value >= threshold:
                warnings.append(f"{name} temperature high: {value:.1f} C (threshold {threshold} C).")
        message = "\n".join(warnings) or f"No measured CPU/GPU temperature is above {threshold} C."
        if missing:
            message += " Unavailable sensors: " + ", ".join(missing) + "; their temperature cannot be assessed."
        return CommandResult(len(missing) < 2, message,
                             metadata={**snapshot.metadata, "warnings": warnings, "missing_sensors": missing})

    def apply_mode(self, mode: str) -> CommandResult:
        modes = {
            "quiet": ("SCHEME_BALANCED", "quiet_volume", 20, "ms-settings:quiethours"),
            "study": ("SCHEME_BALANCED", "study_volume", 35, "ms-settings:quiethours"),
            "battery": ("SCHEME_MAX", "battery_volume", 20, "ms-settings:batterysaver"),
            "gaming": ("SCHEME_MIN", "gaming_volume", 60, None),
        }
        if mode not in modes:
            return CommandResult(False, f"Unknown mode: {mode}")

        power_scheme, volume_key, default_volume, settings_uri = modes[mode]
        settings = self._settings()
        volume = self._mode_volume(settings, volume_key, default_volume)
        if self.dry_run:
            extra = f", open {settings_uri}" if settings_uri else ", open NitroSense and check temperatures"
            return CommandResult(
                True,
                f"Would apply {mode} mode: powercfg {power_scheme}, volume {volume}%{extra}",
                metadata={"mode": mode, "power_scheme": power_scheme, "volume": volume},
            )

        parts: list[str] = []
        previous_scheme = self._active_power_scheme_guid()
        if previous_scheme and self._record_rollback:
            RollbackManager().push("Restore previous power plan", "power_scheme", {"guid": previous_scheme})
        power_result = self._run_command("Power mode", ["powercfg", "/setactive", power_scheme])
        parts.append(power_result.message)
        if not power_result.ok:
            return CommandResult(False, "\n".join(parts), metadata={"mode": mode, "partial": True})
        volume_result = self.set_volume(volume)
        parts.append(volume_result.message)
        results = [power_result, volume_result]
        if settings_uri:
            results.append(self.open_app(settings_uri, settings_uri))
        if mode == "gaming":
            nitro = self.open_nitrosense()
            temps = self.system_temperatures()
            parts.extend([nitro.message, temps.message])
            results.extend([nitro, temps])
        return CommandResult(all(result.ok for result in results), "\n".join(parts),
                             metadata={"mode": mode, "nitrosense_profile_changed": False})

    def undo_last_action(self, expected_timestamp: str = "") -> CommandResult:
        manager = RollbackManager()
        try:
            rollback = manager.peek()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            return CommandResult(False, f"Undo history could not be read: {exc}")
        if expected_timestamp and (rollback is None or rollback.timestamp != expected_timestamp):
            return CommandResult(False, "Undo history changed. Refresh and review the latest action.")
        if self.dry_run:
            return CommandResult(True, "Would undo the last reversible Jarvis action.")

        if rollback is None:
            return CommandResult(False, "There is no reversible action to undo.")

        previous_recording = self._record_rollback
        self._record_rollback = False
        try:
            undo_type = rollback.undo_type
            payload = rollback.payload
            if undo_type == "volume":
                result = self.set_volume(int(payload["percent"]))
            elif undo_type == "power_scheme":
                result = self._run_command("Restore power plan", ["powercfg", "/setactive", str(payload["guid"])])
                if result.ok and self._active_power_scheme_guid() != payload["guid"]:
                    result = CommandResult(False, "Power plan restore could not be verified; undo record retained.")
            elif undo_type in {"enable_internet", "disable_internet", "enable_bluetooth", "disable_bluetooth"}:
                result = getattr(self, undo_type)()
            elif undo_type == "local_path_move":
                result = self.local_files.restore_move(payload)
            else:
                result = CommandResult(False, f"Unsupported rollback action: {undo_type}")
            try:
                removed = manager.discard_if_latest(rollback) if result.ok else False
            except (OSError, ValueError, TypeError, KeyError) as exc:
                return CommandResult(result.ok, result.message + " Undo completed, but history could not be updated.",
                                     metadata={**result.metadata, "undo_record_removed": False,
                                               "undo_label": rollback.label, "undo_history_error": str(exc)})
            return result.with_metadata(metadata={**result.metadata, "undo_record_removed": removed,
                                                  "undo_label": rollback.label})
        finally:
            self._record_rollback = previous_recording

    def game_mode(self) -> CommandResult:
        settings = self._settings()
        close_processes = self._gaming_list(settings, "close_processes", [])
        invalid = [name for name in close_processes if not re.fullmatch(r"[A-Za-z0-9_. -]+", name)
                   or name.casefold().removesuffix(".exe") in {"system", "registry", "smss", "csrss", "wininit",
                   "services", "lsass", "svchost", "winlogon", "dwm", "explorer"}]
        if invalid:
            return CommandResult(False, "Gaming close list must contain exact, non-system app process names, without wildcards.")
        launch_apps = self._gaming_list(settings, "launch_apps", [])
        if self.dry_run:
            close_display = ", ".join(close_processes) if close_processes else "nothing"
            launch_display = ", ".join(launch_apps) if launch_apps else "nothing"
            return CommandResult(
                True,
                "Would enable gaming mode, "
                f"close: {close_display}; launch: {launch_display}; "
                "open NitroSense; check temperatures.",
                metadata={"close_processes": close_processes, "launch_apps": launch_apps},
            )
        quoted_names = ",".join(f'"{self._powershell_string(name)}"' for name in close_processes)
        powershell_names = f"@({quoted_names})" if quoted_names else "@()"
        close_script = f"""
$names = {powershell_names}
foreach ($name in $names) {{
    Get-Process -Name $name -ErrorAction SilentlyContinue | Stop-Process -Force
}}
"Closed configured background apps if they were running."
""".strip()
        close_result = self._run_powershell("Close background apps", close_script, capture=True)
        mode_result = self.apply_mode("gaming")
        launch_results = [self.open_discovered_app(app) for app in launch_apps]
        parts = [close_result.message, mode_result.message, *(result.message for result in launch_results)]
        return CommandResult(
            all(result.ok for result in [close_result, mode_result, *launch_results]),
            "\n".join(part for part in parts if part),
            metadata={"close_processes": close_processes, "launch_apps": launch_apps},
        )

    def open_recent_file(self) -> CommandResult:
        script = """
$shell = New-Object -ComObject WScript.Shell
$recent = [Environment]::GetFolderPath("Recent")
$items = Get-ChildItem $recent -Filter *.lnk -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
foreach ($item in $items) {
    $shortcut = $shell.CreateShortcut($item.FullName)
    if ($shortcut.TargetPath -and (Test-Path $shortcut.TargetPath)) {
        Start-Process $shortcut.TargetPath
        "Opening recent file: $($shortcut.TargetPath)"
        exit 0
    }
}
"No recent file target was found."
exit 1
""".strip()
        return self._run_powershell("Open recent file", script, capture=True)

    def create_docx(self, topic: str) -> CommandResult:
        safe_name = re.sub(r"[^\w-]+", "_", topic, flags=re.UNICODE).strip("_")[:60] or "document"
        path = self._workspace_path(f"documents/{safe_name}.docx")
        if self.dry_run:
            return CommandResult(True, f"Would create DOCX document {path} about: {topic}")
        try:
            from docx import Document
        except ImportError:
            return CommandResult(False, "python-docx is not installed. Run: pip install -r requirements.txt")

        path.parent.mkdir(parents=True, exist_ok=True)
        document = Document()
        document.add_heading(topic.title(), level=0)
        document.add_paragraph("Draft created by Jarvis. Tell me what sections, tone, and length you want next.")
        document.add_heading("Outline", level=1)
        for item in ("Introduction", "Key Points", "Details", "Conclusion"):
            document.add_paragraph(item, style="List Bullet")
        document.save(path)
        return CommandResult(True, f"Created DOCX document {path}")

    def cleanup_temp_files(self) -> CommandResult:
        temp_path = tempfile.gettempdir()
        script = f"""
$temp = "{temp_path}"
$items = Get-ChildItem -LiteralPath $temp -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object {{ -not $_.PSIsContainer -and $_.LastWriteTime -lt (Get-Date).AddDays(-1) }}
$count = 0
$bytes = 0
foreach ($item in $items) {{
    $bytes += $item.Length
    Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue
    $count++
}}
"Removed $count temp files from $temp. Approx bytes considered: $bytes"
""".strip()
        return self._run_powershell("Clean temp files", script, capture=True)

    def top_processes(self) -> CommandResult:
        script = """
$os = Get-CimInstance Win32_OperatingSystem
$total = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$free = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
$used = [math]::Round($total - $free, 1)
"Memory: $used GB used / $total GB total"
"Top processes by memory:"
Get-Process |
    Sort-Object WorkingSet64 -Descending |
    Select-Object -First 10 Name, Id, CPU, @{Name="MemoryMB";Expression={[math]::Round($_.WorkingSet64 / 1MB, 1)}} |
    Format-Table -AutoSize
""".strip()
        return self._run_powershell("Top processes", script, capture=True)

    def startup_programs(self) -> CommandResult:
        script = """
$locations = @(
    "HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup",
    "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\Startup"
)
foreach ($location in $locations) {
    "Startup location: $location"
    if ($location -like "HK*") {
        Get-ItemProperty -Path $location -ErrorAction SilentlyContinue |
            Select-Object -Property * -ExcludeProperty PSPath,PSParentPath,PSChildName,PSDrive,PSProvider |
            Format-List
    } else {
        Get-ChildItem -LiteralPath $location -ErrorAction SilentlyContinue |
            Select-Object Name, FullName |
            Format-Table -AutoSize
    }
}
""".strip()
        return self._run_powershell("Startup programs", script, capture=True)

    def create_folder(self, target: str) -> CommandResult:
        try:
            path = self._workspace_path(target)
        except ValueError as exc:
            return CommandResult(False, str(exc))
        if self.dry_run:
            return CommandResult(True, f"Would create folder {path}")
        try:
            if path.is_dir():
                return CommandResult(True, f"Folder already exists: {path}", metadata={"path": str(path), "created": False})
            path.mkdir(parents=True, exist_ok=True)
            return CommandResult(True, f"Created folder {path}", metadata={"path": str(path), "created": True})
        except OSError as exc:
            return CommandResult(False, f"Could not create folder: {exc}")

    def create_file(self, target: str) -> CommandResult:
        return self.create_text_file(target, "")

    def create_text_file(self, target: str, content: str) -> CommandResult:
        try:
            path = self._workspace_path(target)
        except ValueError as exc:
            return CommandResult(False, str(exc))
        if self.dry_run:
            return CommandResult(True, f"Would create file {path}")
        if len(content.encode("utf-8")) > 1_000_000:
            return CommandResult(False, "Text content exceeds the 1 MB limit.")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as output:
                output.write(content)
            return CommandResult(True, f"Created file {path}", metadata={"path": str(path), "created": True})
        except FileExistsError:
            return CommandResult(False, f"Already exists: {path}. The existing file was not changed.")
        except OSError as exc:
            return CommandResult(False, f"Could not create file: {exc}")

    def list_folder(self, target: str = ".") -> CommandResult:
        try:
            path = self._workspace_path(target)
            entries = []
            with os.scandir(path) as scan:
                for item in scan:
                    entries.append({"name": item.name, "kind": "folder" if item.is_dir(follow_symlinks=False) else "file"})
                    if len(entries) >= 100:
                        break
            entries.sort(key=lambda item: (item["kind"], item["name"].casefold()))
            return CommandResult(True, "\n".join(f"{item['kind']}: {item['name']}" for item in entries) or "Folder is empty.",
                                 metadata={"path": str(path), "entries": entries, "limit": 100, "partial": len(entries) >= 100})
        except (ValueError, OSError) as exc:
            return CommandResult(False, f"Could not list folder: {exc}")

    def restart(self) -> CommandResult:
        return self._run_command("Restart", ["shutdown", "/r", "/t", "10"])

    def shutdown(self) -> CommandResult:
        return self._run_command("Shutdown", ["shutdown", "/s", "/t", "10"])

    def sleep(self) -> CommandResult:
        return self._run_powershell(
            "Sleep",
            "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
        )

    def _run_powershell(self, label: str, script: str, capture: bool = False) -> CommandResult:
        command = powershell_command(script)
        return self._run_command(label, command, capture=capture)

    def _run_readonly_powershell(self, label: str, script: str) -> CommandResult:
        command = powershell_command(script)
        try:
            completed = subprocess.run(command, check=False, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=30,
                                       **background_process_options())
        except subprocess.TimeoutExpired:
            return CommandResult(False, f"{label} timed out. No retry was made.", metadata={"timed_out": True})
        except OSError as exc:
            return CommandResult(False, f"{label} failed: {exc}")
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return CommandResult(False, detail or f"{label} found no result.")
        return CommandResult(True, completed.stdout.strip() or f"{label} returned no output.")

    def _active_power_scheme_guid(self) -> str | None:
        try:
            completed = subprocess.run(
                ["powercfg", "/getactivescheme"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                errors="replace",
                **background_process_options(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        match = re.search(r"([0-9a-fA-F-]{36})", completed.stdout or "")
        return match.group(1) if match else None

    def _run_command(self, label: str, command: list[str], capture: bool = False) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, f"Would run {label}: {' '.join(command)}")

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8" if command[0].lower() == "powershell" else None,
                errors="replace",
                timeout=120 if label in {"Windows Update check", "Driver update check"} else 30,
                **background_process_options(),
            )
        except subprocess.TimeoutExpired:
            return CommandResult(False, f"{label} timed out. The operation may have partially completed; "
                                 "check its state before retrying.", metadata={"timed_out": True, "outcome_uncertain": True})
        except OSError as exc:
            return CommandResult(False, f"{label} failed: {exc}")

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            return CommandResult(False, f"{label} failed. {detail}".strip())

        if capture:
            output = completed.stdout.strip()
            return CommandResult(True, output or f"{label} returned no output.")

        return CommandResult(True, f"{label} done.")

    @staticmethod
    def _workspace_path(target: str) -> Path:
        if not isinstance(target, str) or not target.strip():
            raise ValueError("Specify a file or folder name.")
        base = Path.cwd().resolve()
        candidate = (base / target).resolve()
        if base != candidate and base not in candidate.parents:
            raise ValueError("Refusing to create files outside the Jarvis workspace.")
        for part in candidate.relative_to(base).parts:
            if (any(ord(char) < 32 or char in '<>:"|?*' for char in part)
                    or part.endswith((" ", ".")) or Path(part).is_reserved()):
                raise ValueError("Invalid Windows file or folder name.")
        return candidate

    @staticmethod
    def _powershell_string(value: str) -> str:
        return value.replace("`", "``").replace('"', '`"').replace("$", "`$")

    def _preferred_browser_display(self) -> str:
        settings = self._settings()
        preferred = settings.preferred_browser.strip()
        if preferred == "opera_gx":
            return "Opera GX"
        return preferred

    def _preferred_browser_command(self) -> str | None:
        settings = self._settings()
        preferred = settings.preferred_browser.strip().lower()
        if not preferred:
            return None
        browser_paths = settings.browser_paths
        candidates: list[str] = []
        configured = browser_paths.get(preferred)
        if configured:
            candidates.append(configured)
        if preferred == "opera_gx":
            local_app_data = os.getenv("LOCALAPPDATA", "")
            program_files = os.getenv("ProgramFiles", "")
            candidates.extend(
                [
                    str(Path(local_app_data) / "Programs" / "Opera GX" / "opera.exe"),
                    str(Path(program_files) / "Opera GX" / "opera.exe"),
                    "opera.exe",
                ]
            )
        for candidate in candidates:
            if candidate.endswith(".exe") and Path(candidate).exists():
                return candidate
            if candidate == "opera.exe":
                return candidate
        return None

    def _settings(self) -> JarvisSettings:
        return self.settings if self.settings is not None else JarvisSettings.load()

    @staticmethod
    def _mode_volume(settings: JarvisSettings, key: str, default: int) -> int:
        try:
            value = int(settings.mode_preferences.get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(0, min(100, value))

    @staticmethod
    def _gaming_list(settings: JarvisSettings, key: str, default: list[str]) -> list[str]:
        raw = settings.gaming.get(key, default)
        if not isinstance(raw, list):
            return list(default)
        return [str(item).strip() for item in raw if str(item).strip()]
