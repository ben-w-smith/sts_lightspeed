"""Interface to sts_lightspeed simulator via pybind11 bindings."""
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add build directory to path for the slaythespire module
build_dir = Path(__file__).parent.parent.parent / "build"
if str(build_dir) not in sys.path:
    sys.path.insert(0, str(build_dir))

try:
    import slaythespire as sts
except ImportError as e:
    raise ImportError(
        f"Could not import slaythespire module. "
        f"Ensure the module is built and available at: {build_dir}\n"
        f"Run 'cmake --build build' from the project root."
    ) from e


class SimulatorController:
    """Interface to sts_lightspeed via pybind11 bindings.

    This wraps the ConsoleSimulator and provides a clean API for
    synchronized testing with the real game.
    """

    # Character class mapping
    CHARACTER_MAP = {
        'IRONCLAD': sts.CharacterClass.IRONCLAD,
        'SILENT': sts.CharacterClass.SILENT,
        'DEFECT': sts.CharacterClass.DEFECT,
        'WATCHER': sts.CharacterClass.WATCHER,
    }

    # Screen state mapping
    SCREEN_STATE_MAP = {
        sts.ScreenState.INVALID: 'invalid',
        sts.ScreenState.EVENT_SCREEN: 'event',
        sts.ScreenState.REWARDS: 'reward',
        sts.ScreenState.BOSS_RELIC_REWARDS: 'boss_relic_reward',
        sts.ScreenState.CARD_SELECT: 'card_select',
        sts.ScreenState.MAP_SCREEN: 'map',
        sts.ScreenState.TREASURE_ROOM: 'treasure',
        sts.ScreenState.REST_ROOM: 'rest',
        sts.ScreenState.SHOP_ROOM: 'shop',
        sts.ScreenState.BATTLE: 'combat',
    }

    def __init__(self):
        """Initialize the simulator controller."""
        self.simulator = sts.ConsoleSimulator()
        self._gc = None
        self._battle_ctx = None
        self._initialized = False

    def setup_game(self, seed: int, character: str = 'IRONCLAD', ascension: int = 0):
        """Initialize with same parameters as real game.

        Args:
            seed: Game seed (integer).
            character: Character class ('IRONCLAD', 'SILENT', 'DEFECT', 'WATCHER').
            ascension: Ascension level (0-20).
        """
        char_class = self.CHARACTER_MAP.get(character.upper())
        if char_class is None:
            raise ValueError(f"Unknown character: {character}")

        self.simulator.setup_game(seed, char_class, ascension)
        self._gc = self.simulator.gc
        self._initialized = True

    def sync_from_game(self, game_controller: 'GameController') -> dict:
        """Synchronize simulator state from the real game.

        Reads the game state, extracts seed and parameters, and initializes
        the simulator to match.

        Args:
            game_controller: Connected GameController instance.

        Returns:
            Dictionary with sync information (seed, character, ascension, verified).

        Raises:
            SeedSynchronizationError: If synchronization fails.
        """
        # Import here to avoid circular imports
        import sys
        from pathlib import Path
        tests_path = Path(__file__).parent.parent.parent / 'tests' / 'integration' / 'harness'
        if str(tests_path) not in sys.path:
            sys.path.insert(0, str(tests_path))
        from seed_synchronizer import SeedSynchronizer, SeedSynchronizationError

        synchronizer = SeedSynchronizer()
        return synchronizer.sync_from_game(
            simulator=self,
            game_controller=game_controller
        )

    def take_action(self, action: str):
        """Execute ConsoleSimulator command.

        Args:
            action: Action string (e.g., '0', 'end', 'drink 0', 'card 0 1').
        """
        if not self._initialized:
            raise RuntimeError("Simulator not initialized. Call setup_game first.")

        self.simulator.take_action(action)
        # Refresh references after action
        self._gc = self.simulator.gc

    def get_state(self) -> Dict[str, Any]:
        """Extract state as comparable dictionary.

        Returns:
            Dictionary containing game state.
        """
        if not self._initialized or self._gc is None:
            return {}

        state = {
            'seed': self._gc.seed,
            'floor': self._gc.floor_num,
            'act': self._gc.act,
            'screen_state': self.SCREEN_STATE_MAP.get(
                self._gc.screen_state, 'unknown'
            ),
            'cur_hp': self._gc.cur_hp,
            'max_hp': self._gc.max_hp,
            'gold': self._gc.gold,
            'deck': self._get_deck_state(),
            'relics': self._get_relics_state(),
            'potions': self._get_potions_state(),
        }

        # Add combat state if in battle
        if self._gc.screen_state == sts.ScreenState.BATTLE:
            state['combat_state'] = self._get_combat_state()

        return state

    def _get_deck_state(self) -> List[Dict[str, Any]]:
        """Get deck state as list of card dictionaries."""
        if self._gc is None:
            return []

        deck = []
        for card in self._gc.deck:
            deck.append({
                'id': str(card.id),
                'name': repr(card),
                'upgraded': card.upgraded,
            })
        return deck

    def _get_relics_state(self) -> List[Dict[str, Any]]:
        """Get relics state as list of relic dictionaries."""
        if self._gc is None:
            return []

        relics = []
        for relic in self._gc.relics:
            relics.append({
                'id': str(relic.id),
            })
        return relics

    def _get_potions_state(self) -> List[Dict[str, Any]]:
        """Get potions state as list of potion dictionaries."""
        if self._gc is None:
            return []

        potions = []
        try:
            # Note: Potion enum may not be fully bound, so we catch errors
            for i in range(self._gc.potion_count):
                try:
                    potion = self._gc.potions[i]
                    if str(potion) != 'INVALID':
                        potions.append({'id': str(potion), 'slot': i})
                except (TypeError, AttributeError):
                    pass
        except (TypeError, AttributeError):
            pass
        return potions

    def _get_combat_state(self) -> Dict[str, Any]:
        """Get combat state if in battle."""
        bc = self.simulator.battle_ctx
        if bc is None:
            return {}

        combat = {
            'turn': bc.turn,
            'player': {
                'cur_hp': bc.player.cur_hp,
                'max_hp': bc.player.max_hp,
                'block': bc.player.block,
                'energy': bc.player.energy,
            },
            'monsters': [],
            'hand': [],
            'draw_pile': [],
            'discard_pile': [],
        }

        # Get monster states
        for i, monster in enumerate(bc.monsters.arr):
            if not monster.is_dead_or_escaped():
                combat['monsters'].append({
                    'index': i,
                    'cur_hp': monster.cur_hp,
                    'max_hp': monster.max_hp,
                    'block': monster.block,
                    'intent': monster.intent,
                    'is_dying': monster.is_dying(),
                    'is_targetable': monster.is_targetable(),
                })

        # Get hand cards
        for card in bc.cards.hand:
            combat['hand'].append({
                'id': str(card.id),
                'name': card.name,
                'cost': card.cost,
                'cost_for_turn': card.cost_for_turn,
                'unique_id': card.unique_id,
                'is_upgraded': card.is_upgraded(),
                'requires_target': card.requires_target(),
            })

        # Get draw pile
        for card in bc.cards.draw_pile:
            combat['draw_pile'].append({
                'id': str(card.id),
                'name': card.name,
            })

        # Get discard pile
        for card in bc.cards.discard_pile:
            combat['discard_pile'].append({
                'id': str(card.id),
                'name': card.name,
            })

        return combat

    def get_screen_text(self) -> str:
        """Get the current screen text output.

        Returns:
            String representation of current available actions.
        """
        return self.simulator.get_screen_text()

    def get_seed(self) -> int:
        """Get the current game seed.

        Returns:
            Integer seed value.
        """
        if self._gc is None:
            return 0
        return self._gc.seed

    def get_player_hp(self) -> tuple[int, int]:
        """Get current and max HP.

        Returns:
            Tuple of (current_hp, max_hp).
        """
        if self._gc is None:
            return (0, 0)
        return (self._gc.cur_hp, self._gc.max_hp)

    def get_gold(self) -> int:
        """Get current gold.

        Returns:
            Current gold amount.
        """
        if self._gc is None:
            return 0
        return self._gc.gold

    def get_floor(self) -> int:
        """Get current floor number.

        Returns:
            Current floor.
        """
        if self._gc is None:
            return 1
        return self._gc.floor_num

    def get_act(self) -> int:
        """Get current act.

        Returns:
            Current act (1-4).
        """
        if self._gc is None:
            return 1
        return self._gc.act

    def is_in_combat(self) -> bool:
        """Check if currently in combat.

        Returns:
            True if in combat.
        """
        if self._gc is None:
            return False
        return self._gc.screen_state == sts.ScreenState.BATTLE

    def get_screen_state(self) -> str:
        """Get current screen state.

        Returns:
            Screen state string.
        """
        if self._gc is None:
            return 'invalid'
        return self.SCREEN_STATE_MAP.get(self._gc.screen_state, 'unknown')

    def play_card(self, card_index: int, target_index: int = -1):
        """Play a card from hand.

        Args:
            card_index: Index of card in hand.
            target_index: Target monster index (-1 for auto-target).
        """
        if target_index >= 0:
            self.take_action(f"{card_index} {target_index}")
        else:
            self.take_action(str(card_index))

    def end_turn(self):
        """End the current turn."""
        self.take_action("end")

    def use_potion(self, slot: int, target_index: int = -1):
        """Use a potion.

        Args:
            slot: Potion slot index.
            target_index: Target for targeted potions.
        """
        if target_index >= 0:
            self.take_action(f"drink {slot} {target_index}")
        else:
            self.take_action(f"drink {slot}")

    def discard_potion(self, slot: int):
        """Discard a potion.

        Args:
            slot: Potion slot to discard.
        """
        self.take_action(f"discard potion {slot}")

    def choose_option(self, option_index: int):
        """Choose an option (for events, rewards, etc.).

        Args:
            option_index: Index of option to choose.
        """
        self.take_action(str(option_index))

    def get_available_actions(self) -> List[str]:
        """Get list of available actions for current state.

        Returns:
            List of action strings.
        """
        # Parse screen text to extract available actions
        text = self.get_screen_text()
        actions = []
        for line in text.split('\n'):
            line = line.strip()
            if ':' in line:
                # Format is typically "0: action description"
                parts = line.split(':', 1)
                if parts[0].strip().isdigit():
                    actions.append(parts[0].strip())
        return actions

    def reset(self):
        """Reset the simulator."""
        self.simulator.reset()
        self._gc = None
        self._battle_ctx = None
        self._initialized = False
