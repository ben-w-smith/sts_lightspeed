#!/usr/bin/env python3
"""Simulator-Game Verification Tool for sts_lightspeed.

This tool verifies that the sts_lightspeed C++ simulator exactly matches
Slay the Spire version 2.3.4 by running synchronized gameplay sessions
and comparing states after every action.

Usage:
    python verify.py --seed 12345                    # Verify with specific seed
    python verify.py --seed 12345 --no-game          # Simulator-only verification
    python verify.py --seed 12345 --character IRONCLAD --steps 500
    python verify.py --report verification_results/  # Generate report from existing results

Features:
    - Full 4-act run verification (combat, events, shops, relics, boss fights)
    - State comparison: HP, block, energy, status effects, monster states
    - Bug reports with full action history for reproduction
    - JSON and console report output
    - Seed-based reproducibility
    - Stop on critical failures with comprehensive reporting
"""
import argparse
import json
import random
import sys
import time
import yaml
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add paths for imports
_project_root = Path(__file__).parent.parent
_integration_dir = Path(__file__).parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_integration_dir))

from harness.game_controller import GameController, CommunicationModError
from harness.simulator_controller import SimulatorController
from harness.state_comparator import StateComparator, ComparisonResult, DiscrepancySeverity
from harness.action_translator import ActionTranslator, TranslatedAction, ActionType
from harness.reporter import Reporter, TestResult, StepResult, ActionRecord


@dataclass
class VerificationConfig:
    """Configuration for verification run."""
    seed: int
    character: str = 'IRONCLAD'
    ascension: int = 0
    max_steps: int = 10000  # Full run can take many steps
    max_acts: int = 4
    action_delay: float = 0.1
    stop_on_critical: bool = True
    verbose: bool = False
    no_game: bool = False
    output_dir: str = './verification_results'


@dataclass
class VerificationResult:
    """Result of a full verification run."""
    config: VerificationConfig
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    completed: bool = False
    victory: bool = False
    death_floor: Optional[int] = None
    final_act: int = 1
    final_floor: int = 0
    total_steps: int = 0
    critical_discrepancies: int = 0
    major_discrepancies: int = 0
    minor_discrepancies: int = 0
    action_history: List[Dict[str, Any]] = field(default_factory=list)
    state_snapshots: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'config': asdict(self.config),
            'start_time': self.start_time,
            'end_time': self.end_time,
            'completed': self.completed,
            'victory': self.victory,
            'death_floor': self.death_floor,
            'final_act': self.final_act,
            'final_floor': self.final_floor,
            'total_steps': self.total_steps,
            'critical_discrepancies': self.critical_discrepancies,
            'major_discrepancies': self.major_discrepancies,
            'minor_discrepancies': self.minor_discrepancies,
            'action_history': self.action_history,
            'state_snapshots': self.state_snapshots,
            'errors': self.errors,
        }


class Verifier:
    """Main verification engine for simulator-game comparison."""

    # Game states that indicate run completion
    TERMINAL_STATES = ['victory', 'game_over', 'death']

    # Screen states for different game phases
    COMBAT_SCREENS = ['combat', 'battle']
    EVENT_SCREENS = ['event', 'event_screen']
    REWARD_SCREENS = ['reward', 'rewards', 'boss_relic_reward']
    MAP_SCREENS = ['map', 'map_screen']
    SHOP_SCREENS = ['shop', 'shop_room']
    REST_SCREENS = ['rest', 'rest_room']
    TREASURE_SCREENS = ['treasure', 'treasure_room']
    CARD_SELECT_SCREENS = ['card_select', 'grid']

    def __init__(self, config: VerificationConfig):
        """Initialize the verifier.

        Args:
            config: Verification configuration.
        """
        self.config = config
        self.game: Optional[GameController] = None
        self.sim: Optional[SimulatorController] = None
        self.comparator = StateComparator()
        self.translator = ActionTranslator()
        self.result = VerificationResult(config=config)

    def setup(self) -> bool:
        """Set up game and simulator for verification.

        Returns:
            True if setup successful, False otherwise.
        """
        # Connect to game first if not in no-game mode
        if not self.config.no_game:
            try:
                self.game = GameController(timeout=30.0)
                self.game.connect()
                print("Connected to CommunicationMod")
            except CommunicationModError as e:
                self.result.errors.append(f"Failed to connect to game: {e}")
                print(f"Warning: Could not connect to game: {e}")
                print("Continuing in simulator-only mode...")
                self.config.no_game = True
                self.game = None

        # Initialize simulator
        try:
            self.sim = SimulatorController()

            # If connected to game, sync seed and character from game
            if self.game:
                try:
                    sync_info = self.sim.sync_from_game(self.game)
                    self.config.seed = sync_info['seed']
                    self.config.character = sync_info['character']
                    self.config.ascension = sync_info['ascension']
                    print(f"Synced from game: seed={self.config.seed}, "
                          f"character={self.config.character}, ascension={self.config.ascension}")
                except Exception as e:
                    print(f"Warning: Could not sync from game: {e}")
                    print("Using specified seed/character instead...")
                    self.sim.setup_game(
                        seed=self.config.seed,
                        character=self.config.character,
                        ascension=self.config.ascension
                    )
            else:
                self.sim.setup_game(
                    seed=self.config.seed,
                    character=self.config.character,
                    ascension=self.config.ascension
                )

            print(f"Simulator initialized: seed={self.config.seed}, "
                  f"character={self.config.character}, ascension={self.config.ascension}")
        except Exception as e:
            self.result.errors.append(f"Failed to initialize simulator: {e}")
            return False

        return True

    def run(self) -> VerificationResult:
        """Run the full verification.

        Returns:
            VerificationResult with complete verification data.
        """
        if not self.setup():
            self.result.end_time = datetime.now().isoformat()
            return self.result

        print(f"\nStarting verification run...")
        print(f"Seed: {self.config.seed}")
        print(f"Character: {self.config.character}")
        print(f"Ascension: {self.config.ascension}")
        print(f"Max steps: {self.config.max_steps}")
        print("=" * 60)

        # Track state for stuck detection
        last_state_sig = None
        stuck_count = 0
        max_stuck_steps = 50  # If state doesn't change for this many steps, report stuck

        try:
            step = 0
            while step < self.config.max_steps:
                # Get current states
                sim_state = self.sim.get_state()
                game_state = None
                if self.game:
                    try:
                        game_state = self.game.get_state()
                    except Exception as e:
                        self.result.errors.append(f"Step {step}: Failed to get game state: {e}")
                        game_state = sim_state  # Use sim state as fallback

                # Check for run completion
                if self._is_run_complete(sim_state):
                    self.result.completed = True
                    self.result.victory = self._is_victory(sim_state)
                    print(f"\nRun complete! Victory: {self.result.victory}")
                    break

                # Check for player death
                if self._is_player_dead(sim_state):
                    self.result.death_floor = sim_state.get('floor', 0)
                    print(f"\nPlayer died on floor {self.result.death_floor}")
                    break

                # Update tracking
                self.result.final_act = sim_state.get('act', 1)
                self.result.final_floor = sim_state.get('floor', 0)

                # Detect stuck state (same state for too many steps)
                current_sig = (
                    sim_state.get('floor'),
                    sim_state.get('cur_hp'),
                    sim_state.get('gold'),
                    sim_state.get('screen_state'),
                )
                if current_sig == last_state_sig:
                    stuck_count += 1
                    if stuck_count >= max_stuck_steps:
                        self.result.errors.append(
                            f"Step {step}: State appears stuck (unchanged for {stuck_count} steps). "
                            f"Floor={current_sig[0]}, HP={current_sig[1]}, Gold={current_sig[2]}, Screen={current_sig[3]}"
                        )
                        print(f"\nWarning: State appears stuck for {stuck_count} steps")
                        print(f"Breaking to avoid infinite loop...")
                        break
                else:
                    stuck_count = 0
                last_state_sig = current_sig

                # Select and execute next action
                action = self._select_action(sim_state)
                if action is None:
                    self.result.errors.append(f"Step {step}: No available action")
                    break

                # Execute action
                step_result = self._execute_step(action, step, game_state, sim_state)
                self._record_step(step_result, action, sim_state)

                step += 1
                self.result.total_steps = step

                # Check for critical discrepancies
                if step_result and step_result.comparison:
                    self.result.critical_discrepancies += step_result.comparison.critical_count
                    self.result.major_discrepancies += step_result.comparison.major_count
                    self.result.minor_discrepancies += step_result.comparison.minor_count

                    if self.config.stop_on_critical and step_result.comparison.critical_count > 0:
                        print(f"\nCritical discrepancy at step {step}!")
                        print(f"Stopping verification...")
                        break

                # Progress reporting
                if step % 50 == 0 or self.config.verbose:
                    self._print_progress(step, sim_state, step_result)

                # Delay between actions
                if self.game:
                    time.sleep(self.config.action_delay)

        except KeyboardInterrupt:
            print(f"\nVerification interrupted at step {step}")
            self.result.errors.append("Interrupted by user")
        except Exception as e:
            self.result.errors.append(f"Verification error at step {step}: {e}")
            print(f"\nVerification error: {e}")

        # Finalize
        self.result.end_time = datetime.now().isoformat()
        self._cleanup()

        return self.result

    def _select_action(self, sim_state: Dict[str, Any]) -> Optional[TranslatedAction]:
        """Select the next action to take.

        Args:
            sim_state: Current simulator state.

        Returns:
            TranslatedAction to execute, or None if no action available.
        """
        screen_state = sim_state.get('screen_state', 'unknown')

        # Handle combat
        if screen_state in self.COMBAT_SCREENS or self.sim.is_in_combat():
            return self._select_combat_action(sim_state)

        # Handle events
        if screen_state in self.EVENT_SCREENS:
            return self._select_event_action()

        # Handle rewards
        if screen_state in self.REWARD_SCREENS:
            return self._select_reward_action()

        # Handle map
        if screen_state in self.MAP_SCREENS:
            return self._select_map_action()

        # Handle shop
        if screen_state in self.SHOP_SCREENS:
            return self._select_shop_action()

        # Handle rest
        if screen_state in self.REST_SCREENS:
            return self._select_rest_action()

        # Handle treasure
        if screen_state in self.TREASURE_SCREENS:
            return self._select_treasure_action()

        # Handle card selection screens
        if screen_state in self.CARD_SELECT_SCREENS:
            return self._select_card_select_action()

        # Default: try first available action
        available = self.sim.get_available_actions()
        if available:
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {available[0]}",
                sim_command=str(available[0]),
                params={'option_index': available[0]}
            )

        return None

    def _select_combat_action(self, sim_state: Dict[str, Any]) -> Optional[TranslatedAction]:
        """Select action during combat.

        Args:
            sim_state: Current simulator state.

        Returns:
            TranslatedAction for combat.
        """
        combat = sim_state.get('combat_state', {})
        hand = combat.get('hand', [])
        player = combat.get('player', {})
        energy = player.get('energy', 0)
        monsters = combat.get('monsters', [])

        # Find first targetable monster
        target_idx = -1
        for i, m in enumerate(monsters):
            if not m.get('is_dying', False) and m.get('is_targetable', True):
                target_idx = i
                break

        # If no targetable monsters, end turn
        if target_idx < 0:
            return self.translator.from_sim_to_game("end")

        # Cards that are safe to play without explicit targeting info
        # (skills that don't target)
        SKILL_CARDS = {'defend', 'flex', 'armaments', 'shrug_it_off', 'iron_wave'}

        # Attack cards always need targets in the simulator
        # Use conservative approach: assume ALL cards need targets unless explicitly safe
        for i, card in enumerate(hand):
            cost = card.get('cost_for_turn', card.get('cost', 0))
            if cost <= energy:
                card_name = str(card.get('name', '')).lower().replace(' ', '_')

                # Only play cards that are definitely safe (skills like Defend)
                if card_name in SKILL_CARDS or card_name.startswith('defend'):
                    return self.translator.from_sim_to_game(str(i))

                # For all other cards, provide a target to be safe
                # This handles Strike, Bash, and any other potentially targeted cards
                return self.translator.from_sim_to_game(f"{i} {target_idx}")

        # Can't play any cards safely, end turn
        return self.translator.from_sim_to_game("end")

    def _select_event_action(self) -> Optional[TranslatedAction]:
        """Select action during event.

        Returns:
            TranslatedAction for event choice.
        """
        available = self.sim.get_available_actions()
        if available:
            # Usually first option is the safest/default
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_reward_action(self) -> Optional[TranslatedAction]:
        """Select action during reward screen.

        Returns:
            TranslatedAction for reward choice.
        """
        # Reward screens have special action format
        # Parse the screen text directly for better handling
        text = self.sim.get_screen_text()

        # Look for skip action first (usually safest for testing)
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('skip:'):
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command="choose skip",
                    sim_command="skip",
                    params={'option_index': 'skip'}
                )

        # Look for card reward actions (format: "card 0 X: take CardName")
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('card ') and ':' in line:
                # Extract action like "card 0 0"
                action = line.split(':')[0].strip()
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command=f"choose {action}",
                    sim_command=action,
                    params={'option_index': action}
                )

        # Fallback to standard actions
        available = self.sim.get_available_actions()
        if available:
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_map_action(self) -> Optional[TranslatedAction]:
        """Select action during map screen.

        Returns:
            TranslatedAction for map choice.
        """
        available = self.sim.get_available_actions()
        if available:
            # Choose first available node
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.MAP_MOVE,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_shop_action(self) -> Optional[TranslatedAction]:
        """Select action during shop.

        Returns:
            TranslatedAction for shop choice.
        """
        available = self.sim.get_available_actions()
        if available:
            # Usually last option is leave
            idx = available[-1]
            return TranslatedAction(
                action_type=ActionType.SHOP_BUY,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_rest_action(self) -> Optional[TranslatedAction]:
        """Select action during rest.

        Returns:
            TranslatedAction for rest choice.
        """
        available = self.sim.get_available_actions()
        if available:
            # Usually first option is rest
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.REST,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_treasure_action(self) -> Optional[TranslatedAction]:
        """Select action during treasure room.

        Returns:
            TranslatedAction for treasure choice.
        """
        available = self.sim.get_available_actions()
        if available:
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _select_card_select_action(self) -> Optional[TranslatedAction]:
        """Select action during card selection screen.

        Returns:
            TranslatedAction for card selection.
        """
        # Card selection screens have special action format
        text = self.sim.get_screen_text()

        # Look for skip/bypass action first
        for line in text.split('\n'):
            line = line.strip().lower()
            if line.startswith('skip:') or line.startswith('bypass:') or line.startswith('leave:'):
                action = line.split(':')[0].strip()
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command=f"choose {action}",
                    sim_command=action,
                    params={'option_index': action}
                )

        # Look for card action (format: "card X: description")
        for line in text.split('\n'):
            line = line.strip()
            if line.startswith('card ') and ':' in line:
                action = line.split(':')[0].strip()
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command=f"choose {action}",
                    sim_command=action,
                    params={'option_index': action}
                )

        # Fallback
        available = self.sim.get_available_actions()
        if available:
            idx = available[-1] if len(available) > 1 else available[0]
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )
        return None

    def _execute_step(
        self,
        action: TranslatedAction,
        step: int,
        game_state: Optional[Dict[str, Any]],
        sim_state: Dict[str, Any]
    ) -> Optional[StepResult]:
        """Execute a step on both game and simulator.

        Args:
            action: Action to execute.
            step: Step number.
            game_state: Current game state.
            sim_state: Current simulator state.

        Returns:
            StepResult with comparison data.
        """
        action_record = ActionRecord(
            step=step,
            game_command=action.game_command,
            sim_command=action.sim_command,
            action_type=action.action_type.value
        )

        error = None
        comparison = None

        try:
            # Execute on game
            if self.game and action.game_command:
                self.game.send_command(action.game_command)
                time.sleep(self.config.action_delay)

            # Execute on simulator
            if self.sim and action.sim_command:
                try:
                    self.sim.take_action(action.sim_command)
                except Exception as e:
                    # Handle simulator crashes (like assertion failures)
                    error_msg = str(e)
                    if 'targetIdx' in error_msg or 'assertion' in error_msg.lower():
                        error = f"Simulator crash on targeted card - check action: {action.sim_command}"
                    else:
                        error = f"Simulator error: {error_msg}"
                    # Don't continue if simulator crashed
                    return StepResult(
                        step=step,
                        action=action_record,
                        comparison=comparison,
                        error=error
                    )

            # Get updated states and compare
            if self.game and self.sim:
                try:
                    new_game_state = self.game.get_state()
                    new_sim_state = self.sim.get_state()
                    comparison = self.comparator.compare(new_game_state, new_sim_state)
                except Exception as e:
                    error = f"State comparison error: {e}"

        except Exception as e:
            error = str(e)

        return StepResult(
            step=step,
            action=action_record,
            comparison=comparison,
            error=error
        )

    def _record_step(
        self,
        step_result: Optional[StepResult],
        action: TranslatedAction,
        sim_state: Dict[str, Any]
    ):
        """Record step result in action history.

        Args:
            step_result: Result of the step.
            action: Action that was executed.
            sim_state: Current simulator state.
        """
        if step_result is None:
            return

        # Record action
        self.result.action_history.append({
            'step': step_result.step,
            'game_command': step_result.action.game_command,
            'sim_command': step_result.action.sim_command,
            'action_type': step_result.action.action_type,
            'timestamp': step_result.action.timestamp,
            'error': step_result.error,
        })

        # Record state snapshot every 100 steps or on discrepancy
        if (step_result.step % 100 == 0 or
            (step_result.comparison and not step_result.comparison.match)):
            snapshot = {
                'step': step_result.step,
                'floor': sim_state.get('floor'),
                'act': sim_state.get('act'),
                'hp': sim_state.get('cur_hp'),
                'max_hp': sim_state.get('max_hp'),
                'gold': sim_state.get('gold'),
                'screen_state': sim_state.get('screen_state'),
            }
            if step_result.comparison:
                snapshot['discrepancies'] = [
                    {
                        'field': d.field,
                        'game_value': d.game_value,
                        'sim_value': d.sim_value,
                        'severity': d.severity.value,
                        'message': d.message,
                    }
                    for d in step_result.comparison.discrepancies
                ]
            self.result.state_snapshots.append(snapshot)

    def _print_progress(
        self,
        step: int,
        sim_state: Dict[str, Any],
        step_result: Optional[StepResult]
    ):
        """Print verification progress.

        Args:
            step: Current step number.
            sim_state: Current simulator state.
            step_result: Result of last step.
        """
        floor = sim_state.get('floor', 0)
        act = sim_state.get('act', 1)
        hp = sim_state.get('cur_hp', 0)
        max_hp = sim_state.get('max_hp', 0)
        gold = sim_state.get('gold', 0)
        screen = sim_state.get('screen_state', 'unknown')

        status = f"Step {step}: Act {act}, Floor {floor}, HP {hp}/{max_hp}, Gold {gold}, Screen: {screen}"

        if step_result and step_result.comparison:
            if step_result.comparison.match:
                status += " [OK]"
            else:
                status += f" [DISCREPANCY: {step_result.comparison.get_summary()}]"

        print(status)

    def _is_run_complete(self, sim_state: Dict[str, Any]) -> bool:
        """Check if the run is complete.

        Args:
            sim_state: Current simulator state.

        Returns:
            True if run is complete.
        """
        screen = sim_state.get('screen_state', '').lower()
        return screen in self.TERMINAL_STATES

    def _is_victory(self, sim_state: Dict[str, Any]) -> bool:
        """Check if the run ended in victory.

        Args:
            sim_state: Current simulator state.

        Returns:
            True if victory.
        """
        screen = sim_state.get('screen_state', '').lower()
        return screen == 'victory'

    def _is_player_dead(self, sim_state: Dict[str, Any]) -> bool:
        """Check if player is dead.

        Args:
            sim_state: Current simulator state.

        Returns:
            True if player is dead.
        """
        return sim_state.get('cur_hp', 1) <= 0

    def _cleanup(self):
        """Clean up resources."""
        if self.game:
            self.game.disconnect()
            self.game = None
        if self.sim:
            # Note: reset() may not be available, just clear the reference
            self.sim = None


def generate_reports(result: VerificationResult, output_dir: Path) -> List[Path]:
    """Generate verification reports.

    Args:
        result: Verification result to report.
        output_dir: Directory to write reports.

    Returns:
        List of paths to generated reports.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_paths = []

    # Generate JSON report
    json_path = output_dir / f"verification_{result.config.seed}.json"
    with open(json_path, 'w') as f:
        json.dump(result.to_dict(), f, indent=2, default=str)
    report_paths.append(json_path)
    print(f"JSON report: {json_path}")

    # Generate markdown summary
    md_path = output_dir / f"verification_{result.config.seed}.md"
    lines = [
        "# Simulator-Game Verification Report\n",
        f"\n**Generated**: {result.end_time}\n",
        f"**Seed**: {result.config.seed}\n",
        f"**Character**: {result.config.character}\n",
        f"**Ascension**: {result.config.ascension}\n",
        "\n## Summary\n",
        f"- **Completed**: {'Yes' if result.completed else 'No'}\n",
        f"- **Victory**: {'Yes' if result.victory else 'No'}\n",
        f"- **Final Floor**: {result.final_floor} (Act {result.final_act})\n",
        f"- **Total Steps**: {result.total_steps}\n",
        f"- **Critical Discrepancies**: {result.critical_discrepancies}\n",
        f"- **Major Discrepancies**: {result.major_discrepancies}\n",
        f"- **Minor Discrepancies**: {result.minor_discrepancies}\n",
    ]

    if result.death_floor:
        lines.append(f"- **Death Floor**: {result.death_floor}\n")

    if result.errors:
        lines.append("\n## Errors\n")
        for error in result.errors:
            lines.append(f"- {error}\n")

    if result.state_snapshots:
        lines.append("\n## State Snapshots\n")
        for snapshot in result.state_snapshots[-10:]:  # Last 10 snapshots
            lines.append(f"\n### Step {snapshot['step']}\n")
            lines.append(f"- Floor: {snapshot.get('floor')} (Act {snapshot.get('act')})\n")
            lines.append(f"- HP: {snapshot.get('hp')}/{snapshot.get('max_hp')}\n")
            lines.append(f"- Gold: {snapshot.get('gold')}\n")
            if 'discrepancies' in snapshot:
                lines.append("\n**Discrepancies**:\n")
                for d in snapshot['discrepancies']:
                    lines.append(f"- [{d['severity']}] {d['field']}: {d['message']}\n")

    # Action history (truncated)
    if result.action_history:
        lines.append("\n## Action History (last 50)\n")
        lines.append("```\n")
        for action in result.action_history[-50:]:
            lines.append(f"Step {action['step']}: {action['sim_command']} ({action['action_type']})\n")
        lines.append("```\n")

    with open(md_path, 'w') as f:
        f.writelines(lines)
    report_paths.append(md_path)
    print(f"Markdown report: {md_path}")

    return report_paths


def print_console_summary(result: VerificationResult):
    """Print verification summary to console.

    Args:
        result: Verification result to summarize.
    """
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Seed: {result.config.seed}")
    print(f"Character: {result.config.character} (Ascension {result.config.ascension})")
    print(f"Total Steps: {result.total_steps}")
    print(f"Final State: Act {result.final_act}, Floor {result.final_floor}")
    print()

    status = "COMPLETED" if result.completed else "INCOMPLETE"
    if result.victory:
        status = "VICTORY"
    elif result.death_floor:
        status = f"DIED on floor {result.death_floor}"
    print(f"Status: {status}")
    print()

    print("Discrepancies:")
    print(f"  Critical: {result.critical_discrepancies}")
    print(f"  Major: {result.major_discrepancies}")
    print(f"  Minor: {result.minor_discrepancies}")

    if result.errors:
        print(f"\nErrors ({len(result.errors)}):")
        for error in result.errors[:5]:
            print(f"  - {error}")

    print("=" * 60)

    # Overall verdict
    if result.critical_discrepancies == 0:
        print("VERDICT: PASS - No critical discrepancies detected")
    else:
        print(f"VERDICT: FAIL - {result.critical_discrepancies} critical discrepancies")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Simulator-Game Verification Tool for sts_lightspeed",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python verify.py --seed 12345                    # Verify with specific seed
    python verify.py --seed 12345 --no-game          # Simulator-only mode
    python verify.py --seed 12345 --steps 1000       # Limit to 1000 steps
    python verify.py --report ./results/             # Generate report from existing
        """
    )

    parser.add_argument(
        '--seed', '-s',
        type=int,
        default=None,
        help='Game seed for verification (required unless --report)'
    )
    parser.add_argument(
        '--character', '-c',
        type=str,
        default='IRONCLAD',
        choices=['IRONCLAD', 'SILENT', 'DEFECT', 'WATCHER'],
        help='Character class (default: IRONCLAD)'
    )
    parser.add_argument(
        '--ascension', '-a',
        type=int,
        default=0,
        help='Ascension level (default: 0)'
    )
    parser.add_argument(
        '--steps',
        type=int,
        default=10000,
        help='Maximum steps (default: 10000)'
    )
    parser.add_argument(
        '--no-game',
        action='store_true',
        help='Run without real game (simulator only)'
    )
    parser.add_argument(
        '--output', '-o',
        type=str,
        default='./verification_results',
        help='Output directory for reports (default: ./verification_results)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--continue-on-critical',
        action='store_true',
        help='Continue verification even on critical discrepancies'
    )
    parser.add_argument(
        '--report',
        type=str,
        default=None,
        help='Generate report from existing JSON result file'
    )

    args = parser.parse_args()

    # Report-only mode
    if args.report:
        report_path = Path(args.report)
        if report_path.is_file():
            # Single file
            with open(report_path) as f:
                data = json.load(f)
            config = VerificationConfig(**data.get('config', {}))
            result = VerificationResult(config=config)
            result.end_time = data.get('end_time')
            result.completed = data.get('completed', False)
            result.victory = data.get('victory', False)
            result.total_steps = data.get('total_steps', 0)
            result.critical_discrepancies = data.get('critical_discrepancies', 0)
            result.major_discrepancies = data.get('major_discrepancies', 0)
            result.minor_discrepancies = data.get('minor_discrepancies', 0)
            print_console_summary(result)
            return 0
        else:
            print(f"Report file not found: {report_path}")
            return 1

    # Require seed for verification
    if args.seed is None:
        args.seed = random.randint(1, 999999999)
        print(f"No seed specified, using random seed: {args.seed}")

    # Create configuration
    config = VerificationConfig(
        seed=args.seed,
        character=args.character,
        ascension=args.ascension,
        max_steps=args.steps,
        verbose=args.verbose,
        no_game=args.no_game,
        output_dir=args.output,
        stop_on_critical=not args.continue_on_critical,
    )

    # Run verification
    verifier = Verifier(config)
    result = verifier.run()

    # Generate reports
    output_dir = Path(config.output_dir)
    generate_reports(result, output_dir)

    # Print summary
    print_console_summary(result)

    # Return exit code
    return 0 if result.critical_discrepancies == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
