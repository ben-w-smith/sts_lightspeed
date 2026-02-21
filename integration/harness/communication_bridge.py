#!/usr/bin/env python3
"""Bridge script for CommunicationMod.

This script is designed to be run by CommunicationMod. It:
1. Receives game state JSON via stdin from CommunicationMod
2. Writes state to a file for the test runner to read
3. Reads commands from a file that the test runner writes
4. Sends commands back to CommunicationMod via stdout

Usage in CommunicationMod config:
    command=python /path/to/communication_bridge.py --state-dir /tmp/sts_bridge
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='CommunicationMod bridge')
    parser.add_argument('--state-dir', type=str, default='/tmp/sts_bridge',
                        help='Directory for state/command files')
    parser.add_argument('--timeout', type=float, default=30.0,
                        help='Timeout for waiting on commands')
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / 'game_state.json'
    command_file = state_dir / 'command.txt'
    ready_file = state_dir / 'bridge_ready.txt'

    # Signal that we're ready to receive commands
    print("ready", flush=True)

    # Create ready marker
    ready_file.touch()

    try:
        while True:
            # Read game state from stdin (CommunicationMod sends this)
            line = sys.stdin.readline()
            if not line:
                break

            try:
                state = json.loads(line.strip())
            except json.JSONDecodeError:
                continue

            # Write state to file for test runner
            with open(state_file, 'w') as f:
                json.dump(state, f)

            # Wait for command from test runner
            start_time = time.time()
            command = None

            while time.time() - start_time < args.timeout:
                if command_file.exists():
                    try:
                        with open(command_file, 'r') as f:
                            command = f.read().strip()
                        # Remove command file after reading
                        command_file.unlink()
                        break
                    except FileNotFoundError:
                        pass
                time.sleep(0.05)

            if command:
                # Send command to CommunicationMod
                print(command, flush=True)
            else:
                # No command received, could send 'state' to request update
                # or just wait for next state
                pass

    except KeyboardInterrupt:
        pass
    finally:
        # Cleanup
        if ready_file.exists():
            ready_file.unlink()


if __name__ == '__main__':
    main()
