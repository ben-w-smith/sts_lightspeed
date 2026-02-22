#!/usr/bin/env python3
"""
Sync Test Harness - Compare game and simulator states.

This script replays recorded gameplay through the simulator and compares
states at each step, producing a markdown report of divergences.

Usage:
    # Replay a recording and compare with simulator
    python sync_test_harness.py replay --run-name "sync_test_1"

    # Replay with verbose output
    python sync_test_harness.py replay --run-name "sync_test_1" --verbose

    # Generate report only (no replay)
    python sync_test_harness.py report --run-name "sync_test_1"

Workflow:
    1. Record game: echo "record my_run" > /tmp/sts_bridge/command.txt
    2. Play game normally
    3. Stop recording: echo "stop_record" > /tmp/sts_bridge/command.txt
    4. Replay and compare: python sync_test_harness.py replay --run-name "my_run"
    5. Review report: cat integration/sync_reports/my_run_report.md
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from harness.simulator_controller import SimulatorController
from harness.state_comparator import StateComparator

RECORDINGS_DIR = Path(__file__).parent / "recordings"
REPORTS_DIR = Path(__file__).parent / "sync_reports"


@dataclass
class SyncResult:
    """Result of comparing game and simulator at one step."""
    step_number: int
    game_action: str
    aligned: bool
    differences: List[Tuple[str, Any, Any]]
    game_state: Dict[str, Any]
    sim_state: Dict[str, Any]


class SyncTestHarness:
    """Replays recordings through simulator and compares states."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[SyncResult] = []
        self.sim: Optional[SimulatorController] = None
        self.recording: Optional[Dict[str, Any]] = None

    def load_recording(self, run_name: str) -> bool:
        """Load a recording from disk."""
        path = RECORDINGS_DIR / f"{run_name}.json"

        if not path.exists():
            print(f"Recording not found: {path}")
            return False

        with open(path) as f:
            self.recording = json.load(f)

        print(f"Loaded recording: {run_name}")
        print(f"  Steps: {len(self.recording.get('steps', []))}")
        print(f"  Description: {self.recording.get('description', 'N/A')}")

        return True

    def initialize_simulator(self) -> bool:
        """Initialize simulator with the recording's seed."""
        if not self.recording:
            print("No recording loaded")
            return False

        steps = self.recording.get("steps", [])
        if not steps:
            print("Recording has no steps")
            return False

        # Get seed from first step
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
        print(f"  Raw seed: {raw_seed}")
        print(f"  Converted seed: {seed}")
        print(f"  Character: {character}")
        print(f"  Ascension: {ascension}")

        self.sim = SimulatorController()
        self.sim.setup_game(seed, character, ascension)

        return True

    def compare_states(self, game_state: Dict[str, Any], sim_state: Dict[str, Any]) -> Tuple[bool, List[Tuple[str, Any, Any]]]:
        """Compare game and simulator states, return aligned and differences."""
        gs = game_state.get("game_state", {})
        differences = []

        # Fields to compare with their mappings
        comparisons = [
            ("floor", "floor", gs.get("floor")),
            ("current_hp", "cur_hp", gs.get("current_hp")),
            ("max_hp", "max_hp", gs.get("max_hp")),
            ("gold", "gold", gs.get("gold")),
            ("act", "act", gs.get("act")),
            ("screen_name", "screen_state", gs.get("screen_name")),
        ]

        for game_field, sim_field, game_val in comparisons:
            sim_val = sim_state.get(sim_field)
            if game_val != sim_val:
                differences.append((game_field, game_val, sim_val))

        # Compare deck size
        game_deck_size = len(gs.get("deck", []))
        sim_deck_size = len(sim_state.get("deck", []))
        if game_deck_size != sim_deck_size:
            differences.append(("deck_size", game_deck_size, sim_deck_size))

        # Compare relic count
        game_relic_count = len(gs.get("relics", []))
        sim_relic_count = len(sim_state.get("relics", []))
        if game_relic_count != sim_relic_count:
            differences.append(("relic_count", game_relic_count, sim_relic_count))

        return len(differences) == 0, differences

    def replay_step(self, step: Dict[str, Any], step_number: int) -> SyncResult:
        """Replay a single step and compare states."""
        game_state = step.get("game_state", {})
        action = step.get("detected_action", "unknown")

        if self.verbose:
            gs = game_state.get("game_state", {})
            print(f"\n--- Step {step_number} ---")
            print(f"  Action: {action}")
            print(f"  Floor: {gs.get('floor')}, HP: {gs.get('current_hp')}, Gold: {gs.get('gold')}")

        # Get simulator state
        sim_state = self.sim.get_state()

        # Compare
        aligned, differences = self.compare_states(game_state, sim_state)

        if self.verbose and not aligned:
            print(f"  DIVERGED:")
            for field, game_val, sim_val in differences:
                print(f"    {field}: game={game_val}, sim={sim_val}")

        return SyncResult(
            step_number=step_number,
            game_action=action,
            aligned=aligned,
            differences=differences,
            game_state=game_state,
            sim_state=sim_state
        )

    def replay_all(self) -> List[SyncResult]:
        """Replay all steps and collect results."""
        if not self.recording:
            print("No recording loaded")
            return []

        steps = self.recording.get("steps", [])
        print(f"\nReplaying {len(steps)} steps...")

        self.results = []

        for i, step in enumerate(steps, 1):
            result = self.replay_step(step, i)
            self.results.append(result)

            if not result.aligned:
                print(f"  Step {i}: DIVERGED ({len(result.differences)} differences)")
            elif self.verbose:
                print(f"  Step {i}: aligned")

        return self.results

    def generate_report(self, run_name: str) -> Path:
        """Generate markdown report of sync results."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)

        report_path = REPORTS_DIR / f"{run_name}_report.md"

        lines = [
            f"# Sync Test Report: {run_name}",
            f"",
            f"Generated: {datetime.now().isoformat()}",
            f"",
            "## Recording Info",
            f"",
            f"- **Description**: {self.recording.get('description', 'N/A')}",
            f"- **Started**: {self.recording.get('start_time', '?')}",
            f"- **Ended**: {self.recording.get('end_time', '?')}",
            f"",
        ]

        # Statistics from recording
        stats = self.recording.get("stats", {})
        lines.extend([
            "## Recording Statistics",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total steps | {stats.get('total_steps', 0)} |",
            f"| Combats | {stats.get('combats', 0)} |",
            f"| Floors reached | {stats.get('floors_reached', 0)} |",
            f"| Damage taken | {stats.get('damage_taken', 0)} |",
            f"| Gold gained | {stats.get('gold_gained', 0)} |",
            f"| Relics gained | {stats.get('relics_gained', 0)} |",
            f"",
        ])

        # Sync results summary
        if self.results:
            aligned = sum(1 for r in self.results if r.aligned)
            total = len(self.results)
            rate = (aligned / total * 100) if total > 0 else 0

            lines.extend([
                "## Sync Results",
                f"",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Total steps | {total} |",
                f"| Aligned | {aligned} |",
                f"| Diverged | {total - aligned} |",
                f"| Alignment rate | {rate:.1f}% |",
                f"",
            ])

            # Divergence details
            divergences = [(i, r) for i, r in enumerate(self.results) if not r.aligned]

            if divergences:
                lines.extend([
                    "## Divergences",
                    f"",
                ])

                for idx, result in divergences:
                    lines.append(f"### Step {result.step_number}: {result.game_action}")
                    lines.append("")
                    lines.append("| Field | Game | Simulator |")
                    lines.append("|-------|------|-----------|")
                    for field, game_val, sim_val in result.differences:
                        lines.append(f"| {field} | {game_val} | {sim_val} |")
                    lines.append("")

        # Action timeline
        lines.extend([
            "## Action Timeline",
            f"",
        ])

        steps = self.recording.get("steps", [])
        for step in steps:
            ts = step.get("timestamp", "")[11:19]
            action = step.get("detected_action", "?")
            gs = step.get("game_state", {}).get("game_state", {})

            # Find corresponding result
            step_num = step.get("step_number", 0)
            result = self.results[step_num - 1] if step_num <= len(self.results) else None
            status = "✓" if result and result.aligned else "✗" if result else "?"

            lines.append(f"- [{ts}] Step {step_num}: {action} {status}")

        # Write report
        with open(report_path, "w") as f:
            f.write("\n".join(lines))

        print(f"\nReport saved: {report_path}")
        return report_path

    def run_full_test(self, run_name: str) -> bool:
        """Run complete sync test: load, replay, report."""
        print(f"=== Sync Test: {run_name} ===\n")

        # Load recording
        if not self.load_recording(run_name):
            return False

        # Initialize simulator
        if not self.initialize_simulator():
            return False

        # Replay all steps
        self.replay_all()

        # Summary
        aligned = sum(1 for r in self.results if r.aligned)
        total = len(self.results)
        rate = (aligned / total * 100) if total > 0 else 0

        print(f"\n=== Summary ===")
        print(f"Aligned: {aligned}/{total} ({rate:.1f}%)")

        # Generate report
        self.generate_report(run_name)

        return aligned == total


def main():
    parser = argparse.ArgumentParser(
        description="Sync Test Harness - Compare game and simulator states"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Replay command
    replay_parser = subparsers.add_parser("replay", help="Replay recording and compare with simulator")
    replay_parser.add_argument("--run-name", "-n", required=True, help="Recording name")
    replay_parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    # Report command
    report_parser = subparsers.add_parser("report", help="Generate report from existing results")
    report_parser.add_argument("--run-name", "-n", required=True, help="Recording name")

    args = parser.parse_args()

    if args.command == "replay":
        harness = SyncTestHarness(verbose=args.verbose)
        success = harness.run_full_test(args.run_name)
        sys.exit(0 if success else 1)

    elif args.command == "report":
        harness = SyncTestHarness()
        if harness.load_recording(args.run_name):
            harness.generate_report(args.run_name)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
