"""State comparison with configurable tolerances."""
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum
import re


# Monster intent type mapping between CommunicationMod and simulator
# CommunicationMod uses strings, simulator uses enum values
INTENT_MAP = {
    # Attack intents
    'ATTACK': 0,
    'ATTACK_BUFF': 1,
    'ATTACK_DEBUFF': 2,
    'ATTACK_DEFEND': 3,
    # Defend intents
    'DEFEND': 4,
    'DEFEND_BUFF': 5,
    'DEFEND_DEBUFF': 6,
    # Buff/Debuff intents
    'BUFF': 7,
    'DEBUFF': 8,
    'STRONG_ATTACK': 9,
    'MALAISE': 10,
    # Special intents
    'SLEEP': 11,
    'STUN': 12,
    'UNKNOWN': 13,
    'NONE': 14,
    'ESCAPE': 15,
}

# Reverse map for lookup
INTENT_REVERSE_MAP = {v: k for k, v in INTENT_MAP.items()}

# Status effect fields to compare for player and monsters
PLAYER_STATUS_EFFECTS = [
    'strength', 'dexterity', 'focus', 'block',
    'vulnerable', 'weak', 'frail', 'poison', 'burn',
    'dexterity_loss', 'strength_loss',
    'energized', 'constricted', 'no_block',
    'cannot_gain_block', 'entangled', 'intangible',
]

MONSTER_STATUS_EFFECTS = [
    'strength', 'block', 'vulnerable', 'weak', 'poison',
    'burn', 'artifact', 'plated_armor', 'regen',
    'intangible', 'corpse_explosion', 'lock_on',
    'shackled', 'painful_stabs',
]

# Card ID normalization mapping between CommunicationMod and simulator formats
CARD_ID_NORMALIZE_MAP = {
    # CommunicationMod format -> normalized format
    'Strike_R': 'STRIKE',
    'Defend_R': 'DEFEND',
    'Bash': 'BASH',
    # Simulator format -> normalized format
    'CardId.STRIKE_RED': 'STRIKE',
    'CardId.DEFEND_RED': 'DEFEND',
    'CardId.BASH': 'BASH',
    'Strike': 'STRIKE',
    'Defend': 'DEFEND',
}

# Relic ID normalization mapping
RELIC_ID_NORMALIZE_MAP = {
    # CommunicationMod format -> normalized format
    'Burning Blood': 'BURNING_BLOOD',
    'NeowsBlessing': 'NEOWS_BLESSING',
    # Simulator format -> normalized format
    'RelicId.BURNING_BLOOD': 'BURNING_BLOOD',
    'Burning_Blood': 'BURNING_BLOOD',
}


def normalize_card_id(card_id: str) -> str:
    """Normalize card ID to a common format for comparison.

    Args:
        card_id: Card ID from either game or simulator.

    Returns:
        Normalized card ID.
    """
    if card_id is None:
        return 'UNKNOWN'

    card_id = str(card_id).strip()

    # Check direct mapping
    if card_id in CARD_ID_NORMALIZE_MAP:
        return CARD_ID_NORMALIZE_MAP[card_id]

    # Try to extract the core name
    # Handle formats like "CardId.STRIKE_RED" -> "STRIKE_RED"
    if '.' in card_id:
        card_id = card_id.split('.')[-1]

    # Remove common suffixes
    card_id = card_id.replace('_R', '').replace('_RED', '')

    return card_id.upper()


def normalize_relic_id(relic_id: str) -> str:
    """Normalize relic ID to a common format for comparison.

    Args:
        relic_id: Relic ID from either game or simulator.

    Returns:
        Normalized relic ID.
    """
    if relic_id is None:
        return 'UNKNOWN'

    relic_id = str(relic_id).strip()

    # Check direct mapping
    if relic_id in RELIC_ID_NORMALIZE_MAP:
        return RELIC_ID_NORMALIZE_MAP[relic_id]

    # Try to extract the core name
    if '.' in relic_id:
        relic_id = relic_id.split('.')[-1]

    # Normalize spaces to underscores
    relic_id = relic_id.replace(' ', '_')

    return relic_id.upper()


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

        # Compare player status effects
        discrepancies.extend(
            self._compare_player_status_effects(game_player, sim_player)
        )

        return discrepancies

    def _compare_player_status_effects(
        self,
        game_player: Dict[str, Any],
        sim_player: Dict[str, Any]
    ) -> List[Discrepancy]:
        """Compare status effects on the player.

        Args:
            game_player: Player state from game.
            sim_player: Player state from simulator.

        Returns:
            List of discrepancies found.
        """
        discrepancies = []

        for effect in PLAYER_STATUS_EFFECTS:
            game_val = game_player.get(effect, 0)
            sim_val = sim_player.get(effect, 0)

            # Handle None values
            if game_val is None:
                game_val = 0
            if sim_val is None:
                sim_val = 0

            if game_val != sim_val:
                # Determine severity based on effect type
                if effect in ['strength', 'dexterity', 'focus', 'block']:
                    severity = DiscrepancySeverity.CRITICAL
                elif effect in ['vulnerable', 'weak', 'frail', 'poison']:
                    severity = DiscrepancySeverity.MAJOR
                else:
                    severity = DiscrepancySeverity.MINOR

                discrepancies.append(Discrepancy(
                    field=f"player.{effect}",
                    game_value=game_val,
                    sim_value=sim_val,
                    severity=severity,
                    message=f"Player {effect} mismatch: game={game_val}, sim={sim_val}"
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

        # Compare intent
        game_intent = game_monster.get('intent')
        sim_intent = sim_monster.get('intent')
        if game_intent is not None and sim_intent is not None:
            intent_disc = self._compare_monster_intent(game_intent, sim_intent, index)
            if intent_disc:
                discrepancies.append(intent_disc)

        # Compare monster status effects
        discrepancies.extend(
            self._compare_monster_status_effects(game_monster, sim_monster, index)
        )

        return discrepancies

    def _compare_monster_intent(
        self,
        game_intent: Any,
        sim_intent: Any,
        monster_index: int
    ) -> Optional[Discrepancy]:
        """Compare monster intents between game and simulator.

        Args:
            game_intent: Intent from CommunicationMod (string or dict).
            sim_intent: Intent from simulator (int or enum).
            monster_index: Monster index for error messages.

        Returns:
            Discrepancy if intents don't match, None otherwise.
        """
        # Normalize game intent to string
        if isinstance(game_intent, dict):
            game_intent_name = game_intent.get('name', game_intent.get('type', 'UNKNOWN'))
        else:
            game_intent_name = str(game_intent).upper()

        # Normalize sim intent to string
        if isinstance(sim_intent, int):
            sim_intent_name = INTENT_REVERSE_MAP.get(sim_intent, f'UNKNOWN_{sim_intent}')
        else:
            sim_intent_name = str(sim_intent).upper()

        # Map game intent to sim value for comparison
        game_intent_value = INTENT_MAP.get(game_intent_name, -1)
        sim_intent_value = INTENT_MAP.get(sim_intent_name, -1)

        # If both are unknown types, just compare strings
        if game_intent_value == -1 and sim_intent_value == -1:
            if game_intent_name != sim_intent_name:
                return Discrepancy(
                    field=f"monster[{monster_index}].intent",
                    game_value=game_intent,
                    sim_value=sim_intent,
                    severity=DiscrepancySeverity.MAJOR,
                    message=f"Monster {monster_index} intent mismatch: game={game_intent_name}, sim={sim_intent_name}"
                )
        elif game_intent_value != sim_intent_value:
            return Discrepancy(
                field=f"monster[{monster_index}].intent",
                game_value=game_intent,
                sim_value=sim_intent,
                severity=DiscrepancySeverity.MAJOR,
                message=f"Monster {monster_index} intent mismatch: game={game_intent_name}, sim={sim_intent_name}"
            )

        return None

    def _compare_monster_status_effects(
        self,
        game_monster: Dict[str, Any],
        sim_monster: Dict[str, Any],
        index: int
    ) -> List[Discrepancy]:
        """Compare status effects on a monster.

        Args:
            game_monster: Monster state from game.
            sim_monster: Monster state from simulator.
            index: Monster index.

        Returns:
            List of discrepancies found.
        """
        discrepancies = []

        for effect in MONSTER_STATUS_EFFECTS:
            game_val = game_monster.get(effect, 0)
            sim_val = sim_monster.get(effect, 0)

            # Handle None values
            if game_val is None:
                game_val = 0
            if sim_val is None:
                sim_val = 0

            if game_val != sim_val:
                # Determine severity based on effect type
                if effect in ['strength', 'block']:
                    severity = DiscrepancySeverity.CRITICAL
                elif effect in ['vulnerable', 'weak', 'poison']:
                    severity = DiscrepancySeverity.MAJOR
                else:
                    severity = DiscrepancySeverity.MINOR

                discrepancies.append(Discrepancy(
                    field=f"monster[{index}].{effect}",
                    game_value=game_val,
                    sim_value=sim_val,
                    severity=severity,
                    message=f"Monster {index} {effect} mismatch: game={game_val}, sim={sim_val}"
                ))

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

        # Compare card counts by normalized type (order may differ)
        game_cards = {}
        sim_cards = {}

        for card in game_deck:
            raw_id = card.get('id') or card.get('name')
            card_id = normalize_card_id(raw_id)
            game_cards[card_id] = game_cards.get(card_id, {'count': 0, 'cards': []})
            game_cards[card_id]['count'] += 1
            game_cards[card_id]['cards'].append(card)

        for card in sim_deck:
            raw_id = card.get('id') or card.get('name')
            card_id = normalize_card_id(raw_id)
            sim_cards[card_id] = sim_cards.get(card_id, {'count': 0, 'cards': []})
            sim_cards[card_id]['count'] += 1
            sim_cards[card_id]['cards'].append(card)

        all_card_ids = set(game_cards.keys()) | set(sim_cards.keys())
        for card_id in all_card_ids:
            game_count = game_cards.get(card_id, {}).get('count', 0)
            sim_count = sim_cards.get(card_id, {}).get('count', 0)
            if game_count != sim_count:
                discrepancies.append(Discrepancy(
                    field=f"deck.{card_id}",
                    game_value=game_count,
                    sim_value=sim_count,
                    severity=DiscrepancySeverity.MAJOR,
                    message=f"Card count mismatch for {card_id}: game={game_count}, sim={sim_count}"
                ))
            elif game_count > 0 and sim_count > 0:
                # Counts match, compare card properties
                prop_disc = self._compare_card_properties(
                    game_cards[card_id]['cards'],
                    sim_cards[card_id]['cards'],
                    card_id
                )
                discrepancies.extend(prop_disc)

        return discrepancies

    def _compare_card_properties(
        self,
        game_cards: List[Dict[str, Any]],
        sim_cards: List[Dict[str, Any]],
        card_id: str
    ) -> List[Discrepancy]:
        """Compare properties of cards with the same ID.

        Args:
            game_cards: List of game cards with this ID.
            sim_cards: List of simulator cards with this ID.
            card_id: Card ID being compared.

        Returns:
            List of discrepancies found.
        """
        discrepancies = []

        # Count upgraded vs non-upgraded
        game_upgraded = sum(1 for c in game_cards if c.get('upgraded', False))
        sim_upgraded = sum(1 for c in sim_cards if c.get('upgraded', c.get('is_upgraded', False)))

        if game_upgraded != sim_upgraded:
            discrepancies.append(Discrepancy(
                field=f"deck.{card_id}.upgraded",
                game_value=game_upgraded,
                sim_value=sim_upgraded,
                severity=DiscrepancySeverity.MAJOR,
                message=f"Upgraded count mismatch for {card_id}: game={game_upgraded}, sim={sim_upgraded}"
            ))

        # Compare costs (if available)
        game_costs = [c.get('cost', c.get('base_cost', -1)) for c in game_cards]
        sim_costs = [c.get('cost', c.get('base_cost', -1)) for c in sim_cards]

        # Sort for comparison (order may differ)
        if sorted(game_costs) != sorted(sim_costs):
            discrepancies.append(Discrepancy(
                field=f"deck.{card_id}.costs",
                game_value=game_costs,
                sim_value=sim_costs,
                severity=DiscrepancySeverity.MAJOR,
                message=f"Card costs mismatch for {card_id}: game={game_costs}, sim={sim_costs}"
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

        # Normalize relic IDs for comparison
        game_relic_ids = {normalize_relic_id(r.get('id')) for r in game_relics if r.get('id')}
        sim_relic_ids = {normalize_relic_id(r.get('id')) for r in sim_relics if r.get('id')}

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
