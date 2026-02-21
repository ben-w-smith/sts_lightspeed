"""Expected state management for test scenarios.

This module provides data structures and utilities for defining
expected game states at specific points during test scenarios.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Union


@dataclass
class Range:
    """Represents a range of acceptable values."""
    min_val: int
    max_val: int

    def __contains__(self, value: int) -> bool:
        """Check if value is within range."""
        return self.min_val <= value <= self.max_val

    @classmethod
    def exact(cls, value: int) -> 'Range':
        """Create a range with exact value."""
        return cls(value, value)

    @classmethod
    def at_least(cls, min_val: int) -> 'Range':
        """Create a range with minimum value."""
        return cls(min_val, 999999)

    @classmethod
    def at_most(cls, max_val: int) -> 'Range':
        """Create a range with maximum value."""
        return cls(0, max_val)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {'min': self.min_val, 'max': self.max_val}


@dataclass
class ExpectedMonsterState:
    """Expected state for a single monster."""
    index: int
    hp_change: Optional[int] = None  # Relative to start of combat
    hp_range: Optional[Range] = None  # Absolute HP range
    block: Optional[int] = None
    block_range: Optional[Range] = None
    intent: Optional[str] = None
    is_dead: Optional[bool] = None
    status_effects: Dict[str, int] = field(default_factory=dict)


@dataclass
class ExpectedState:
    """Expected state at a specific step in a test scenario."""
    step: int
    description: str = ""

    # Player state
    player_hp: Optional[Range] = None
    player_hp_change: Optional[int] = None  # Relative to previous state
    player_block: Optional[int] = None
    player_block_range: Optional[Range] = None
    player_energy: Optional[int] = None
    player_energy_range: Optional[Range] = None

    # Monster states (indexed by monster position)
    monster_states: Dict[int, ExpectedMonsterState] = field(default_factory=dict)

    # Hand state
    hand_size: Optional[int] = None
    hand_size_range: Optional[Range] = None
    hand_contains: List[str] = field(default_factory=list)  # Card names that should be in hand

    # Combat state
    turn: Optional[int] = None
    in_combat: Optional[bool] = None

    # Game state
    floor: Optional[int] = None
    act: Optional[int] = None
    screen_state: Optional[str] = None

    # Deck state
    deck_size: Optional[int] = None
    draw_pile_size: Optional[int] = None
    discard_pile_size: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result = {'step': self.step}
        if self.description:
            result['description'] = self.description
        if self.player_hp:
            result['player_hp'] = self.player_hp.to_dict()
        if self.player_hp_change is not None:
            result['player_hp_change'] = self.player_hp_change
        if self.player_block is not None:
            result['player_block'] = self.player_block
        if self.player_energy is not None:
            result['player_energy'] = self.player_energy
        if self.hand_size is not None:
            result['hand_size'] = self.hand_size
        if self.turn is not None:
            result['turn'] = self.turn
        return result


@dataclass
class Discrepancy:
    """Represents a discrepancy between expected and actual state."""
    field: str
    expected: Any
    actual: Any
    message: str = ""

    def __str__(self) -> str:
        return f"{self.field}: expected={self.expected}, actual={self.actual}"


class ExpectedStateManager:
    """Manages expected states and verification against actual states."""

    def __init__(self):
        """Initialize the manager."""
        self.expected_states: Dict[int, ExpectedState] = {}
        self._previous_state: Optional[Dict[str, Any]] = None

    def add_expected_state(self, state: ExpectedState):
        """Add an expected state for a step.

        Args:
            state: ExpectedState to add.
        """
        self.expected_states[state.step] = state

    def get_expected_state(self, step: int) -> Optional[ExpectedState]:
        """Get expected state for a step.

        Args:
            step: Step number.

        Returns:
            ExpectedState or None if not defined.
        """
        return self.expected_states.get(step)

    def load_from_yaml(self, yaml_data: dict) -> List[ExpectedState]:
        """Load expected states from YAML data.

        Args:
            yaml_data: Dictionary from YAML file.

        Returns:
            List of ExpectedState objects.
        """
        states = []

        expected_states_data = yaml_data.get('expected_states', {})

        for key, data in expected_states_data.items():
            # Parse step number from key (e.g., "after_step_0" -> 0)
            step = self._parse_step_key(key)
            if step is None:
                continue

            state = self._parse_expected_state(step, data)
            states.append(state)
            self.add_expected_state(state)

        return states

    def _parse_step_key(self, key: str) -> Optional[int]:
        """Parse step number from a key like 'after_step_0'."""
        import re
        match = re.search(r'(\d+)', key)
        if match:
            return int(match.group(1))
        return None

    def _parse_expected_state(self, step: int, data: dict) -> ExpectedState:
        """Parse expected state from dictionary data."""
        state = ExpectedState(
            step=step,
            description=data.get('description', '')
        )

        # Player HP
        if 'player_hp' in data:
            hp_data = data['player_hp']
            if isinstance(hp_data, dict):
                state.player_hp = Range(
                    hp_data.get('min', 0),
                    hp_data.get('max', 999)
                )
            else:
                state.player_hp = Range.exact(hp_data)

        if 'player_hp_change' in data:
            state.player_hp_change = data['player_hp_change']

        # Player block
        if 'player_block' in data:
            state.player_block = data['player_block']

        # Player energy
        if 'player_energy' in data:
            state.player_energy = data['player_energy']

        # Hand size
        if 'hand_size' in data:
            state.hand_size = data['hand_size']

        # Monster states
        for key, monster_data in data.items():
            if key.startswith('monster_'):
                # Parse monster index from key (e.g., "monster_0_hp_change" -> 0)
                import re
                match = re.match(r'monster_(\d+)(?:_(.*))?', key)
                if match:
                    idx = int(match.group(1))
                    suffix = match.group(2) or ''

                    if idx not in state.monster_states:
                        state.monster_states[idx] = ExpectedMonsterState(index=idx)

                    monster_state = state.monster_states[idx]

                    if suffix == 'hp_change':
                        monster_state.hp_change = monster_data
                    elif suffix == 'hp':
                        if isinstance(monster_data, dict):
                            monster_state.hp_range = Range(
                                monster_data.get('min', 0),
                                monster_data.get('max', 999)
                            )
                        else:
                            monster_state.hp_range = Range.exact(monster_data)
                    elif suffix == 'block':
                        monster_state.block = monster_data
                    elif suffix == 'intent':
                        monster_state.intent = monster_data

        # Turn
        if 'turn' in data:
            state.turn = data['turn']

        # Screen state
        if 'screen_state' in data:
            state.screen_state = data['screen_state']

        return state

    def verify_against_expected(
        self,
        actual: Dict[str, Any],
        expected: ExpectedState,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> List[Discrepancy]:
        """Verify actual state against expected state.

        Args:
            actual: Actual game/sim state.
            expected: ExpectedState to verify against.
            previous_state: Previous state for relative comparisons.

        Returns:
            List of Discrepancy objects for any mismatches.
        """
        discrepancies = []

        # Verify player HP
        if expected.player_hp is not None:
            actual_hp = actual.get('combat_state', {}).get('player', {}).get('cur_hp')
            if actual_hp is not None and actual_hp not in expected.player_hp:
                discrepancies.append(Discrepancy(
                    field="player.cur_hp",
                    expected=f"[{expected.player_hp.min_val}, {expected.player_hp.max_val}]",
                    actual=actual_hp,
                    message=f"Player HP {actual_hp} not in expected range"
                ))

        # Verify player HP change
        if expected.player_hp_change is not None and previous_state is not None:
            prev_hp = previous_state.get('combat_state', {}).get('player', {}).get('cur_hp', 0)
            actual_hp = actual.get('combat_state', {}).get('player', {}).get('cur_hp', 0)
            actual_change = actual_hp - prev_hp
            if actual_change != expected.player_hp_change:
                discrepancies.append(Discrepancy(
                    field="player.hp_change",
                    expected=expected.player_hp_change,
                    actual=actual_change,
                    message=f"HP change should be {expected.player_hp_change}, was {actual_change}"
                ))

        # Verify player block
        if expected.player_block is not None:
            actual_block = actual.get('combat_state', {}).get('player', {}).get('block', 0)
            if actual_block != expected.player_block:
                discrepancies.append(Discrepancy(
                    field="player.block",
                    expected=expected.player_block,
                    actual=actual_block
                ))

        # Verify player energy
        if expected.player_energy is not None:
            actual_energy = actual.get('combat_state', {}).get('player', {}).get('energy')
            if actual_energy is not None and actual_energy != expected.player_energy:
                discrepancies.append(Discrepancy(
                    field="player.energy",
                    expected=expected.player_energy,
                    actual=actual_energy
                ))

        # Verify hand size
        if expected.hand_size is not None:
            actual_hand_size = len(actual.get('combat_state', {}).get('hand', []))
            if actual_hand_size != expected.hand_size:
                discrepancies.append(Discrepancy(
                    field="hand.size",
                    expected=expected.hand_size,
                    actual=actual_hand_size
                ))

        # Verify turn
        if expected.turn is not None:
            actual_turn = actual.get('combat_state', {}).get('turn')
            if actual_turn is not None and actual_turn != expected.turn:
                discrepancies.append(Discrepancy(
                    field="combat.turn",
                    expected=expected.turn,
                    actual=actual_turn
                ))

        # Verify monster states
        for idx, monster_expected in expected.monster_states.items():
            monsters = actual.get('combat_state', {}).get('monsters', [])

            if idx >= len(monsters):
                discrepancies.append(Discrepancy(
                    field=f"monster[{idx}]",
                    expected="present",
                    actual="missing",
                    message=f"Monster {idx} not found"
                ))
                continue

            actual_monster = monsters[idx]

            # HP change
            if monster_expected.hp_change is not None and previous_state is not None:
                prev_monsters = previous_state.get('combat_state', {}).get('monsters', [])
                if idx < len(prev_monsters):
                    prev_hp = prev_monsters[idx].get('cur_hp', 0)
                    actual_hp = actual_monster.get('cur_hp', 0)
                    actual_change = actual_hp - prev_hp
                    if actual_change != monster_expected.hp_change:
                        discrepancies.append(Discrepancy(
                            field=f"monster[{idx}].hp_change",
                            expected=monster_expected.hp_change,
                            actual=actual_change
                        ))

            # HP range
            if monster_expected.hp_range is not None:
                actual_hp = actual_monster.get('cur_hp')
                if actual_hp is not None and actual_hp not in monster_expected.hp_range:
                    discrepancies.append(Discrepancy(
                        field=f"monster[{idx}].cur_hp",
                        expected=f"[{monster_expected.hp_range.min_val}, {monster_expected.hp_range.max_val}]",
                        actual=actual_hp
                    ))

            # Block
            if monster_expected.block is not None:
                actual_block = actual_monster.get('block', 0)
                if actual_block != monster_expected.block:
                    discrepancies.append(Discrepancy(
                        field=f"monster[{idx}].block",
                        expected=monster_expected.block,
                        actual=actual_block
                    ))

        # Verify screen state
        if expected.screen_state is not None:
            actual_screen = actual.get('screen_state', '')
            if actual_screen != expected.screen_state:
                discrepancies.append(Discrepancy(
                    field="screen_state",
                    expected=expected.screen_state,
                    actual=actual_screen
                ))

        self._previous_state = actual
        return discrepancies

    def clear(self):
        """Clear all expected states."""
        self.expected_states.clear()
        self._previous_state = None
