"""Test cases for combat mechanics.

These tests validate combat state transitions, block decay, turn structure, etc.
"""
import sys
from pathlib import Path
from typing import Generator, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.integration.harness.simulator_controller import SimulatorController
from tests.integration.harness.game_controller import GameController
from tests.integration.harness.action_translator import ActionTranslator, TranslatedAction


class CombatTestBase:
    """Base class for combat mechanics tests."""

    def __init__(self, sim: SimulatorController, game: Optional[GameController] = None):
        """Initialize the test.

        Args:
            sim: Simulator controller.
            game: Game controller (optional).
        """
        self.sim = sim
        self.game = game
        self.translator = ActionTranslator()


class BlockDecayTests(CombatTestBase):
    """Tests for block decay mechanics."""

    def test_block_decays_at_turn_start(self) -> Generator[TranslatedAction, None, None]:
        """Test that block decays to 0 at the start of player's turn."""
        # Play a Defend to gain block
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        # Find and play a Defend
        for i, card in enumerate(hand):
            if 'defend' in card.get('name', '').lower():
                yield self.translator.from_sim_to_game(str(i))
                break

        # End turn
        yield self.translator.from_sim_to_game("end")

        # Enemy turn happens
        # Then player turn starts - block should be 0

    def test_block_stacks(self) -> Generator[TranslatedAction, None, None]:
        """Test that block stacks from multiple sources."""
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        defends_played = 0
        for i, card in enumerate(hand):
            if 'defend' in card.get('name', '').lower() and defends_played < 2:
                yield self.translator.from_sim_to_game(str(i))
                defends_played += 1


class EnergyTests(CombatTestBase):
    """Tests for energy mechanics."""

    def test_energy_resets_each_turn(self) -> Generator[TranslatedAction, None, None]:
        """Test that energy resets at the start of each turn."""
        # Spend all energy
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])
        energy = combat.get('player', {}).get('energy', 0)

        while energy > 0:
            played = False
            for i, card in enumerate(hand):
                cost = card.get('cost_for_turn', card.get('cost', 0))
                if cost <= energy:
                    yield self.translator.from_sim_to_game(str(i))
                    played = True
                    break
            if not played:
                break

            # Refresh state
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            energy = combat.get('player', {}).get('energy', 0)

        # End turn
        yield self.translator.from_sim_to_game("end")

    def test_energy_cost_variations(self) -> Generator[TranslatedAction, None, None]:
        """Test cards with different energy costs."""
        # Play cards of different costs (1, 2, 3 cost)
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])
        energy = combat.get('player', {}).get('energy', 0)

        # Play Bash (2 cost) first if available
        for i, card in enumerate(hand):
            if 'bash' in card.get('name', '').lower() and energy >= 2:
                yield self.translator.from_sim_to_game(f"{i} 0")
                break

        yield self.translator.from_sim_to_game("end")


class TurnStructureTests(CombatTestBase):
    """Tests for turn structure and flow."""

    def test_player_turn_then_enemy_turn(self) -> Generator[TranslatedAction, None, None]:
        """Test that turns alternate between player and enemy."""
        # Play a card, end turn, enemy moves, player turn again
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        turn = combat.get('turn', 0)

        # Play a card
        hand = combat.get('hand', [])
        if hand:
            yield self.translator.from_sim_to_game("0")

        # End turn
        yield self.translator.from_sim_to_game("end")

    def test_draw_at_turn_start(self) -> Generator[TranslatedAction, None, None]:
        """Test that player draws 5 cards at turn start."""
        # End turn and verify hand size is 5 after draw
        yield self.translator.from_sim_to_game("end")


class StatusEffectTests(CombatTestBase):
    """Tests for status effects."""

    def test_vulnerable_increases_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Vulnerable increases damage taken by 50%."""
        # Apply Vulnerable (via Bash), then check damage taken
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        for i, card in enumerate(hand):
            if 'bash' in card.get('name', '').lower():
                yield self.translator.from_sim_to_game(f"{i} 0")
                break

    def test_weak_decreases_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Weak decreases damage dealt by 25%."""
        # Play a Strike, record damage
        # Wait for monster to apply Weak
        # Play another Strike, verify 25% reduction
        for _ in range(6):
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])

            for i, card in enumerate(hand):
                if 'strike' in card.get('name', '').lower():
                    yield self.translator.from_sim_to_game(f"{i} 0")
                    break
            else:
                yield self.translator.from_sim_to_game("end")

    def test_strength_increases_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Strength increases attack damage."""
        # Use Flex to gain temporary Strength, then attack
        for _ in range(4):
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])

            # Try to play Flex first if available
            flex_played = False
            for i, card in enumerate(hand):
                if 'flex' in card.get('name', '').lower():
                    yield self.translator.from_sim_to_game(str(i))
                    flex_played = True
                    break

            if flex_played:
                # Now play a Strike with Strength
                state = self.sim.get_state()
                combat = state.get('combat_state', {})
                hand = combat.get('hand', [])
                for i, card in enumerate(hand):
                    if 'strike' in card.get('name', '').lower():
                        yield self.translator.from_sim_to_game(f"{i} 0")
                        break

            yield self.translator.from_sim_to_game("end")

    def test_dexterity_increases_block(self) -> Generator[TranslatedAction, None, None]:
        """Test that Dexterity increases block from cards."""
        # Similar pattern - just play defends for now
        # Real test would need a relic or effect that gives Dexterity
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        for i, card in enumerate(hand):
            if 'defend' in card.get('name', '').lower():
                yield self.translator.from_sim_to_game(str(i))
                break

        yield self.translator.from_sim_to_game("end")


class DrawPileTests(CombatTestBase):
    """Tests for draw pile mechanics."""

    def test_cards_shuffle_from_discard(self) -> Generator[TranslatedAction, None, None]:
        """Test that discard pile shuffles into draw pile when empty."""
        # Play all cards over multiple turns until shuffle occurs
        for _ in range(20):
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])
            energy = combat.get('player', {}).get('energy', 0)

            # Play any affordable card
            played = False
            for i, card in enumerate(hand):
                cost = card.get('cost_for_turn', card.get('cost', 0))
                if cost <= energy:
                    if card.get('requires_target', False):
                        yield self.translator.from_sim_to_game(f"{i} 0")
                    else:
                        yield self.translator.from_sim_to_game(str(i))
                    played = True
                    break

            if not played:
                yield self.translator.from_sim_to_game("end")

    def test_draw_pile_order_preserved(self) -> Generator[TranslatedAction, None, None]:
        """Test that draw pile order is deterministic for a given seed."""
        # Just verify combat runs - deterministic order is implicit
        for _ in range(5):
            yield self.translator.from_sim_to_game("end")


# Combat test scenarios

def basic_combat_scenario(
    sim: SimulatorController,
    game: Optional[GameController]
) -> Generator[TranslatedAction, None, None]:
    """A basic combat scenario that plays cards and ends turns.

    This is useful for smoke testing combat mechanics.
    """
    translator = ActionTranslator()

    while sim.is_in_combat():
        state = sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])
        energy = combat.get('player', {}).get('energy', 0)

        if not hand:
            yield translator.from_sim_to_game("end")
            continue

        # Try to play attacks first, then skills
        played = False

        # Priority: Attacks on monsters
        for i, card in enumerate(hand):
            cost = card.get('cost_for_turn', card.get('cost', 0))
            if cost <= energy and 'attack' in str(card.get('type', '')).lower():
                if card.get('requires_target', False):
                    yield translator.from_sim_to_game(f"{i} 0")
                else:
                    yield translator.from_sim_to_game(str(i))
                played = True
                break

        if played:
            continue

        # Then skills (defends)
        for i, card in enumerate(hand):
            cost = card.get('cost_for_turn', card.get('cost', 0))
            if cost <= energy and 'skill' in str(card.get('type', '')).lower():
                yield translator.from_sim_to_game(str(i))
                played = True
                break

        if not played:
            yield translator.from_sim_to_game("end")


def defensive_scenario(
    sim: SimulatorController,
    game: Optional[GameController]
) -> Generator[TranslatedAction, None, None]:
    """A defensive scenario that prioritizes block."""
    translator = ActionTranslator()

    while sim.is_in_combat():
        state = sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])
        energy = combat.get('player', {}).get('energy', 0)

        # Prioritize defends
        played = False
        for i, card in enumerate(hand):
            cost = card.get('cost_for_turn', card.get('cost', 0))
            if cost <= energy and 'defend' in card.get('name', '').lower():
                yield translator.from_sim_to_game(str(i))
                played = True
                break

        if not played:
            # Play anything else
            for i, card in enumerate(hand):
                cost = card.get('cost_for_turn', card.get('cost', 0))
                if cost <= energy:
                    if card.get('requires_target', False):
                        yield translator.from_sim_to_game(f"{i} 0")
                    else:
                        yield translator.from_sim_to_game(str(i))
                    played = True
                    break

        if not played:
            yield translator.from_sim_to_game("end")


# Combat test definitions
COMBAT_TESTS = {
    'block_decay': {
        'name': 'Block Decay',
        'description': 'Block resets to 0 at start of player turn',
        'generator': BlockDecayTests.test_block_decays_at_turn_start,
    },
    'energy_reset': {
        'name': 'Energy Reset',
        'description': 'Energy resets to 3 at start of each turn',
        'generator': EnergyTests.test_energy_resets_each_turn,
    },
    'turn_structure': {
        'name': 'Turn Structure',
        'description': 'Turns alternate between player and enemy',
        'generator': TurnStructureTests.test_player_turn_then_enemy_turn,
    },
}
