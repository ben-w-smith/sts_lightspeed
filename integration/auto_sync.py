#!/usr/bin/env python3
"""Automated sync testing pipeline.

This script runs both the real game (via CommunicationMod) and the simulator
in parallel, executing the same actions and comparing states to find divergences.

Usage:
    # Run with a fresh game (will wait for game to start)
    python -m integration.auto_sync --seed 12345 --floors 3

    # Replay a recording and compare
    python -m integration.auto_sync --replay recordings/my_run.json

    # Just generate a report from existing data
    python -m integration.auto_sync --report
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from integration.harness.sync_orchestrator import SyncOrchestrator, StepResult, ScenarioResult
from integration.harness.game_controller import GameController, CommunicationModError
from integration.harness.action_translator import ActionTranslator, ActionType, TranslatedAction
from integration.harness.recorder import GameplayRecorder, RecordedStep


def convert_seed_to_sim(seed: int) -> int:
    """Convert seed to format expected by simulator.

    CommunicationMod may report seeds as either signed or unsigned.
    The pybind11 binding expects unsigned format for large values.
    """
    # If negative, convert to unsigned representation
    if seed < 0:
        return seed & 0xFFFFFFFFFFFFFFFF
    return seed


class AutoSyncPipeline:
    """Automated sync testing pipeline.

    This class orchestrates:
    1. Connecting to the game
    2. Initializing the simulator with the same seed
    3. Executing actions on both in parallel
    4. Comparing states and reporting divergences
    """

    def __init__(
        self,
        state_dir: str = "/tmp/sts_bridge",
        reports_dir: Optional[str] = None,
        verbose: bool = False
    ):
        self.state_dir = Path(state_dir)
        self.reports_dir = Path(reports_dir or (Path(__file__).parent / "sync_reports"))
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose

        self.orchestrator = SyncOrchestrator(
            state_dir=str(self.state_dir),
            action_delay=0.3,
            stop_on_critical=False,  # Continue to collect all discrepancies
            verbose=verbose,
        )

        self.translator = ActionTranslator()
        self.divergences: List[Dict[str, Any]] = []

    def _log(self, msg: str):
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] {msg}")

    def wait_for_game_start(self, timeout: float = 60.0) -> bool:
        """Wait for game to start and return initial state.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            True if game started successfully.
        """
        self._log("Waiting for game to start...")

        game = GameController(state_dir=str(self.state_dir), timeout=timeout)

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                game.connect()
                state = game.get_state()
                if state and state.get('in_game'):
                    gs = state.get('game_state', {})
                    floor = gs.get('floor')
                    if floor is not None and floor >= 0:
                        self._log(f"Game detected at floor {floor}")
                        game.disconnect()
                        return True
            except CommunicationModError:
                pass
            except Exception as e:
                self._log(f"Error checking game state: {e}")

            time.sleep(0.5)
            game.disconnect()

        return False

    def replay_recording(self, recording_path: str) -> ScenarioResult:
        """Replay a recorded game on both game and simulator.

        This is the main sync testing method. It:
        1. Loads the recording
        2. Initializes simulator with same seed
        3. For each recorded action, executes on simulator
        4. Compares game state (from recording) with simulator state

        Args:
            recording_path: Path to recording JSON file.

        Returns:
            ScenarioResult with comparison details.
        """
        self._log(f"Loading recording: {recording_path}")

        with open(recording_path, 'r') as f:
            recording = json.load(f)

        # Extract recording metadata
        metadata = recording.get('metadata', {})
        steps = recording.get('steps', [])

        # Get seed from first step
        first_step = steps[0] if steps else {}
        first_state = first_step.get('game_state', {})
        game_state = first_state.get('game_state', first_state)

        raw_seed = game_state.get('seed', 12345)
        seed = convert_seed_to_sim(raw_seed)
        character = game_state.get('class', 'IRONCLAD')
        ascension = game_state.get('ascension_level', 0)

        self._log(f"Seed: {seed}, Character: {character}, Ascension: {ascension}")

        # Initialize simulator
        self.orchestrator.initialize_simulator(seed, character, ascension)

        # Start scenario
        scenario = self.orchestrator.start_scenario(
            name=f"replay_{Path(recording_path).stem}",
            seed=seed,
            character=character,
            ascension=ascension,
        )

        # Replay each step
        for i, step in enumerate(steps):
            game_state = step.get('game_state', {})
            gs = game_state.get('game_state', game_state)

            # Get recorded action
            action_taken = step.get('detected_action', '')
            command_sent = step.get('command_sent', '')

            self._log(f"Step {i}: floor={gs.get('floor')} hp={gs.get('current_hp')} action={action_taken}")

            # Get simulator state for comparison
            sim_state = self.orchestrator.get_sim_state()

            # Compare states
            comparison = self.orchestrator.comparator.compare(game_state, sim_state)

            if not comparison.match:
                self._log(f"  DIVERGENCE: {comparison.get_summary()}")
                self.divergences.append({
                    'step': i,
                    'floor': gs.get('floor'),
                    'comparison': {
                        'match': comparison.match,
                        'critical_count': comparison.critical_count,
                        'major_count': comparison.major_count,
                        'minor_count': comparison.minor_count,
                        'discrepancies': [
                            {
                                'field': d.field,
                                'game_value': d.game_value,
                                'sim_value': d.sim_value,
                                'severity': d.severity.value,
                            }
                            for d in comparison.discrepancies
                        ]
                    }
                })

            # If a command was sent, execute on simulator
            if command_sent:
                # Parse the command and translate to simulator format
                action = self.translator.from_game_to_sim(command_sent)
                if action.sim_command:
                    self._log(f"  Executing on sim: {action.sim_command}")
                    try:
                        self.orchestrator.sim.take_action(action.sim_command)
                    except Exception as e:
                        self._log(f"  ERROR executing: {e}")

            # Record result
            step_result = StepResult(
                step_number=i,
                action=TranslatedAction(
                    action_type=ActionType.UNKNOWN,
                    game_command=command_sent or '',
                    sim_command='',
                    params={}
                ),
                post_game_state=game_state,
                post_sim_state=sim_state,
                comparison=comparison,
            )
            scenario.steps.append(step_result)

        scenario.finalize()
        return scenario

    def live_sync(self, max_floors: int = 3, timeout: float = 300.0) -> ScenarioResult:
        """Run live sync test with game.

        This watches the game state and mirrors actions to the simulator.

        Args:
            max_floors: Stop after this many floors.
            timeout: Maximum time to run.

        Returns:
            ScenarioResult with comparison details.
        """
        self._log("Starting live sync test...")

        # Connect to game
        self.orchestrator.connect_game(project_name="auto_sync")

        try:
            # Get initial state and sync simulator
            sync_info = self.orchestrator.sync_simulator_from_game()
            self._log(f"Synced: seed={sync_info['seed']} char={sync_info['character']}")

            # Start scenario
            scenario = self.orchestrator.start_scenario(
                name=f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                seed=sync_info['seed'],
                character=sync_info['character'],
                ascension=sync_info['ascension'],
            )

            start_time = time.time()
            last_floor = 0
            last_state_hash = None

            while time.time() - start_time < timeout:
                # Get current game state
                game_state = self.orchestrator.get_game_state()
                if not game_state:
                    time.sleep(0.1)
                    continue

                gs = game_state.get('game_state', game_state)
                current_floor = gs.get('floor', 0)

                # Check if we've reached max floors
                if current_floor > max_floors:
                    self._log(f"Reached floor {current_floor}, stopping")
                    break

                # Detect state changes
                import hashlib
                state_hash = hashlib.md5(json.dumps(gs, sort_keys=True).encode()).hexdigest()

                if state_hash != last_state_hash:
                    last_state_hash = state_hash

                    # Get simulator state
                    sim_state = self.orchestrator.get_sim_state()

                    # Compare
                    comparison = self.orchestrator.comparator.compare(game_state, sim_state)

                    if not comparison.match:
                        self._log(f"DIVERGENCE at floor {current_floor}: {comparison.get_summary()}")
                        self.divergences.append({
                            'floor': current_floor,
                            'comparison': {
                                'match': comparison.match,
                                'critical_count': comparison.critical_count,
                                'discrepancies': [
                                    {'field': d.field, 'game': d.game_value, 'sim': d.sim_value}
                                    for d in comparison.discrepancies
                                ]
                            }
                        })

                    # Record step
                    step_result = StepResult(
                        step_number=len(scenario.steps),
                        action=TranslatedAction(
                            action_type=ActionType.UNKNOWN,
                            game_command='',
                            sim_command='',
                            params={}
                        ),
                        post_game_state=game_state,
                        post_sim_state=sim_state,
                        comparison=comparison,
                    )
                    scenario.steps.append(step_result)

                    if current_floor != last_floor:
                        self._log(f"Floor changed: {last_floor} -> {current_floor}")
                        last_floor = current_floor

                time.sleep(0.1)

            scenario.finalize()
            return scenario

        finally:
            self.orchestrator.disconnect()

    def generate_report(self, scenario: ScenarioResult, output_path: Optional[str] = None) -> str:
        """Generate a detailed sync report.

        Args:
            scenario: The scenario result to report on.
            output_path: Optional path for report file.

        Returns:
            Path to generated report.
        """
        if output_path is None:
            output_path = self.reports_dir / f"sync_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        else:
            output_path = Path(output_path)

        with open(output_path, 'w') as f:
            f.write("# Sync Test Report\n\n")
            f.write(f"**Generated:** {datetime.now().isoformat()}\n\n")

            # Summary
            f.write("## Summary\n\n")
            f.write(f"- **Scenario:** {scenario.scenario_name}\n")
            f.write(f"- **Seed:** {scenario.seed}\n")
            f.write(f"- **Character:** {scenario.character}\n")
            f.write(f"- **Ascension:** {scenario.ascension}\n")
            f.write(f"- **Total Steps:** {scenario.total_steps}\n")
            f.write(f"- **Passed:** {'Yes' if scenario.passed else 'No'}\n")
            f.write(f"- **Critical Divergences:** {scenario.critical_discrepancy_count}\n")
            f.write(f"- **Major Divergences:** {scenario.major_discrepancy_count}\n")
            f.write(f"- **Minor Divergences:** {scenario.minor_discrepancy_count}\n\n")

            # Divergences
            if self.divergences:
                f.write("## Divergences\n\n")
                for div in self.divergences:
                    f.write(f"### Step {div.get('step', 'N/A')} (Floor {div.get('floor', 'N/A')})\n\n")
                    comp = div.get('comparison', {})
                    for disc in comp.get('discrepancies', []):
                        f.write(f"- **{disc['field']}:** Game={disc['game_value']} Sim={disc['sim_value']} ({disc['severity']})\n")
                    f.write("\n")

            # Failed steps
            failed_steps = scenario.failed_steps
            if failed_steps:
                f.write("## Failed Steps\n\n")
                for step in failed_steps:
                    f.write(f"- Step {step.step_number}: {step.error or 'Discrepancy'}\n")

        self._log(f"Report saved to: {output_path}")
        return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='Automated sync testing pipeline')
    parser.add_argument('--seed', type=int, help='Game seed')
    parser.add_argument('--floors', type=int, default=3, help='Max floors to test')
    parser.add_argument('--character', type=str, default='IRONCLAD', help='Character class')
    parser.add_argument('--replay', type=str, help='Replay recording file')
    parser.add_argument('--report', action='store_true', help='Generate report from latest')
    parser.add_argument('--state-dir', type=str, default='/tmp/sts_bridge', help='Bridge state dir')
    parser.add_argument('--reports-dir', type=str, help='Reports output directory')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--timeout', type=float, default=300.0, help='Timeout for live sync')

    args = parser.parse_args()

    pipeline = AutoSyncPipeline(
        state_dir=args.state_dir,
        reports_dir=args.reports_dir,
        verbose=args.verbose,
    )

    try:
        if args.replay:
            # Replay a recording
            scenario = pipeline.replay_recording(args.replay)
            report_path = pipeline.generate_report(scenario)
            print(f"\nReplay complete. Report: {report_path}")

        elif args.report:
            # Just generate a report from existing data
            print("Report generation from existing data not yet implemented")
            print("Use --replay to analyze a recording")

        else:
            # Run live sync
            print("Waiting for game to start...")
            if not pipeline.wait_for_game_start(timeout=60.0):
                print("ERROR: Game did not start within timeout")
                sys.exit(1)

            print("Starting live sync...")
            scenario = pipeline.live_sync(max_floors=args.floors, timeout=args.timeout)
            report_path = pipeline.generate_report(scenario)
            print(f"\nSync test complete. Report: {report_path}")

        # Print summary
        print(f"\nResults:")
        print(f"  Total Steps: {scenario.total_steps}")
        print(f"  Passed: {scenario.passed}")
        print(f"  Critical Divergences: {scenario.critical_discrepancy_count}")
        print(f"  Major Divergences: {scenario.major_discrepancy_count}")
        print(f"  Minor Divergences: {scenario.minor_discrepancy_count}")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as e:
        print(f"ERROR: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
