"""Test assertion helpers for state comparison.

This module provides assertion functions for comparing game states
between the real game and simulator. Each assertion returns an
AssertionResult with detailed information about the comparison.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class AssertionStatus(Enum):
    """Status of an assertion result."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class AssertionResult:
    """Result of a single assertion check."""
    assertion_type: str
    status: AssertionStatus
    message: str = ""
    expected: Any = None
    actual: Any = None
    tolerance: float = 0.0
    delta: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if assertion passed."""
        return self.status == AssertionStatus.PASSED

    @property
    def failed(self) -> bool:
        """Check if assertion failed."""
        return self.status == AssertionStatus.FAILED

    def __str__(self) -> str:
        """String representation."""
        status_str = self.status.value.upper()
        if self.passed:
            return f"[{status_str}] {self.assertion_type}"
        return f"[{status_str}] {self.assertion_type}: {self.message}"


class TestAssertions:
    """Collection of assertion helpers for state comparison."""

    @staticmethod
    def assert_hp_match(
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        entity_type: str,
        index: int = 0,
        tolerance: int = 0
    ) -> AssertionResult:
        """Assert HP values match between game and simulator.

        Args:
            game_state: State from game.
            sim_state: State from simulator.
            entity_type: 'player' or 'monster'.
            index: Monster index (ignored for player).
            tolerance: Allowed HP difference.

        Returns:
            AssertionResult with comparison details.
        """
        try:
            if entity_type == 'player':
                game_hp = game_state.get('combat_state', {}).get('player', {}).get('cur_hp')
                game_max = game_state.get('combat_state', {}).get('player', {}).get('max_hp')
                sim_hp = sim_state.get('combat_state', {}).get('player', {}).get('cur_hp')
                sim_max = sim_state.get('combat_state', {}).get('player', {}).get('max_hp')
            else:
                game_monsters = game_state.get('combat_state', {}).get('monsters', [])
                sim_monsters = sim_state.get('combat_state', {}).get('monsters', [])

                if index >= len(game_monsters) or index >= len(sim_monsters):
                    return AssertionResult(
                        assertion_type=f"hp_match.{entity_type}[{index}]",
                        status=AssertionStatus.ERROR,
                        message=f"Monster index {index} out of range",
                        details={'game_count': len(game_monsters), 'sim_count': len(sim_monsters)}
                    )

                game_hp = game_monsters[index].get('cur_hp')
                game_max = game_monsters[index].get('max_hp')
                sim_hp = sim_monsters[index].get('cur_hp')
                sim_max = sim_monsters[index].get('max_hp')

            if game_hp is None or sim_hp is None:
                return AssertionResult(
                    assertion_type=f"hp_match.{entity_type}[{index}]",
                    status=AssertionStatus.ERROR,
                    message="Could not extract HP values"
                )

            delta = abs(game_hp - sim_hp)

            if delta <= tolerance:
                return AssertionResult(
                    assertion_type=f"hp_match.{entity_type}[{index}]",
                    status=AssertionStatus.PASSED,
                    expected=game_hp,
                    actual=sim_hp,
                    tolerance=tolerance,
                    delta=delta
                )
            else:
                return AssertionResult(
                    assertion_type=f"hp_match.{entity_type}[{index}]",
                    status=AssertionStatus.FAILED,
                    message=f"HP mismatch: game={game_hp}, sim={sim_hp} (delta={delta})",
                    expected=game_hp,
                    actual=sim_hp,
                    tolerance=tolerance,
                    delta=delta
                )

        except Exception as e:
            return AssertionResult(
                assertion_type=f"hp_match.{entity_type}[{index}]",
                status=AssertionStatus.ERROR,
                message=str(e)
            )

    @staticmethod
    def assert_block_match(
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        entity_type: str,
        index: int = 0,
        tolerance: int = 0
    ) -> AssertionResult:
        """Assert block values match between game and simulator.

        Args:
            game_state: State from game.
            sim_state: State from simulator.
            entity_type: 'player' or 'monster'.
            index: Monster index (ignored for player).
            tolerance: Allowed block difference.

        Returns:
            AssertionResult with comparison details.
        """
        try:
            if entity_type == 'player':
                game_block = game_state.get('combat_state', {}).get('player', {}).get('block', 0)
                sim_block = sim_state.get('combat_state', {}).get('player', {}).get('block', 0)
            else:
                game_monsters = game_state.get('combat_state', {}).get('monsters', [])
                sim_monsters = sim_state.get('combat_state', {}).get('monsters', [])

                if index >= len(game_monsters) or index >= len(sim_monsters):
                    return AssertionResult(
                        assertion_type=f"block_match.{entity_type}[{index}]",
                        status=AssertionStatus.ERROR,
                        message=f"Monster index {index} out of range"
                    )

                game_block = game_monsters[index].get('block', 0)
                sim_block = sim_monsters[index].get('block', 0)

            delta = abs(game_block - sim_block)

            if delta <= tolerance:
                return AssertionResult(
                    assertion_type=f"block_match.{entity_type}[{index}]",
                    status=AssertionStatus.PASSED,
                    expected=game_block,
                    actual=sim_block,
                    tolerance=tolerance,
                    delta=delta
                )
            else:
                return AssertionResult(
                    assertion_type=f"block_match.{entity_type}[{index}]",
                    status=AssertionStatus.FAILED,
                    message=f"Block mismatch: game={game_block}, sim={sim_block} (delta={delta})",
                    expected=game_block,
                    actual=sim_block,
                    tolerance=tolerance,
                    delta=delta
                )

        except Exception as e:
            return AssertionResult(
                assertion_type=f"block_match.{entity_type}[{index}]",
                status=AssertionStatus.ERROR,
                message=str(e)
            )

    @staticmethod
    def assert_deck_match(
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        check_order: bool = False
    ) -> AssertionResult:
        """Assert deck contents match between game and simulator.

        Args:
            game_state: State from game.
            sim_state: State from simulator.
            check_order: Whether to check card order (default: False).

        Returns:
            AssertionResult with comparison details.
        """
        try:
            game_deck = game_state.get('deck', [])
            sim_deck = sim_state.get('deck', [])

            if len(game_deck) != len(sim_deck):
                return AssertionResult(
                    assertion_type="deck_match",
                    status=AssertionStatus.FAILED,
                    message=f"Deck size mismatch: game={len(game_deck)}, sim={len(sim_deck)}",
                    expected=len(game_deck),
                    actual=len(sim_deck)
                )

            # Count cards by ID/name
            def get_card_key(card):
                return card.get('id') or card.get('name')

            game_counts = {}
            for card in game_deck:
                key = get_card_key(card)
                game_counts[key] = game_counts.get(key, 0) + 1

            sim_counts = {}
            for card in sim_deck:
                key = get_card_key(card)
                sim_counts[key] = sim_counts.get(key, 0) + 1

            # Find discrepancies
            all_keys = set(game_counts.keys()) | set(sim_counts.keys())
            mismatches = []
            for key in all_keys:
                game_count = game_counts.get(key, 0)
                sim_count = sim_counts.get(key, 0)
                if game_count != sim_count:
                    mismatches.append(f"{key}: game={game_count}, sim={sim_count}")

            if mismatches:
                return AssertionResult(
                    assertion_type="deck_match",
                    status=AssertionStatus.FAILED,
                    message="Card count mismatches: " + "; ".join(mismatches),
                    details={'mismatches': mismatches}
                )

            if check_order:
                # Check exact order
                for i, (gc, sc) in enumerate(zip(game_deck, sim_deck)):
                    if get_card_key(gc) != get_card_key(sc):
                        return AssertionResult(
                            assertion_type="deck_match",
                            status=AssertionStatus.FAILED,
                            message=f"Card order mismatch at position {i}",
                            details={'game': get_card_key(gc), 'sim': get_card_key(sc)}
                        )

            return AssertionResult(
                assertion_type="deck_match",
                status=AssertionStatus.PASSED,
                expected=len(game_deck),
                actual=len(sim_deck)
            )

        except Exception as e:
            return AssertionResult(
                assertion_type="deck_match",
                status=AssertionStatus.ERROR,
                message=str(e)
            )

    @staticmethod
    def assert_combat_state_match(
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        check_hand: bool = True,
        check_monsters: bool = True
    ) -> List[AssertionResult]:
        """Assert full combat state matches between game and simulator.

        Args:
            game_state: State from game.
            sim_state: State from simulator.
            check_hand: Whether to verify hand size.
            check_monsters: Whether to verify monster states.

        Returns:
            List of AssertionResults for each check.
        """
        results = []

        # Check turn number
        game_turn = game_state.get('combat_state', {}).get('turn')
        sim_turn = sim_state.get('combat_state', {}).get('turn')

        if game_turn is not None and sim_turn is not None:
            if game_turn == sim_turn:
                results.append(AssertionResult(
                    assertion_type="combat.turn",
                    status=AssertionStatus.PASSED,
                    expected=game_turn,
                    actual=sim_turn
                ))
            else:
                results.append(AssertionResult(
                    assertion_type="combat.turn",
                    status=AssertionStatus.FAILED,
                    message=f"Turn mismatch: game={game_turn}, sim={sim_turn}",
                    expected=game_turn,
                    actual=sim_turn
                ))

        # Check player state
        results.append(TestAssertions.assert_hp_match(
            game_state, sim_state, 'player'
        ))
        results.append(TestAssertions.assert_block_match(
            game_state, sim_state, 'player'
        ))

        # Check energy
        game_energy = game_state.get('combat_state', {}).get('player', {}).get('energy')
        sim_energy = sim_state.get('combat_state', {}).get('player', {}).get('energy')

        if game_energy is not None and sim_energy is not None:
            if game_energy == sim_energy:
                results.append(AssertionResult(
                    assertion_type="combat.player.energy",
                    status=AssertionStatus.PASSED,
                    expected=game_energy,
                    actual=sim_energy
                ))
            else:
                results.append(AssertionResult(
                    assertion_type="combat.player.energy",
                    status=AssertionStatus.FAILED,
                    message=f"Energy mismatch: game={game_energy}, sim={sim_energy}",
                    expected=game_energy,
                    actual=sim_energy
                ))

        # Check hand size
        if check_hand:
            game_hand = game_state.get('combat_state', {}).get('hand', [])
            sim_hand = sim_state.get('combat_state', {}).get('hand', [])

            if len(game_hand) == len(sim_hand):
                results.append(AssertionResult(
                    assertion_type="combat.hand.size",
                    status=AssertionStatus.PASSED,
                    expected=len(game_hand),
                    actual=len(sim_hand)
                ))
            else:
                results.append(AssertionResult(
                    assertion_type="combat.hand.size",
                    status=AssertionStatus.FAILED,
                    message=f"Hand size mismatch: game={len(game_hand)}, sim={len(sim_hand)}",
                    expected=len(game_hand),
                    actual=len(sim_hand)
                ))

        # Check monsters
        if check_monsters:
            game_monsters = game_state.get('combat_state', {}).get('monsters', [])
            sim_monsters = sim_state.get('combat_state', {}).get('monsters', [])

            if len(game_monsters) == len(sim_monsters):
                results.append(AssertionResult(
                    assertion_type="combat.monsters.count",
                    status=AssertionStatus.PASSED,
                    expected=len(game_monsters),
                    actual=len(sim_monsters)
                ))

                for i in range(len(game_monsters)):
                    results.append(TestAssertions.assert_hp_match(
                        game_state, sim_state, 'monster', i
                    ))
                    results.append(TestAssertions.assert_block_match(
                        game_state, sim_state, 'monster', i
                    ))
            else:
                results.append(AssertionResult(
                    assertion_type="combat.monsters.count",
                    status=AssertionStatus.FAILED,
                    message=f"Monster count mismatch: game={len(game_monsters)}, sim={len(sim_monsters)}",
                    expected=len(game_monsters),
                    actual=len(sim_monsters)
                ))

        return results

    @staticmethod
    def assert_card_damage(
        card_name: str,
        expected_damage: int,
        actual_damage: int,
        strength: int = 0,
        vulnerable: bool = False
    ) -> AssertionResult:
        """Assert card damage matches expected value.

        This accounts for modifiers like Strength and Vulnerable.

        Args:
            card_name: Name of the card.
            expected_damage: Expected base damage.
            actual_damage: Actual damage dealt.
            strength: Player's current strength.
            vulnerable: Whether target is vulnerable.

        Returns:
            AssertionResult with comparison details.
        """
        # Calculate expected total damage
        total_expected = expected_damage + strength

        if vulnerable:
            total_expected = int(total_expected * 1.5)

        if actual_damage == total_expected:
            return AssertionResult(
                assertion_type=f"card_damage.{card_name}",
                status=AssertionStatus.PASSED,
                expected=total_expected,
                actual=actual_damage,
                details={
                    'base_damage': expected_damage,
                    'strength': strength,
                    'vulnerable': vulnerable
                }
            )
        else:
            return AssertionResult(
                assertion_type=f"card_damage.{card_name}",
                status=AssertionStatus.FAILED,
                message=f"Damage mismatch for {card_name}: expected={total_expected}, actual={actual_damage}",
                expected=total_expected,
                actual=actual_damage,
                details={
                    'base_damage': expected_damage,
                    'strength': strength,
                    'vulnerable': vulnerable
                }
            )

    @staticmethod
    def assert_monster_intent(
        game_state: Dict[str, Any],
        monster_index: int,
        expected_intent: Optional[str] = None
    ) -> AssertionResult:
        """Assert monster intent matches expected value.

        Args:
            game_state: State from game.
            monster_index: Index of monster to check.
            expected_intent: Expected intent type (optional, just reports if not provided).

        Returns:
            AssertionResult with intent information.
        """
        try:
            monsters = game_state.get('combat_state', {}).get('monsters', [])

            if monster_index >= len(monsters):
                return AssertionResult(
                    assertion_type=f"monster_intent[{monster_index}]",
                    status=AssertionStatus.ERROR,
                    message=f"Monster index {monster_index} out of range"
                )

            actual_intent = monsters[monster_index].get('intent')

            if expected_intent is None:
                # Just report the intent
                return AssertionResult(
                    assertion_type=f"monster_intent[{monster_index}]",
                    status=AssertionStatus.PASSED,
                    actual=actual_intent,
                    message=f"Monster {monster_index} intent: {actual_intent}"
                )

            # Intent comparison might need translation between formats
            # For now, do a simple comparison
            if str(actual_intent).upper() == str(expected_intent).upper():
                return AssertionResult(
                    assertion_type=f"monster_intent[{monster_index}]",
                    status=AssertionStatus.PASSED,
                    expected=expected_intent,
                    actual=actual_intent
                )
            else:
                return AssertionResult(
                    assertion_type=f"monster_intent[{monster_index}]",
                    status=AssertionStatus.FAILED,
                    message=f"Intent mismatch: expected={expected_intent}, actual={actual_intent}",
                    expected=expected_intent,
                    actual=actual_intent
                )

        except Exception as e:
            return AssertionResult(
                assertion_type=f"monster_intent[{monster_index}]",
                status=AssertionStatus.ERROR,
                message=str(e)
            )

    @staticmethod
    def assert_status_effect(
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        entity_type: str,
        effect_name: str,
        index: int = 0
    ) -> AssertionResult:
        """Assert status effect stacks match.

        Args:
            game_state: State from game.
            sim_state: State from simulator.
            entity_type: 'player' or 'monster'.
            effect_name: Name of status effect (e.g., 'Strength', 'Vulnerable').
            index: Monster index (ignored for player).

        Returns:
            AssertionResult with comparison details.
        """
        try:
            # Get entity from both states
            if entity_type == 'player':
                game_entity = game_state.get('combat_state', {}).get('player', {})
                sim_entity = sim_state.get('combat_state', {}).get('player', {})
            else:
                game_monsters = game_state.get('combat_state', {}).get('monsters', [])
                sim_monsters = sim_state.get('combat_state', {}).get('monsters', [])

                if index >= len(game_monsters) or index >= len(sim_monsters):
                    return AssertionResult(
                        assertion_type=f"status_effect.{entity_type}[{index}].{effect_name}",
                        status=AssertionStatus.ERROR,
                        message=f"Monster index {index} out of range"
                    )

                game_entity = game_monsters[index]
                sim_entity = sim_monsters[index]

            # Try to get status effect value
            # Status effects might be in various locations depending on the implementation
            game_value = game_entity.get(effect_name.lower(), game_entity.get(effect_name, 0))
            sim_value = sim_entity.get(effect_name.lower(), sim_entity.get(effect_name, 0))

            if game_value == sim_value:
                return AssertionResult(
                    assertion_type=f"status_effect.{entity_type}[{index}].{effect_name}",
                    status=AssertionStatus.PASSED,
                    expected=game_value,
                    actual=sim_value
                )
            else:
                return AssertionResult(
                    assertion_type=f"status_effect.{entity_type}[{index}].{effect_name}",
                    status=AssertionStatus.FAILED,
                    message=f"{effect_name} mismatch: game={game_value}, sim={sim_value}",
                    expected=game_value,
                    actual=sim_value
                )

        except Exception as e:
            return AssertionResult(
                assertion_type=f"status_effect.{entity_type}[{index}].{effect_name}",
                status=AssertionStatus.ERROR,
                message=str(e)
            )


def run_all_assertions(
    game_state: Dict[str, Any],
    sim_state: Dict[str, Any]
) -> List[AssertionResult]:
    """Run all standard assertions on game and simulator states.

    Args:
        game_state: State from game.
        sim_state: State from simulator.

    Returns:
        List of all AssertionResults.
    """
    return TestAssertions.assert_combat_state_match(
        game_state, sim_state,
        check_hand=True,
        check_monsters=True
    )
