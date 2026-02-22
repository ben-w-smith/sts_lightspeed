"""Fix analyzer for mapping discrepancies to C++ source files.

This module provides functionality to analyze state discrepancies and
generate actionable fix suggestions by mapping field patterns to
relevant C++ source files.
"""
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


@dataclass
class FixSuggestion:
    """A suggestion for fixing a discrepancy."""
    field: str
    issue_type: str
    description: str
    files: List[str] = field(default_factory=list)
    search_terms: List[str] = field(default_factory=list)
    likely_functions: List[str] = field(default_factory=list)
    related_patterns: List[str] = field(default_factory=list)
    priority: str = "normal"  # high, normal, low

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'field': self.field,
            'issue_type': self.issue_type,
            'description': self.description,
            'files': self.files,
            'search_terms': self.search_terms,
            'likely_functions': self.likely_functions,
            'related_patterns': self.related_patterns,
            'priority': self.priority,
        }


@dataclass
class CodeLocation:
    """A specific code location reference."""
    file: str
    line: Optional[int] = None
    function: Optional[str] = None
    description: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'file': self.file,
            'line': self.line,
            'function': self.function,
            'description': self.description,
        }


# Mapping of discrepancy field patterns to code locations
DISCREPANCY_TO_CODE: Dict[str, Dict[str, Any]] = {
    # Monster-related discrepancies
    'monster[*].cur_hp': {
        'files': [
            'src/combat/Monster.cpp',
            'src/combat/Actions.cpp',
            'src/combat/Damage.cpp',
        ],
        'likely_issue': 'Damage calculation or HP modification',
        'search_terms': ['cur_hp', 'damage', 'hp', 'loseHp', 'heal'],
        'likely_functions': ['damage', 'loseHp', 'heal', 'attack'],
    },
    'monster[*].max_hp': {
        'files': [
            'src/combat/Monster.cpp',
            'src/combat/MonsterSpecific.cpp',
        ],
        'likely_issue': 'Monster initialization or max HP calculation',
        'search_terms': ['max_hp', 'maxHp', 'hp'],
        'likely_functions': ['init', 'constructor'],
    },
    'monster[*].block': {
        'files': [
            'src/combat/Monster.cpp',
            'src/combat/Actions.cpp',
        ],
        'likely_issue': 'Block gain or decay for monsters',
        'search_terms': ['block', 'addBlock', 'loseBlock'],
        'likely_functions': ['addBlock', 'loseBlock', 'endTurn'],
    },
    'monster[*].intent': {
        'files': [
            'src/combat/Monster.cpp',
            'src/combat/MonsterSpecific.cpp',
            'src/combat/MonsterIntent.cpp',
        ],
        'likely_issue': 'Monster AI or intent calculation',
        'search_terms': ['intent', 'move', 'nextMove', 'action'],
        'likely_functions': ['getNextMove', 'setMove', 'determineMove'],
    },
    'combat.monsters.count': {
        'files': [
            'src/combat/BattleContext.cpp',
            'src/combat/Monster.cpp',
        ],
        'likely_issue': 'Monster spawn or death handling',
        'search_terms': ['monster', 'spawn', 'die', 'death', 'escape'],
        'likely_functions': ['spawnMonster', 'onDeath', 'isDead'],
    },

    # Player-related discrepancies
    'player.cur_hp': {
        'files': [
            'src/combat/Player.cpp',
            'src/combat/Actions.cpp',
            'src/game/GameContext.cpp',
        ],
        'likely_issue': 'Player damage or healing calculation',
        'search_terms': ['cur_hp', 'hp', 'damage', 'loseHp', 'heal'],
        'likely_functions': ['damage', 'loseHp', 'heal'],
    },
    'player.max_hp': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Player.cpp',
        ],
        'likely_issue': 'Max HP modification (relics, events)',
        'search_terms': ['max_hp', 'maxHp', 'increaseMaxHp'],
        'likely_functions': ['increaseMaxHp', 'constructor'],
    },
    'player.block': {
        'files': [
            'src/combat/Player.cpp',
            'src/combat/Actions.cpp',
            'src/combat/Card.cpp',
        ],
        'likely_issue': 'Block gain, decay, or card effects',
        'search_terms': ['block', 'gainBlock', 'addBlock'],
        'likely_functions': ['gainBlock', 'addBlock', 'endTurnPlayer'],
    },
    'player.energy': {
        'files': [
            'src/combat/Player.cpp',
            'src/combat/Actions.cpp',
            'src/combat/Card.cpp',
        ],
        'likely_issue': 'Energy gain, usage, or card costs',
        'search_terms': ['energy', 'loseEnergy', 'gainEnergy'],
        'likely_functions': ['useEnergy', 'gainEnergy', 'startTurn'],
    },

    # Card-related discrepancies
    'combat.hand.count': {
        'files': [
            'src/combat/CardManager.cpp',
            'src/combat/Actions.cpp',
        ],
        'likely_issue': 'Card draw or hand management',
        'search_terms': ['hand', 'draw', 'drawCard'],
        'likely_functions': ['drawCard', 'addToHand', 'removeFromHand'],
    },
    'deck.*': {
        'files': [
            'src/game/Deck.cpp',
            'src/game/GameContext.cpp',
        ],
        'likely_issue': 'Deck management or card addition/removal',
        'search_terms': ['deck', 'addCard', 'removeCard', 'masterDeck'],
        'likely_functions': ['addCard', 'removeCard', 'initializeDeck'],
    },

    # Combat state discrepancies
    'combat.turn': {
        'files': [
            'src/combat/BattleContext.cpp',
            'src/combat/Actions.cpp',
        ],
        'likely_issue': 'Turn management or increment logic',
        'search_terms': ['turn', 'endTurn', 'startTurn'],
        'likely_functions': ['endTurn', 'startTurn'],
    },

    # Game state discrepancies
    'cur_hp': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Player.cpp',
        ],
        'likely_issue': 'Player HP tracking outside combat',
        'search_terms': ['cur_hp', 'hp', 'currentHp'],
        'likely_functions': ['damage', 'heal'],
    },
    'max_hp': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Player.cpp',
        ],
        'likely_issue': 'Max HP tracking or modification',
        'search_terms': ['max_hp', 'maxHp'],
        'likely_functions': ['increaseMaxHp'],
    },
    'gold': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Actions.cpp',
        ],
        'likely_issue': 'Gold gain or spending',
        'search_terms': ['gold', 'loseGold', 'gainGold'],
        'likely_functions': ['gainGold', 'loseGold', 'spendGold'],
    },
    'floor': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Actions.cpp',
        ],
        'likely_issue': 'Floor progression',
        'search_terms': ['floor', 'floor_num', 'advanceFloor'],
        'likely_functions': ['advanceFloor', 'nextFloor'],
    },
    'act': {
        'files': [
            'src/game/GameContext.cpp',
        ],
        'likely_issue': 'Act progression',
        'search_terms': ['act', 'actNum'],
        'likely_functions': ['advanceFloor'],
    },
    'screen_state': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Game.cpp',
        ],
        'likely_issue': 'Screen state transitions',
        'search_terms': ['screen_state', 'screenState', 'openScreen'],
        'likely_functions': ['setState', 'openScreen'],
    },

    # Relic discrepancies
    'relics.*': {
        'files': [
            'src/game/Relic.cpp',
            'src/game/RelicEffects.cpp',
        ],
        'likely_issue': 'Relic addition, removal, or effects',
        'search_terms': ['relic', 'addRelic', 'onEquip'],
        'likely_functions': ['addRelic', 'onEquip', 'onTrigger'],
    },
    'relics.count': {
        'files': [
            'src/game/GameContext.cpp',
            'src/game/Relic.cpp',
        ],
        'likely_issue': 'Relic list management',
        'search_terms': ['relics', 'addRelic'],
        'likely_functions': ['addRelic', 'removeRelic'],
    },

    # Potion discrepancies
    'potions.*': {
        'files': [
            'src/game/Potion.cpp',
            'src/game/GameContext.cpp',
        ],
        'likely_issue': 'Potion use, gain, or discard',
        'search_terms': ['potion', 'usePotion', 'obtainPotion'],
        'likely_functions': ['usePotion', 'obtainPotion', 'discardPotion'],
    },
}


class FixAnalyzer:
    """Analyzes discrepancies and generates fix suggestions.

    This class maps state discrepancies to relevant C++ source files
    and generates actionable suggestions for fixing bugs.
    """

    def __init__(self, project_root: Optional[str] = None):
        """Initialize the fix analyzer.

        Args:
            project_root: Root directory of the project (for file lookups).
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self._discrepancy_map = DISCREPANCY_TO_CODE.copy()

    def analyze_discrepancy(
        self,
        field: str,
        game_value: Any,
        sim_value: Any,
        severity: str = "major"
    ) -> FixSuggestion:
        """Analyze a single discrepancy and generate a fix suggestion.

        Args:
            field: The field path (e.g., 'monster[0].cur_hp').
            game_value: Value from the game.
            sim_value: Value from the simulator.
            severity: Discrepancy severity.

        Returns:
            FixSuggestion with relevant code locations.
        """
        # Find matching pattern
        pattern_data = self._find_pattern(field)

        if pattern_data is None:
            return FixSuggestion(
                field=field,
                issue_type='unknown',
                description=f"Unknown discrepancy field: {field}",
                priority=severity,
            )

        # Build suggestion
        issue_type = pattern_data.get('likely_issue', 'unknown')

        # Determine description based on values
        if game_value is None and sim_value is not None:
            description = f"Simulator has value '{sim_value}' but game has none for {field}"
        elif game_value is not None and sim_value is None:
            description = f"Game has value '{game_value}' but simulator has none for {field}"
        else:
            description = f"Value mismatch for {field}: game={game_value}, sim={sim_value}"

        return FixSuggestion(
            field=field,
            issue_type=issue_type,
            description=description,
            files=pattern_data.get('files', []),
            search_terms=pattern_data.get('search_terms', []),
            likely_functions=pattern_data.get('likely_functions', []),
            related_patterns=self._find_related_patterns(field),
            priority=severity,
        )

    def analyze_discrepancies(
        self,
        discrepancies: List[Dict[str, Any]]
    ) -> List[FixSuggestion]:
        """Analyze multiple discrepancies.

        Args:
            discrepancies: List of discrepancy dictionaries.

        Returns:
            List of FixSuggestions.
        """
        suggestions = []
        for disc in discrepancies:
            field = disc.get('field', '')
            game_value = disc.get('game_value')
            sim_value = disc.get('sim_value')
            severity = disc.get('severity', 'major')

            suggestion = self.analyze_discrepancy(
                field, game_value, sim_value, severity
            )
            suggestions.append(suggestion)

        return suggestions

    def _find_pattern(self, field: str) -> Optional[Dict[str, Any]]:
        """Find a matching pattern for a field.

        Args:
            field: The field path.

        Returns:
            Pattern data or None if no match.
        """
        # Try exact match first
        if field in self._discrepancy_map:
            return self._discrepancy_map[field]

        # Try pattern matching (e.g., 'monster[0].cur_hp' matches 'monster[*].cur_hp')
        field_lower = field.lower()
        for pattern, data in self._discrepancy_map.items():
            # Handle wildcard patterns
            if '*' in pattern:
                # Convert pattern to regex-like matching
                pattern_parts = pattern.split('.')
                field_parts = field.split('.')

                if len(pattern_parts) != len(field_parts):
                    continue

                match = True
                for pp, fp in zip(pattern_parts, field_parts):
                    if pp == '*':
                        continue
                    if '[' in pp:
                        # Handle array patterns like monster[*]
                        base_pattern = pp.split('[')[0]
                        base_field = fp.split('[')[0]
                        if base_pattern != base_field:
                            match = False
                            break
                    elif pp != fp:
                        match = False
                        break

                if match:
                    return data

        # Try partial match
        for pattern, data in self._discrepancy_map.items():
            pattern_base = pattern.split('.')[0].split('[')[0]
            field_base = field.split('.')[0].split('[')[0]
            if pattern_base and field_base and pattern_base == field_base:
                return data

        return None

    def _find_related_patterns(self, field: str) -> List[str]:
        """Find related field patterns.

        Args:
            field: The field path.

        Returns:
            List of related patterns.
        """
        related = []
        base = field.split('.')[0].split('[')[0]

        for pattern in self._discrepancy_map.keys():
            if pattern != field:
                pattern_base = pattern.split('.')[0].split('[')[0]
                if pattern_base == base:
                    related.append(pattern)

        return related[:5]  # Limit to 5 related patterns

    def find_code_references(
        self,
        search_term: str,
        file_patterns: Optional[List[str]] = None
    ) -> List[CodeLocation]:
        """Find code references for a search term using grep.

        Args:
            search_term: Term to search for.
            file_patterns: Optional list of file patterns to search.

        Returns:
            List of CodeLocation references.
        """
        locations = []
        src_dir = self.project_root / 'src'

        if not src_dir.exists():
            return locations

        try:
            # Build grep command
            cmd = ['grep', '-rn', '--include=*.cpp', '--include=*.h']
            if file_patterns:
                for fp in file_patterns:
                    cmd.extend(['--include', fp])
            cmd.extend([search_term, str(src_dir)])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )

            for line in result.stdout.split('\n')[:20]:  # Limit results
                if ':' in line:
                    parts = line.split(':', 2)
                    if len(parts) >= 2:
                        file_path = parts[0]
                        try:
                            line_num = int(parts[1])
                        except ValueError:
                            continue

                        rel_path = os.path.relpath(file_path, self.project_root)
                        locations.append(CodeLocation(
                            file=rel_path,
                            line=line_num,
                            description=parts[2].strip() if len(parts) > 2 else ""
                        ))

        except Exception:
            pass

        return locations

    def generate_fix_report(
        self,
        suggestions: List[FixSuggestion],
        include_code_refs: bool = False
    ) -> str:
        """Generate a Markdown report from fix suggestions.

        Args:
            suggestions: List of FixSuggestions.
            include_code_refs: Whether to include grep code references.

        Returns:
            Markdown report string.
        """
        lines = []
        lines.append("# Fix Analysis Report")
        lines.append("")
        lines.append(f"Generated: {self._timestamp()}")
        lines.append(f"Total suggestions: {len(suggestions)}")
        lines.append("")

        # Group by priority
        high_priority = [s for s in suggestions if s.priority == 'critical' or s.priority == 'high']
        normal_priority = [s for s in suggestions if s.priority == 'normal' or s.priority == 'major']
        low_priority = [s for s in suggestions if s.priority not in ('critical', 'high', 'normal', 'major')]

        if high_priority:
            lines.append("## High Priority")
            lines.append("")
            for s in high_priority:
                lines.extend(self._format_suggestion(s, include_code_refs))
                lines.append("")

        if normal_priority:
            lines.append("## Normal Priority")
            lines.append("")
            for s in normal_priority:
                lines.extend(self._format_suggestion(s, include_code_refs))
                lines.append("")

        if low_priority:
            lines.append("## Low Priority")
            lines.append("")
            for s in low_priority:
                lines.extend(self._format_suggestion(s, include_code_refs))
                lines.append("")

        return "\n".join(lines)

    def _format_suggestion(
        self,
        suggestion: FixSuggestion,
        include_code_refs: bool
    ) -> List[str]:
        """Format a single suggestion as Markdown lines."""
        lines = []

        lines.append(f"### `{suggestion.field}`")
        lines.append("")
        lines.append(f"**Issue**: {suggestion.issue_type}")
        lines.append("")
        lines.append(f"**Description**: {suggestion.description}")
        lines.append("")

        if suggestion.files:
            lines.append("**Files to check**:")
            lines.append("")
            for f in suggestion.files:
                lines.append(f"- `{f}`")
            lines.append("")

        if suggestion.search_terms:
            lines.append("**Search terms**:")
            lines.append("")
            lines.append(", ".join(f"`{t}`" for t in suggestion.search_terms))
            lines.append("")

        if suggestion.likely_functions:
            lines.append("**Likely functions**:")
            lines.append("")
            lines.append(", ".join(f"`{f}()`" for f in suggestion.likely_functions))
            lines.append("")

        if suggestion.related_patterns:
            lines.append("**Related fields**:")
            lines.append("")
            lines.append(", ".join(f"`{p}`" for p in suggestion.related_patterns))
            lines.append("")

        if include_code_refs and suggestion.search_terms:
            lines.append("**Code references**:")
            lines.append("")
            for term in suggestion.search_terms[:2]:
                refs = self.find_code_references(term, suggestion.files)
                if refs:
                    lines.append(f"Searching for `{term}`:")
                    for ref in refs[:5]:
                        lines.append(f"- {ref.file}:{ref.line} - {ref.description[:50]}")
                    lines.append("")

        return lines

    def _timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().isoformat()

    def add_pattern(
        self,
        field_pattern: str,
        files: List[str],
        likely_issue: str,
        search_terms: Optional[List[str]] = None,
        likely_functions: Optional[List[str]] = None
    ):
        """Add a custom pattern mapping.

        Args:
            field_pattern: Field pattern to match.
            files: List of relevant files.
            likely_issue: Description of the likely issue.
            search_terms: Optional search terms.
            likely_functions: Optional likely function names.
        """
        self._discrepancy_map[field_pattern] = {
            'files': files,
            'likely_issue': likely_issue,
            'search_terms': search_terms or [],
            'likely_functions': likely_functions or [],
        }
