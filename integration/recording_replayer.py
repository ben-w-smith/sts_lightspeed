#!/usr/bin/env python3
"""
Replay recorded gameplay in simulator and verify state alignment.

Takes recordings from gameplay_recorder.py and replays them step-by-step
in the simulator, comparing states at each point.

Usage:
    # Replay a recording and compare states
    python recording_replayer.py replay --run-name "ironclad_run_1"

    # Replay with verbose output
    python recording_replayer.py replay --run-name "ironclad_run_1" --verbose

    # Compare specific step
    python recording_replayer.py step --run-name "ironclad_run_1" --step 42

    # Generate comparison report
    python recording_replayer.py report --run-name "ironclad_run_1"
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.simulator_controller import SimulatorController

RECORDINGS_DIR = Path(__file__).parent / "recordings"


@dataclass
class ComparisonResult:
    """Result of comparing game state to simulator state."""
    step_number: int
    game_action: str
    fields_match: int
    fields_differ: int
    differences: List[Tuple[str, Any, Any]]
    is_aligned: bool


class RecordingReplayer:
    """Replays recorded gameplay in the simulator."""

    def __init__(self, run_name: str):
        self.run_name = run_name
        self.recording_path = RECORDINGS_DIR / f"{run_name}.json"
        self.recording: Optional[Dict[str, Any]] = None
        self.sim: Optional[SimulatorController] = None
        self.comparison_results: List[ComparisonResult] = []

    def load_recording(self) -> bool:
        """Load the recording from disk."""
        if not self.recording_path.exists():
            print(f"Recording not found: {self.recording_path}")
            return False

        with open(self.recording_path) as f:
            self.recording = json.load(f)

        print(f"Loaded recording: {self.run_name}")
        print(f"  Steps: {len(self.recording.get('steps', []))}")
        print(f"  Started: {self.recording.get('start_time', '?')}")

        return True

    def initialize_simulator(self) -> bool:
        """Initialize the simulator with the recording's seed."""
        if not self.recording:
            print("No recording loaded")
            return False

        # Get seed from first step
        steps = self.recording.get("steps", [])
        if not steps:
            print("Recording has no steps")
            return False

        first_step = steps[0]
        gs = first_step.get("game_state", {}).get("game_state", {})

        # Extract seed
        raw_seed = gs.get("seed", 0)
        if raw_seed < 0:
            seed = raw_seed + (1 << 64)
        else:
            seed = raw_seed

        character = gs.get("class", "IRONCLAD")
        ascension = gs.get("ascension_level", 1)

        print(f"\nInitializing simulator:")
        print(f"  Seed: {raw_seed} (unsigned: {seed})")
        print(f"  Character: {character}")
        print(f"  Ascension: {ascension}")

        self.sim = SimulatorController()
        self.sim.setup_game(seed, character, ascension)

        return True

    def compare_states(self, game_state: Dict[str, Any], sim_state: Dict[str, Any]) -> ComparisonResult:
        """Compare game state with simulator state."""
        gs = game_state.get("game_state", {})

        differences = []
        matches = 0

        # Define field comparisons (game_field, sim_field)
        comparisons = [
            ("floor", "floor"),
            ("current_hp", "cur_hp"),
            ("max_hp", "max_hp"),
            ("gold", "gold"),
            ("act", "act"),
            ("screen_name", "screen_state"),
        ]

        for game_field, sim_field in comparisons:
            game_val = gs.get(game_field)
            sim_val = sim_state.get(sim_field)

            if game_val == sim_val:
                matches += 1
            else:
                differences.append((game_field, game_val, sim_val))

        # Check deck size
        game_deck_size = len(gs.get("deck", []))
        sim_deck_size = len(sim_state.get("deck", []))
        if game_deck_size != sim_deck_size:
            differences.append(("deck_size", game_deck_size, sim_deck_size))
        else:
            matches += 1

        # Check relic count
        game_relic_count = len(gs.get("relics", []))
        sim_relic_count = len(sim_state.get("relics", []))
        if game_relic_count != sim_relic_count:
            differences.append(("relic_count", game_relic_count, sim_relic_count))
        else:
            matches += 1

        return ComparisonResult(
            step_number=0,
            game_action="",
            fields_match=matches,
            fields_differ=len(differences),
            differences=differences,
            is_aligned=len(differences) == 0
        )

    def replay_step(self, step: Dict[str, Any], step_number: int, verbose: bool = False) -> ComparisonResult:
        """Replay a single step and compare states."""
        gs = step.get("game_state", {}).get("game_state", {})
        action = step.get("detected_action", "unknown")

        if verbose:
            print(f"\n--- Step {step_number} ---")
            print(f"  Action: {action}")
            print(f"  Floor: {gs.get('floor')}, HP: {gs.get('current_hp')}/{gs.get('max_hp')}")
            print(f"  Screen: {gs.get('screen_name')}")

        # Get simulator state
        sim_state = self.sim.get_state()

        # Compare
        result = self.compare_states(step.get("game_state", {}), sim_state)
        result.step_number = step_number
        result.game_action = action

        if verbose and not result.is_aligned:
            print(f"  Differences ({result.fields_differ}):")
            for field, game_val, sim_val in result.differences:
                print(f"    {field}: game={game_val}, sim={sim_val}")

        return result

    def replay_all(self, verbose: bool = False, stop_on_diverge: bool = False) -> List[ComparisonResult]:
        """Replay all steps and collect comparison results."""
        if not self.recording:
            print("No recording loaded")
            return []

        steps = self.recording.get("steps", [])
        print(f"\nReplaying {len(steps)} steps...")

        results = []
        diverged_at = None

        for i, step in enumerate(steps, 1):
            result = self.replay_step(step, i, verbose=verbose)
            results.append(result)

            if not result.is_aligned and diverged_at is None:
                diverged_at = i
                if stop_on_diverge:
                    print(f"\nDivergence detected at step {i}")
                    break

        # Summary
        aligned = sum(1 for r in results if r.is_aligned)
        total = len(results)

        print(f"\n=== Replay Summary ===")
        print(f"  Steps replayed: {total}")
        print(f"  Aligned steps: {aligned}")
        print(f"  Diverged steps: {total - aligned}")

        if diverged_at:
            print(f"  First divergence: step {diverged_at}")
            result = results[diverged_at - 1]
            print(f"  Action at divergence: {result.game_action}")
            print(f"  Differences:")
            for field, game_val, sim_val in result.differences:
                print(f"    {field}: game={game_val}, sim={sim_val}")

        self.comparison_results = results
        return results

    def generate_report(self) -> str:
        """Generate a detailed comparison report."""
        if not self.comparison_results:
            return "No comparison results available. Run replay first."

        lines = [
            f"# Recording Replay Report: {self.run_name}",
            f"",
            f"Generated: {datetime.now().isoformat()}",
            f"",
            "## Overview",
            f"",
        ]

        stats = self.recording.get("stats", {})
        lines.extend([
            f"- Total steps: {stats.get('total_steps', 0)}",
            f"- Combats: {stats.get('combats', 0)}",
            f"- Floors reached: {stats.get('floors_reached', 0)}",
            f"- Damage taken: {stats.get('damage_taken', 0)}",
            f"- Deaths: {stats.get('deaths', 0)}",
            f"",
        ])

        # Alignment summary
        aligned = sum(1 for r in self.comparison_results if r.is_aligned)
        total = len(self.comparison_results)
        alignment_rate = (aligned / total * 100) if total > 0 else 0

        lines.extend([
            "## Alignment Results",
            f"",
            f"- Aligned steps: {aligned}/{total} ({alignment_rate:.1f}%)",
            f"",
        ])

        # Divergence points
        divergences = [(i, r) for i, r in enumerate(self.comparison_results) if not r.is_aligned]

        if divergences:
            lines.extend([
                "## Divergence Points",
                "",
            ])

            for idx, (i, result) in enumerate(divergences[:10]):  # First 10
                lines.append(f"### Step {result.step_number}: {result.game_action}")
                lines.append("")
                lines.append("| Field | Game | Simulator |")
                lines.append("|-------|------|-----------|")
                for field, game_val, sim_val in result.differences:
                    lines.append(f"| {field} | {game_val} | {sim_val} |")
                lines.append("")

                if idx >= 9 and len(divergences) > 10:
                    lines.append(f"... and {len(divergences) - 10} more divergences")
                    break

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Replay recorded gameplay in simulator"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Replay command
    replay_parser = subparsers.add_parser("replay", help="Replay a recording")
    replay_parser.add_argument("--run-name", "-n", required=True, help="Recording name")
    replay_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    replay_parser.add_argument("--stop-on-diverge", action="store_true", help="Stop at first divergence")

    # Step command
    step_parser = subparsers.add_parser("step", help="Compare specific step")
    step_parser.add_argument("--run-name", "-n", required=True, help="Recording name")
    step_parser.add_argument("--step", "-s", type=int, required=True, help="Step number")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate comparison report")
    report_parser.add_argument("--run-name", "-n", required=True, help="Recording name")
    report_parser.add_argument("--output", "-o", help="Output file (default: stdout)")

    args = parser.parse_args()

    if args.command == "replay":
        replayer = RecordingReplayer(args.run_name)
        if replayer.load_recording():
            if replayer.initialize_simulator():
                replayer.replay_all(verbose=args.verbose, stop_on_diverge=args.stop_on_diverge)

    elif args.command == "step":
        replayer = RecordingReplayer(args.run_name)
        if replayer.load_recording():
            if replayer.initialize_simulator():
                steps = replayer.recording.get("steps", [])
                if 1 <= args.step <= len(steps):
                    result = replayer.replay_step(steps[args.step - 1], args.step, verbose=True)
                    print(f"\nResult: {'ALIGNED' if result.is_aligned else 'DIVERGED'}")
                else:
                    print(f"Step {args.step} out of range (1-{len(steps)})")

    elif args.command == "report":
        replayer = RecordingReplayer(args.run_name)
        if replayer.load_recording():
            if replayer.initialize_simulator():
                replayer.replay_all(verbose=False)
                report = replayer.generate_report()

                if args.output:
                    Path(args.output).write_text(report)
                    print(f"Report saved to: {args.output}")
                else:
                    print(report)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
