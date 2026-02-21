"""State comparison with configurable tolerances."""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum


class DiscrepancySeverity(Enum):
    """Severity levels for state discrepancies."""
    CRITICAL = "critical"    # Wrong damage, wrong HP - must fix
    MAJOR = "major"          # Functional bug - wrong status effect duration
    MINOR = "minor"          # Cosmetic - card ordering in display
    SKIP = "skip"            # Known unimplemented feature


@dataclass
class Discrepancy:
    """Represents a single discrepancy between game and simulator states."""
    field: str
    game_value: Any
    sim_value: Any
    severity: DiscrepancySeverity
    message: str = ""
    tolerance: float = 0.0


@dataclass
class ComparisonResult:
    """Result of comparing game and simulator states."""
    match: bool
    discrepancies: List[Discrepancy] = field(default_factory=list)
    game_state: Optional[Dict[str, Any]] = None
    sim_state: Optional[Dict[str, Any]] = None

    @property
    def critical_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.CRITICAL)

    @property
    def major_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.MAJOR)

    @property
    def minor_count(self) -> int:
        return sum(1 for d in self.discrepancies if d.severity == DiscrepancySeverity.MINOR)

    def get_summary(self) -> str:
        """Get a summary string of the comparison."""
        if self.match:
            return "States match perfectly"

        parts = []
        if self.critical_count > 0:
            parts.append(f"{self.critical_count} critical")
        if self.major_count > 0:
            parts.append(f"{self.major_count} major")
        if self.minor_count > 0:
            parts.append(f"{self.minor_count} minor")

        return f"Discrepancies: {', '.join(parts)}"


class StateComparator:
    """Compare game and simulator states with configurable tolerances."""

    # Fields that must match exactly
    EXACT_FIELDS = ['seed', 'floor', 'act', 'screen_state']

    # Fields that must match with tolerance 0
    NUMERIC_FIELDS = {
        'cur_hp': 0,
        'max_hp': 0,
        'gold': 0,
        'energy': 0,
        'block': 0,
    }

    # Fields that can have some tolerance (for floating point comparisons)
    TOLERANT_FIELDS = {}

    # Fields to skip comparison (known differences)
    SKIP_FIELDS = []

    def __init__(self, tolerances: Optional[Dict[str, float]] = None):
        """Initialize the comparator.

        Args:
            tolerances: Optional tolerance overrides for specific fields.
        """
        self.tolerances = {**self.NUMERIC_FIELDS, **self.TOLERANT_FIELDS}
        if tolerances:
            self.tolerances.update(tolerances)

        # Track known discrepancies for specific scenarios
        self._known_discrepancies: List[Dict[str, Any]] = []

    def compare(
        self,
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any]
    ) -> ComparisonResult:
        """Compare game and simulator states.

        Args:
            game_state: State from real game via CommunicationMod.
            sim_state: State from sts_lightspeed simulator.

        Returns:
            ComparisonResult with match status and list of discrepancies.
        """
        discrepancies = []

        # Compare top-level fields
        discrepancies.extend(self._compare_fields(game_state, sim_state, ""))

        # Compare combat state if present
        if 'combat_state' in game_state and 'combat_state' in sim_state:
            discrepancies.extend(
                self._compare_combat_states(
                    game_state['combat_state'],
                    sim_state['combat_state']
                )
            )
        elif ('combat_state' in game_state) != ('combat_state' in sim_state):
            discrepancies.append(Discrepancy(
                field="combat_state",
                game_value='combat_state' in game_state,
                sim_value='combat_state' in sim_state,
                severity=DiscrepancySeverity.CRITICAL,
                message="Combat state presence mismatch"
            ))

        # Compare deck
        if 'deck' in game_state and 'deck' in sim_state:
            discrepancies.extend(
                self._compare_decks(game_state['deck'], sim_state['deck'])
            )

        # Compare relics
        if 'relics' in game_state and 'relics' in sim_state:
            discrepancies.extend(
                self._compare_relics(game_state['relics'], sim_state['relics'])
            )

        # Compare potions
        if 'potions' in game_state and 'potions' in sim_state:
            discrepancies.extend(
                self._compare_potions(game_state['potions'], sim_state['potions'])
            )

        # Filter out known discrepancies
        discrepancies = self._filter_known_discrepancies(discrepancies, game_state)

        return ComparisonResult(
            match=len(discrepancies) == 0,
            discrepancies=discrepancies,
            game_state=game_state,
            sim_state=sim_state
        )

    def _compare_fields(
        self,
        game_state: Dict[str, Any],
        sim_state: Dict[str, Any],
        prefix: str
    ) -> List[Discrepancy]:
        """Compare top-level fields between states."""
        discrepancies = []

        for field in self.EXACT_FIELDS:
            game_val = game_state.get(field)
            sim_val = sim_state.get(field)

            if game_val != sim_val:
                field_path = f"{prefix}.{field}" if prefix else field
                discrepancies.append(Discrepancy(
                    field=field_path,
                    game_value=game_val,
                    sim_value=sim_val,
                    severity=DiscrepancySeverity.CRITICAL,
                    message=f"{field_path} mismatch: game={game_val}, sim={sim_val}"
                ))

        for field, tolerance in self.tolerances.items():
            game_val = game_state.get(field)
            sim_val = sim_state.get(field)

            if game_val is not None and sim_val is not None:
                if abs(game_val - sim_val) > tolerance:
                    field_path = f"{prefix}.{field}" if prefix else field
                    discrepancies.append(Discrepancy(
                        field=field_path,
                        game_value=game_val,
                        sim_value=sim_val,
                        severity=DiscrepancySeverity.CRITICAL if tolerance == 0 else DiscrepancySeverity.MAJOR,
                        tolerance=tolerance,
                        message=f"{field_path} mismatch: game={game_val}, sim={sim_val} (tolerance={tolerance})"
                    ))

        return discrepancies

    def _compare_combat_states(
        self,
        game_combat: Dict[str, Any],
        sim_combat: Dict[str, Any]
    ) -> List[Discrepancy]:
        """Compare combat-specific states."""
        discrepancies = []

        # Compare turn number
        if game_combat.get('turn') != sim_combat.get('turn'):
            discrepancies.append(Discrepancy(
                field="combat.turn",
                game_value=game_combat.get('turn'),
                sim_value=sim_combat.get('turn'),
                severity=DiscrepancySeverity.CRITICAL,
                message="Turn number mismatch"
            ))

        # Compare player state
        if 'player' in game_combat and 'player' in sim_combat:
            discrepancies.extend(
                self._compare_player_states(
                    game_combat['player'],
                    sim_combat['player']
                )
            )

        # Compare monsters
        game_monsters = game_combat.get('monsters', [])
        sim_monsters = sim_combat.get('monsters', [])

        if len(game_monsters) != len(sim_monsters):
            discrepancies.append(Discrepancy(
                field="combat.monsters.count",
                game_value=len(game_monsters),
                sim_value=len(sim_monsters),
                severity=DiscrepancySeverity.CRITICAL,
                message="Monster count mismatch"
            ))
        else:
            for i, (gm, sm) in enumerate(zip(game_monsters, sim_monsters)):
                discrepancies.extend(
                    self._compare_monster_states(gm, sm, i)
                )

        # Compare hand
        game_hand = game_combat.get('hand', [])
        sim_hand = sim_combat.get('hand', [])

        if len(game_hand) != len(sim_hand):
            discrepancies.append(Discrepancy(
                field="combat.hand.count",
                game_value=len(game_hand),
                sim_value=len(sim_hand),
                severity=DiscrepancySeverity.CRITICAL,
                message="Hand size mismatch"
            ))
        # Note: We don't compare exact card order as it may differ

        return discrepancies

    def _compare_player_states(
        self,
        game_player: Dict[str, Any],
        sim_player: Dict[str, Any]
    ) -> List[Discrepancy]:
        """Compare player states in combat."""
        discrepancies = []

        for field in ['cur_hp', 'max_hp', 'block', 'energy']:
            game_val = game_player.get(field)
            sim_val = sim_player.get(field)

            if game_val is not None and sim_val is not None:
                if game_val != sim_val:
                    discrepancies.append(Discrepancy(
                        field=f"player.{field}",
                        game_value=game_val,
                        sim_value=sim_val,
                        severity=DiscrepancySeverity.CRITICAL,
                        message=f"Player {field} mismatch: game={game_val}, sim={sim_val}"
                    ))

        return discrepancies

    def _compare_monster_states(
        self,
        game_monster: Dict[str, Any],
        sim_monster: Dict[str, Any],
        index: int
    ) -> List[Discrepancy]:
        """Compare individual monster states."""
        discrepancies = []

        for field in ['cur_hp', 'max_hp', 'block']:
            game_val = game_monster.get(field)
            sim_val = sim_monster.get(field)

            if game_val is not None and sim_val is not None:
                if game_val != sim_val:
                    discrepancies.append(Discrepancy(
                        field=f"monster[{index}].{field}",
                        game_value=game_val,
                        sim_value=sim_val,
                        severity=DiscrepancySeverity.CRITICAL,
                        message=f"Monster {index} {field} mismatch: game={game_val}, sim={sim_val}"
                    ))

        # Compare intent (might have different encoding)
        game_intent = game_monster.get('intent')
        sim_intent = sim_monster.get('intent')
        # Intent comparison might need translation - skip for now

        return discrepancies

    def _compare_decks(
        self,
        game_deck: List[Dict[str, Any]],
        sim_deck: List[Dict[str, Any]]
    ) -> List[Discrepancy]:
        """Compare deck contents."""
        discrepancies = []

        if len(game_deck) != len(sim_deck):
            discrepancies.append(Discrepancy(
                field="deck.count",
                game_value=len(game_deck),
                sim_value=len(sim_deck),
                severity=DiscrepancySeverity.CRITICAL,
                message=f"Deck size mismatch: game={len(game_deck)}, sim={len(sim_deck)}"
            ))
            return discrepancies  # Don't try to compare individual cards

        # Compare card counts by type (order may differ)
        game_cards = {}
        sim_cards = {}

        for card in game_deck:
            card_id = card.get('id') or card.get('name')
            game_cards[card_id] = game_cards.get(card_id, 0) + 1

        for card in sim_deck:
            card_id = card.get('id') or card.get('name')
            sim_cards[card_id] = sim_cards.get(card_id, 0) + 1

        all_card_ids = set(game_cards.keys()) | set(sim_cards.keys())
        for card_id in all_card_ids:
            game_count = game_cards.get(card_id, 0)
            sim_count = sim_cards.get(card_id, 0)
            if game_count != sim_count:
                discrepancies.append(Discrepancy(
                    field=f"deck.{card_id}",
                    game_value=game_count,
                    sim_value=sim_count,
                    severity=DiscrepancySeverity.MAJOR,
                    message=f"Card count mismatch for {card_id}: game={game_count}, sim={sim_count}"
                ))

        return discrepancies

    def _compare_relics(
        self,
        game_relics: List[Dict[str, Any]],
        sim_relics: List[Dict[str, Any]]
    ) -> List[Discrepancy]:
        """Compare relic lists."""
        discrepancies = []

        if len(game_relics) != len(sim_relics):
            discrepancies.append(Discrepancy(
                field="relics.count",
                game_value=len(game_relics),
                sim_value=len(sim_relics),
                severity=DiscrepancySeverity.MAJOR,
                message=f"Relic count mismatch: game={len(game_relics)}, sim={len(sim_relics)}"
            ))

        game_relic_ids = {r.get('id') for r in game_relics}
        sim_relic_ids = {r.get('id') for r in sim_relics}

        missing_in_sim = game_relic_ids - sim_relic_ids
        extra_in_sim = sim_relic_ids - game_relic_ids

        for relic_id in missing_in_sim:
            discrepancies.append(Discrepancy(
                field=f"relics.{relic_id}",
                game_value=True,
                sim_value=False,
                severity=DiscrepancySeverity.MAJOR,
                message=f"Relic {relic_id} missing in simulator"
            ))

        for relic_id in extra_in_sim:
            discrepancies.append(Discrepancy(
                field=f"relics.{relic_id}",
                game_value=False,
                sim_value=True,
                severity=DiscrepancySeverity.MAJOR,
                message=f"Extra relic {relic_id} in simulator"
            ))

        return discrepancies

    def _compare_potions(
        self,
        game_potions: List[Dict[str, Any]],
        sim_potions: List[Dict[str, Any]]
    ) -> List[Discrepancy]:
        """Compare potion lists."""
        discrepancies = []

        if len(game_potions) != len(sim_potions):
            discrepancies.append(Discrepancy(
                field="potions.count",
                game_value=len(game_potions),
                sim_value=len(sim_potions),
                severity=DiscrepancySeverity.MINOR,
                message=f"Potion count mismatch: game={len(game_potions)}, sim={len(sim_potions)}"
            ))

        return discrepancies

    def _filter_known_discrepancies(
        self,
        discrepancies: List[Discrepancy],
        game_state: Dict[str, Any]
    ) -> List[Discrepancy]:
        """Filter out known/expected discrepancies."""
        filtered = []
        for disc in discrepancies:
            is_known = False
            for known in self._known_discrepancies:
                if self._matches_known_pattern(disc, known, game_state):
                    disc.severity = DiscrepancySeverity.SKIP
                    is_known = True
                    break
            if not is_known:
                filtered.append(disc)
        return filtered

    def _matches_known_pattern(
        self,
        discrepancy: Discrepancy,
        known_pattern: Dict[str, Any],
        game_state: Dict[str, Any]
    ) -> bool:
        """Check if a discrepancy matches a known pattern."""
        if discrepancy.field != known_pattern.get('field'):
            return False

        if 'condition' in known_pattern:
            condition = known_pattern['condition']
            # Check character condition
            if 'character' in condition:
                if game_state.get('character') != condition['character']:
                    return False
            # Check act condition
            if 'act' in condition:
                if game_state.get('act') != condition['act']:
                    return False
            # Check floor range
            if 'min_floor' in condition:
                if game_state.get('floor', 0) < condition['min_floor']:
                    return False
            # Check screen state
            if 'screen_state' in condition:
                if game_state.get('screen_state') != condition['screen_state']:
                    return False

        return True

    def add_known_discrepancy(self, pattern: Dict[str, Any]):
        """Add a known discrepancy pattern to skip.

        Args:
            pattern: Dictionary with 'field' and optional 'condition' keys.
        """
        self._known_discrepancies.append(pattern)
