"""Game launcher for Mac/Steam version of Slay the Spire.

This module provides automated launching and management of the
real Slay the Spire game with ModTheSpire and CommunicationMod.
"""
import os
import subprocess
import time
from pathlib import Path
from typing import Optional


class GameLauncherError(Exception):
    """Exception raised for game launcher errors."""
    pass


class MacGameLauncher:
    """Launcher for Slay the Spire on Mac via Steam.

    This class handles:
    - Launching the game with ModTheSpire
    - Waiting for the game to be ready
    - Checking if the game is running
    - Terminating the game
    """

    # Steam App ID for Slay the Spire
    STS_APP_ID = "646570"

    # Default paths for Mac
    DEFAULT_STEAM_PATH = Path("~/Library/Application Support/Steam").expanduser()
    DEFAULT_STS_PATH = Path(
        "~/Library/Application Support/Steam/steamapps/common/SlayTheSpire"
    ).expanduser()

    # ModTheSpire jar location
    MTS_JAR_NAME = "ModTheSpire.jar"

    def __init__(
        self,
        steam_path: Optional[str] = None,
        sts_path: Optional[str] = None,
        mods: Optional[list] = None
    ):
        """Initialize the game launcher.

        Args:
            steam_path: Path to Steam directory.
            sts_path: Path to Slay the Spire installation.
            mods: List of mod IDs to enable.
        """
        self.steam_path = Path(steam_path) if steam_path else self.DEFAULT_STEAM_PATH
        self.sts_path = Path(sts_path) if sts_path else self.DEFAULT_STS_PATH
        self.mods = mods or ["CommunicationMod"]

        self._process: Optional[subprocess.Popen] = None
        self._mts_jar: Optional[Path] = None

        # Find ModTheSpire jar
        self._find_mts_jar()

    def _find_mts_jar(self):
        """Find the ModTheSpire jar file."""
        # Check common locations
        possible_paths = [
            self.sts_path / "ModTheSpire.jar",
            self.sts_path / "mods" / "ModTheSpire.jar",
            self.steam_path / "steamapps" / "common" / "SlayTheSpire" / "ModTheSpire.jar",
        ]

        for path in possible_paths:
            if path.exists():
                self._mts_jar = path
                return

        # Try to find via find command
        try:
            result = subprocess.run(
                ["find", str(self.sts_path), "-name", "ModTheSpire.jar"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.stdout.strip():
                self._mts_jar = Path(result.stdout.strip().split('\n')[0])
                return
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    def launch_game(self, with_mods: bool = True) -> bool:
        """Launch Slay the Spire with ModTheSpire.

        Args:
            with_mods: Whether to enable mods.

        Returns:
            True if launch initiated successfully.

        Raises:
            GameLauncherError: If launch fails.
        """
        if self.is_running():
            print("Game is already running")
            return True

        # Check for ModTheSpire
        if with_mods and self._mts_jar is None:
            raise GameLauncherError(
                "ModTheSpire.jar not found. Please install ModTheSpire:\n"
                "1. Download from https://github.com/kiooeht/ModTheSpire\n"
                "2. Extract to SlayTheSpire directory\n"
                "3. Install CommunicationMod from Steam Workshop"
            )

        try:
            if with_mods:
                # Launch with ModTheSpire
                cmd = self._build_mts_command()

                print(f"Launching game with command: {' '.join(cmd)}")

                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(self.sts_path),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
            else:
                # Launch vanilla via Steam
                cmd = ["open", f"steam://rungameid/{self.STS_APP_ID}"]

                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

            return True

        except Exception as e:
            raise GameLauncherError(f"Failed to launch game: {e}")

    def _build_mts_command(self) -> list:
        """Build the ModTheSpire launch command."""
        cmd = ["java", "-jar", str(self._mts_jar)]

        # Add mods
        for mod in self.mods:
            cmd.extend(["--mod", mod])

        return cmd

    def wait_for_ready(self, timeout: float = 120.0) -> bool:
        """Wait for the game to be ready.

        Args:
            timeout: Maximum time to wait in seconds.

        Returns:
            True if game is ready, False on timeout.
        """
        print(f"Waiting for game to be ready (timeout: {timeout}s)...")

        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.is_running():
                # Check for CommunicationMod bridge readiness
                # This requires the bridge file to exist
                bridge_ready = Path("/tmp/sts_bridge/bridge_ready.txt")
                if bridge_ready.exists():
                    print("Game is ready!")
                    return True

            time.sleep(1.0)
            elapsed = time.time() - start_time
            if elapsed % 10 < 1:
                print(f"  Still waiting... ({elapsed:.0f}s)")

        print(f"Timeout waiting for game to be ready after {timeout}s")
        return False

    def is_running(self) -> bool:
        """Check if the game is currently running.

        Returns:
            True if game is running.
        """
        # Check if our process is still running
        if self._process is not None:
            return self._process.poll() is None

        # Check via pgrep for Slay the Spire processes
        try:
            # Check for Java process (ModTheSpire)
            result = subprocess.run(
                ["pgrep", "-f", "ModTheSpire"],
                capture_output=True
            )
            if result.returncode == 0:
                return True

            # Check for Steam game process
            result = subprocess.run(
                ["pgrep", "-f", "SlayTheSpire"],
                capture_output=True
            )
            return result.returncode == 0

        except FileNotFoundError:
            # pgrep not available, try alternative
            try:
                result = subprocess.run(
                    ["ps", "aux"],
                    capture_output=True,
                    text=True
                )
                return "SlayTheSpire" in result.stdout or "ModTheSpire" in result.stdout
            except Exception:
                return False

    def terminate(self):
        """Terminate the game process."""
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            except Exception:
                pass
            finally:
                self._process = None

        # Also kill any stray processes
        try:
            subprocess.run(["pkill", "-f", "ModTheSpire"], capture_output=True)
        except Exception:
            pass

    def get_game_version(self) -> Optional[str]:
        """Get the installed game version.

        Returns:
            Version string or None if not found.
        """
        # Try to read from version file or prefs
        version_file = self.sts_path / "version.txt"
        if version_file.exists():
            try:
                with open(version_file) as f:
                    return f.read().strip()
            except Exception:
                pass

        # Check Steam appinfo
        # This would require parsing Steam's appinfo.vdf
        return None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - terminates game."""
        self.terminate()
        return False


class GameLauncherFactory:
    """Factory for creating platform-specific game launchers."""

    @staticmethod
    def create_launcher(platform: Optional[str] = None, **kwargs):
        """Create a game launcher for the current platform.

        Args:
            platform: Platform override ('mac', 'windows', 'linux').
            **kwargs: Additional arguments for the launcher.

        Returns:
            Platform-specific GameLauncher instance.
        """
        import platform as plt

        system = platform or plt.system()

        if system == "Darwin":
            return MacGameLauncher(**kwargs)
        elif system == "Windows":
            # Would need WindowsGameLauncher implementation
            raise NotImplementedError(
                "Windows game launcher not yet implemented. "
                "Contributions welcome!"
            )
        elif system == "Linux":
            # Would need LinuxGameLauncher implementation
            raise NotImplementedError(
                "Linux game launcher not yet implemented. "
                "Contributions welcome!"
            )
        else:
            raise GameLauncherError(f"Unsupported platform: {system}")
