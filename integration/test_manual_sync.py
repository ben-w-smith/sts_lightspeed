#!/usr/bin/env python3
"""Automated sync test - executes a sequence of commands and reports discrepancies.

This script runs without interactive input, making it suitable for automated testing.
"""
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import datetime

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from harness.game_controller import GameController, CommunicationModError
from harness.simulator_controller import SimulatorController
from harness.state_comparator import StateComparator
from harness.action_translator import ActionTranslator


def convert_seed(raw_seed):
    """Convert seed to unsigned int64 if negative."""
    if raw_seed < 0:
        return raw_seed + (1 << 64)
    return raw_seed


def run_sync_test(commands, seed=None, verbose=False):
    """Run a sync test with the given commands."""

    results = {
        'start_time': datetime.now().isoformat(),
        'steps': [],
        'total_discrepancies': 0,
        'critical_discrepancies': 0,
    }

    gc = GameController(state_dir='/tmp/sts_bridge', project_name='auto_sync_test', timeout=30.0)
    comparator = StateComparator()
    translator = ActionTranslator()

    try:
        print("Connecting to game...")
        gc.connect()
        print("Connected!")

        # Get game state and extract seed if not provided
        game_state = gc.get_state()
        gs = game_state.get('game_state', game_state)

        if seed is None:
            raw_seed = gs.get('seed', 12345)
            seed = convert_seed(raw_seed)

        print(f"Using seed: {seed}")

        # Initialize simulator
        character = gs.get('class', 'IRONCLAD').upper()
        ascension = gs.get('ascension_level', 0)

        print(f"Initializing simulator: {character}, ascension {ascension}")
        sim = SimulatorController()
        sim.setup_game(seed, character, ascension)

        # Initial state comparison
        sim_state = sim.get_state()
        initial_comparison = comparator.compare(game_state, sim_state)

        print(f"\nInitial state comparison:")
        print(f"  Match: {initial_comparison.match}")
        print(f"  Summary: {initial_comparison.get_summary()}")

        if not initial_comparison.match and verbose:
            for d in initial_comparison.discrepancies[:5]:
                print(f"    [{d.severity.value}] {d.field}: game={d.game_value}, sim={d.sim_value}")

        # Execute commands
        for i, cmd in enumerate(commands):
            print(f"\n--- Step {i+1}: {cmd} ---")

            # Translate command
            action = translator.from_game_to_sim(cmd)

            # Get pre-states
            pre_game = gc.get_state()
            pre_sim = sim.get_state()

            # Execute on game
            if action.game_command:
                print(f"  Game command: {action.game_command}")
                gc.send_command(action.game_command)
                time.sleep(1.5)  # Wait for game to process

            # Execute on simulator
            if action.sim_command:
                print(f"  Sim command: {action.sim_command}")
                try:
                    sim.take_action(action.sim_command)
                except Exception as e:
                    print(f"  Sim error: {e}")

            # Get post-states
            post_game = gc.get_state()
            post_sim = sim.get_state()

            # Compare
            comparison = comparator.compare(post_game, post_sim)

            step_result = {
                'step': i + 1,
                'command': cmd,
                'passed': comparison.critical_count == 0,
                'critical_count': comparison.critical_count,
                'major_count': comparison.major_count,
                'minor_count': comparison.minor_count,
            }
            results['steps'].append(step_result)

            print(f"  Result: {'PASS' if step_result['passed'] else 'FAIL'}")
            print(f"  Discrepancies: {comparison.get_summary()}")

            if not comparison.match:
                results['total_discrepancies'] += len(comparison.discrepancies)
                results['critical_discrepancies'] += comparison.critical_count

                if verbose:
                    for d in comparison.discrepancies[:3]:
                        print(f"    [{d.severity.value}] {d.field}: game={d.game_value}, sim={d.sim_value}")

        results['end_time'] = datetime.now().isoformat()
        results['success'] = results['critical_discrepancies'] == 0

    except Exception as e:
        print(f"Error: {e}")
        results['error'] = str(e)
        results['success'] = False

    finally:
        gc.disconnect()

    return results


def main():
    parser = argparse.ArgumentParser(description="Automated sync test")
    parser.add_argument('--seed', type=int, default=None, help='Game seed (extracted from game if not provided)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    parser.add_argument('--commands', '-c', nargs='+', default=['choose 0'], help='Commands to execute')
    parser.add_argument('--output', '-o', type=str, default=None, help='Output file for results')

    args = parser.parse_args()

    print(f"Commands to execute: {args.commands}")
    results = run_sync_test(args.commands, args.seed, args.verbose)

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total steps: {len(results['steps'])}")
    print(f"Critical discrepancies: {results.get('critical_discrepancies', 0)}")
    print(f"Success: {results.get('success', False)}")

    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"Results saved to: {args.output}")

    return 0 if results.get('success', False) else 1


if __name__ == "__main__":
    sys.exit(main())
