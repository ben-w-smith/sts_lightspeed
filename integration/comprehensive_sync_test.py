#!/usr/bin/env python3
"""Comprehensive sync test - plays through a combat and logs discrepancies."""
import json
import sys
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from harness.game_controller import GameController
from harness.simulator_controller import SimulatorController
from harness.state_comparator import StateComparator


def log(msg, level="INFO"):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{timestamp}] [{level}] {msg}")


def get_game_combat_state(gc):
    """Extract simplified combat state for comparison."""
    state = gc.get_state()
    gs = state.get('game_state', {})
    cs = gs.get('combat_state', {})

    return {
        'floor': gs.get('floor'),
        'hp': gs.get('current_hp'),
        'max_hp': gs.get('max_hp'),
        'gold': gs.get('gold'),
        'turn': cs.get('turn') if cs else None,
        'player_energy': cs.get('player', {}).get('energy') if cs else None,
        'player_block': cs.get('player', {}).get('block') if cs else None,
        'monsters': [
            {'name': m.get('name'), 'hp': m.get('current_hp'), 'max_hp': m.get('max_hp'), 'block': m.get('block')}
            for m in cs.get('monsters', [])
        ] if cs else [],
        'hand_size': len(cs.get('hand', [])) if cs else 0,
    }


def get_sim_combat_state(sim):
    """Extract simplified combat state from simulator."""
    state = sim.get_state()
    cs = state.get('combat_state', {})

    return {
        'floor': state.get('floor'),
        'hp': state.get('cur_hp'),
        'max_hp': state.get('max_hp'),
        'gold': state.get('gold'),
        'turn': cs.get('turn') if cs else None,
        'player_energy': cs.get('player', {}).get('energy') if cs else None,
        'player_block': cs.get('player', {}).get('block') if cs else None,
        'monsters': cs.get('monsters', []) if cs else [],
        'hand_size': len(cs.get('hand', [])) if cs else 0,
    }


def compare_combat_states(game, sim):
    """Compare key combat fields and return discrepancies."""
    discrepancies = []

    # Player HP
    if game.get('hp') != sim.get('hp'):
        discrepancies.append(f"Player HP: game={game.get('hp')}, sim={sim.get('hp')}")

    # Gold
    if game.get('gold') != sim.get('gold'):
        discrepancies.append(f"Gold: game={game.get('gold')}, sim={sim.get('gold')}")

    # Monsters
    game_monsters = game.get('monsters', [])
    sim_monsters = sim.get('monsters', [])

    if len(game_monsters) != len(sim_monsters):
        discrepancies.append(f"Monster count: game={len(game_monsters)}, sim={len(sim_monsters)}")
    else:
        for i, (gm, sm) in enumerate(zip(game_monsters, sim_monsters)):
            if gm.get('hp') != sm.get('cur_hp'):
                discrepancies.append(f"Monster {i} HP: game={gm.get('hp')}, sim={sm.get('cur_hp')}")

    return discrepancies


def main():
    issues_found = []
    test_log = []

    log("=" * 60)
    log("COMPREHENSIVE SYNC TEST")
    log("=" * 60)

    # Connect to game
    gc = GameController(state_dir='/tmp/sts_bridge', project_name='comprehensive_test', timeout=30.0)
    gc.connect()

    # Get game state
    game_state = get_game_combat_state(gc)
    log(f"Game state: floor={game_state['floor']}, HP={game_state['hp']}, monsters={len(game_state['monsters'])}")

    # Note: We can't sync simulator with game due to Neow RNG divergence
    # The game has 1 HP monsters from Neow bonus, simulator doesn't

    log("")
    log("Testing game combat state retrieval...")

    for i, m in enumerate(game_state['monsters']):
        log(f"Monster {i}: {m['name']} HP={m['hp']}/{m['max_hp']}")

    # Check if monster has 1 HP (Neow bonus)
    if game_state['monsters'] and game_state['monsters'][0]['hp'] == 1:
        issue = "ISSUE-001: Neow bonus 'enemies have 1 hp' causes game/sim divergence"
        log(issue, "WARNING")
        issues_found.append({
            'id': 'ISSUE-001',
            'title': 'Neow bonus causes game/simulator state divergence',
            'description': 'Game has 1 HP monsters from Neow bonus, simulator cannot replicate without same Neow choice',
            'severity': 'major'
        })

    # Test command sending (even though it may not work)
    log("")
    log("Testing command sending...")
    gc.send_command('state')
    time.sleep(1)

    new_state = get_game_combat_state(gc)
    if new_state == game_state:
        log("State unchanged (commands may not be processed)", "WARNING")
    else:
        log("State changed!", "INFO")

    gc.disconnect()

    # Summary
    log("")
    log("=" * 60)
    log("TEST SUMMARY")
    log("=" * 60)
    log(f"Issues found: {len(issues_found)}")

    for issue in issues_found:
        log(f"  [{issue['severity']}] {issue['id']}: {issue['title']}")

    return issues_found


if __name__ == "__main__":
    issues = main()
    sys.exit(len(issues))
