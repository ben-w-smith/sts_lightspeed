#!/usr/bin/env python3
"""Bridge script for CommunicationMod.

This script is designed to be run by CommunicationMod. It:
1. Receives game state JSON via stdin from CommunicationMod
2. Writes state to a file for the test runner to read
3. Reads commands from a file that the test runner writes
4. Sends commands back to CommunicationMod via stdout
5. Optionally records gameplay for sync verification

Usage in CommunicationMod config:
    command=python /path/to/communication_bridge.py --state-dir /tmp/sts_bridge

Recording commands (via command.txt):
    record <name> [description] - Start recording
    stop_record                 - Stop recording and save

Example:
    echo "record my_run" > /tmp/sts_bridge/command.txt
    # Play game...
    echo "stop_record" > /tmp/sts_bridge/command.txt
"""
import argparse
import json
import os
import sys
import time
import queue
import threading
from pathlib import Path
from datetime import datetime

# Import recorder - handle both direct execution and module import
try:
    from recorder import GameplayRecorder
except ImportError:
    # When run directly, add parent to path
    sys.path.insert(0, str(Path(__file__).parent))
    from recorder import GameplayRecorder


def stdin_reader_thread(input_queue, log_file):
    """Read lines from stdin and put them in a queue.

    This runs in a separate thread so we don't block on stdin.
    """
    def log(msg):
        with open(log_file, 'a') as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                log("stdin closed, exiting reader thread")
                input_queue.put(None)  # Signal EOF
                break
            input_queue.put(line)
        except Exception as e:
            log(f"stdin reader error: {e}")
            break


def parse_bridge_command(command: str):
    """Parse bridge-specific commands.

    Bridge commands are handled locally and not sent to CommunicationMod.

    Args:
        command: The command string from command.txt

    Returns:
        Tuple of (bridge_cmd_tuple, game_cmd_string)
        - bridge_cmd_tuple: ('record', name, desc), ('stop_record',), or None
        - game_cmd_string: The command to send to CommunicationMod, or None
    """
    if command.startswith('record '):
        # Format: "record <name> [description]"
        parts = command[7:].strip().split(maxsplit=1)
        name = parts[0] if parts else 'unnamed'
        desc = parts[1] if len(parts) > 1 else ''
        return ('record', name, desc), None
    elif command == 'stop_record':
        return ('stop_record',), None
    else:
        # Not a bridge command, pass through to CommunicationMod
        return None, command


def main():
    parser = argparse.ArgumentParser(description='CommunicationMod bridge')
    parser.add_argument('--state-dir', type=str, default='/tmp/sts_bridge',
                        help='Directory for state/command files')
    parser.add_argument('--timeout', type=float, default=30.0,
                        help='Timeout for waiting on commands (not used in threaded mode)')
    parser.add_argument('--record-dir', type=str,
                        default=str(Path(__file__).parent.parent / 'recordings'),
                        help='Directory for recordings')
    parser.add_argument('--log-file', type=str,
                        default='/tmp/sts_bridge/bridge.log',
                        help='Log file for debug output')
    parser.add_argument('--auto-record', type=str, default=None,
                        help='Auto-start recording with this name when game starts')
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)

    state_file = state_dir / 'game_state.json'
    command_file = state_dir / 'command.txt'
    ready_file = state_dir / 'bridge_ready.txt'
    record_dir = Path(args.record_dir)
    log_file = Path(args.log_file)

    # Set up logging to file
    def log(msg):
        with open(log_file, 'a') as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")

    log("=== Bridge started (threaded mode) ===")

    # Start stdin reader thread
    input_queue = queue.Queue()
    reader_thread = threading.Thread(
        target=stdin_reader_thread,
        args=(input_queue, log_file),
        daemon=True
    )
    reader_thread.start()

    # Recording state
    recorder = None
    states_received = 0
    states_recorded = 0
    states_filtered = 0
    auto_record_name = args.auto_record
    auto_record_started = False

    # Signal that we're ready to receive commands
    print("ready", flush=True)

    # Create ready marker
    ready_file.touch()

    try:
        while True:
            # Check for commands first (non-blocking)
            if command_file.exists():
                try:
                    with open(command_file, 'r') as f:
                        command = f.read().strip()
                    command_file.unlink()

                    log(f"COMMAND received: {command}")
                    bridge_cmd, game_cmd = parse_bridge_command(command)

                    # Handle bridge commands
                    if bridge_cmd:
                        if bridge_cmd[0] == 'record':
                            _, name, desc = bridge_cmd
                            recorder = GameplayRecorder(name, desc, recordings_dir=record_dir)
                            log(f"[BRIDGE] Started recording: {name}")
                        elif bridge_cmd[0] == 'stop_record':
                            if recorder:
                                recorder.end_time = datetime.now().isoformat()
                                try:
                                    path = recorder.save()
                                    log(f"[BRIDGE] Saved recording: {path} (states: received={states_received}, recorded={states_recorded}, filtered={states_filtered})")
                                except Exception as e:
                                    log(f"[BRIDGE] Error saving recording: {e}")
                                recorder = None
                                states_received = 0
                                states_recorded = 0
                                states_filtered = 0
                            else:
                                log("[BRIDGE] No active recording to stop")

                    # Send game command to CommunicationMod
                    if game_cmd:
                        log(f"Sending to game: {game_cmd}")
                        print(game_cmd, flush=True)

                except FileNotFoundError:
                    pass

            # Check for state from stdin (with timeout so we can check commands)
            try:
                line = input_queue.get(timeout=0.1)
            except queue.Empty:
                # No state available, loop back to check commands
                continue

            if line is None:
                # EOF from stdin
                log("stdin closed, exiting")
                break

            states_received += 1

            try:
                state = json.loads(line.strip())
            except json.JSONDecodeError:
                log(f"Failed to parse JSON: {line[:100]}...")
                continue

            # Log every state received
            gs = state.get("game_state", {})
            log(f"STATE #{states_received}: Floor={gs.get('floor')} HP={gs.get('current_hp')} Gold={gs.get('gold')} Screen={gs.get('screen_name')} RoomPhase={gs.get('room_phase')}")

            # Write state to file for test runner
            with open(state_file, 'w') as f:
                json.dump(state, f)

            # Auto-start recording if requested and not yet started
            if auto_record_name and not auto_record_started:
                recorder = GameplayRecorder(auto_record_name, "Auto-started recording", recordings_dir=record_dir)
                log(f"[BRIDGE] Auto-started recording: {auto_record_name}")
                auto_record_started = True

            # Record state if recording is active
            if recorder is not None:
                try:
                    step = recorder.record_step(state)
                    if step:
                        states_recorded += 1
                        log(f"[REC] Recorded step {step.step_number}: {step.detected_action}")
                    else:
                        states_filtered += 1
                        log(f"[REC] Filtered (same hash) - total filtered: {states_filtered}")
                except Exception as e:
                    log(f"[REC] ERROR: {e}")

    except KeyboardInterrupt:
        log("Interrupted")
    finally:
        # Save recording if still active
        if recorder:
            log("[BRIDGE] Saving recording before exit...")
            try:
                recorder.end_time = datetime.now().isoformat()
                recorder.save()
            except Exception as e:
                log(f"[BRIDGE] Error saving recording: {e}")

        # Cleanup
        if ready_file.exists():
            ready_file.unlink()

        log("=== Bridge stopped ===")


if __name__ == '__main__':
    main()
