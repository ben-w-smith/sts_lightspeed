#!/usr/bin/env python3
"""Quick script to verify simulator determinism with seeds.

STS-002: Game vs simulator play same seed, compare state.

This script runs the simulator multiple times with the same seed
and verifies that all runs produce identical outcomes.
"""
import sys
import os
sys.path.insert(0, os.path.expanduser("~/development/sts_lightspeed/build"))

import slaythespire
from typing import List, Dict, Any
import re


def get_available_actions(screen_text: str) -> List[str]:
    """Parse available actions from screen text.

    Returns list of action strings (e.g., ['0', '1', '2']).
    """
    actions = []
    for line in screen_text.split('\n'):
        # Match "0: description" or "1) description" patterns
        match = re.match(r'^(\d+)[\):]\s', line.strip())
        if match:
            actions.append(match.group(1))
    return actions


def play_game_with_seed(seed: int, max_steps: int = 1000) -> Dict[str, Any]:
    """Play a single game with the given seed.

    Returns a dict with the game outcome and key state snapshots.
    """
    sim = slaythespire.ConsoleSimulator()
    sim.setup_game(seed, slaythespire.CharacterClass.IRONCLAD, 0)  # Ascension 0

    gc = sim.gc
    states = []
    step = 0
    last_floor = 0
    outcome = None

    while step < max_steps:
        current_floor = gc.floor_num
        current_act = gc.act
        hp = gc.cur_hp
        gold = gc.gold

        # Record state on floor change
        if current_floor != last_floor:
            states.append({
                'step': step,
                'floor': current_floor,
                'hp': hp,
                'gold': gold,
                'act': current_act,
            })
            last_floor = current_floor

        # Check if game over
        if gc.outcome != slaythespire.GameOutcome.UNDECIDED:
            outcome = gc.outcome.name
            states.append({
                'step': step,
                'floor': current_floor,
                'hp': hp,
                'outcome': outcome,
            })
            break

        # Get available actions and take first one (deterministic)
        screen_text = sim.get_screen_text()
        actions = get_available_actions(screen_text)

        if not actions:
            # No actions available, stuck
            outcome = 'STUCK'
            break

        # Always pick first option for determinism
        sim.take_action(actions[0])
        step += 1
        gc = sim.gc  # Refresh reference

    return {
        'seed': seed,
        'steps': step,
        'states': states,
        'final_hp': gc.cur_hp,
        'final_floor': gc.floor_num,
        'outcome': outcome or 'INCOMPLETE',
    }


def compare_runs(runs: List[Dict[str, Any]]) -> bool:
    """Compare multiple runs to verify they're identical.

    Returns True if all runs match, False otherwise.
    """
    if len(runs) < 2:
        return True

    first = runs[0]

    # Check final outcomes match
    for i, run in enumerate(runs[1:], 1):
        if run['final_floor'] != first['final_floor']:
            print(f"  MISMATCH: Run {i} floor {run['final_floor']} vs run 0 floor {first['final_floor']}")
            return False
        if run['final_hp'] != first['final_hp']:
            print(f"  MISMATCH: Run {i} HP {run['final_hp']} vs run 0 HP {first['final_hp']}")
            return False
        if run['outcome'] != first['outcome']:
            print(f"  MISMATCH: Run {i} outcome {run['outcome']} vs run 0 outcome {first['outcome']}")
            return False

        # Check state snapshots match
        for j, (s1, s2) in enumerate(zip(first['states'], run['states'])):
            if s1 != s2:
                print(f"  MISMATCH at state {j}:")
                print(f"    Run 0: {s1}")
                print(f"    Run {i}: {s2}")
                return False

    return True


def main():
    print("=" * 60)
    print("STS Seed Sync Check - Verifying Simulator Determinism")
    print("=" * 60)

    # Test with a few different seeds
    test_seeds = [12345, 54321, 99999]
    num_runs_per_seed = 3

    all_passed = True

    for seed in test_seeds:
        print(f"\n--- Testing seed {seed} ({num_runs_per_seed} runs) ---")

        runs = []
        for i in range(num_runs_per_seed):
            print(f"  Run {i+1}...", end=" ", flush=True)
            result = play_game_with_seed(seed)
            runs.append(result)
            print(f"floor {result['final_floor']}, HP {result['final_hp']}, {result['outcome']}")

        if compare_runs(runs):
            print(f"  PASS: All {num_runs_per_seed} runs identical")
        else:
            print(f"  FAIL: Runs diverged!")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("SUCCESS: All seeds produce deterministic results")
        return 0
    else:
        print("FAILURE: Non-deterministic behavior detected")
        return 1


if __name__ == "__main__":
    sys.exit(main())
