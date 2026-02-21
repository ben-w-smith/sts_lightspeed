"""RNG seed synchronization between game and simulator.

This module handles synchronizing the random number generator seeds between
the real Slay the Spire game (via CommunicationMod) and the sts_lightspeed
simulator.

Key Challenge: CommunicationMod does NOT provide a command to set seed.
Sync works by:
1. Start new game in real game
2. Read seed from CommunicationMod state
3. Initialize simulator with same seed
"""
import struct
from typing import Optional, Tuple

from .game_controller import GameController
from .simulator_controller import SimulatorController


class SeedSynchronizationError(Exception):
    """Exception raised when seed synchronization fails."""
    pass


class SeedSynchronizer:
    """Handles RNG seed synchronization between game and simulator.

    The game uses a 64-bit seed internally but may represent it differently
    in CommunicationMod output. This class handles the conversion.
    """

    @staticmethod
    def convert_seed_to_int64(seed_value) -> int:
        """Convert seed value to signed 64-bit integer.

        CommunicationMod may return seed as:
        - Integer (may be unsigned)
        - String representation
        - Float (if JSON parsing went wrong)

        Args:
            seed_value: Seed value from CommunicationMod.

        Returns:
            Signed 64-bit integer seed.
        """
        if isinstance(seed_value, int):
            # Handle unsigned to signed conversion if needed
            if seed_value > 0x7FFFFFFFFFFFFFFF:
                # Convert from unsigned to signed
                return seed_value - 0x10000000000000000
            return seed_value

        if isinstance(seed_value, str):
            # Try parsing as integer
            try:
                val = int(seed_value)
                if val > 0x7FFFFFFFFFFFFFFF:
                    return val - 0x10000000000000000
                return val
            except ValueError:
                raise SeedSynchronizationError(
                    f"Cannot parse seed string: {seed_value}"
                )

        if isinstance(seed_value, float):
            # Might be from JSON number handling
            return int(seed_value)

        raise SeedSynchronizationError(
            f"Unknown seed type: {type(seed_value)} value={seed_value}"
        )

    @staticmethod
    def convert_seed_to_unsigned(seed: int) -> int:
        """Convert signed 64-bit seed to unsigned representation.

        Args:
            seed: Signed 64-bit integer seed.

        Returns:
            Unsigned 64-bit representation.
        """
        if seed < 0:
            return seed + 0x10000000000000000
        return seed

    @staticmethod
    def seed_to_string(seed: int) -> str:
        """Convert seed to human-readable string format.

        The game displays seeds as alphanumeric strings, but internally
        uses 64-bit integers.

        Args:
            seed: Integer seed value.

        Returns:
            String representation.
        """
        # Game uses a specific base conversion for display
        # For now, just return hex representation
        unsigned = SeedSynchronizer.convert_seed_to_unsigned(seed)
        return f"{unsigned:X}"

    @staticmethod
    def string_to_seed(seed_string: str) -> int:
        """Convert human-readable seed string to integer.

        Args:
            seed_string: String representation of seed.

        Returns:
            Integer seed value.
        """
        try:
            # Try hex first (our format)
            return int(seed_string, 16)
        except ValueError:
            pass

        # Try decimal
        try:
            return int(seed_string)
        except ValueError:
            raise SeedSynchronizationError(
                f"Cannot parse seed string: {seed_string}"
            )

    def get_game_seed(self, game_controller: GameController) -> Tuple[int, str]:
        """Extract seed from the real game.

        Args:
            game_controller: Connected GameController instance.

        Returns:
            Tuple of (integer_seed, seed_string).
        """
        state = game_controller.get_state()
        game_state = state.get('game_state', state)

        # Try different possible locations for seed
        seed_value = None

        # Direct seed field
        if 'seed' in game_state:
            seed_value = game_state['seed']
        elif 'seed_value' in game_state:
            seed_value = game_state['seed_value']
        elif 'rng_seed' in game_state:
            seed_value = game_state['rng_seed']

        if seed_value is None:
            raise SeedSynchronizationError(
                "Could not find seed in game state. "
                "Ensure CommunicationMod is properly connected."
            )

        int_seed = self.convert_seed_to_int64(seed_value)
        str_seed = self.seed_to_string(int_seed)

        return int_seed, str_seed

    def init_sim_with_game_seed(
        self,
        simulator: SimulatorController,
        game_controller: GameController,
        character: str = 'IRONCLAD',
        ascension: int = 0
    ) -> Tuple[int, str]:
        """Initialize simulator with seed from the real game.

        Args:
            simulator: SimulatorController instance.
            game_controller: Connected GameController instance.
            character: Character class to initialize.
            ascension: Ascension level.

        Returns:
            Tuple of (integer_seed, seed_string).
        """
        int_seed, str_seed = self.get_game_seed(game_controller)

        # Initialize simulator with same parameters
        simulator.setup_game(int_seed, character, ascension)

        return int_seed, str_seed

    def verify_seed_match(
        self,
        game_state: dict,
        sim_state: dict
    ) -> bool:
        """Verify that seeds match between game and simulator.

        Args:
            game_state: State from game controller.
            sim_state: State from simulator.

        Returns:
            True if seeds match, False otherwise.
        """
        game_seed = game_state.get('seed')
        sim_seed = sim_state.get('seed')

        if game_seed is None or sim_seed is None:
            return False

        # Normalize both to signed int64
        try:
            game_int = self.convert_seed_to_int64(game_seed)
            sim_int = self.convert_seed_to_int64(sim_seed)
            return game_int == sim_int
        except SeedSynchronizationError:
            return False

    def sync_from_game(
        self,
        simulator: SimulatorController,
        game_controller: GameController,
        character: str = 'IRONCLAD',
        ascension: int = 0
    ) -> dict:
        """Full synchronization from game to simulator.

        This is the main entry point for seed synchronization.
        It reads the game state, extracts the seed, and initializes
        the simulator with matching parameters.

        Args:
            simulator: SimulatorController instance.
            game_controller: Connected GameController instance.
            character: Character class.
            ascension: Ascension level.

        Returns:
            Dictionary with sync information:
            - seed: Integer seed
            - seed_string: Human-readable seed
            - character: Character class
            - ascension: Ascension level
            - verified: Whether verification passed
        """
        int_seed, str_seed = self.init_sim_with_game_seed(
            simulator, game_controller, character, ascension
        )

        # Verify the sync worked
        game_state = game_controller.get_state()
        sim_state = simulator.get_state()
        verified = self.verify_seed_match(game_state, sim_state)

        return {
            'seed': int_seed,
            'seed_string': str_seed,
            'character': character,
            'ascension': ascension,
            'verified': verified
        }


def create_synchronizer() -> SeedSynchronizer:
    """Factory function to create a SeedSynchronizer.

    Returns:
        New SeedSynchronizer instance.
    """
    return SeedSynchronizer()
