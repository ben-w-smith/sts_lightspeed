#!/usr/bin/env python3
"""Game state monitor - watches and logs game state changes."""
import json
import sys
import time
from pathlib import Path
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from harness.game_controller import GameController


class GameStateMonitor:
    def __init__(self, log_file="game_session_log.json"):
        self.log_file = log_file
        self.events = []
        self.stats = defaultdict(int)
        self.last_state = None

    def log_event(self, event_type, data):
        event = {
            'time': datetime.now().isoformat(),
            'type': event_type,
            'data': data
        }
        self.events.append(event)
        print(f"[{event['time']}] {event_type}: {data.get('summary', '')}")

    def extract_state_summary(self, state):
        gs = state.get('game_state', state)
        cs = gs.get('combat_state', {})

        summary = {
            'floor': gs.get('floor'),
            'hp': gs.get('current_hp'),
            'max_hp': gs.get('max_hp'),
            'gold': gs.get('gold'),
            'act': gs.get('act'),
            'room_type': gs.get('room_type'),
            'room_phase': gs.get('room_phase'),
            'screen_type': gs.get('screen_type'),
        }

        if cs:
            summary['turn'] = cs.get('turn')
            summary['energy'] = cs.get('player', {}).get('energy')
            summary['monsters'] = [(m.get('name'), m.get('current_hp')) for m in cs.get('monsters', [])]
            summary['hand_size'] = len(cs.get('hand', []))

        return summary

    def detect_changes(self, old_state, new_state):
        changes = []
        if old_state is None:
            return ['initial_state']

        old = self.extract_state_summary(old_state)
        new = self.extract_state_summary(new_state)

        if old.get('floor') != new.get('floor'):
            changes.append(f"floor: {old.get('floor')} -> {new.get('floor')}")
            self.stats['floor_changes'] += 1

        if old.get('hp') != new.get('hp'):
            changes.append(f"hp: {old.get('hp')} -> {new.get('hp')}")
            self.stats['hp_changes'] += 1

        if old.get('gold') != new.get('gold'):
            changes.append(f"gold: {old.get('gold')} -> {new.get('gold')}")
            self.stats['gold_changes'] += 1

        if old.get('room_type') != new.get('room_type'):
            changes.append(f"room: {old.get('room_type')} -> {new.get('room_type')}")
            self.stats['room_changes'] += 1

        if old.get('room_phase') == 'COMBAT' and new.get('room_phase') != 'COMBAT':
            changes.append("combat_ended")
            self.stats['combats_completed'] += 1

        if old.get('room_phase') != 'COMBAT' and new.get('room_phase') == 'COMBAT':
            changes.append("combat_started")
            self.stats['combats_started'] += 1

        if old.get('turn') != new.get('turn') and old.get('turn') is not None:
            changes.append(f"turn: {old.get('turn')} -> {new.get('turn')}")
            self.stats['turns'] += 1

        return changes

    def run(self, duration_seconds=300, poll_interval=0.5):
        gc = GameController(state_dir='/tmp/sts_bridge', project_name='monitor', timeout=30.0)
        gc.connect()

        print(f"Monitoring game state for {duration_seconds}s...")
        print("Play the game normally. Press Ctrl+C to stop.\n")

        start_time = time.time()

        try:
            while time.time() - start_time < duration_seconds:
                state = gc.get_state()
                changes = self.detect_changes(self.last_state, state)

                if changes:
                    summary = self.extract_state_summary(state)
                    self.log_event('state_change', {
                        'summary': ', '.join(changes),
                        'state': summary
                    })

                self.last_state = state
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\n\nMonitoring stopped by user.")

        finally:
            gc.disconnect()

        # Save log
        with open(self.log_file, 'w') as f:
            json.dump({
                'stats': dict(self.stats),
                'events': self.events
            }, f, indent=2)

        print(f"\nSession log saved to: {self.log_file}")
        print(f"Stats: {dict(self.stats)}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Monitor game state")
    parser.add_argument('--duration', type=int, default=600, help='Duration in seconds')
    parser.add_argument('--output', type=str, default='game_session_log.json', help='Output file')
    args = parser.parse_args()

    monitor = GameStateMonitor(log_file=args.output)
    monitor.run(duration_seconds=args.duration)
