#!/usr/bin/env python3
"""
CLI for gameplay recording in sts_lightspeed.

This script provides command-line access to recording functionality.
For programmatic recording, use the bridge commands directly:
    echo "record my_run" > /tmp/sts_bridge/command.txt
    echo "stop_record" > /tmp/sts_bridge/command.txt

Usage:
    # Start recording (run in background while you play)
    python gameplay_recorder.py record --run-name "ironclad_run_1"

    # List recorded runs
    python gameplay_recorder.py list

    # Show run summary
    python gameplay_recorder.py summary --run-name "ironclad_run_1"

    # Export run for analysis
    python gameplay_recorder.py export --run-name "ironclad_run_1"
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, Any
import argparse
import signal

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from harness.recorder import GameplayRecorder

RECORDINGS_DIR = Path(__file__).parent / "recordings"
BRIDGE_STATE_PATH = Path("/tmp/sts_bridge/game_state.json")


def list_recordings():
    """List all recorded runs."""
    if not RECORDINGS_DIR.exists():
        print("No recordings found.")
        print("\nTo start recording via bridge:")
        print("  echo \"record my_run\" > /tmp/sts_bridge/command.txt")
        print("\nOr use this CLI (polling-based):")
        print("  python gameplay_recorder.py record --run-name 'my_run'")
        return

    recordings = sorted(RECORDINGS_DIR.glob("*.json"))

    if not recordings:
        print("No recordings found.")
        return

    print(f"Found {len(recordings)} recordings:\n")

    for path in recordings:
        with open(path) as f:
            data = json.load(f)

        stats = data.get("stats", {})
        print(f"  {data['run_name']}")
        print(f"    Steps: {stats.get('total_steps', 0)}, Combats: {stats.get('combats', 0)}, Floors: {stats.get('floors_reached', 0)}")
        print(f"    Started: {data.get('start_time', '?')}")
        if stats.get("deaths", 0) > 0:
            print(f"    Result: DIED")
        print()


def show_summary(run_name: str):
    """Show summary of a recorded run."""
    path = RECORDINGS_DIR / f"{run_name}.json"

    if not path.exists():
        print(f"Recording '{run_name}' not found.")
        return

    with open(path) as f:
        data = json.load(f)

    print(f"=== Recording: {run_name} ===\n")
    print(f"Description: {data.get('description', 'N/A')}")
    print(f"Started: {data.get('start_time', '?')}")
    print(f"Ended: {data.get('end_time', '?')}")

    stats = data.get("stats", {})
    print(f"\n--- Statistics ---")
    print(f"  Total steps: {stats.get('total_steps', 0)}")
    print(f"  Combats: {stats.get('combats', 0)}")
    print(f"  Floors reached: {stats.get('floors_reached', 0)}")
    print(f"  Cards played: {stats.get('cards_played', 0)}")
    print(f"  Damage taken: {stats.get('damage_taken', 0)}")
    print(f"  Gold gained: {stats.get('gold_gained', 0)}")
    print(f"  Relics gained: {stats.get('relics_gained', 0)}")
    print(f"  Deaths: {stats.get('deaths', 0)}")

    # Show action timeline
    print(f"\n--- Action Timeline ---")
    steps = data.get("steps", [])

    # Group by interesting actions
    interesting = []
    for step in steps:
        action = step.get("detected_action", "")
        if any(kw in action for kw in ["floor", "combat", "died", "relic", "gained gold", "card"]):
            interesting.append(step)

    for step in interesting[-30:]:  # Last 30 interesting actions
        ts = step.get("timestamp", "")[11:19]  # Just time
        print(f"  [{ts}] Step {step['step_number']}: {step['detected_action']}")


def export_recording(run_name: str, output_format: str = "json"):
    """Export recording in specified format."""
    path = RECORDINGS_DIR / f"{run_name}.json"

    if not path.exists():
        print(f"Recording '{run_name}' not found.")
        return

    with open(path) as f:
        data = json.load(f)

    if output_format == "json":
        print(json.dumps(data, indent=2))
    elif output_format == "summary":
        show_summary(run_name)
    else:
        print(f"Unknown format: {output_format}")


def run_polling_recorder(run_name: str, description: str, poll_interval: float):
    """Run polling-based recorder (legacy method).

    Note: This polls the game_state.json file, which is less efficient
    than using bridge commands. Prefer:
        echo "record my_run" > /tmp/sts_bridge/command.txt
    """
    recorder = GameplayRecorder(run_name, description, recordings_dir=RECORDINGS_DIR)
    recorder.start_time = datetime.now().isoformat()

    print(f"Recording run: {run_name}")
    print(f"Started at: {recorder.start_time}")
    print(f"Polling interval: {poll_interval}s")
    print("-" * 50)
    print("Play the game normally. Press Ctrl+C to stop recording.")
    print("-" * 50)
    print("\nNOTE: This uses polling (legacy). For better performance, use:")
    print('  echo "record my_run" > /tmp/sts_bridge/command.txt')
    print("-" * 50 + "\n")

    running = True
    last_step = None

    def handle_signal(sig, frame):
        nonlocal running
        print("\nStopping recording...")
        running = False

    signal.signal(signal.SIGINT, handle_signal)

    while running:
        try:
            if BRIDGE_STATE_PATH.exists():
                with open(BRIDGE_STATE_PATH) as f:
                    state = json.load(f)

                step = recorder.record_step(state)
                if step and step != last_step:
                    gs = state.get("game_state", {})
                    print(f"  Step {step.step_number}: {step.detected_action}")
                    print(f"    Floor {gs.get('floor', '?')}, HP {gs.get('current_hp', '?')}/{gs.get('max_hp', '?')}, Gold {gs.get('gold', '?')}")
                    last_step = step

            time.sleep(poll_interval)

        except json.JSONDecodeError:
            # State file being written, skip this poll
            time.sleep(0.1)
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(poll_interval)

    recorder.end_time = datetime.now().isoformat()
    print("\n" + "-" * 50)
    print("Recording stopped.")

    path = recorder.save()
    print(f"Saved recording to: {path}")


def main():
    parser = argparse.ArgumentParser(
        description="CLI for gameplay recording in sts_lightspeed"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Record command (polling-based, legacy)
    record_parser = subparsers.add_parser("record", help="Record a gameplay run (polling-based)")
    record_parser.add_argument("--run-name", "-n", required=True, help="Name for this run")
    record_parser.add_argument("--description", "-d", default="", help="Run description")
    record_parser.add_argument("--interval", "-i", type=float, default=0.5, help="Poll interval in seconds")

    # List command
    subparsers.add_parser("list", help="List recorded runs")

    # Summary command
    summary_parser = subparsers.add_parser("summary", help="Show run summary")
    summary_parser.add_argument("--run-name", "-n", required=True, help="Run name")

    # Export command
    export_parser = subparsers.add_parser("export", help="Export recording")
    export_parser.add_argument("--run-name", "-n", required=True, help="Run name")
    export_parser.add_argument("--format", "-f", default="json", choices=["json", "summary"])

    args = parser.parse_args()

    if args.command == "record":
        run_polling_recorder(args.run_name, args.description, args.interval)
    elif args.command == "list":
        list_recordings()
    elif args.command == "summary":
        show_summary(args.run_name)
    elif args.command == "export":
        export_recording(args.run_name, args.format)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
