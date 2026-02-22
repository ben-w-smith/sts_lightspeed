#!/usr/bin/env python3
"""Sync agent using spirecomm for real game/simulator sync testing.

This script is designed to be run BY CommunicationMod. It:
1. Uses spirecomm's Coordinator to communicate with the game
2. Mirrors all actions to the simulator
3. Compares states and logs divergences
4. Reports results to a file

Usage in CommunicationMod config:
    command=python3 /path/to/spirecomm_sync.py --report-dir /path/to/reports
"""
import argparse
import json
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add build directory for simulator
script_dir = Path(__file__).parent
build_dir = script_dir.parent / "build"
if str(build_dir) not in sys.path:
    sys.path.insert(0, str(build_dir))

from spirecomm.communication.coordinator import Coordinator
from spirecomm.communication.action import *
from spirecomm.spire.character import PlayerClass
from spirecomm.spire.screen import ScreenType
import spirecomm.spire.card

# Import simulator
try:
    import slaythespire as sts
    SIMULATOR_AVAILABLE = True
except ImportError:
    SIMULATOR_AVAILABLE = False
    print("WARNING: Simulator not available", file=sys.stderr)


class SyncAgent:
    """Agent that plays both game and simulator in sync."""

    def __init__(
        self,
        report_dir: str,
        character: PlayerClass = PlayerClass.IRONCLAD,
        ascension: int = 0,
        seed: Optional[str] = None,
        verbose: bool = False
    ):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.character = character
        self.ascension = ascension
        self.seed = seed
        self.verbose = verbose

        # Game state
        self.game = None
        self.errors = 0

        # Simulator state
        self.simulator = None
        self.sim_initialized = False
        self.last_sim_floor = 0

        # Tracking
        self.step_count = 0
        self.divergences: List[Dict] = []
        self.actions_taken: List[str] = []
        self.visited_shop = False  # Prevent shop loop

        # Map route (from SimpleAgent)
        self.map_route = []

        # Log file
        self.log_file = self.report_dir / f"sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._log("=== Sync Agent Started ===")

    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        with open(self.log_file, 'a') as f:
            f.write(line + "\n")
        if self.verbose:
            print(line, file=sys.stderr)

    def _init_simulator(self, seed: int, character: str, ascension: int):
        """Initialize simulator with game parameters."""
        if not SIMULATOR_AVAILABLE:
            return

        self._log(f"Initializing simulator: seed={seed}, char={character}, asc={ascension}")

        self.simulator = sts.ConsoleSimulator()

        # Convert character string to enum
        char_map = {
            'IRONCLAD': sts.CharacterClass.IRONCLAD,
            'THE_SILENT': sts.CharacterClass.SILENT,
            'DEFECT': sts.CharacterClass.DEFECT,
            'WATCHER': sts.CharacterClass.WATCHER,
        }
        char_class = char_map.get(character.upper(), sts.CharacterClass.IRONCLAD)

        # Handle seed (convert negative to unsigned for pybind11)
        if seed < 0:
            seed = seed & 0xFFFFFFFFFFFFFFFF

        self.simulator.setup_game(seed, char_class, ascension)
        self.sim_initialized = True
        self._log("Simulator initialized")

    def _compare_states(self, game_state) -> Optional[Dict]:
        """Compare game and simulator states, return divergence if any."""
        if not self.sim_initialized or self.simulator is None:
            return None

        gc = self.simulator.gc
        if gc is None:
            return None

        divergences = []

        # Compare floor
        game_floor = game_state.floor
        sim_floor = gc.floor_num
        if game_floor != sim_floor:
            divergences.append({
                'field': 'floor',
                'game': game_floor,
                'sim': sim_floor
            })

        # Compare HP
        game_hp = game_state.current_hp
        sim_hp = gc.cur_hp
        if game_hp != sim_hp:
            divergences.append({
                'field': 'current_hp',
                'game': game_hp,
                'sim': sim_hp
            })

        # Compare max HP
        game_max_hp = game_state.max_hp
        sim_max_hp = gc.max_hp
        if game_max_hp != sim_max_hp:
            divergences.append({
                'field': 'max_hp',
                'game': game_max_hp,
                'sim': sim_max_hp
            })

        # Compare gold
        game_gold = game_state.gold
        sim_gold = gc.gold
        if game_gold != sim_gold:
            divergences.append({
                'field': 'gold',
                'game': game_gold,
                'sim': sim_gold
            })

        if divergences:
            return {
                'step': self.step_count,
                'floor': game_floor,
                'divergences': divergences
            }
        return None

    def _execute_on_simulator(self, action):
        """Execute an action on the simulator."""
        if not self.sim_initialized or self.simulator is None:
            return

        try:
            gc = self.simulator.gc
            sim_cmd = None

            if isinstance(action, PlayCardAction):
                if action.card and gc and hasattr(gc, 'battle_ctx') and gc.battle_ctx:
                    bc = gc.battle_ctx
                    hand = bc.cards.hand
                    # Find card by name
                    for i, c in enumerate(hand):
                        if c.name.lower() == action.card.name.lower():
                            if action.target_monster is not None:
                                # Find target monster index
                                target_idx = 0
                                for mi, m in enumerate(bc.monsters.arr):
                                    if not m.is_dead_or_escaped():
                                        target_idx = mi
                                        break
                                sim_cmd = f"{i} {target_idx}"
                            else:
                                sim_cmd = str(i)
                            break

            elif isinstance(action, EndTurnAction):
                sim_cmd = "end"

            elif isinstance(action, ChooseAction):
                # ChooseAction can have index or be for specific purposes
                if hasattr(action, 'index') and action.index is not None:
                    sim_cmd = str(action.index)
                else:
                    sim_cmd = "0"  # Default first option

            elif isinstance(action, ChooseMapNodeAction):
                # Map node - need to find the index of the chosen node
                if action.node and gc:
                    # Find which index this node corresponds to
                    game_x = action.node.x
                    game_y = action.node.y
                    # The simulator expects the index of the next_nodes array
                    # We need to find which available node matches
                    sim_cmd = "0"  # Default first
                    # Try to match by x coordinate
                    if hasattr(gc, 'map'):
                        # For now, just use the node's position to determine choice
                        # This is a simplification - ideally we'd match exact nodes
                        pass

            elif isinstance(action, CombatRewardAction):
                sim_cmd = "0"  # Take first reward

            elif isinstance(action, CardRewardAction):
                sim_cmd = "0"  # Pick first card

            elif isinstance(action, ProceedAction):
                sim_cmd = "proceed"

            elif isinstance(action, CancelAction):
                sim_cmd = "cancel"

            elif isinstance(action, RestAction):
                from spirecomm.spire.screen import RestOption
                if action.option == RestOption.REST:
                    sim_cmd = "0"
                elif action.option == RestOption.SMITH:
                    sim_cmd = "1"
                else:
                    sim_cmd = "0"

            elif isinstance(action, StartGameAction):
                # Already handled by simulator setup
                pass

            elif isinstance(action, OpenChestAction):
                sim_cmd = "0"

            elif isinstance(action, ChooseShopkeeperAction):
                sim_cmd = "0"

            elif isinstance(action, BossRewardAction):
                sim_cmd = "0"  # Pick first boss relic

            if sim_cmd:
                self._log(f"SIM CMD: {sim_cmd}")
                self.simulator.take_action(sim_cmd)

        except Exception as e:
            self._log(f"Simulator error: {e}")

    def handle_error(self, error: str):
        """Handle errors from CommunicationMod."""
        self._log(f"ERROR: {error}")
        self.errors += 1
        return CancelAction()

    def get_next_action(self, game_state):
        """Main callback - decides next action and syncs with simulator."""
        self.game = game_state
        self.step_count += 1

        floor = game_state.floor
        hp = game_state.current_hp
        screen = game_state.screen_type.name if game_state.screen_type else "NONE"

        self._log(f"Step {self.step_count}: Floor={floor} HP={hp}/{game_state.max_hp} Screen={screen}")

        # Initialize simulator if needed
        if not self.sim_initialized and game_state.seed:
            self._init_simulator(
                game_state.seed,
                str(self.character.name),
                game_state.ascension_level
            )

        # Compare states
        divergence = self._compare_states(game_state)
        if divergence:
            self.divergences.append(divergence)
            self._log(f"DIVERGENCE: {divergence}")

        # Get action based on game state
        action = self._get_action(game_state)

        # Execute on simulator
        self._execute_on_simulator(action)

        # Log action
        action_str = str(action)
        self.actions_taken.append(action_str)
        self._log(f"Action: {action_str}")

        return action

    def _get_action(self, game_state):
        """Determine next action based on game state."""
        # Handle choice screens
        if game_state.choice_available:
            return self._handle_screen(game_state)

        if game_state.proceed_available:
            return ProceedAction()

        if game_state.play_available:
            return self._get_play_card_action(game_state)

        if game_state.end_available:
            return EndTurnAction()

        if game_state.cancel_available:
            return CancelAction()

        return ProceedAction()

    def _handle_screen(self, game_state):
        """Handle various screen types."""
        screen_type = game_state.screen_type

        if screen_type == ScreenType.MAP:
            return self._make_map_choice(game_state)
        elif screen_type == ScreenType.EVENT:
            return ChooseAction(0)  # Take first option
        elif screen_type == ScreenType.CHEST:
            return OpenChestAction()
        elif screen_type == ScreenType.REST:
            from spirecomm.spire.screen import RestOption
            if game_state.current_hp < game_state.max_hp // 2:
                return RestAction(RestOption.REST)
            else:
                return RestAction(RestOption.SMITH)
        elif screen_type == ScreenType.CARD_REWARD:
            if game_state.screen and game_state.screen.cards:
                return CardRewardAction(game_state.screen.cards[0])
            return CancelAction()
        elif screen_type == ScreenType.COMBAT_REWARD:
            if game_state.screen and game_state.screen.rewards:
                return CombatRewardAction(game_state.screen.rewards[0])
            return ProceedAction()
        elif screen_type == ScreenType.BOSS_REWARD:
            if game_state.screen and game_state.screen.relics:
                return BossRewardAction(game_state.screen.relics[0])
            return ChooseAction(0)
        elif screen_type == ScreenType.SHOP_ROOM:
            if not self.visited_shop:
                self.visited_shop = True
                return ChooseShopkeeperAction()
            else:
                # Already visited, skip
                return ProceedAction()
        elif screen_type == ScreenType.SHOP_SCREEN:
            self.visited_shop = True  # Mark as visited in case we got here directly
            return CancelAction()  # Leave shop

        return ChooseAction(0)

    def _make_map_choice(self, game_state):
        """Choose next map node."""
        if game_state.screen.boss_available:
            return ChooseMapBossAction()

        if game_state.screen.next_nodes:
            # Pick first available node (simple strategy)
            # Could implement pathfinding here
            return ChooseMapNodeAction(game_state.screen.next_nodes[0])

        return ChooseAction(0)

    def _get_play_card_action(self, game_state):
        """Choose a card to play."""
        playable = [c for c in game_state.hand if c.is_playable]

        if not playable:
            return EndTurnAction()

        # Simple priority: 0-cost first, then attacks, then skills
        zero_cost = [c for c in playable if c.cost == 0]
        attacks = [c for c in playable if c.type == spirecomm.spire.card.CardType.ATTACK]

        if zero_cost:
            card = zero_cost[0]
        elif attacks:
            card = attacks[0]
        else:
            card = playable[0]

        if card.has_target:
            # Find lowest HP monster
            monsters = [m for m in game_state.monsters if m.current_hp > 0 and not m.is_gone]
            if monsters:
                target = min(monsters, key=lambda m: m.current_hp)
                return PlayCardAction(card=card, target_monster=target)

        return PlayCardAction(card=card)

    def get_out_of_game_action(self):
        """Called when at main menu."""
        self._log("Out of game - starting new run")
        return StartGameAction(self.character, self.ascension, self.seed)

    def save_report(self):
        """Save the sync report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'character': self.character.name,
            'ascension': self.ascension,
            'seed': self.seed,
            'total_steps': self.step_count,
            'divergences': self.divergences,
            'actions': self.actions_taken[-100:],  # Last 100 actions
        }

        report_path = self.report_dir / f"sync_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        self._log(f"Report saved to: {report_path}")
        self._log(f"Total divergences: {len(self.divergences)}")
        return str(report_path)


def main():
    parser = argparse.ArgumentParser(description='Sync agent for game/simulator testing')
    parser.add_argument('--report-dir', type=str, default='integration/sync_reports',
                        help='Directory for reports')
    parser.add_argument('--character', type=str, default='IRONCLAD',
                        choices=['IRONCLAD', 'THE_SILENT', 'DEFECT'])
    parser.add_argument('--ascension', type=int, default=0)
    parser.add_argument('--seed', type=str, default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    # Map character string to enum (spirecomm doesn't have WATCHER)
    char_map = {
        'IRONCLAD': PlayerClass.IRONCLAD,
        'THE_SILENT': PlayerClass.THE_SILENT,
        'DEFECT': PlayerClass.DEFECT,
    }

    agent = SyncAgent(
        report_dir=args.report_dir,
        character=char_map[args.character],
        ascension=args.ascension,
        seed=args.seed,
        verbose=args.verbose
    )

    # Create coordinator
    coordinator = Coordinator()
    coordinator.signal_ready()

    # Register callbacks
    coordinator.register_state_change_callback(agent.get_next_action)
    coordinator.register_command_error_callback(agent.handle_error)
    coordinator.register_out_of_game_callback(agent.get_out_of_game_action)

    try:
        # Run until game ends - keep checking for state updates
        while True:
            coordinator.execute_next_action_if_ready()
            coordinator.receive_game_state_update(block=True, perform_callbacks=True)
    except KeyboardInterrupt:
        agent._log("Interrupted by user")
    finally:
        report_path = agent.save_report()

    print(f"\nSync test complete. Report: {report_path}", file=sys.stderr)


if __name__ == '__main__':
    main()
