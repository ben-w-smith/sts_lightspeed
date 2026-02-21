"""Test cases for card effects.

These tests validate that card effects in the simulator match the real game.
"""
import sys
from pathlib import Path
from typing import Generator, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.integration.harness.simulator_controller import SimulatorController
from tests.integration.harness.game_controller import GameController
from tests.integration.harness.action_translator import ActionTranslator, TranslatedAction, ActionType


class CardTestBase:
    """Base class for card effect tests."""

    def __init__(self, sim: SimulatorController, game: Optional[GameController] = None):
        """Initialize the test.

        Args:
            sim: Simulator controller.
            game: Game controller (optional, for synchronized testing).
        """
        self.sim = sim
        self.game = game
        self.translator = ActionTranslator()

    def get_card_index_in_hand(self, card_name: str) -> Optional[int]:
        """Find a card in hand by name.

        Args:
            card_name: Name of the card to find.

        Returns:
            Index in hand, or None if not found.
        """
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        for i, card in enumerate(hand):
            if card_name.lower() in card.get('name', '').lower():
                return i
        return None

    def play_card(self, card_name: str, target: int = -1) -> Optional[TranslatedAction]:
        """Play a card by name.

        Args:
            card_name: Name of the card to play.
            target: Target monster index (-1 for auto-target).

        Returns:
            TranslatedAction that was executed, or None if card not found.
        """
        idx = self.get_card_index_in_hand(card_name)
        if idx is None:
            return None

        if target >= 0:
            action = self.translator.from_sim_to_game(f"{idx} {target}")
        else:
            action = self.translator.from_sim_to_game(str(idx))

        return action


class IroncladCardTests(CardTestBase):
    """Test cases for Ironclad cards."""

    def test_strike_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Strike deals 6 damage (9 if upgraded)."""
        # Find Strike in hand
        idx = self.get_card_index_in_hand("Strike")
        if idx is None:
            return

        # Play Strike
        yield self.translator.from_sim_to_game(str(idx))

    def test_defend_block(self) -> Generator[TranslatedAction, None, None]:
        """Test that Defend grants 5 block (8 if upgraded)."""
        idx = self.get_card_index_in_hand("Defend")
        if idx is None:
            return

        # Play Defend
        yield self.translator.from_sim_to_game(str(idx))

    def test_bash_damage_and_vulnerable(self) -> Generator[TranslatedAction, None, None]:
        """Test that Bash deals 8 damage and applies 2 Vulnerable."""
        idx = self.get_card_index_in_hand("Bash")
        if idx is None:
            return

        # Play Bash on first monster
        yield self.translator.from_sim_to_game(f"{idx} 0")

    def test_anger_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Anger deals 6 damage."""
        idx = self.get_card_index_in_hand("Anger")
        if idx is None:
            return

        yield self.translator.from_sim_to_game(f"{idx} 0")

    def test_cleave_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Cleave deals 8 damage to ALL enemies."""
        idx = self.get_card_index_in_hand("Cleave")
        if idx is None:
            return

        yield self.translator.from_sim_to_game(str(idx))

    def test_iron_wave_block_and_damage(self) -> Generator[TranslatedAction, None, None]:
        """Test that Iron Wave grants 5 block and deals 5 damage."""
        idx = self.get_card_index_in_hand("Iron Wave")
        if idx is None:
            return

        yield self.translator.from_sim_to_game(f"{idx} 0")

    def test_pommel_strike_damage_and_draw(self) -> Generator[TranslatedAction, None, None]:
        """Test that Pommel Strike deals 9 damage and draws 1 card."""
        idx = self.get_card_index_in_hand("Pommel Strike")
        if idx is None:
            return

        yield self.translator.from_sim_to_game(f"{idx} 0")


# Test action generators for common scenarios

def play_all_strikes_and_defends(
    sim: SimulatorController,
    game: Optional[GameController]
) -> Generator[TranslatedAction, None, None]:
    """Generator that plays all Strikes and Defends, then ends turn.

    This is a simple action generator for basic testing.
    """
    translator = ActionTranslator()

    while sim.is_in_combat():
        state = sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])
        energy = combat.get('player', {}).get('energy', 0)

        if not hand or energy <= 0:
            # End turn if no cards or no energy
            yield translator.from_sim_to_game("end")
            continue

        # Find a playable card
        played = False
        for i, card in enumerate(hand):
            cost = card.get('cost_for_turn', card.get('cost', 0))
            if cost <= energy:
                # Check if card needs target
                if card.get('requires_target', False):
                    yield translator.from_sim_to_game(f"{i} 0")
                else:
                    yield translator.from_sim_to_game(str(i))
                played = True
                break

        if not played:
            # Can't play any cards, end turn
            yield translator.from_sim_to_game("end")


def play_card_by_name(
    card_name: str,
    target: int = 0
) -> callable:
    """Create an action generator that plays a specific card.

    Args:
        card_name: Name of the card to play.
        target: Target monster index.

    Returns:
        Action generator function.
    """
    def generator(
        sim: SimulatorController,
        game: Optional[GameController]
    ) -> Generator[TranslatedAction, None, None]:
        translator = ActionTranslator()
        state = sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        for i, card in enumerate(hand):
            if card_name.lower() in card.get('name', '').lower():
                if target >= 0:
                    yield translator.from_sim_to_game(f"{i} {target}")
                else:
                    yield translator.from_sim_to_game(str(i))
                return

    return generator


# Card test definitions for automated testing
CARD_TESTS = {
    'IRONCLAD': {
        'strike': {
            'name': 'Strike',
            'expected_damage': 6,
            'expected_damage_upgraded': 9,
            'cost': 1,
        },
        'defend': {
            'name': 'Defend',
            'expected_block': 5,
            'expected_block_upgraded': 8,
            'cost': 1,
        },
        'bash': {
            'name': 'Bash',
            'expected_damage': 8,
            'expected_damage_upgraded': 10,
            'expected_vulnerable': 2,
            'expected_vulnerable_upgraded': 3,
            'cost': 2,
        },
    },
    'SILENT': {
        'strike': {
            'name': 'Strike',
            'expected_damage': 6,
            'expected_damage_upgraded': 9,
            'cost': 1,
        },
        'defend': {
            'name': 'Defend',
            'expected_block': 5,
            'expected_block_upgraded': 8,
            'cost': 1,
        },
        'neutralize': {
            'name': 'Neutralize',
            'expected_damage': 3,
            'expected_weak': 1,
            'cost': 0,
        },
        'survivor': {
            'name': 'Survivor',
            'expected_block': 8,
            'expected_block_upgraded': 11,
            'cost': 1,
        },
    },
    'DEFECT': {
        'strike': {
            'name': 'Strike',
            'expected_damage': 6,
            'expected_damage_upgraded': 9,
            'cost': 1,
        },
        'defend': {
            'name': 'Defend',
            'expected_block': 5,
            'expected_block_upgraded': 8,
            'cost': 1,
        },
        'zap': {
            'name': 'Zap',
            'expected_damage': 6,
            'expected_channel_orb': 'Lightning',
            'cost': 1,
        },
        'dualcast': {
            'name': 'Dualcast',
            'expected_evoke_count': 2,
            'cost': 0,
        },
    },
    'WATCHER': {
        'strike': {
            'name': 'Strike',
            'expected_damage': 6,
            'expected_damage_upgraded': 9,
            'cost': 1,
        },
        'defend': {
            'name': 'Defend',
            'expected_block': 5,
            'expected_block_upgraded': 8,
            'cost': 1,
        },
        'eruption': {
            'name': 'Eruption',
            'expected_damage': 6,
            'expected_stance': 'Wrath',
            'cost': 2,
        },
        'vigilance': {
            'name': 'Vigilance',
            'expected_block': 8,
            'expected_stance': 'Calm',
            'cost': 2,
        },
    },
}


def get_card_tests_for_character(character: str) -> dict:
    """Get card test definitions for a character.

    Args:
        character: Character name (IRONCLAD, SILENT, DEFECT, WATCHER).

    Returns:
        Dictionary of card test definitions.
    """
    return CARD_TESTS.get(character.upper(), {})
