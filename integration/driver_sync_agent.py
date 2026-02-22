#!/usr/bin/env python3
"""Driver-based sync agent.

This agent makes ONE decision and sends it to BOTH the game and simulator,
then compares the results to find simulator bugs.

Architecture:
    Decision Agent ──┬──▶ Game (via CommunicationMod)
                     │
                     └──▶ Simulator (via sts_lightspeed)

After each action:
    - Compare game state vs simulator state
    - Log any divergences
    - Continue to find more issues
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


class DriverSyncAgent:
    """Agent that drives both game and simulator with the same decisions."""

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

        # Game state (from spirecomm)
        self.game = None
        self.errors = 0

        # Simulator state
        self.sim = None
        self.sim_initialized = False
        self.sim_gc = None

        # Tracking
        self.step_count = 0
        self.divergences: List[Dict] = []
        self.visited_shop = False

        # Log file
        self.log_file = self.report_dir / f"driver_sync_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._log("=== Driver Sync Agent Started ===")
        self._log(f"Character: {character.name}, Ascension: {ascension}, Seed: {seed}")

    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        with open(self.log_file, 'a') as f:
            f.write(line + "\n")
        if self.verbose:
            print(line, file=sys.stderr)

    def _init_simulator(self, seed: int, character: str, ascension: int):
        """Initialize simulator with same parameters as game."""
        if not SIMULATOR_AVAILABLE:
            self._log("WARNING: Simulator not available")
            return

        self._log(f"Initializing simulator: seed={seed}, char={character}, asc={ascension}")

        self.sim = sts.ConsoleSimulator()

        char_map = {
            'IRONCLAD': sts.CharacterClass.IRONCLAD,
            'THE_SILENT': sts.CharacterClass.SILENT,
            'DEFECT': sts.CharacterClass.DEFECT,
        }
        char_class = char_map.get(character.upper(), sts.CharacterClass.IRONCLAD)

        # Handle seed for pybind11
        if seed < 0:
            seed = seed & 0xFFFFFFFFFFFFFFFF

        self.sim.setup_game(seed, char_class, ascension)
        self.sim_gc = self.sim.gc
        self.sim_initialized = True
        self._log("Simulator initialized")

    def _execute_on_both(self, action, coordinator):
        """Execute the SAME action on both game and simulator."""
        game_cmd = self._action_to_game_command(action)
        sim_cmd = self._action_to_sim_command(action)

        self._log(f"ACTION: game='{game_cmd}' sim='{sim_cmd}'")

        # Execute on simulator FIRST (faster, no network delay)
        if self.sim_initialized and sim_cmd:
            try:
                self.sim.take_action(sim_cmd)
                self.sim_gc = self.sim.gc
            except Exception as e:
                self._log(f"SIM ERROR: {e}")

        # Return action for game (coordinator will send it)
        return action

    def _action_to_game_command(self, action) -> str:
        """Convert action to human-readable game command."""
        return str(action).replace('<', '').replace('>', '').split()[0]

    def _action_to_sim_command(self, action) -> Optional[str]:
        """Convert action to simulator command string."""
        if not self.sim_initialized or self.sim_gc is None:
            return None

        try:
            if isinstance(action, PlayCardAction):
                if action.card:
                    # Find card index in simulator's hand
                    if self.sim_gc.screen_state == sts.ScreenState.BATTLE:
                        bc = self.sim.battle_ctx
                        if bc:
                            for i, c in enumerate(bc.cards.hand):
                                if c.name.lower() == action.card.name.lower():
                                    if action.target_monster is not None:
                                        # Find target index
                                        target_idx = 0
                                        for mi, m in enumerate(bc.monsters.arr):
                                            if not m.is_dead_or_escaped():
                                                target_idx = mi
                                                break
                                        return f"{i} {target_idx}"
                                    return str(i)
                return None

            elif isinstance(action, EndTurnAction):
                return "end"

            elif isinstance(action, ChooseAction):
                if hasattr(action, 'index') and action.index is not None:
                    return str(action.index)
                return "0"

            elif isinstance(action, ChooseMapNodeAction):
                # Map choice - simulator uses index
                return "0"  # Simplified - would need to match exact node

            elif isinstance(action, CombatRewardAction):
                return "0"

            elif isinstance(action, CardRewardAction):
                return "0"

            elif isinstance(action, ProceedAction):
                return "proceed"

            elif isinstance(action, CancelAction):
                return "cancel"

            elif isinstance(action, RestAction):
                from spirecomm.spire.screen import RestOption
                if action.option == RestOption.REST:
                    return "0"
                elif action.option == RestOption.SMITH:
                    return "1"
                return "0"

            elif isinstance(action, OpenChestAction):
                return "0"

            elif isinstance(action, ChooseShopkeeperAction):
                return "0"

            elif isinstance(action, BossRewardAction):
                return "0"

            elif isinstance(action, StartGameAction):
                return None  # Handled by setup

        except Exception as e:
            self._log(f"CMD CONVERT ERROR: {e}")

        return None

    def _compare_states(self) -> Optional[Dict]:
        """Compare game and simulator states. Return divergence if found."""
        if not self.sim_initialized or self.sim_gc is None or self.game is None:
            return None

        divergences = []

        # Floor
        game_floor = self.game.floor
        sim_floor = self.sim_gc.floor_num
        if game_floor != sim_floor:
            divergences.append({
                'field': 'floor',
                'game': game_floor,
                'sim': sim_floor
            })

        # HP
        game_hp = self.game.current_hp
        sim_hp = self.sim_gc.cur_hp
        if game_hp != sim_hp:
            divergences.append({
                'field': 'current_hp',
                'game': game_hp,
                'sim': sim_hp
            })

        # Max HP
        game_max_hp = self.game.max_hp
        sim_max_hp = self.sim_gc.max_hp
        if game_max_hp != sim_max_hp:
            divergences.append({
                'field': 'max_hp',
                'game': game_max_hp,
                'sim': sim_max_hp
            })

        # Gold
        game_gold = self.game.gold
        sim_gold = self.sim_gc.gold
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

    def _make_decision(self, game_state):
        """Make ONE decision for both game and simulator.

        This is the core decision-making logic. The same decision
        is sent to both systems.
        """
        self.game = game_state
        self.step_count += 1

        # Initialize simulator if needed
        if not self.sim_initialized and game_state.seed:
            self._init_simulator(
                game_state.seed,
                self.character.name,
                game_state.ascension_level
            )

        # Log current state
        floor = game_state.floor
        hp = game_state.current_hp
        screen = game_state.screen_type.name if game_state.screen_type else "NONE"
        self._log(f"Step {self.step_count}: Floor={floor} HP={hp}/{game_state.max_hp} Screen={screen}")

        # Compare states BEFORE action
        pre_divergence = self._compare_states()
        if pre_divergence:
            self.divergences.append(pre_divergence)
            self._log(f"PRE-ACTION DIVERGENCE: {pre_divergence}")

        # Make decision based on game state
        action = self._decide_action(game_state)

        # Execute on BOTH systems
        action = self._execute_on_both(action, None)  # coordinator not needed for game, just return action

        # Compare states AFTER action (will happen on next callback)
        return action

    def _decide_action(self, game_state):
        """Decide what action to take based on game state."""
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
            if game_state.screen.boss_available:
                return ChooseMapBossAction()
            if game_state.screen.next_nodes:
                return ChooseMapNodeAction(game_state.screen.next_nodes[0])
            return ChooseAction(0)

        elif screen_type == ScreenType.EVENT:
            return ChooseAction(0)

        elif screen_type == ScreenType.CHEST:
            return OpenChestAction()

        elif screen_type == ScreenType.REST:
            from spirecomm.spire.screen import RestOption
            if game_state.current_hp < game_state.max_hp // 2:
                return RestAction(RestOption.REST)
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
            return ProceedAction()

        elif screen_type == ScreenType.SHOP_SCREEN:
            self.visited_shop = True
            return CancelAction()

        elif screen_type == ScreenType.GRID:
            return ChooseAction(0)

        return ChooseAction(0)

    def _get_play_card_action(self, game_state):
        """Decide which card to play."""
        playable = [c for c in game_state.hand if c.is_playable]

        if not playable:
            return EndTurnAction()

        # Simple priority: 0-cost first
        zero_cost = [c for c in playable if c.cost == 0]
        if zero_cost:
            card = zero_cost[0]
        else:
            card = playable[0]

        if card.has_target:
            monsters = [m for m in game_state.monsters if m.current_hp > 0 and not m.is_gone]
            if monsters:
                target = min(monsters, key=lambda m: m.current_hp)
                return PlayCardAction(card=card, target_monster=target)

        return PlayCardAction(card=card)

    def handle_error(self, error: str):
        """Handle CommunicationMod errors."""
        self._log(f"ERROR: {error}")
        self.errors += 1
        return CancelAction()

    def get_out_of_game_action(self):
        """Start a new game when at main menu."""
        self._log("Starting new run")
        self.visited_shop = False
        return StartGameAction(self.character, self.ascension, self.seed)

    def save_report(self):
        """Save sync report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'character': self.character.name,
            'ascension': self.ascension,
            'seed': self.seed,
            'total_steps': self.step_count,
            'total_divergences': len(self.divergences),
            'divergences': self.divergences,
        }

        report_path = self.report_dir / f"driver_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        self._log(f"Report saved: {report_path}")
        self._log(f"Total divergences: {len(self.divergences)}")

        # Generate summary
        if self.divergences:
            self._log("\n=== DIVERGENCE SUMMARY ===")
            field_counts = {}
            for d in self.divergences:
                for div in d.get('divergences', []):
                    field = div['field']
                    field_counts[field] = field_counts.get(field, 0) + 1
            for field, count in sorted(field_counts.items(), key=lambda x: -x[1]):
                self._log(f"  {field}: {count} divergences")

        return str(report_path)


def main():
    parser = argparse.ArgumentParser(description='Driver-based sync agent')
    parser.add_argument('--report-dir', type=str, default='integration/sync_reports')
    parser.add_argument('--character', type=str, default='IRONCLAD',
                        choices=['IRONCLAD', 'THE_SILENT', 'DEFECT'])
    parser.add_argument('--ascension', type=int, default=0)
    parser.add_argument('--seed', type=str, default=None)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    char_map = {
        'IRONCLAD': PlayerClass.IRONCLAD,
        'THE_SILENT': PlayerClass.THE_SILENT,
        'DEFECT': PlayerClass.DEFECT,
    }

    agent = DriverSyncAgent(
        report_dir=args.report_dir,
        character=char_map[args.character],
        ascension=args.ascension,
        seed=args.seed,
        verbose=args.verbose
    )

    coordinator = Coordinator()
    coordinator.signal_ready()

    coordinator.register_state_change_callback(agent._make_decision)
    coordinator.register_command_error_callback(agent.handle_error)
    coordinator.register_out_of_game_callback(agent.get_out_of_game_action)

    try:
        while True:
            coordinator.execute_next_action_if_ready()
            coordinator.receive_game_state_update(block=True, perform_callbacks=True)
    except KeyboardInterrupt:
        agent._log("Interrupted")
    finally:
        agent.save_report()

    print(f"\nSync complete. Report: {agent.save_report()}", file=sys.stderr)


if __name__ == '__main__':
    main()
