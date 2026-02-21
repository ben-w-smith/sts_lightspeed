"""Interface to real Slay the Spire game via CommunicationMod.

This works with the communication_bridge.py script. Setup:

1. Configure CommunicationMod to run the bridge:
   command=python /path/to/tests/integration/harness/communication_bridge.py --state-dir /tmp/sts_bridge

2. The test runner connects to the bridge via files in the state directory.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional, Dict, Any, List


class CommunicationModError(Exception):
    """Exception raised for CommunicationMod communication errors."""
    pass


class GameController:
    """Interface to real Slay the Spire via CommunicationMod bridge.

    The bridge script (communication_bridge.py) runs as a subprocess of
    CommunicationMod and communicates via files.
    """

    def __init__(
        self,
        state_dir: str = "/tmp/sts_bridge",
        config_path: Optional[str] = None,
        timeout: float = 30.0
    ):
        """Initialize the game controller.

        Args:
            state_dir: Directory for bridge communication files.
            config_path: Ignored (kept for backwards compatibility).
            timeout: Timeout for waiting on game state/commands.
        """
        self.state_dir = Path(state_dir)
        self.timeout = timeout

        # Bridge communication files
        self.state_file = self.state_dir / 'game_state.json'
        self.command_file = self.state_dir / 'command.txt'
        self.ready_file = self.state_dir / 'bridge_ready.txt'

        self._connected = False
        self._last_state: Optional[Dict[str, Any]] = None

    def is_connected(self) -> bool:
        """Check if bridge is ready."""
        return self.ready_file.exists()

    def connect(self) -> bool:
        """Wait for bridge to be ready.

        Returns:
            True if connection successful, False otherwise.
        """
        print(f"Waiting for CommunicationMod bridge at {self.state_dir}...")

        start_time = time.time()
        while time.time() - start_time < self.timeout:
            if self.ready_file.exists():
                self._connected = True
                print("Connected to CommunicationMod bridge")
                return True
            time.sleep(0.1)

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
        """Disconnect from CommunicationMod bridge."""
        self._connected = False

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
            Dictionary containing game state.
        """
        if not self._connected:
            raise CommunicationModError("Not connected to CommunicationMod bridge")

        try:
            with open(self.state_file, 'r') as f:
                state = json.load(f)
            self._last_state = state
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
        """Extract seed from game state.

        Returns:
            Integer seed value.
        """
        state = self.get_state()
        game_state = state.get('game_state', {})
        return game_state.get('seed', 0)

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
