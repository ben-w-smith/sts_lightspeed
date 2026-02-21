"""Test cases for monster AI and behavior.

These tests validate that monster AI in the simulator matches the real game.
"""
import sys
from pathlib import Path
from typing import Generator, Optional, Dict, Any, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from tests.integration.harness.simulator_controller import SimulatorController
from tests.integration.harness.game_controller import GameController
from tests.integration.harness.action_translator import ActionTranslator, TranslatedAction


class MonsterTestBase:
    """Base class for monster AI tests."""

    def __init__(self, sim: SimulatorController, game: Optional[GameController] = None):
        """Initialize the test.

        Args:
            sim: Simulator controller.
            game: Game controller (optional).
        """
        self.sim = sim
        self.game = game
        self.translator = ActionTranslator()

    def get_monster_state(self, index: int = 0) -> Dict[str, Any]:
        """Get state of a specific monster.

        Args:
            index: Monster index.

        Returns:
            Monster state dictionary.
        """
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        monsters = combat.get('monsters', [])

        if index < len(monsters):
            return monsters[index]
        return {}

    def get_monster_intent(self, index: int = 0) -> int:
        """Get the intent of a monster.

        Args:
            index: Monster index.

        Returns:
            Intent value.
        """
        monster = self.get_monster_state(index)
        return monster.get('intent', 0)

    def get_monster_hp(self, index: int = 0) -> tuple[int, int]:
        """Get current and max HP of a monster.

        Args:
            index: Monster index.

        Returns:
            Tuple of (current_hp, max_hp).
        """
        monster = self.get_monster_state(index)
        return (monster.get('cur_hp', 0), monster.get('max_hp', 0))


class CultistTests(MonsterTestBase):
    """Tests for Cultist monster AI.

    Cultist AI pattern:
    - Turn 1: Incantation (gains 3 Ritual)
    - Turn 2+: Ritual Strike (deals 6 damage, gains Ritual from Ritual stacks)
    """

    def test_incantation_first_turn(self) -> Generator[TranslatedAction, None, None]:
        """Test that Cultist uses Incantation on first turn."""
        # End turn to see Cultist action
        yield self.translator.from_sim_to_game("end")

    def test_ritual_strike_subsequent_turns(self) -> Generator[TranslatedAction, None, None]:
        """Test that Cultist uses Ritual Strike after first turn."""
        # End first turn (Incantation)
        yield self.translator.from_sim_to_game("end")

        # End second turn (should be Ritual Strike)
        yield self.translator.from_sim_to_game("end")

    def test_ritual_stacks_strength(self) -> Generator[TranslatedAction, None, None]:
        """Test that Ritual stacks increase Cultist's strength."""
        # Play multiple turns and check damage increase
        for _ in range(5):
            yield self.translator.from_sim_to_game("end")


class JawWormTests(MonsterTestBase):
    """Tests for Jaw Worm monster AI.

    Jaw Worm moveset:
    - Chomp: Deal 11 damage
    - Thrash: Deal 7 damage, gain 5 block
    - Bellow: Gain 2 Strength, gain 6 block
    """

    def test_jaw_worm_moveset(self) -> Generator[TranslatedAction, None, None]:
        """Test that Jaw Worm uses valid moves from its moveset."""
        # Observe multiple turns
        for _ in range(10):
            yield self.translator.from_sim_to_game("end")

    def test_jaw_worm_block_gained(self) -> Generator[TranslatedAction, None, None]:
        """Test that Jaw Worm gains block when using Thrash or Bellow."""
        yield self.translator.from_sim_to_game("end")


class LouseTests(MonsterTestBase):
    """Tests for Louse monster AI.

    Louse (Red/Green) behavior:
    - Accumulates strength when taking damage
    - Bite: Deal damage based on accumulated strength
    - Spittle Web: Apply Weak
    """

    def test_louse_accumulates_strength(self) -> Generator[TranslatedAction, None, None]:
        """Test that Louse gains strength when damaged."""
        # Attack the louse multiple times
        state = self.sim.get_state()
        combat = state.get('combat_state', {})
        hand = combat.get('hand', [])

        for i, card in enumerate(hand):
            if 'strike' in card.get('name', '').lower():
                yield self.translator.from_sim_to_game(f"{i} 0")
                break

        yield self.translator.from_sim_to_game("end")

    def test_louse_spittle_web(self) -> Generator[TranslatedAction, None, None]:
        """Test that Louse can apply Weak with Spittle Web."""
        for _ in range(5):
            yield self.translator.from_sim_to_game("end")


class SlimeTests(MonsterTestBase):
    """Tests for Slime monsters.

    Spike Slime behavior:
    - Flame Tackle: Deal damage, add Slimed to discard
    - Lick: Apply Weak

    Acid Slime behavior:
    - Corrosive Spit: Deal damage, apply Acid
    - Lick: Apply Weak
    """

    def test_spike_slime_flame_tackle(self) -> Generator[TranslatedAction, None, None]:
        """Test that Spike Slime adds Slimed with Flame Tackle."""
        yield self.translator.from_sim_to_game("end")

    def test_acid_slime_corrosive_spit(self) -> Generator[TranslatedAction, None, None]:
        """Test that Acid Slime applies Acid."""
        yield self.translator.from_sim_to_game("end")


class GremlinTests(MonsterTestBase):
    """Tests for Gremlin monsters in Gremlin Gang encounter."""

    def test_gremlin_fat_gremlin(self) -> Generator[TranslatedAction, None, None]:
        """Test Fat Gremlin applies Weak."""
        yield self.translator.from_sim_to_game("end")

    def test_gremlin_mad_gremlin(self) -> Generator[TranslatedAction, None, None]:
        """Test Mad Gremlin gains Strength when damaged."""
        yield self.translator.from_sim_to_game("end")

    def test_gremlin_shield_gremlin(self) -> Generator[TranslatedAction, None, None]:
        """Test Shield Gremlin gives block to other gremlins."""
        yield self.translator.from_sim_to_game("end")


class EliteMonsterTests(MonsterTestBase):
    """Tests for elite monsters."""

    def test_gremlin_nob_angular(self) -> Generator[TranslatedAction, None, None]:
        """Test Gremlin Nob uses Angering/Skull Bash."""
        # Nob always uses Bellow first turn
        yield self.translator.from_sim_to_game("end")

        # Then uses attacks, gaining strength when skills are played
        yield self.translator.from_sim_to_game("end")

    def test_lagavulin_sleep(self) -> Generator[TranslatedAction, None, None]:
        """Test Lagavulin starts asleep and wakes up."""
        # First two turns: asleep
        yield self.translator.from_sim_to_game("end")
        yield self.translator.from_sim_to_game("end")

        # Third turn: awake and attacks
        yield self.translator.from_sim_to_game("end")


class BossMonsterTests(MonsterTestBase):
    """Tests for boss monsters."""

    def test_slime_boss_split(self) -> Generator[TranslatedAction, None, None]:
        """Test Slime Boss splits into two Large Slimes at half HP."""
        # Attack Slime Boss until split occurs
        for _ in range(15):  # Multiple attacks to reach half HP
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])

            for i, card in enumerate(hand):
                if 'strike' in card.get('name', '').lower():
                    yield self.translator.from_sim_to_game(f"{i} 0")
                    break
            else:
                yield self.translator.from_sim_to_game("end")

    def test_hexaghost_cycle(self) -> Generator[TranslatedAction, None, None]:
        """Test Hexaghost follows its attack cycle."""
        # Observe full cycle: Activate -> Divider -> etc.
        # 7-turn cycle
        for _ in range(8):
            yield self.translator.from_sim_to_game("end")

    def test_guardian_defensive_mode(self) -> Generator[TranslatedAction, None, None]:
        """Test Guardian switches to Defensive Mode."""
        # Attack Guardian to trigger mode switch
        for _ in range(10):
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])

            for i, card in enumerate(hand):
                if 'strike' in card.get('name', '').lower():
                    yield self.translator.from_sim_to_game(f"{i} 0")
                    break
            else:
                yield self.translator.from_sim_to_game("end")


# Monster test definitions
MONSTER_TESTS = {
    'cultist': {
        'name': 'Cultist',
        'encounter': 'CULTIST',
        'description': 'Tests Cultist ritual mechanic',
        'generator': CultistTests.test_incantation_first_turn,
    },
    'jaw_worm': {
        'name': 'Jaw Worm',
        'encounter': 'JAW_WORM',
        'description': 'Tests Jaw Worm moveset',
        'generator': JawWormTests.test_jaw_worm_moveset,
    },
    'louse': {
        'name': 'Louse',
        'encounter': 'TWO_LOUSE',
        'description': 'Tests Louse strength accumulation',
        'generator': LouseTests.test_louse_accumulates_strength,
    },
    'slimes': {
        'name': 'Slimes',
        'encounter': 'SMALL_SLIMES',
        'description': 'Tests Slime behaviors',
        'generator': SlimeTests.test_spike_slime_flame_tackle,
    },
}


def get_monster_test_generator(monster_name: str):
    """Get a test generator for a specific monster.

    Args:
        monster_name: Name of the monster to test.

    Returns:
        Generator function for the monster test.
    """
    test_def = MONSTER_TESTS.get(monster_name.lower())
    if test_def:
        return test_def['generator']
    return None


# Encounter to monster mapping
ENCOUNTER_MONSTERS = {
    'CULTIST': ['Cultist'],
    'JAW_WORM': ['Jaw Worm'],
    'TWO_LOUSE': ['Louse', 'Louse'],
    'THREE_LOUSE': ['Louse', 'Louse', 'Louse'],
    'SMALL_SLIMES': ['Spike Slime', 'Acid Slime'],
    'LARGE_SLIME': ['Spike Slime (L)'],
    'LOTS_OF_SLIMES': ['Spike Slime (L)', 'Spike Slime (L)'],
    'BLUE_SLAVER': ['Blue Slaver'],
    'RED_SLAVER': ['Red Slaver'],
    'GREMLIN_GANG': ['Fat Gremlin', 'Mad Gremlin', 'Shield Gremlin', 'Sneaky Gremlin', 'Gremlin Wizard'],
    'LOOTER': ['Looter'],
    'EXORDIUM_THUGS': ['Looter', 'Mugger'],
    'EXORDIUM_WILDLIFE': ['Fungi Beast', 'Louse'],
    'TWO_FUNGI_BEASTS': ['Fungi Beast', 'Fungi Beast'],
    # Elites
    'GREMLIN_NOB': ['Gremlin Nob'],
    'LAGAVULIN': ['Lagavulin'],
    'THREE_SENTRIES': ['Sentry', 'Sentry', 'Sentry'],
    # Bosses
    'SLIME_BOSS': ['Slime Boss'],
    'THE_GUARDIAN': ['The Guardian'],
    'HEXAGHOST': ['Hexaghost'],
}
