#!/usr/bin/env python3
"""Main test runner for Slay the Spire integration tests.

This script synchronizes the sts_lightspeed simulator with the real game
via CommunicationMod and compares states to validate simulator accuracy.

Usage:
    python run_tests.py --quick                    # Quick smoke test
    python run_tests.py --character IRONCLAD       # Test specific character
    python run_tests.py --test test_basic_strike   # Run specific test
    python run_tests.py --report-only test_results/  # Generate report from existing results
"""
import argparse
import json
import sys
import time
import yaml
from pathlib import Path
from typing import Optional, Callable, List, Tuple

# Add paths for imports
_project_root = Path(__file__).parent.parent  # worktree root
_integration_dir = Path(__file__).parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_integration_dir))

# Import from local integration harness (has state_comparator, action_translator)
from harness.game_controller import GameController, CommunicationModError
from harness.simulator_controller import SimulatorController
from harness.state_comparator import StateComparator, ComparisonResult
from harness.action_translator import ActionTranslator, TranslatedAction, ActionType
from harness.reporter import Reporter, TestResult, StepResult, ActionRecord

# Import from tests harness (has scenario_loader, seed_synchronizer, etc.)
from tests.integration.harness.scenario_loader import ScenarioLoader, Scenario, ScenarioStep


class TestRunner:
    """Main test runner that synchronizes game and simulator execution."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the test runner.

        Args:
            config_path: Path to config.yaml. Defaults to same directory as this file.
        """
        if config_path is None:
            config_path = Path(__file__).parent / "config.yaml"

        self.config = self._load_config(config_path)
        self.game: Optional[GameController] = None
        self.sim: Optional[SimulatorController] = None
        self.comparator = StateComparator(
            tolerances=self.config.get('comparison', {}).get('tolerances', {})
        )
        self.reporter = Reporter(
            output_dir=self.config.get('reporting', {}).get('output_dir', './test_results')
        )
        self.translator = ActionTranslator()
        self._current_result: Optional[TestResult] = None

    def _load_config(self, config_path: Path) -> dict:
        """Load configuration from YAML file."""
        if not config_path.exists():
            print(f"Warning: Config file not found at {config_path}, using defaults")
            return {}

        with open(config_path) as f:
            return yaml.safe_load(f)

    def connect_game(self) -> bool:
        """Connect to the real game via CommunicationMod.

        Returns:
            True if connection successful.
        """
        comm_config = self.config.get('communication_mod', {})
        state_dir = comm_config.get('state_dir', '/tmp/sts_bridge')
        timeout = comm_config.get('timeout', 30.0)

        self.game = GameController(state_dir=state_dir, timeout=timeout)

        try:
            self.game.connect()
            return True
        except CommunicationModError as e:
            print(f"Failed to connect to CommunicationMod: {e}")
            return False

    def disconnect_game(self):
        """Disconnect from the real game."""
        if self.game:
            self.game.disconnect()
            self.game = None

    def init_simulator(self, seed: int, character: str, ascension: int):
        """Initialize the simulator with the same parameters as the game.

        Args:
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
        """
        self.sim = SimulatorController()
        self.sim.setup_game(seed, character, ascension)
        print(f"Initialized simulator: seed={seed}, character={character}, ascension={ascension}")

    def run_synchronized_step(self, action: TranslatedAction) -> StepResult:
        """Execute an action on both game and simulator, then compare states.

        Args:
            action: Translated action to execute.

        Returns:
            StepResult with comparison data.
        """
        step_num = self._current_result.total_steps if self._current_result else 0

        # Record the action
        action_record = ActionRecord(
            step=step_num,
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
                time.sleep(self.config.get('test_execution', {}).get('action_delay', 0.1))

            # Execute on simulator
            if self.sim and action.sim_command:
                self.sim.take_action(action.sim_command)

            # Get states and compare
            if self.game and self.sim:
                game_state = self.game.get_state()
                sim_state = self.sim.get_state()
                comparison = self.comparator.compare(game_state, sim_state)

        except Exception as e:
            error = str(e)

        return StepResult(
            step=step_num,
            action=action_record,
            comparison=comparison,
            error=error
        )

    def run_test(
        self,
        test_name: str,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        action_generator: Optional[Callable] = None,
        max_steps: int = 1000
    ) -> TestResult:
        """Run a synchronized test.

        Args:
            test_name: Name for the test.
            seed: Game seed to use.
            character: Character class.
            ascension: Ascension level.
            action_generator: Optional function that yields actions.
                             If None, uses default action selection.
            max_steps: Maximum steps before stopping.

        Returns:
            TestResult with complete test data.
        """
        result = TestResult(
            test_name=test_name,
            seed=seed,
            character=character,
            ascension=ascension
        )
        self._current_result = result

        # Initialize simulator
        self.init_simulator(seed, character, ascension)

        # If connected to game, sync with game state
        if self.game:
            try:
                game_state = self.game.get_state()
                print(f"Game state: floor={game_state.get('floor')}, "
                      f"act={game_state.get('act')}, "
                      f"hp={game_state.get('current_hp')}/{game_state.get('max_hp')}")
            except Exception as e:
                print(f"Warning: Could not get initial game state: {e}")

        step = 0
        stop_on_critical = self.config.get('test_execution', {}).get('stop_on_critical', True)

        try:
            while step < max_steps:
                # Get next action
                if action_generator:
                    action = next(action_generator(self.sim, self.game), None)
                    if action is None:
                        break
                    if isinstance(action, str):
                        action = self.translator.from_sim_to_game(action)
                else:
                    # Default: use simulator's available actions
                    action = self._select_next_action()
                    if action is None:
                        break

                # Execute step
                step_result = self.run_synchronized_step(action)
                result.add_step(step_result)

                step += 1

                # Print progress
                if step % 10 == 0:
                    print(f"Step {step}: {step_result.comparison.get_summary() if step_result.comparison else 'no comparison'}")

                # Stop on critical failure if configured
                if stop_on_critical and step_result.comparison and step_result.comparison.critical_count > 0:
                    print(f"Stopping: Critical discrepancy detected at step {step}")
                    break

        except KeyboardInterrupt:
            print(f"\nTest interrupted at step {step}")
        except Exception as e:
            result.error_message = str(e)
            print(f"Test error at step {step}: {e}")

        result.finalize()

        # Store final states
        if self.game:
            try:
                result.final_game_state = self.game.get_state()
            except:
                pass
        if self.sim:
            result.final_sim_state = self.sim.get_state()

        self._current_result = None
        return result

    def _select_next_action(self) -> Optional[TranslatedAction]:
        """Select the next action to take (default implementation).

        Returns:
            TranslatedAction or None if no action available.
        """
        if not self.sim:
            return None

        screen_state = self.sim.get_screen_state()

        # Handle events - use "choose" command
        if screen_state == 'event':
            available = self.sim.get_available_actions()
            if available:
                # For events, use "choose <idx>" for game
                idx = available[0]
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command=f"choose {idx}",
                    sim_command=str(idx),
                    params={'option_index': idx}
                )

        # Check if in combat - need to handle targeted cards
        if self.sim.is_in_combat():
            state = self.sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])
            energy = combat.get('player', {}).get('energy', 0)
            monsters = combat.get('monsters', [])

            # Find first monster that's targetable
            target_idx = -1
            for i, m in enumerate(monsters):
                if not m.get('is_dying', False) and m.get('is_targetable', True):
                    target_idx = i
                    break

            # Find a playable card
            for i, card in enumerate(hand):
                cost = card.get('cost_for_turn', card.get('cost', 0))
                if cost <= energy:
                    # Check if card needs a target
                    if card.get('requires_target', False) and target_idx >= 0:
                        return self.translator.from_sim_to_game(f"{i} {target_idx}")
                    elif not card.get('requires_target', False):
                        return self.translator.from_sim_to_game(str(i))

            # Can't play any cards, end turn
            return self.translator.from_sim_to_game("end")

        # Handle rewards, map, etc.
        available = self.sim.get_available_actions()
        if available:
            # For non-event screens, use "choose" for game
            idx = available[0]
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=f"choose {idx}",
                sim_command=str(idx),
                params={'option_index': idx}
            )

        # No actions available - try to proceed
        if screen_state in ['reward', 'map']:
            return self.translator.from_sim_to_game("proceed")

        return None

    def run_quick_test(self, seed: int = 12345, character: str = 'IRONCLAD') -> TestResult:
        """Run a quick smoke test.

        Args:
            seed: Game seed.
            character: Character class.

        Returns:
            TestResult.
        """
        return self.run_test(
            test_name="quick_smoke_test",
            seed=seed,
            character=character,
            ascension=0,
            max_steps=self.config.get('scenarios', {}).get('quick', {}).get('max_steps', 50)
        )

    def run_scenario(self, scenario_path: str) -> TestResult:
        """Run a YAML scenario file.

        Args:
            scenario_path: Path to the YAML scenario file.

        Returns:
            TestResult with scenario execution results.
        """
        loader = ScenarioLoader()
        scenario = loader.load(scenario_path)

        result = TestResult(
            test_name=scenario.name,
            seed=scenario.seed or 12345,
            character=scenario.character,
            ascension=scenario.ascension
        )
        self._current_result = result

        # Initialize simulator
        self.init_simulator(
            seed=scenario.seed or 12345,
            character=scenario.character,
            ascension=scenario.ascension
        )

        # Execute scenario steps
        for step in scenario.steps:
            action = self._translate_scenario_step(step)
            if action is None:
                continue

            step_result = self.run_synchronized_step(action)
            result.add_step(step_result)

            # Check expected state if defined
            if step.expected:
                verification = self._verify_expected_state(step.expected)
                if not verification.get('match', True):
                    print(f"Step {step_result.step}: State mismatch - {verification.get('message', '')}")

            # Stop on critical failure
            if step_result.comparison and step_result.comparison.critical_count > 0:
                print(f"Stopping scenario: Critical discrepancy at step {step_result.step}")
                break

        result.finalize()
        self._current_result = None
        return result

    def _translate_scenario_step(self, step: ScenarioStep) -> Optional[TranslatedAction]:
        """Translate a scenario step to a TranslatedAction.

        Args:
            step: ScenarioStep to translate.

        Returns:
            TranslatedAction or None if translation failed.
        """
        params = step.params

        if step.action_type == 'play':
            # Find card by name in hand
            card_name = params.get('card', '')
            target = params.get('target', -1)
            if self.sim:
                state = self.sim.get_state()
                combat = state.get('combat_state', {})
                for i, card in enumerate(combat.get('hand', [])):
                    if card_name.lower() in card.get('name', '').lower():
                        if target >= 0:
                            return self.translator.from_sim_to_game(f"{i} {target}")
                        return self.translator.from_sim_to_game(str(i))

        elif step.action_type == 'end_turn' or step.action_type == 'end':
            return self.translator.from_sim_to_game("end")

        elif step.action_type == 'choose':
            option = params.get('option', 0)
            return self.translator.from_sim_to_game(str(option))

        elif step.action_type == 'potion':
            slot = params.get('slot', 0)
            target = params.get('target', -1)
            subaction = params.get('subaction', 'use')
            if subaction == 'use':
                if target >= 0:
                    return self.translator.from_sim_to_game(f"drink {slot} {target}")
                return self.translator.from_sim_to_game(f"drink {slot}")
            else:
                return self.translator.from_sim_to_game(f"discard potion {slot}")

        return None

    def _verify_expected_state(self, expected_state) -> dict:
        """Verify current state against expected state.

        Args:
            expected_state: ExpectedState to verify against.

        Returns:
            Dictionary with 'match' boolean and optional 'message'.
        """
        if not self.sim:
            return {'match': True}

        current_state = self.sim.get_state()

        # Check player HP
        if hasattr(expected_state, 'player_hp_min') and expected_state.player_hp_min is not None:
            if current_state.get('cur_hp', 0) < expected_state.player_hp_min:
                return {'match': False, 'message': f"HP {current_state.get('cur_hp')} < min {expected_state.player_hp_min}"}

        if hasattr(expected_state, 'player_hp_max') and expected_state.player_hp_max is not None:
            if current_state.get('cur_hp', 0) > expected_state.player_hp_max:
                return {'match': False, 'message': f"HP {current_state.get('cur_hp')} > max {expected_state.player_hp_max}"}

        # Check block
        if hasattr(expected_state, 'player_block') and expected_state.player_block is not None:
            combat = current_state.get('combat_state', {})
            actual_block = combat.get('player', {}).get('block', 0)
            if actual_block != expected_state.player_block:
                return {'match': False, 'message': f"Block {actual_block} != expected {expected_state.player_block}"}

        # Check energy
        if hasattr(expected_state, 'player_energy') and expected_state.player_energy is not None:
            combat = current_state.get('combat_state', {})
            actual_energy = combat.get('player', {}).get('energy', 0)
            if actual_energy != expected_state.player_energy:
                return {'match': False, 'message': f"Energy {actual_energy} != expected {expected_state.player_energy}"}

        return {'match': True}


def main():
    """Main entry point for the test runner."""
    parser = argparse.ArgumentParser(
        description="Slay the Spire Integration Test Runner"
    )
    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config.yaml'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick smoke test'
    )
    parser.add_argument(
        '--character',
        type=str,
        default='IRONCLAD',
        choices=['IRONCLAD', 'SILENT', 'DEFECT', 'WATCHER'],
        help='Character to test'
    )
    parser.add_argument(
        '--ascension',
        type=int,
        default=0,
        help='Ascension level'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=None,
        help='Game seed (random if not specified)'
    )
    parser.add_argument(
        '--steps',
        type=int,
        default=100,
        help='Maximum steps per test'
    )
    parser.add_argument(
        '--test',
        type=str,
        default=None,
        help='Run specific test'
    )
    parser.add_argument(
        '--scenario',
        type=str,
        default=None,
        help='Run a specific YAML scenario file'
    )
    parser.add_argument(
        '--no-game',
        action='store_true',
        help='Run without connecting to real game (simulator only)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--report-only',
        type=str,
        default=None,
        help='Generate report from existing results directory'
    )

    args = parser.parse_args()

    # Report-only mode
    if args.report_only:
        reporter = Reporter(output_dir=args.report_only)
        results_dir = Path(args.report_only)

        # Load all JSON result files
        for result_file in results_dir.glob("*.json"):
            try:
                with open(result_file) as f:
                    data = json.load(f)
                    # Handle both single result and wrapped results format
                    if 'results' in data:
                        # Wrapped format (from generate_json_report)
                        for result_data in data['results']:
                            result = TestResult.from_dict(result_data)
                            reporter.add_result(result)
                    else:
                        # Single result format
                        result = TestResult.from_dict(data)
                        reporter.add_result(result)
            except Exception as e:
                print(f"Warning: Could not load {result_file}: {e}")

        if not reporter.results:
            print(f"No results found in {args.report_only}")
            return 1

        # Generate reports
        reporter.print_console_report(verbose=args.verbose)
        reporter.generate_all_reports()
        return 0 if all(r.passed for r in reporter.results) else 1

    # Create test runner
    runner = TestRunner(config_path=args.config)

    # Connect to game unless --no-game
    if not args.no_game:
        if not runner.connect_game():
            print("Failed to connect to game. Use --no-game for simulator-only testing.")
            return 1

    # Generate random seed if not specified
    import random
    seed = args.seed if args.seed is not None else random.randint(1, 999999999)

    try:
        # Run test(s)
        if args.quick:
            result = runner.run_quick_test(seed=seed, character=args.character)
            runner.reporter.add_result(result)
        elif args.test:
            result = runner.run_test(
                test_name=args.test,
                seed=seed,
                character=args.character,
                ascension=args.ascension,
                max_steps=args.steps
            )
            runner.reporter.add_result(result)
        elif args.scenario:
            result = runner.run_scenario(args.scenario)
            runner.reporter.add_result(result)
        else:
            # Default: run quick test
            result = runner.run_quick_test(seed=seed, character=args.character)
            runner.reporter.add_result(result)

        # Generate reports
        runner.reporter.print_console_report(verbose=args.verbose)
        runner.reporter.generate_all_reports()

        # Return exit code based on test results
        return 0 if all(r.passed for r in runner.reporter.results) else 1

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    finally:
        runner.disconnect_game()


if __name__ == "__main__":
    sys.exit(main())
