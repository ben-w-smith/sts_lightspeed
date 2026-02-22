#!/usr/bin/env python3
"""
Snapshot-based sync testing for sts_lightspeed.

This approach avoids the timing issues of real-time sync by:
1. Capturing game state snapshots manually
2. Loading snapshots into the simulator
3. Comparing states without time pressure

Usage:
    # Capture current game state as a snapshot
    python snapshot_sync_test.py capture --name "post_neow"

    # List captured snapshots
    python snapshot_sync_test.py list

    # Compare snapshot with simulator state
    python snapshot_sync_test.py compare --name "post_neow"

    # Run all snapshot comparisons
    python snapshot_sync_test.py test-all
"""

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import argparse

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from harness.simulator_controller import SimulatorController

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"
BRIDGE_STATE_PATH = Path("/tmp/sts_bridge/game_state.json")


def ensure_snapshot_dir():
    """Ensure snapshot directory exists."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)


def capture_snapshot(name: str, description: str = "") -> Path:
    """Capture current game state as a named snapshot."""
    ensure_snapshot_dir()

    if not BRIDGE_STATE_PATH.exists():
        print(f"ERROR: No game state found at {BRIDGE_STATE_PATH}")
        print("Make sure the game is running with CommunicationMod")
        sys.exit(1)

    with open(BRIDGE_STATE_PATH) as f:
        game_state = json.load(f)

    # Create snapshot with metadata
    snapshot = {
        "name": name,
        "description": description,
        "captured_at": datetime.now().isoformat(),
        "game_state": game_state
    }

    # Save snapshot
    snapshot_path = SNAPSHOT_DIR / f"{name}.json"
    with open(snapshot_path, "w") as f:
        json.dump(snapshot, f, indent=2)

    print(f"Captured snapshot: {name}")
    print(f"  Floor: {game_state.get('game_state', {}).get('floor', '?')}")
    print(f"  HP: {game_state.get('game_state', {}).get('current_hp', '?')}/{game_state.get('game_state', {}).get('max_hp', '?')}")
    print(f"  Gold: {game_state.get('game_state', {}).get('gold', '?')}")
    print(f"  Screen: {game_state.get('game_state', {}).get('screen_name', '?')}")

    return snapshot_path


def list_snapshots():
    """List all captured snapshots."""
    ensure_snapshot_dir()

    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))

    if not snapshots:
        print("No snapshots found.")
        print("\nTo capture a snapshot:")
        print("  python snapshot_sync_test.py capture --name 'my_snapshot'")
        return

    print(f"Found {len(snapshots)} snapshots:\n")

    for path in snapshots:
        with open(path) as f:
            data = json.load(f)

        gs = data.get("game_state", {}).get("game_state", {})
        print(f"  {data['name']}")
        print(f"    Captured: {data.get('captured_at', '?')}")
        print(f"    Floor: {gs.get('floor', '?')}, HP: {gs.get('current_hp', '?')}/{gs.get('max_hp', '?')}")
        print(f"    Screen: {gs.get('screen_name', '?')}")
        print()


def compare_snapshot(name: str) -> Dict[str, Any]:
    """Compare a snapshot with simulator state."""
    snapshot_path = SNAPSHOT_DIR / f"{name}.json"

    if not snapshot_path.exists():
        print(f"ERROR: Snapshot '{name}' not found")
        print("Available snapshots:")
        list_snapshots()
        sys.exit(1)

    with open(snapshot_path) as f:
        snapshot = json.load(f)

    game_state = snapshot["game_state"]
    gs = game_state.get("game_state", {})

    print(f"Comparing snapshot: {name}")
    print(f"  Description: {snapshot.get('description', 'N/A')}")
    print(f"  Captured: {snapshot.get('captured_at', '?')}")
    print()

    # Extract seed and convert for simulator
    raw_seed = gs.get("seed", 0)
    if raw_seed < 0:
        seed = raw_seed + (1 << 64)
    else:
        seed = raw_seed

    print(f"Game seed: {raw_seed} (unsigned: {seed})")
    print(f"Character: {gs.get('class', 'IRONCLAD')}")
    print(f"Ascension: {gs.get('ascension_level', 1)}")
    print()

    # Initialize simulator
    print("Initializing simulator...")
    sim = SimulatorController()
    sim.setup_game(seed, gs.get("class", "IRONCLAD"), gs.get("ascension_level", 1))

    # Get simulator state
    sim_state = sim.get_state()

    # Compare key fields
    print("\n=== State Comparison ===\n")

    # Map game state fields to simulator state fields
    comparisons = [
        ("Floor", gs.get("floor"), sim_state.get("floor")),
        ("Current HP", gs.get("current_hp"), sim_state.get("cur_hp")),
        ("Max HP", gs.get("max_hp"), sim_state.get("max_hp")),
        ("Gold", gs.get("gold"), sim_state.get("gold")),
        ("Act", gs.get("act"), sim_state.get("act")),
        ("Screen", gs.get("screen_name"), sim_state.get("screen_state")),
    ]

    matches = 0
    mismatches = 0

    for field, game_val, sim_val in comparisons:
        match = "✓" if game_val == sim_val else "✗"
        if game_val == sim_val:
            matches += 1
        else:
            mismatches += 1
        print(f"  {field:15} Game: {game_val!r:20} Sim: {sim_val!r:20} {match}")

    print()

    # Compare deck
    print("=== Deck Comparison ===\n")
    game_deck = gs.get("deck", [])
    sim_deck = sim_state.get("deck", [])

    print(f"  Game deck: {len(game_deck)} cards")
    print(f"  Sim deck:  {len(sim_deck)} cards")

    game_card_names = sorted([c.get("name", c.get("id", "?")) for c in game_deck])
    sim_card_names = sorted([c.get("name", c.get("id", "?")) for c in sim_deck])

    if game_card_names == sim_card_names:
        print("  ✓ Deck composition matches")
    else:
        print("  ✗ Deck composition differs")
        print(f"    Game only: {set(game_card_names) - set(sim_card_names)}")
        print(f"    Sim only:  {set(sim_card_names) - set(game_card_names)}")

    # Compare relics
    print("\n=== Relic Comparison ===\n")
    game_relics = [r.get("name", r.get("id", "?")) for r in gs.get("relics", [])]
    sim_relics = sim_state.get("relics", [])

    print(f"  Game relics: {game_relics}")
    print(f"  Sim relics:  {sim_relics}")

    # Summary
    print("\n=== Summary ===\n")
    print(f"  Matches: {matches}/{len(comparisons)}")

    result = {
        "snapshot": name,
        "matches": matches,
        "mismatches": mismatches,
        "total_fields": len(comparisons)
    }

    if mismatches == 0:
        print("  Result: ✓ ALL FIELDS MATCH")
    else:
        print(f"  Result: ✗ {mismatches} mismatches found")
        print("\nNote: Mismatches are expected if Neow event choices differ.")
        print("The snapshot-based approach isolates these differences for analysis.")

    return result


def test_all_snapshots():
    """Run comparison on all captured snapshots."""
    ensure_snapshot_dir()

    snapshots = sorted(SNAPSHOT_DIR.glob("*.json"))

    if not snapshots:
        print("No snapshots found to test.")
        return

    print(f"Running comparison on {len(snapshots)} snapshots...\n")
    print("=" * 60)

    results = []

    for path in snapshots:
        name = path.stem
        print(f"\n--- Testing: {name} ---\n")
        try:
            result = compare_snapshot(name)
            results.append(result)
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"snapshot": name, "error": str(e)})

    # Summary
    print("\n" + "=" * 60)
    print("\n=== Test Summary ===\n")

    total_matches = sum(r.get("matches", 0) for r in results)
    total_mismatches = sum(r.get("mismatches", 0) for r in results)
    errors = [r for r in results if "error" in r]

    for r in results:
        if "error" in r:
            print(f"  {r['snapshot']}: ERROR - {r['error']}")
        else:
            status = "✓" if r["mismatches"] == 0 else "✗"
            print(f"  {r['snapshot']}: {status} ({r['matches']}/{r['total_fields']} matches)")

    print(f"\nTotal: {total_matches} matches, {total_mismatches} mismatches, {len(errors)} errors")


def main():
    parser = argparse.ArgumentParser(
        description="Snapshot-based sync testing for sts_lightspeed"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Capture command
    capture_parser = subparsers.add_parser("capture", help="Capture current game state")
    capture_parser.add_argument("--name", "-n", required=True, help="Snapshot name")
    capture_parser.add_argument("--description", "-d", default="", help="Snapshot description")

    # List command
    subparsers.add_parser("list", help="List captured snapshots")

    # Compare command
    compare_parser = subparsers.add_parser("compare", help="Compare snapshot with simulator")
    compare_parser.add_argument("--name", "-n", required=True, help="Snapshot name")

    # Test all command
    subparsers.add_parser("test-all", help="Test all snapshots")

    args = parser.parse_args()

    if args.command == "capture":
        capture_snapshot(args.name, args.description)
    elif args.command == "list":
        list_snapshots()
    elif args.command == "compare":
        compare_snapshot(args.name)
    elif args.command == "test-all":
        test_all_snapshots()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
