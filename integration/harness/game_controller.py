"""Interface to real Slay the Spire game via CommunicationMod.

This works with the communication_bridge.py script. Setup:

1. Configure CommunicationMod to run the bridge:
   command=python /path/to/tests/integration/harness/communication_bridge.py --state-dir /tmp/sts_bridge

2. The test runner connects to the bridge via files in the state directory.

Multi-Project Coordination:
    The controller acquires an exclusive lock on connect() to prevent
    multiple projects from using the bridge simultaneously. The lock
    is automatically released on disconnect() or when the process exits.

    from harness.game_controller import GameController

    # Lock is acquired on connect, released on disconnect
    with GameController(project_name="my_test") as game:
        state = game.get_state()  # Exclusive access guaranteed
"""
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from .bridge_lock import bridge_lock, get_lock_info, LockInfo, BridgeLockedError


class CommunicationModError(Exception):
    """Exception raised for CommunicationMod communication errors."""
    pass


class BridgeInUseError(CommunicationModError):
    """Raised when bridge is locked by another process."""
    def __init__(self, lock_info: Optional[LockInfo]):
        self.lock_info = lock_info
        if lock_info:
            message = (
                f"Bridge is locked by '{lock_info.project}' (PID {lock_info.pid})\n\n"
                f"Options:\n"
                f"  1. Wait for the current process to finish\n"
                f"  2. Kill the process: kill {lock_info.pid}\n"
                f"  3. Force remove lock: rm /tmp/sts_bridge/.coordinator/lock"
            )
        else:
            message = "Bridge is locked by another process"
        super().__init__(message)


class GameController:
    """Interface to real Slay the Spire via CommunicationMod bridge.

    The bridge script (communication_bridge.py) runs as a subprocess of
    CommunicationMod and communicates via files.
    """

    def __init__(
        self,
        state_dir: str = "/tmp/sts_bridge",
        config_path: Optional[str] = None,
        timeout: float = 30.0,
        project_name: Optional[str] = None,
        lock_timeout: Optional[float] = None
    ):
        """Initialize the game controller.

        Args:
            state_dir: Directory for bridge communication files.
            config_path: Ignored (kept for backwards compatibility).
            timeout: Timeout for waiting on game state/commands.
            project_name: Name of the project for lock identification.
                         If None, lock is only acquired on connect().
            lock_timeout: Maximum seconds to wait for lock (None = wait forever).
        """
        self.state_dir = Path(state_dir)
        self.timeout = timeout
        self.project_name = project_name or "unknown"
        self.lock_timeout = lock_timeout

        # Bridge communication files
        self.state_file = self.state_dir / 'game_state.json'
        self.command_file = self.state_dir / 'command.txt'
        self.ready_file = self.state_dir / 'bridge_ready.txt'

        self._connected = False
        self._last_state: Optional[Dict[str, Any]] = None
        self._lock_context = None
        self._lock_info: Optional[LockInfo] = None
        self._recording_name: Optional[str] = None

    def is_connected(self) -> bool:
        """Check if bridge is ready."""
        return self.ready_file.exists()

    def connect(self) -> bool:
        """Wait for bridge to be ready and acquire exclusive lock.

        The lock ensures only one project can use the bridge at a time.
        Lock is automatically released on disconnect() or process exit.

        Returns:
            True if connection successful.

        Raises:
            CommunicationModError: If bridge not ready within timeout.
            BridgeInUseError: If bridge is locked by another process.
            TimeoutError: If lock cannot be acquired within lock_timeout.
        """
        # First, acquire the lock to ensure exclusive access
        try:
            self._lock_context = bridge_lock(self.project_name, timeout=self.lock_timeout)
            self._lock_info = self._lock_context.__enter__()
            print(f"Acquired bridge lock for '{self.project_name}' (PID {self._lock_info.pid})")
        except TimeoutError as e:
            # Check who holds the lock
            info = get_lock_info()
            raise BridgeInUseError(info) from e

        print(f"Waiting for CommunicationMod bridge at {self.state_dir}...")

        start_time = time.time()
        while time.time() - start_time < self.timeout:
            if self.ready_file.exists():
                self._connected = True
                print("Connected to CommunicationMod bridge")
                return True
            time.sleep(0.1)

        # Failed to connect - release lock
        self._release_lock()

        raise CommunicationModError(
            f"CommunicationMod bridge not ready after {self.timeout}s.\n"
            f"Expected bridge marker at: {self.ready_file}\n\n"
            f"To set up CommunicationMod:\n"
            f"1. Install ModTheSpire: https://github.com/kiooeht/ModTheSpire\n"
            f"2. Install CommunicationMod: https://github.com/ForgottenArbiter/CommunicationMod\n"
            f"3. Edit ~/Library/Preferences/ModTheSpire/CommunicationMod/config.properties:\n"
            f"   command=python {Path(__file__).parent / 'communication_bridge.py'} --state-dir {self.state_dir}\n"
            f"4. Launch Slay the Spire through ModTheSpire\n"
        )

    def disconnect(self):
        """Disconnect from CommunicationMod bridge and release lock."""
        self._connected = False
        self._release_lock()

    def _release_lock(self):
        """Release the bridge lock if held."""
        if self._lock_context:
            try:
                self._lock_context.__exit__(None, None, None)
            except Exception:
                pass
            self._lock_context = None
            self._lock_info = None

    def get_lock_info(self) -> Optional[LockInfo]:
        """Get information about the current lock.

        Returns:
            LockInfo if this controller holds the lock, None otherwise.
        """
        return self._lock_info

    def _wait_for_state_update(self, timeout: Optional[float] = None) -> bool:
        """Wait for the state file to be updated by the bridge.

        Returns:
            True if state was updated, False on timeout.
        """
        if timeout is None:
            timeout = self.timeout

        # Get current modification time
        try:
            old_mtime = self.state_file.stat().st_mtime
        except FileNotFoundError:
            old_mtime = 0

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                new_mtime = self.state_file.stat().st_mtime
                if new_mtime > old_mtime:
                    return True
            except FileNotFoundError:
                pass
            time.sleep(0.05)

        return False

    def get_state(self) -> Dict[str, Any]:
        """Read current game state from bridge.

        Returns:
            Dictionary containing game state with nested game_state flattened.
        """
        if not self._connected:
            raise CommunicationModError("Not connected to CommunicationMod bridge")

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            self._last_state = state

            # Flatten the nested game_state for comparison with simulator
            # CommunicationMod returns: {"available_commands": [...], "game_state": {...}}
            # We want to merge game_state to top level for comparison
            if 'game_state' in state:
                flattened = state.copy()
                flattened.update(state['game_state'])
                return flattened
            return state
        except FileNotFoundError:
            raise CommunicationModError(
                f"State file not found: {self.state_file}\n"
                f"Ensure CommunicationMod is running with the bridge script."
            )
        except json.JSONDecodeError as e:
            raise CommunicationModError(f"Invalid state JSON: {e}")

    def send_command(self, command: str):
        """Send a command to CommunicationMod via the bridge.

        Args:
            command: Command string to send.
        """
        if not self._connected:
            raise CommunicationModError("Not connected to CommunicationMod bridge")

        # Write command to file for bridge to pick up
        with open(self.command_file, 'w') as f:
            f.write(command + '\n')

        # Wait a moment for command to be processed
        time.sleep(0.1)

    def get_seed(self) -> int:
        """Extract seed from game state with proper int64 conversion.

        Returns:
            Signed 64-bit integer seed value.
        """
        # Import here to avoid circular imports
        import sys
        from pathlib import Path
        tests_path = Path(__file__).parent.parent.parent / 'tests' / 'integration' / 'harness'
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))
        from seed_synchronizer import SeedSynchronizer

        state = self.get_state()
        game_state = state.get('game_state', {})
        raw_seed = game_state.get('seed', 0)
        return SeedSynchronizer.convert_seed_to_int64(raw_seed)

    def start_recording(self, name: str, description: str = "") -> None:
        """Start recording gameplay.

        The recording captures game states as they are received from
        CommunicationMod. Call stop_recording() to save the recording.

        Args:
            name: Name for this recording (used as filename).
            description: Optional description of the recording.
        """
        cmd = f"record {name}"
        if description:
            cmd += f" {description}"
        self.send_command(cmd)
        self._recording_name = name

    def stop_recording(self) -> Optional[str]:
        """Stop recording and return recording name.

        Returns:
            Name of the recording that was stopped, or None if not recording.
        """
        if self._recording_name:
            self.send_command("stop_record")
            name = self._recording_name
            self._recording_name = None
            return name
        return None

    def is_recording(self) -> bool:
        """Check if currently recording.

        Returns:
            True if recording is active.
        """
        return self._recording_name is not None

    def get_combat_state(self) -> Optional[Dict[str, Any]]:
        """Get current combat state if in combat.

        Returns:
            Combat state dictionary or None if not in combat.
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return game_state.get('combat_state')

    def play_card(self, card_index: int, target_index: int = -1):
        """Send 'play <idx> [target]' command.

        Args:
            card_index: Index of card in hand to play.
            target_index: Target monster index (-1 for auto-target/untargeted).
        """
        if target_index >= 0:
            command = f"play {card_index} {target_index}"
        else:
            command = f"play {card_index}"
        self.send_command(command)

    def end_turn(self):
        """Send 'end' command to end current turn."""
        self.send_command("end")

    def choose_option(self, option_index: int):
        """Send choice command for events/rewards.

        Args:
            option_index: Index of option to choose.
        """
        self.send_command(f"choose {option_index}")

    def use_potion(self, slot: int, target_index: int = -1):
        """Use a potion.

        Args:
            slot: Potion slot index (0-2 typically).
            target_index: Target for targeted potions (-1 for untargeted).
        """
        if target_index >= 0:
            command = f"potion use {slot} {target_index}"
        else:
            command = f"potion use {slot}"
        self.send_command(command)

    def discard_potion(self, slot: int):
        """Discard a potion.

        Args:
            slot: Potion slot index to discard.
        """
        self.send_command(f"potion discard {slot}")

    def wait(self, frames: int = 1):
        """Wait for specified number of frames.

        Args:
            frames: Number of game frames to wait.
        """
        self.send_command(f"wait {frames}")

    def press_key(self, key: str):
        """Simulate a key press.

        Args:
            key: Key to press (e.g., 'space', 'escape').
        """
        self.send_command(f"key {key}")

    def get_player_hp(self) -> tuple[int, int]:
        """Get current and max HP.

        Returns:
            Tuple of (current_hp, max_hp).
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return (game_state.get('current_hp', 0), game_state.get('max_hp', 0))

    def get_gold(self) -> int:
        """Get current gold amount.

        Returns:
            Current gold.
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return game_state.get('gold', 0)

    def get_floor(self) -> int:
        """Get current floor number.

        Returns:
            Current floor (1-55+).
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return game_state.get('floor', 1)

    def get_act(self) -> int:
        """Get current act number.

        Returns:
            Current act (1-4).
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return game_state.get('act', 1)

    def get_hand(self) -> List[Dict[str, Any]]:
        """Get list of cards in hand.

        Returns:
            List of card dictionaries.
        """
        combat = self.get_combat_state()
        if combat:
            return combat.get('hand', [])
        return []

    def get_monsters(self) -> List[Dict[str, Any]]:
        """Get list of monsters in combat.

        Returns:
            List of monster dictionaries with hp, block, intent, etc.
        """
        combat = self.get_combat_state()
        if combat:
            return combat.get('monsters', [])
        return []

    def is_in_combat(self) -> bool:
        """Check if currently in combat.

        Returns:
            True if in combat, False otherwise.
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        room_phase = game_state.get('room_phase', '')
        return room_phase == 'COMBAT'

    def get_screen_state(self) -> str:
        """Get current screen state.

        Returns:
            Screen state string (e.g., 'combat', 'reward', 'map', 'event').
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        screen_type = game_state.get('screen_type', 'unknown')
        screen_name = game_state.get('screen_name', '')
        room_phase = game_state.get('room_phase', '')

        if room_phase == 'COMBAT':
            return 'combat'
        elif screen_type == 'NONE':
            return 'game'
        else:
            return screen_name.lower() if screen_name else screen_type.lower()

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
