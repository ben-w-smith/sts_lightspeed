"""Gameplay recorder for sts_lightspeed.

This module provides the GameplayRecorder class for recording game states
as they are received from CommunicationMod. It is used by both the bridge
and the CLI recorder.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class RecordedStep:
    """A single step in a recorded run."""
    step_number: int
    timestamp: str
    game_state: Dict[str, Any]
    state_hash: str
    detected_action: Optional[str]
    state_changes: Dict[str, Any]
    command_sent: Optional[str] = None  # What command was sent to game at this step
    available_commands: List[str] = None  # What commands were available

    def __post_init__(self):
        if self.available_commands is None:
            self.available_commands = []


class GameplayRecorder:
    """Records gameplay states for sync verification.

    This class captures game states and detects actions between states.
    It does NOT poll files - states must be passed to record_step().

    Usage:
        recorder = GameplayRecorder("my_run", "test run")
        recorder.record_step(state_dict)
        recorder.save()
    """

    def __init__(self, run_name: str, description: str = "", recordings_dir: Optional[Path] = None):
        """Initialize the recorder.

        Args:
            run_name: Name for this recording.
            description: Optional description.
            recordings_dir: Directory for recordings. Defaults to integration/recordings/.
        """
        self.run_name = run_name
        self.description = description
        self.recordings_dir = recordings_dir or Path(__file__).parent.parent / "recordings"
        self.steps: List[RecordedStep] = []
        self.previous_state: Optional[Dict[str, Any]] = None
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None

        # Statistics
        self.stats = {
            "total_steps": 0,
            "combats": 0,
            "cards_played": 0,
            "damage_taken": 0,
            "gold_gained": 0,
            "relics_gained": 0,
            "floors_reached": 0,
            "deaths": 0,
        }

    def _compute_state_hash(self, state: Dict[str, Any]) -> str:
        """Compute hash of game state for change detection."""
        gs = state.get("game_state", {})
        hash_fields = {
            "floor": gs.get("floor"),
            "current_hp": gs.get("current_hp"),
            "max_hp": gs.get("max_hp"),
            "gold": gs.get("gold"),
            "screen_name": gs.get("screen_name"),
            "screen_type": gs.get("screen_type"),
            "room_phase": gs.get("room_phase"),
            "action_phase": gs.get("action_phase"),
            # Include choice_list to detect menu/choice changes
            "choice_list": tuple(gs.get("choice_list", [])),
        }
        return hashlib.md5(json.dumps(hash_fields, sort_keys=True).encode()).hexdigest()[:8]

    def _detect_action(self, prev_gs: Dict[str, Any], curr_gs: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """Detect what action occurred between states."""
        changes = {}
        actions = []

        # Check HP changes
        prev_hp = prev_gs.get("current_hp", 0)
        curr_hp = curr_gs.get("current_hp", 0)
        if prev_hp != curr_hp:
            delta = curr_hp - prev_hp
            if delta < 0:
                actions.append(f"took {-delta} damage")
                self.stats["damage_taken"] += -delta
            else:
                actions.append(f"healed {delta}")
            changes["hp_delta"] = delta

        # Check gold changes
        prev_gold = prev_gs.get("gold", 0)
        curr_gold = curr_gs.get("gold", 0)
        if prev_gold != curr_gold:
            delta = curr_gold - prev_gold
            if delta > 0:
                actions.append(f"gained {delta} gold")
                self.stats["gold_gained"] += delta
            else:
                actions.append(f"spent {-delta} gold")
            changes["gold_delta"] = delta

        # Check floor changes
        prev_floor = prev_gs.get("floor", 0)
        curr_floor = curr_gs.get("floor", 0)
        if prev_floor != curr_floor:
            actions.append(f"moved to floor {curr_floor}")
            self.stats["floors_reached"] = max(self.stats["floors_reached"], curr_floor)
            changes["floor_delta"] = curr_floor - prev_floor

        # Check screen changes
        prev_screen = prev_gs.get("screen_name", "")
        curr_screen = curr_gs.get("screen_name", "")
        if prev_screen != curr_screen:
            actions.append(f"screen: {prev_screen} → {curr_screen}")
            changes["screen_change"] = (prev_screen, curr_screen)

            # Track combats
            if curr_screen == "COMBAT" and prev_screen != "COMBAT":
                self.stats["combats"] += 1

        # Check deck changes
        prev_deck = set(c.get("id") for c in prev_gs.get("deck", []))
        curr_deck = set(c.get("id") for c in curr_gs.get("deck", []))
        if prev_deck != curr_deck:
            added = curr_deck - prev_deck
            removed = prev_deck - curr_deck
            if added:
                actions.append(f"added cards: {added}")
            if removed:
                actions.append(f"removed cards: {removed}")
            changes["deck_change"] = {"added": list(added), "removed": list(removed)}

        # Check relic changes
        prev_relics = set(r.get("name") for r in prev_gs.get("relics", []))
        curr_relics = set(r.get("name") for r in curr_gs.get("relics", []))
        if prev_relics != curr_relics:
            added = curr_relics - prev_relics
            if added:
                actions.append(f"gained relic: {added}")
                self.stats["relics_gained"] += len(added)
            changes["relic_change"] = {"added": list(added)}

        # Check death
        if curr_hp <= 0 and prev_hp > 0:
            actions.append("DIED")
            self.stats["deaths"] += 1

        action_str = "; ".join(actions) if actions else "state_update"
        return action_str, changes

    def record_step(self, state: Dict[str, Any], command_sent: Optional[str] = None) -> Optional[RecordedStep]:
        """Record a game state step.

        Args:
            state: The game state dictionary from CommunicationMod.
            command_sent: Optional command that was sent to cause this state.

        Returns:
            RecordedStep if state changed, None if unchanged or invalid.
        """
        gs = state.get("game_state", {})

        # Skip if no game state
        if not gs:
            return None

        state_hash = self._compute_state_hash(state)

        # Skip if state unchanged (same hash)
        if self.previous_state and self._compute_state_hash(self.previous_state) == state_hash:
            return None

        # Initialize start_time on first step
        if self.start_time is None:
            self.start_time = datetime.now().isoformat()

        # Detect action from previous state
        if self.previous_state:
            action, changes = self._detect_action(
                self.previous_state.get("game_state", {}),
                gs
            )
        else:
            action = "game_start"
            changes = {}

        # Capture available commands from state
        available_commands = state.get("available_commands", [])

        step = RecordedStep(
            step_number=len(self.steps) + 1,
            timestamp=datetime.now().isoformat(),
            game_state=state,
            state_hash=state_hash,
            detected_action=action,
            state_changes=changes,
            command_sent=command_sent,
            available_commands=available_commands
        )

        self.steps.append(step)
        self.previous_state = state
        self.stats["total_steps"] = len(self.steps)

        return step

    def save(self) -> Path:
        """Save the recording to disk.

        Returns:
            Path to the saved recording file.
        """
        self.recordings_dir.mkdir(parents=True, exist_ok=True)

        # Set end_time if not already set
        if self.end_time is None:
            self.end_time = datetime.now().isoformat()

        recording = {
            "run_name": self.run_name,
            "description": self.description,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "stats": self.stats,
            "steps": [asdict(s) for s in self.steps]
        }

        path = self.recordings_dir / f"{self.run_name}.json"
        with open(path, "w") as f:
            json.dump(recording, f, indent=2)

        return path

    def get_step_count(self) -> int:
        """Get the number of recorded steps."""
        return len(self.steps)

    def get_last_step(self) -> Optional[RecordedStep]:
        """Get the most recent recorded step."""
        return self.steps[-1] if self.steps else None
