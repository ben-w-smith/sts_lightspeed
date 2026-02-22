#!/usr/bin/env python3
"""Main entry point for automated validation of STS Lightspeed simulator.

This script provides automated validation of simulator accuracy against
the real Slay the Spire game via CommunicationMod. It supports multiple
modes: quick smoke tests, full validation, specific scenarios, and
regression testing.

Usage:
    # Quick validation (simulator only, no game needed)
    python integration/validation_runner.py --quick --no-game --seed 12345

    # Quick validation with game
    python integration/validation_runner.py --quick --seed 12345 --output ./reports

    # Full validation
    python integration/validation_runner.py --mode full --character IRONCLAD --seeds 10

    # Specific scenario
    python integration/validation_runner.py --scenario integration/test_suites/smoke.yaml

    # Regression test (run all scenarios in a directory)
    python integration/validation_runner.py --regression integration/test_suites/

Exit Codes:
    0 = All tests passed
    1 = Test failures detected
    2 = Execution error (configuration, connection, etc.)
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add paths for imports
_project_root = Path(__file__).parent.parent
_integration_dir = Path(__file__).parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_integration_dir))

from harness.game_controller import GameController, CommunicationModError, BridgeInUseError
from harness.simulator_controller import SimulatorController
from harness.sync_orchestrator import SyncOrchestrator, ScenarioResult, StepResult
from harness.action_recorder import ActionRecorder, RecordedSession
from harness.state_comparator import StateComparator, ComparisonResult
from harness.action_translator import ActionTranslator, TranslatedAction, ActionType

# Try to import bug report components
try:
    from tests.integration.harness.bug_report import BugReport, BugReportGenerator
    HAS_BUG_REPORT = True
except ImportError:
    HAS_BUG_REPORT = False

# Try to import fix analyzer
try:
    from harness.fix_analyzer import FixAnalyzer
    HAS_FIX_ANALYZER = True
except ImportError:
    HAS_FIX_ANALYZER = False

# Try to import YAML
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


@dataclass
class ValidationSummary:
    """Summary of validation run."""
    mode: str
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    total_scenarios: int = 0
    passed_scenarios: int = 0
    failed_scenarios: int = 0
    error_scenarios: int = 0
    total_steps: int = 0
    total_critical_discrepancies: int = 0
    total_major_discrepancies: int = 0
    total_minor_discrepancies: int = 0
    scenarios: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Check if all scenarios passed."""
        return self.failed_scenarios == 0 and self.error_scenarios == 0

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TestSuite:
    """A test suite containing multiple scenarios."""
    name: str
    description: str = ""
    scenarios: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, filepath: str) -> 'TestSuite':
        """Load a test suite from YAML file."""
        if not HAS_YAML:
            raise ImportError("PyYAML is required for loading test suites")

        with open(filepath) as f:
            data = yaml.safe_load(f)

        return cls(
            name=data.get('name', Path(filepath).stem),
            description=data.get('description', ''),
            scenarios=data.get('scenarios', []),
        )


class ValidationRunner:
    """Main validation runner for automated testing.

    This class orchestrates validation runs, manages connections,
    and generates reports.
    """

    def __init__(
        self,
        output_dir: str = "./reports",
        verbose: bool = False,
        action_delay: float = 0.1,
        stop_on_critical: bool = True,
    ):
        """Initialize the validation runner.

        Args:
            output_dir: Directory for output reports.
            verbose: Enable verbose output.
            action_delay: Delay after game commands.
            stop_on_critical: Stop scenario on critical discrepancy.
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.action_delay = action_delay
        self.stop_on_critical = stop_on_critical

        self.orchestrator: Optional[SyncOrchestrator] = None
        self.comparator = StateComparator()
        self.translator = ActionTranslator()

        if HAS_BUG_REPORT:
            self.bug_reporter = BugReportGenerator(
                output_dir=str(self.output_dir / "bug_reports")
            )
        else:
            self.bug_reporter = None

        if HAS_FIX_ANALYZER:
            self.fix_analyzer = FixAnalyzer()
        else:
            self.fix_analyzer = None

    def _log(self, message: str, level: str = "INFO"):
        """Log a message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level}]"
        if self.verbose or level in ("ERROR", "WARNING", "SUMMARY"):
            print(f"{prefix} {message}")

    def connect_game(
        self,
        state_dir: str = "/tmp/sts_bridge",
        timeout: float = 30.0,
        project_name: str = "validation_runner"
    ) -> bool:
        """Connect to the game via CommunicationMod.

        Args:
            state_dir: Bridge state directory.
            timeout: Connection timeout.
            project_name: Project name for lock.

        Returns:
            True if connected.
        """
        try:
            self.orchestrator = SyncOrchestrator(
                state_dir=state_dir,
                action_delay=self.action_delay,
                stop_on_critical=self.stop_on_critical,
                verbose=self.verbose,
            )
            self.orchestrator.connect_game(project_name=project_name, timeout=timeout)
            self._log("Connected to game")
            return True
        except (CommunicationModError, BridgeInUseError) as e:
            self._log(f"Failed to connect to game: {e}", level="ERROR")
            return False

    def disconnect(self):
        """Disconnect from all systems."""
        if self.orchestrator:
            self.orchestrator.disconnect()
            self.orchestrator = None

    def run_simulator_only(
        self,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        max_steps: int = 50,
        name: str = "simulator_only"
    ) -> ScenarioResult:
        """Run a simulator-only test (no game connection).

        This is useful for testing simulator logic without the game.

        Args:
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
            max_steps: Maximum steps to execute.
            name: Test name.

        Returns:
            ScenarioResult.
        """
        self._log(f"Running simulator-only test: {name} (seed={seed})")

        sim = SimulatorController()
        sim.setup_game(seed, character, ascension)

        result = ScenarioResult(
            scenario_name=name,
            seed=seed,
            character=character,
            ascension=ascension,
        )

        try:
            for step in range(max_steps):
                # Get available actions from simulator
                screen_state = sim.get_screen_state()

                # Select action based on screen state
                action = self._select_simulator_action(sim)
                if action is None:
                    break

                translated = self.translator.from_sim_to_game(action)

                # Execute on simulator
                pre_state = sim.get_state()
                sim.take_action(action)
                post_state = sim.get_state()

                # Create step result (no comparison since no game)
                step_result = StepResult(
                    step_number=step,
                    action=translated,
                    pre_sim_state=pre_state,
                    post_sim_state=post_state,
                )
                result.steps.append(step_result)

        except Exception as e:
            result.error = str(e)
            self._log(f"Error in simulator-only test: {e}", level="ERROR")

        result.finalize()
        return result

    def _select_simulator_action(self, sim: SimulatorController) -> Optional[str]:
        """Select next action for simulator-only testing.

        Args:
            sim: Simulator controller.

        Returns:
            Action string or None if no action available.
        """
        screen_state = sim.get_screen_state()

        # Handle events
        if screen_state == 'event':
            available = sim.get_available_actions()
            if available:
                return str(available[0])

        # In combat
        if sim.is_in_combat():
            state = sim.get_state()
            combat = state.get('combat_state', {})
            hand = combat.get('hand', [])
            energy = combat.get('player', {}).get('energy', 0)
            monsters = combat.get('monsters', [])

            # Find target
            target_idx = -1
            for i, m in enumerate(monsters):
                if not m.get('is_dying', False) and m.get('is_targetable', True):
                    target_idx = i
                    break

            # Find playable card
            for i, card in enumerate(hand):
                cost = card.get('cost_for_turn', card.get('cost', 0))
                if cost <= energy:
                    if card.get('requires_target', False) and target_idx >= 0:
                        return f"{i} {target_idx}"
                    elif not card.get('requires_target', False):
                        return str(i)

            return "end"

        # Other screens
        available = sim.get_available_actions()
        if available:
            return str(available[0])

        return None

    def run_scenario_from_actions(
        self,
        name: str,
        actions: List[str],
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        action_type: str = "sim"
    ) -> ScenarioResult:
        """Run a scenario from a list of action strings.

        Args:
            name: Scenario name.
            actions: List of action strings.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
            action_type: "sim" or "game" format.

        Returns:
            ScenarioResult.
        """
        if not self.orchestrator:
            # Simulator-only mode
            return self.run_simulator_only(seed, character, ascension, len(actions), name)

        # Translate actions
        translated = []
        for action_str in actions:
            if action_type == "game":
                translated.append(self.translator.from_game_to_sim(action_str))
            else:
                translated.append(self.translator.from_sim_to_game(action_str))

        return self.orchestrator.run_scenario(
            name=name,
            actions=translated,
            seed=seed,
            character=character,
            ascension=ascension,
        )

    def run_scenario_from_file(self, filepath: str) -> ScenarioResult:
        """Run a scenario from a YAML or JSON file.

        Args:
            filepath: Path to scenario file.

        Returns:
            ScenarioResult.
        """
        path = Path(filepath)

        if path.suffix in ('.yaml', '.yml'):
            if not HAS_YAML:
                raise ImportError("PyYAML is required for YAML scenarios")

            with open(path) as f:
                data = yaml.safe_load(f)
        else:
            with open(path) as f:
                data = json.load(f)

        # Extract scenario data
        name = data.get('name', path.stem)
        seed = data.get('seed', 12345)
        character = data.get('character', 'IRONCLAD')
        ascension = data.get('ascension', 0)

        # Get actions
        actions = []
        for step in data.get('steps', []):
            if isinstance(step, str):
                actions.append(step)
            elif isinstance(step, dict):
                cmd = step.get('command') or step.get('sim_command') or step.get('action', '')
                if cmd:
                    actions.append(cmd)

        return self.run_scenario_from_actions(
            name=name,
            actions=actions,
            seed=seed,
            character=character,
            ascension=ascension,
        )

    def run_test_suite(self, suite_path: str) -> List[ScenarioResult]:
        """Run all scenarios in a test suite.

        Args:
            suite_path: Path to test suite file or directory.

        Returns:
            List of ScenarioResults.
        """
        results = []
        path = Path(suite_path)

        if path.is_file():
            # Single file
            suite = TestSuite.from_yaml(str(path))
            for scenario_data in suite.scenarios:
                result = self._run_scenario_from_dict(scenario_data)
                results.append(result)
        elif path.is_dir():
            # Directory of scenario files
            for scenario_file in sorted(path.glob("**/*.yaml")):
                try:
                    result = self.run_scenario_from_file(str(scenario_file))
                    results.append(result)
                except Exception as e:
                    self._log(f"Error running {scenario_file}: {e}", level="ERROR")
        else:
            raise FileNotFoundError(f"Test suite not found: {suite_path}")

        return results

    def _run_scenario_from_dict(self, data: Dict[str, Any]) -> ScenarioResult:
        """Run a scenario from a dictionary."""
        name = data.get('name', 'unnamed')
        seed = data.get('seed', 12345)
        character = data.get('character', 'IRONCLAD')
        ascension = data.get('ascension', 0)

        actions = []
        for step in data.get('steps', []):
            if isinstance(step, str):
                actions.append(step)
            elif isinstance(step, dict):
                cmd = step.get('command') or step.get('sim_command') or step.get('action', '')
                if cmd:
                    actions.append(cmd)

        return self.run_scenario_from_actions(name, actions, seed, character, ascension)

    def run_quick_validation(
        self,
        seed: int = 12345,
        character: str = 'IRONCLAD',
        max_steps: int = 50
    ) -> ScenarioResult:
        """Run a quick smoke test.

        Args:
            seed: Game seed.
            character: Character class.
            max_steps: Maximum steps.

        Returns:
            ScenarioResult.
        """
        return self.run_simulator_only(seed, character, 0, max_steps, "quick_smoke_test")

    def run_full_validation(
        self,
        character: str = 'IRONCLAD',
        num_seeds: int = 10,
        steps_per_seed: int = 100
    ) -> ValidationSummary:
        """Run full validation with multiple seeds.

        Args:
            character: Character class.
            num_seeds: Number of seeds to test.
            steps_per_seed: Steps per seed.

        Returns:
            ValidationSummary.
        """
        summary = ValidationSummary(mode="full")

        seeds = [random.randint(1, 999999999) for _ in range(num_seeds)]

        for i, seed in enumerate(seeds):
            self._log(f"Running seed {i+1}/{num_seeds}: {seed}")

            try:
                result = self.run_simulator_only(
                    seed=seed,
                    character=character,
                    max_steps=steps_per_seed,
                    name=f"full_validation_seed_{seed}"
                )

                summary.total_scenarios += 1
                summary.total_steps += result.total_steps
                summary.total_critical_discrepancies += result.critical_discrepancy_count
                summary.total_major_discrepancies += result.major_discrepancy_count
                summary.total_minor_discrepancies += result.minor_discrepancy_count

                if result.passed:
                    summary.passed_scenarios += 1
                else:
                    summary.failed_scenarios += 1

                summary.scenarios.append(result.to_dict())

            except Exception as e:
                self._log(f"Error with seed {seed}: {e}", level="ERROR")
                summary.error_scenarios += 1
                summary.errors.append(f"Seed {seed}: {str(e)}")

        summary.end_time = datetime.now().isoformat()
        return summary

    def generate_report(
        self,
        results: List[ScenarioResult],
        output_file: Optional[str] = None
    ) -> str:
        """Generate a JSON report from results.

        Args:
            results: List of ScenarioResults.
            output_file: Optional output file path.

        Returns:
            Path to the report file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = output_file or f"validation_{timestamp}.json"
        filepath = self.output_dir / filename

        report = {
            'generated_at': datetime.now().isoformat(),
            'total_scenarios': len(results),
            'passed': sum(1 for r in results if r.passed),
            'failed': sum(1 for r in results if not r.passed),
            'total_critical_discrepancies': sum(r.critical_discrepancy_count for r in results),
            'total_major_discrepancies': sum(r.major_discrepancy_count for r in results),
            'total_minor_discrepancies': sum(r.minor_discrepancy_count for r in results),
            'scenarios': [r.to_dict() for r in results],
        }

        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        self._log(f"Report saved to: {filepath}")
        return str(filepath)

    def generate_summary_report(self, summary: ValidationSummary) -> str:
        """Generate a summary report.

        Args:
            summary: ValidationSummary.

        Returns:
            Path to the report file.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.output_dir / f"validation_summary_{timestamp}.json"

        with open(filepath, 'w') as f:
            json.dump(summary.to_dict(), f, indent=2, default=str)

        self._log(f"Summary report saved to: {filepath}")
        return str(filepath)

    def print_summary(self, summary: ValidationSummary):
        """Print a summary to console."""
        print("\n" + "=" * 60)
        print("VALIDATION SUMMARY")
        print("=" * 60)
        print(f"Mode: {summary.mode}")
        print(f"Start: {summary.start_time}")
        print(f"End: {summary.end_time}")
        print()
        print(f"Total Scenarios: {summary.total_scenarios}")
        print(f"  Passed:  {summary.passed_scenarios}")
        print(f"  Failed:  {summary.failed_scenarios}")
        print(f"  Errors:  {summary.error_scenarios}")
        print()
        print(f"Total Steps: {summary.total_steps}")
        print(f"Critical Discrepancies: {summary.total_critical_discrepancies}")
        print(f"Major Discrepancies: {summary.total_major_discrepancies}")
        print(f"Minor Discrepancies: {summary.total_minor_discrepancies}")
        print()
        print(f"Result: {'PASSED' if summary.passed else 'FAILED'}")
        print("=" * 60)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="STS Lightspeed Validation Runner"
    )
    parser.add_argument(
        '--mode',
        type=str,
        default='quick',
        choices=['quick', 'full', 'scenario', 'regression'],
        help='Validation mode'
    )
    parser.add_argument(
        '--quick',
        action='store_true',
        help='Run quick validation (shorthand for --mode quick)'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Run full validation (shorthand for --mode full)'
    )
    parser.add_argument(
        '--no-game',
        action='store_true',
        help='Run without game connection (simulator only)'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=None,
        help='Game seed (random if not specified)'
    )
    parser.add_argument(
        '--seeds',
        type=int,
        default=10,
        help='Number of seeds for full validation'
    )
    parser.add_argument(
        '--character',
        type=str,
        default='IRONCLAD',
        choices=['IRONCLAD', 'SILENT', 'DEFECT', 'WATCHER'],
        help='Character class'
    )
    parser.add_argument(
        '--ascension',
        type=int,
        default=0,
        help='Ascension level'
    )
    parser.add_argument(
        '--steps',
        type=int,
        default=100,
        help='Maximum steps per scenario'
    )
    parser.add_argument(
        '--scenario',
        type=str,
        default=None,
        help='Path to scenario file (YAML or JSON)'
    )
    parser.add_argument(
        '--regression',
        type=str,
        default=None,
        help='Path to test suite or directory of scenarios'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='./reports',
        help='Output directory for reports'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose output'
    )
    parser.add_argument(
        '--state-dir',
        type=str,
        default='/tmp/sts_bridge',
        help='Bridge state directory'
    )

    args = parser.parse_args()

    # Determine mode
    if args.quick:
        mode = 'quick'
    elif args.full:
        mode = 'full'
    elif args.scenario:
        mode = 'scenario'
    elif args.regression:
        mode = 'regression'
    else:
        mode = args.mode

    # Generate seed if not specified
    seed = args.seed if args.seed is not None else random.randint(1, 999999999)

    # Create runner
    runner = ValidationRunner(
        output_dir=args.output,
        verbose=args.verbose,
    )

    summary = ValidationSummary(mode=mode)
    results: List[ScenarioResult] = []

    try:
        # Connect to game unless --no-game
        if not args.no_game:
            if not runner.connect_game(state_dir=args.state_dir):
                print("Failed to connect to game. Use --no-game for simulator-only testing.")
                return 2

        # Run based on mode
        if mode == 'quick':
            result = runner.run_quick_validation(
                seed=seed,
                character=args.character,
                max_steps=args.steps
            )
            results.append(result)

        elif mode == 'full':
            summary = runner.run_full_validation(
                character=args.character,
                num_seeds=args.seeds,
                steps_per_seed=args.steps
            )
            results = [ScenarioResult(**s) for s in summary.scenarios]

        elif mode == 'scenario':
            if not args.scenario:
                print("Error: --scenario requires a file path")
                return 2
            result = runner.run_scenario_from_file(args.scenario)
            results.append(result)

        elif mode == 'regression':
            if not args.regression:
                print("Error: --regression requires a path")
                return 2
            results = runner.run_test_suite(args.regression)

        # Generate summary if not already done
        if mode != 'full':
            for result in results:
                summary.total_scenarios += 1
                summary.total_steps += result.total_steps
                summary.total_critical_discrepancies += result.critical_discrepancy_count
                summary.total_major_discrepancies += result.major_discrepancy_count
                summary.total_minor_discrepancies += result.minor_discrepancy_count

                if result.passed:
                    summary.passed_scenarios += 1
                elif result.error:
                    summary.error_scenarios += 1
                else:
                    summary.failed_scenarios += 1

                summary.scenarios.append(result.to_dict())

            summary.end_time = datetime.now().isoformat()

        # Print and save reports
        runner.print_summary(summary)
        runner.generate_report(results)

        if mode == 'full':
            runner.generate_summary_report(summary)

        # Return exit code
        if summary.passed:
            return 0
        elif summary.error_scenarios > 0:
            return 2
        else:
            return 1

    except KeyboardInterrupt:
        print("\nInterrupted by user")
        return 130
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 2
    finally:
        runner.disconnect()


if __name__ == "__main__":
    sys.exit(main())
