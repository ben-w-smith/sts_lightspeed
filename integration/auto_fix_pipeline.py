#!/usr/bin/env python3
"""Automated sync testing with auto-fix pipeline.

This orchestrates:
1. Play both game and simulator in sync
2. Detect divergences
3. Create worktree and spawn Claude to fix
4. Merge fix and rerun
5. Loop until no issues found

Usage:
    python -m integration.auto_fix_pipeline --max-fixes 10
"""
import argparse
import json
import subprocess
import sys
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Any

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

try:
    import slaythespire as sts
    SIMULATOR_AVAILABLE = True
except ImportError:
    SIMULATOR_AVAILABLE = False


class DivergenceIssue:
    """Represents a divergence issue to be fixed."""

    def __init__(self, step: int, seed: int, character: str, ascension: int,
                 action_taken: str, divergences: List[Dict]):
        self.step = step
        self.seed = seed
        self.character = character
        self.ascension = ascension
        self.action_taken = action_taken
        self.divergences = divergences
        self.timestamp = datetime.now().isoformat()
        self.issue_id = f"div-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def to_fix_prompt(self) -> str:
        """Generate a prompt for the fix agent."""
        div_summary = "\n".join([
            f"  - {d['field']}: game={d['game']}, sim={d['sim']}"
            for d in self.divergences
        ])

        return f"""# Simulator Divergence Bug

## Summary
The simulator diverges from the real game after action `{self.action_taken}` at step {self.step}.

## Reproduction
- Seed: {self.seed}
- Character: {self.character}
- Ascension: {self.ascension}
- Step: {self.step}
- Action: {self.action_taken}

## Divergences
{div_summary}

## Task
1. Find the root cause in the simulator code
2. Fix the bug to match the real game behavior
3. Ensure the fix doesn't break other tests
4. Commit with message: "fix: {self.issue_id} - {self.divergences[0]['field']} divergence"

## Files to Check
- src/combat/ - Combat logic
- src/game/ - Game state management
- src/_rng/ - RNG handling
- bindings/ - Python bindings

Focus on the field(s) that diverged: {', '.join(d['field'] for d in self.divergences)}
"""

    def to_dict(self) -> Dict:
        return {
            'issue_id': self.issue_id,
            'timestamp': self.timestamp,
            'step': self.step,
            'seed': self.seed,
            'character': self.character,
            'ascension': self.ascension,
            'action_taken': self.action_taken,
            'divergences': self.divergences,
        }


class AutoFixPipeline:
    """Orchestrates automated sync testing and fixing."""

    def __init__(
        self,
        report_dir: str,
        max_fixes: int = 10,
        verbose: bool = False
    ):
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.max_fixes = max_fixes
        self.verbose = verbose

        self.fixes_attempted = 0
        self.fixes_successful = 0
        self.issues_found: List[DivergenceIssue] = []
        self.current_issue: Optional[DivergenceIssue] = None

        # Agent state
        self.game = None
        self.sim = None
        self.sim_gc = None
        self.sim_initialized = False
        self.step_count = 0
        self.visited_shop = False
        self.last_action = None
        self.current_seed = None
        self.current_character = None
        self.current_ascension = 0

        # Log file
        self.log_file = self.report_dir / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._log("=== Auto-Fix Pipeline Started ===")

    def _log(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{timestamp}] {msg}"
        with open(self.log_file, 'a') as f:
            f.write(line + "\n")
        if self.verbose:
            print(line, file=sys.stderr)

    def _init_simulator(self, seed: int, character: str, ascension: int):
        """Initialize simulator."""
        if not SIMULATOR_AVAILABLE:
            self._log("ERROR: Simulator not available")
            return

        self._log(f"Init simulator: seed={seed}, char={character}, asc={ascension}")
        self.sim = sts.ConsoleSimulator()

        char_map = {
            'IRONCLAD': sts.CharacterClass.IRONCLAD,
            'THE_SILENT': sts.CharacterClass.SILENT,
            'DEFECT': sts.CharacterClass.DEFECT,
        }
        char_class = char_map.get(character.upper(), sts.CharacterClass.IRONCLAD)

        if seed < 0:
            seed = seed & 0xFFFFFFFFFFFFFFFF

        self.sim.setup_game(seed, char_class, ascension)
        self.sim_gc = self.sim.gc
        self.sim_initialized = True

    def _compare_states(self) -> List[Dict]:
        """Compare game and simulator states."""
        if not self.sim_initialized or self.sim_gc is None or self.game is None:
            return []

        divergences = []

        comparisons = [
            ('floor', self.game.floor, self.sim_gc.floor_num),
            ('current_hp', self.game.current_hp, self.sim_gc.cur_hp),
            ('max_hp', self.game.max_hp, self.sim_gc.max_hp),
            ('gold', self.game.gold, self.sim_gc.gold),
        ]

        for field, game_val, sim_val in comparisons:
            if game_val != sim_val:
                divergences.append({
                    'field': field,
                    'game': game_val,
                    'sim': sim_val
                })

        return divergences

    def _execute_on_simulator(self, action):
        """Execute action on simulator."""
        if not self.sim_initialized or self.sim_gc is None:
            return

        sim_cmd = None

        try:
            if isinstance(action, PlayCardAction) and action.card:
                if self.sim_gc.screen_state == sts.ScreenState.BATTLE:
                    bc = self.sim.battle_ctx
                    if bc:
                        for i, c in enumerate(bc.cards.hand):
                            if c.name.lower() == action.card.name.lower():
                                if action.target_monster is not None:
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
                sim_cmd = str(action.index) if hasattr(action, 'index') else "0"

            elif isinstance(action, ChooseMapNodeAction):
                sim_cmd = "0"

            elif isinstance(action, (CombatRewardAction, CardRewardAction)):
                sim_cmd = "0"

            elif isinstance(action, ProceedAction):
                sim_cmd = "proceed"

            elif isinstance(action, CancelAction):
                sim_cmd = "cancel"

            elif isinstance(action, RestAction):
                from spirecomm.spire.screen import RestOption
                sim_cmd = "0" if action.option == RestOption.REST else "1"

            elif isinstance(action, (OpenChestAction, ChooseShopkeeperAction, BossRewardAction)):
                sim_cmd = "0"

            if sim_cmd:
                self.sim.take_action(sim_cmd)
                self.sim_gc = self.sim.gc

        except Exception as e:
            self._log(f"SIM ERROR: {e}")

    def _make_decision(self, game_state):
        """Make decision and execute on both systems."""
        self.game = game_state
        self.step_count += 1

        # Initialize simulator if needed
        if not self.sim_initialized and game_state.seed:
            self.current_seed = game_state.seed
            self.current_character = self.character.name if hasattr(self, 'character') else 'IRONCLAD'
            self.current_ascension = game_state.ascension_level
            self._init_simulator(game_state.seed, self.current_character, game_state.ascension_level)

        # Log state
        floor = game_state.floor
        hp = game_state.current_hp
        screen = game_state.screen_type.name if game_state.screen_type else "NONE"
        self._log(f"Step {self.step_count}: F={floor} HP={hp} Screen={screen}")

        # Compare BEFORE action
        pre_div = self._compare_states()
        if pre_div:
            self._log(f"PRE-DIVERGENCE: {pre_div}")

        # Make decision
        action = self._decide_action(game_state)
        self.last_action = str(type(action).__name__)

        # Execute on BOTH
        self._execute_on_simulator(action)

        # Compare AFTER action
        post_div = self._compare_states()
        if post_div and self.fixes_attempted < self.max_fixes:
            # Create issue
            issue = DivergenceIssue(
                step=self.step_count,
                seed=self.current_seed or 0,
                character=self.current_character or 'IRONCLAD',
                ascension=self.current_ascension,
                action_taken=self.last_action,
                divergences=post_div
            )
            self.issues_found.append(issue)
            self._log(f"DIVERGENCE FOUND: {issue.issue_id}")
            self._log(f"  {post_div}")

            # Would trigger fix here in full implementation
            # For now, just log it

        return action

    def _decide_action(self, game_state):
        """Decide action based on game state."""
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
        """Handle screen types."""
        st = game_state.screen_type

        if st == ScreenType.MAP:
            if game_state.screen.boss_available:
                return ChooseMapBossAction()
            if game_state.screen.next_nodes:
                return ChooseMapNodeAction(game_state.screen.next_nodes[0])
            return ChooseAction(0)

        elif st == ScreenType.EVENT:
            return ChooseAction(0)

        elif st == ScreenType.CHEST:
            return OpenChestAction()

        elif st == ScreenType.REST:
            from spirecomm.spire.screen import RestOption
            return RestAction(RestOption.REST if game_state.current_hp < game_state.max_hp // 2 else RestOption.SMITH)

        elif st == ScreenType.CARD_REWARD:
            if game_state.screen and game_state.screen.cards:
                return CardRewardAction(game_state.screen.cards[0])
            return CancelAction()

        elif st == ScreenType.COMBAT_REWARD:
            if game_state.screen and game_state.screen.rewards:
                return CombatRewardAction(game_state.screen.rewards[0])
            return ProceedAction()

        elif st == ScreenType.BOSS_REWARD:
            if game_state.screen and game_state.screen.relics:
                return BossRewardAction(game_state.screen.relics[0])
            return ChooseAction(0)

        elif st == ScreenType.SHOP_ROOM:
            if not self.visited_shop:
                self.visited_shop = True
                return ChooseShopkeeperAction()
            return ProceedAction()

        elif st == ScreenType.SHOP_SCREEN:
            self.visited_shop = True
            return CancelAction()

        return ChooseAction(0)

    def _get_play_card_action(self, game_state):
        """Choose card to play."""
        playable = [c for c in game_state.hand if c.is_playable]
        if not playable:
            return EndTurnAction()

        zero_cost = [c for c in playable if c.cost == 0]
        card = zero_cost[0] if zero_cost else playable[0]

        if card.has_target:
            monsters = [m for m in game_state.monsters if m.current_hp > 0 and not m.is_gone]
            if monsters:
                return PlayCardAction(card=card, target_monster=min(monsters, key=lambda m: m.current_hp))

        return PlayCardAction(card=card)

    def handle_error(self, error: str):
        self._log(f"ERROR: {error}")
        return CancelAction()

    def get_out_of_game_action(self):
        self._log("Starting new run")
        self.visited_shop = False
        self.step_count = 0
        self.sim_initialized = False
        return StartGameAction(PlayerClass.IRONCLAD, 0, None)

    def create_fix_worktree(self, issue: DivergenceIssue) -> Path:
        """Create a worktree for fixing the issue."""
        worktree_path = Path(__file__).parent.parent.parent / ".worktrees" / f"fix-{issue.issue_id}"

        self._log(f"Creating worktree: {worktree_path}")

        # Create worktree
        result = subprocess.run(
            ["git", "worktree", "add", str(worktree_path), "-b", f"fix/{issue.issue_id}"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            self._log(f"Worktree creation failed: {result.stderr}")
            return None

        return worktree_path

    def spawn_fix_agent(self, worktree_path: Path, issue: DivergenceIssue) -> bool:
        """Spawn Claude agent to fix the issue."""
        self._log(f"Spawning fix agent in {worktree_path}")

        prompt = issue.to_fix_prompt()

        # Create issue file in worktree
        issue_file = worktree_path / f"ISSUE_{issue.issue_id}.md"
        with open(issue_file, 'w') as f:
            f.write(prompt)

        # In a real implementation, this would spawn a Claude CLI instance
        # For now, we just log what would happen
        self._log(f"Would spawn: claude --dangerously-skip-permissions -p '{prompt[:200]}...'")

        # Placeholder - in real implementation, this would:
        # 1. Spawn Claude CLI with --dangerously-skip-permissions
        # 2. Wait for fix to complete
        # 3. Verify fix with tests
        # 4. Return success/failure

        return False  # Not implemented yet

    def run_game_loop(self):
        """Run the game/simulator sync loop."""
        self._log("Starting game loop...")

        coordinator = Coordinator()
        coordinator.signal_ready()

        coordinator.register_state_change_callback(self._make_decision)
        coordinator.register_command_error_callback(self.handle_error)
        coordinator.register_out_of_game_callback(self.get_out_of_game_action)

        try:
            while True:
                coordinator.execute_next_action_if_ready()
                coordinator.receive_game_state_update(block=True, perform_callbacks=True)
        except KeyboardInterrupt:
            self._log("Interrupted by user")
        finally:
            self.save_report()

    def save_report(self):
        """Save pipeline report."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'fixes_attempted': self.fixes_attempted,
            'fixes_successful': self.fixes_successful,
            'total_issues': len(self.issues_found),
            'issues': [i.to_dict() for i in self.issues_found],
        }

        report_path = self.report_dir / f"pipeline_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)

        self._log(f"Report saved: {report_path}")

        # Print summary
        print(f"\n{'='*50}", file=sys.stderr)
        print(f"Pipeline Complete", file=sys.stderr)
        print(f"  Issues Found: {len(self.issues_found)}", file=sys.stderr)
        print(f"  Fixes Attempted: {self.fixes_attempted}", file=sys.stderr)
        print(f"  Fixes Successful: {self.fixes_successful}", file=sys.stderr)
        print(f"{'='*50}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description='Auto-fix pipeline for simulator sync')
    parser.add_argument('--report-dir', type=str, default='integration/sync_reports')
    parser.add_argument('--max-fixes', type=int, default=10)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args()

    pipeline = AutoFixPipeline(
        report_dir=args.report_dir,
        max_fixes=args.max_fixes,
        verbose=args.verbose
    )

    pipeline.run_game_loop()


if __name__ == '__main__':
    main()
