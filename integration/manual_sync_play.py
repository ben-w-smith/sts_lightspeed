#!/usr/bin/env python3
"""Manual sync play - play Slay the Spire while simulator mirrors your actions.

This lets you manually play the game by typing commands, which are sent to
both the real game (via CommunicationMod) and the simulator simultaneously.
After each action, states are compared and discrepancies reported.

Usage:
    python manual_sync_play.py --seed 12345

Commands you can type:
    play <idx> [target]  - Play card at index, optionally targeting monster
    end                  - End your turn
    choose <idx>         - Choose option at events/rewards
    potion use <slot>    - Use potion
    potion discard <slot> - Discard potion
    map <idx>            - Choose map node
    rest                 - Rest at campfire
    status               - Show current state comparison
    history              - Show action history
    undo                 - Not supported (can't undo in real game)
    quit                 - Exit

Example session:
    > play 0           # Play first card
    > play 2 1         # Play card 2 targeting monster 1
    > end              # End turn
    > choose 0         # Pick first reward option
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Add paths for imports
_project_root = Path(__file__).parent.parent
_integration_dir = Path(__file__).parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_integration_dir))

from harness.game_controller import GameController, CommunicationModError
from harness.sync_orchestrator import SyncOrchestrator, StepResult
from harness.action_translator import ActionTranslator, TranslatedAction, ActionType


class ManualSyncPlay:
    """Manual play with synchronized game and simulator."""

    def __init__(
        self,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        state_dir: str = '/tmp/sts_bridge',
        verbose: bool = False
    ):
        self.seed = seed
        self.character = character
        self.ascension = ascension
        self.state_dir = state_dir
        self.verbose = verbose

        self.orchestrator: Optional[SyncOrchestrator] = None
        self.translator = ActionTranslator()
        self.history: List[StepResult] = []
        self._running = False

    def start(self) -> bool:
        """Start the sync play session."""
        print(f"\n{'='*60}")
        print(f"MANUAL SYNC PLAY")
        print(f"{'='*60}")
        print(f"Seed: {self.seed}")
        print(f"Character: {self.character}")
        print(f"Ascension: {self.ascension}")
        print(f"{'='*60}\n")

        # Create orchestrator
        self.orchestrator = SyncOrchestrator(
            state_dir=self.state_dir,
            action_delay=0.3,  # Give game time to process
            stop_on_critical=False,  # Keep going even on discrepancies
            verbose=self.verbose,
        )

        # Connect to game
        print("Connecting to CommunicationMod...")
        try:
            self.orchestrator.connect_game(project_name="manual_sync_play")
        except CommunicationModError as e:
            print(f"ERROR: {e}")
            return False

        # Initialize simulator with same seed
        print(f"Initializing simulator with seed {self.seed}...")
        self.orchestrator.initialize_simulator(
            seed=self.seed,
            character=self.character,
            ascension=self.ascension
        )

        # Verify initial states match
        print("Verifying initial state...")
        try:
            comparison = self.orchestrator.verify_initial_states()
            if comparison.match:
                print("Initial states match!")
            else:
                print(f"WARNING: Initial state mismatch!")
                print(f"  {comparison.get_summary()}")
                for d in comparison.discrepancies[:5]:
                    print(f"    - {d.field}: game={d.game_value}, sim={d.sim_value}")
        except Exception as e:
            print(f"Warning: Could not verify initial states: {e}")

        print("\nReady! Type 'help' for commands.\n")
        return True

    def stop(self):
        """Stop the sync play session."""
        if self.orchestrator:
            self.orchestrator.disconnect()
        print("\nSession ended.")

    def execute_command(self, command_str: str) -> Optional[StepResult]:
        """Execute a command on both game and simulator."""
        if not self.orchestrator:
            print("Not connected!")
            return None

        command_str = command_str.strip()
        if not command_str:
            return None

        # Parse command
        parts = command_str.lower().split()
        cmd = parts[0] if parts else ""

        # Handle meta commands
        if cmd in ('help', 'h', '?'):
            self._show_help()
            return None
        elif cmd in ('quit', 'q', 'exit'):
            self._running = False
            return None
        elif cmd == 'status':
            self._show_status()
            return None
        elif cmd == 'history':
            self._show_history()
            return None
        elif cmd == 'gamestate':
            self._show_game_state()
            return None
        elif cmd == 'simstate':
            self._show_sim_state()
            return None

        # Translate command to action
        action = self._translate_command(command_str)
        if action is None:
            print(f"Unknown command: {command_str}")
            return None

        # Execute on both game and simulator
        print(f"\n> {command_str}")
        result = self.orchestrator.execute_action(action, compare=True)
        self.history.append(result)

        # Report result
        if result.error:
            print(f"  ERROR: {result.error}")
        elif result.passed:
            print(f"  OK (step {result.step_number})")
        else:
            print(f"  DISCREPANCY at step {result.step_number}:")
            if result.comparison:
                for d in result.comparison.discrepancies:
                    severity = d.severity.value.upper()
                    print(f"    [{severity}] {d.field}: game={d.game_value}, sim={d.sim_value}")

        return result

    def _translate_command(self, command_str: str) -> Optional[TranslatedAction]:
        """Translate a command string to TranslatedAction."""
        parts = command_str.strip().split()
        if not parts:
            return None

        cmd = parts[0].lower()

        # Map commands to game format
        if cmd == 'play':
            if len(parts) >= 3:
                return self.translator.from_game_to_sim(f"play {parts[1]} {parts[2]}")
            elif len(parts) >= 2:
                return self.translator.from_game_to_sim(f"play {parts[1]}")
            else:
                print("Usage: play <card_idx> [target_idx]")
                return None

        elif cmd == 'end':
            return self.translator.from_game_to_sim("end")

        elif cmd == 'choose':
            if len(parts) >= 2:
                return self.translator.from_game_to_sim(f"choose {parts[1]}")
            else:
                print("Usage: choose <option_idx>")
                return None

        elif cmd == 'potion':
            if len(parts) >= 3:
                subcmd = parts[1].lower()
                if subcmd == 'use':
                    if len(parts) >= 4:
                        return self.translator.from_game_to_sim(f"potion use {parts[2]} {parts[3]}")
                    else:
                        return self.translator.from_game_to_sim(f"potion use {parts[2]}")
                elif subcmd == 'discard':
                    return self.translator.from_game_to_sim(f"potion discard {parts[2]}")
            print("Usage: potion use <slot> [target] | potion discard <slot>")
            return None

        elif cmd == 'map':
            if len(parts) >= 2:
                return TranslatedAction(
                    action_type=ActionType.MAP_MOVE,
                    game_command=f"choose {parts[1]}",
                    sim_command=parts[1],
                    params={'node_index': int(parts[1])}
                )
            print("Usage: map <node_idx>")
            return None

        elif cmd == 'rest':
            return TranslatedAction(
                action_type=ActionType.REST,
                game_command="choose 0",
                sim_command="0",
                params={'rest_choice': 0}
            )

        # Try as raw game command
        return self.translator.from_game_to_sim(command_str)

    def _show_help(self):
        """Show help text."""
        print("""
Commands:
  play <idx> [target]  - Play card (optionally target monster)
  end                  - End turn
  choose <idx>         - Choose option at events/rewards
  potion use <slot> [target] - Use potion
  potion discard <slot> - Discard potion
  map <idx>            - Choose map node
  rest                 - Rest at campfire

Meta commands:
  status    - Show current state comparison
  history   - Show action history
  gamestate - Show full game state
  simstate  - Show full simulator state
  help      - Show this help
  quit      - Exit

Examples:
  play 0        # Play first card in hand
  play 2 1      # Play card 2 targeting monster 1
  end           # End your turn
  choose 0      # Pick first option
""")

    def _show_status(self):
        """Show current state comparison."""
        if not self.orchestrator:
            return

        game_state = self.orchestrator.get_game_state()
        sim_state = self.orchestrator.get_sim_state()

        if not game_state or not sim_state:
            print("States not available")
            return

        # Show summary
        gs = game_state.get('game_state', game_state)
        ss = sim_state

        print(f"\n{'='*40}")
        print(f"GAME                          SIMULATOR")
        print(f"{'='*40}")
        print(f"Floor:    {gs.get('floor', '?'):>6}              {ss.get('floor', '?')}")
        print(f"HP:       {gs.get('current_hp', '?')}/{gs.get('max_hp', '?'):<6}        {ss.get('cur_hp', '?')}/{ss.get('max_hp', '?')}")
        print(f"Gold:     {gs.get('gold', '?'):>6}              {ss.get('gold', '?')}")
        print(f"Act:      {gs.get('act', '?'):>6}              {ss.get('act', '?')}")

        # Combat info
        if gs.get('room_phase') == 'COMBAT':
            combat = gs.get('combat_state', {})
            print(f"\n--- COMBAT ---")
            monsters = combat.get('monsters', [])
            for i, m in enumerate(monsters):
                print(f"Monster {i}: HP={m.get('current_hp', '?')}/{m.get('max_hp', '?')}  Block={m.get('block', 0)}")

        print(f"{'='*40}\n")

    def _show_history(self):
        """Show action history."""
        print(f"\nAction History ({len(self.history)} actions):")
        print("-" * 40)
        for result in self.history[-20:]:  # Last 20
            status = "OK" if result.passed else "MISMATCH"
            cmd = result.action.game_command if result.action else "?"
            print(f"  {result.step_number:3d}: {cmd:<20} [{status}]")
        print("-" * 40 + "\n")

    def _show_game_state(self):
        """Show full game state."""
        if not self.orchestrator:
            return
        state = self.orchestrator.get_game_state()
        print(json.dumps(state, indent=2, default=str))

    def _show_sim_state(self):
        """Show full simulator state."""
        if not self.orchestrator:
            return
        state = self.orchestrator.get_sim_state()
        print(json.dumps(state, indent=2, default=str))

    def run(self):
        """Run the interactive session."""
        if not self.start():
            return 1

        self._running = True

        try:
            while self._running:
                try:
                    command = input("sync> ").strip()
                    if command:
                        self.execute_command(command)
                except EOFError:
                    break
                except KeyboardInterrupt:
                    print("\nInterrupted.")
                    break
        finally:
            self.stop()

        # Print summary
        self._print_summary()
        return 0

    def _print_summary(self):
        """Print session summary."""
        print(f"\n{'='*60}")
        print("SESSION SUMMARY")
        print(f"{'='*60}")
        print(f"Total actions: {len(self.history)}")

        passed = sum(1 for r in self.history if r.passed)
        failed = len(self.history) - passed
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")

        if failed > 0:
            print("\nFailed steps:")
            for r in self.history:
                if not r.passed:
                    print(f"  Step {r.step_number}: {r.action.game_command if r.action else '?'}")
                    if r.comparison:
                        for d in r.comparison.discrepancies[:3]:
                            print(f"    - {d.field}")

        print(f"{'='*60}")

        # Export option
        if self.history:
            export_path = f"manual_sync_{self.seed}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            self._export_session(export_path)

    def _export_session(self, filepath: str):
        """Export session to JSON."""
        data = {
            'seed': self.seed,
            'character': self.character,
            'ascension': self.ascension,
            'total_steps': len(self.history),
            'passed': sum(1 for r in self.history if r.passed),
            'steps': [r.to_dict() for r in self.history]
        }

        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        print(f"Session exported to: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Manual sync play - play Slay the Spire with simulator sync"
    )
    parser.add_argument(
        '--seed', '-s',
        type=int,
        required=True,
        help='Game seed to play'
    )
    parser.add_argument(
        '--character', '-c',
        type=str,
        default='IRONCLAD',
        choices=['IRONCLAD', 'SILENT', 'DEFECT', 'WATCHER'],
        help='Character class'
    )
    parser.add_argument(
        '--ascension', '-a',
        type=int,
        default=0,
        help='Ascension level'
    )
    parser.add_argument(
        '--state-dir',
        type=str,
        default='/tmp/sts_bridge',
        help='CommunicationMod bridge state directory'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    session = ManualSyncPlay(
        seed=args.seed,
        character=args.character,
        ascension=args.ascension,
        state_dir=args.state_dir,
        verbose=args.verbose
    )

    return session.run()


if __name__ == "__main__":
    sys.exit(main())
