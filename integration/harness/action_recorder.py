"""Action recording and replay for game-simulator validation.

This module provides functionality to record actions with full context
during game play and replay them later for validation.

Recorded sessions can be exported to JSON and reloaded for replay,
making them useful for bug reproduction and regression testing.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

from .action_translator import ActionTranslator, TranslatedAction, ActionType


@dataclass
class RecordedAction:
    """A single recorded action with full context."""
    step_number: int
    action_type: str
    game_command: str
    sim_command: str
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    # Optional state snapshots
    pre_state: Optional[Dict[str, Any]] = None
    post_state: Optional[Dict[str, Any]] = None

    # Metadata
    screen_state: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'step_number': self.step_number,
            'action_type': self.action_type,
            'game_command': self.game_command,
            'sim_command': self.sim_command,
            'params': self.params,
            'timestamp': self.timestamp,
            'pre_state': self.pre_state,
            'post_state': self.post_state,
            'screen_state': self.screen_state,
            'notes': self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'RecordedAction':
        """Create from dictionary."""
        return cls(
            step_number=data['step_number'],
            action_type=data['action_type'],
            game_command=data['game_command'],
            sim_command=data['sim_command'],
            params=data.get('params', {}),
            timestamp=data.get('timestamp', datetime.now().isoformat()),
            pre_state=data.get('pre_state'),
            post_state=data.get('post_state'),
            screen_state=data.get('screen_state'),
            notes=data.get('notes', ''),
        )

    @classmethod
    def from_translated_action(
        cls,
        action: TranslatedAction,
        step_number: int,
        pre_state: Optional[Dict[str, Any]] = None,
        post_state: Optional[Dict[str, Any]] = None,
        screen_state: Optional[str] = None,
        notes: str = ""
    ) -> 'RecordedAction':
        """Create from a TranslatedAction."""
        return cls(
            step_number=step_number,
            action_type=action.action_type.value,
            game_command=action.game_command,
            sim_command=action.sim_command,
            params=action.params.copy(),
            pre_state=pre_state,
            post_state=post_state,
            screen_state=screen_state,
            notes=notes,
        )

    def to_translated_action(self) -> TranslatedAction:
        """Convert to TranslatedAction for replay."""
        return TranslatedAction(
            action_type=ActionType(self.action_type),
            game_command=self.game_command,
            sim_command=self.sim_command,
            params=self.params.copy(),
        )


@dataclass
class RecordedSession:
    """A complete recorded session with metadata and actions."""
    session_id: str
    name: str
    seed: int
    character: str
    ascension: int
    actions: List[RecordedAction] = field(default_factory=list)

    # Session metadata
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    duration_seconds: Optional[float] = None

    # Additional metadata
    game_version: str = "unknown"
    simulator_commit: str = "unknown"
    platform: str = ""
    tags: List[str] = field(default_factory=list)
    notes: str = ""

    # Outcome tracking
    outcome: str = "incomplete"  # incomplete, passed, failed, error
    error_message: Optional[str] = None

    @property
    def total_actions(self) -> int:
        """Total number of actions in the session."""
        return len(self.actions)

    @property
    def action_types_summary(self) -> Dict[str, int]:
        """Summary of action types used."""
        summary: Dict[str, int] = {}
        for action in self.actions:
            summary[action.action_type] = summary.get(action.action_type, 0) + 1
        return summary

    def add_action(self, action: RecordedAction):
        """Add an action to the session."""
        self.actions.append(action)

    def finalize(self, outcome: str = "complete", error: Optional[str] = None):
        """Mark the session as complete."""
        self.end_time = datetime.now().isoformat()
        self.outcome = outcome
        self.error_message = error

        # Calculate duration
        if self.start_time and self.end_time:
            try:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time)
                self.duration_seconds = (end - start).total_seconds()
            except (ValueError, TypeError):
                pass

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'session_id': self.session_id,
            'name': self.name,
            'seed': self.seed,
            'character': self.character,
            'ascension': self.ascension,
            'actions': [a.to_dict() for a in self.actions],
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration_seconds': self.duration_seconds,
            'total_actions': self.total_actions,
            'action_types_summary': self.action_types_summary,
            'game_version': self.game_version,
            'simulator_commit': self.simulator_commit,
            'platform': self.platform,
            'tags': self.tags,
            'notes': self.notes,
            'outcome': self.outcome,
            'error_message': self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'RecordedSession':
        """Create from dictionary."""
        session = cls(
            session_id=data['session_id'],
            name=data['name'],
            seed=data['seed'],
            character=data['character'],
            ascension=data['ascension'],
            start_time=data.get('start_time', datetime.now().isoformat()),
            end_time=data.get('end_time'),
            duration_seconds=data.get('duration_seconds'),
            game_version=data.get('game_version', 'unknown'),
            simulator_commit=data.get('simulator_commit', 'unknown'),
            platform=data.get('platform', ''),
            tags=data.get('tags', []),
            notes=data.get('notes', ''),
            outcome=data.get('outcome', 'incomplete'),
            error_message=data.get('error_message'),
        )

        for action_data in data.get('actions', []):
            session.actions.append(RecordedAction.from_dict(action_data))

        return session

    def get_actions_for_replay(self) -> List[TranslatedAction]:
        """Get all actions as TranslatedActions for replay."""
        return [a.to_translated_action() for a in self.actions]

    def get_sim_commands(self) -> List[str]:
        """Get all simulator commands as strings."""
        return [a.sim_command for a in self.actions]

    def get_game_commands(self) -> List[str]:
        """Get all game commands as strings."""
        return [a.game_command for a in self.actions]


class ActionRecorder:
    """Recorder for capturing actions with full context.

    The ActionRecorder captures actions during gameplay, along with
    state snapshots and metadata. Sessions can be exported to JSON
    and reloaded for replay.

    Usage:
        recorder = ActionRecorder()

        # Start recording
        recorder.start_session("test_scenario", seed=12345, character="IRONCLAD")

        # Record actions
        recorder.record_action(translated_action, pre_state, post_state)

        # End session
        recorder.end_session(outcome="passed")

        # Export
        recorder.save_session("recorded_session.json")

        # Load and replay
        recorder.load_session("recorded_session.json")
        actions = recorder.get_replay_actions()
    """

    def __init__(
        self,
        capture_states: bool = True,
        auto_timestamp: bool = True
    ):
        """Initialize the action recorder.

        Args:
            capture_states: Whether to capture state snapshots with actions.
            auto_timestamp: Whether to auto-add timestamps to actions.
        """
        self.capture_states = capture_states
        self.auto_timestamp = auto_timestamp
        self.translator = ActionTranslator()

        self._current_session: Optional[RecordedSession] = None
        self._step_counter: int = 0

    def start_session(
        self,
        name: str,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        notes: str = ""
    ) -> RecordedSession:
        """Start a new recording session.

        Args:
            name: Session name.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
            session_id: Optional session ID (auto-generated if None).
            tags: Optional tags for categorization.
            notes: Optional notes about the session.

        Returns:
            The new RecordedSession.
        """
        import uuid
        import platform

        # End any existing session
        if self._current_session:
            self.end_session(outcome="superseded")

        self._current_session = RecordedSession(
            session_id=session_id or str(uuid.uuid4())[:8],
            name=name,
            seed=seed,
            character=character,
            ascension=ascension,
            tags=tags or [],
            notes=notes,
            platform=platform.system(),
        )

        self._step_counter = 0

        # Try to get git commit
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                self._current_session.simulator_commit = result.stdout.strip()[:8]
        except Exception:
            pass

        return self._current_session

    def record_action(
        self,
        action: Union[TranslatedAction, str],
        pre_state: Optional[Dict[str, Any]] = None,
        post_state: Optional[Dict[str, Any]] = None,
        screen_state: Optional[str] = None,
        notes: str = "",
        action_type_hint: str = "sim"
    ) -> RecordedAction:
        """Record an action with optional state snapshots.

        Args:
            action: The action (TranslatedAction or string command).
            pre_state: Optional pre-action state snapshot.
            post_state: Optional post-action state snapshot.
            screen_state: Current screen state.
            notes: Notes about this action.
            action_type_hint: "sim" or "game" if action is a string.

        Returns:
            The recorded action.
        """
        if not self._current_session:
            raise RuntimeError("No active session. Call start_session() first.")

        # Convert string to TranslatedAction if needed
        if isinstance(action, str):
            if action_type_hint == "game":
                action = self.translator.from_game_to_sim(action)
            else:
                action = self.translator.from_sim_to_game(action)

        recorded = RecordedAction.from_translated_action(
            action=action,
            step_number=self._step_counter,
            pre_state=pre_state if self.capture_states else None,
            post_state=post_state if self.capture_states else None,
            screen_state=screen_state,
            notes=notes,
        )

        self._current_session.add_action(recorded)
        self._step_counter += 1

        return recorded

    def record_game_command(
        self,
        command: str,
        pre_state: Optional[Dict[str, Any]] = None,
        post_state: Optional[Dict[str, Any]] = None,
        notes: str = ""
    ) -> RecordedAction:
        """Record a game command (CommunicationMod format).

        Args:
            command: The game command string.
            pre_state: Optional pre-action state.
            post_state: Optional post-action state.
            notes: Notes about this action.

        Returns:
            The recorded action.
        """
        return self.record_action(
            action=command,
            pre_state=pre_state,
            post_state=post_state,
            notes=notes,
            action_type_hint="game"
        )

    def record_sim_command(
        self,
        command: str,
        pre_state: Optional[Dict[str, Any]] = None,
        post_state: Optional[Dict[str, Any]] = None,
        notes: str = ""
    ) -> RecordedAction:
        """Record a simulator command.

        Args:
            command: The simulator command string.
            pre_state: Optional pre-action state.
            post_state: Optional post-action state.
            notes: Notes about this action.

        Returns:
            The recorded action.
        """
        return self.record_action(
            action=command,
            pre_state=pre_state,
            post_state=post_state,
            notes=notes,
            action_type_hint="sim"
        )

    def end_session(
        self,
        outcome: str = "complete",
        error: Optional[str] = None
    ) -> Optional[RecordedSession]:
        """End the current recording session.

        Args:
            outcome: Session outcome ("complete", "passed", "failed", "error").
            error: Optional error message.

        Returns:
            The completed session, or None if no session was active.
        """
        if not self._current_session:
            return None

        self._current_session.finalize(outcome=outcome, error=error)
        session = self._current_session
        self._current_session = None
        self._last_session = session  # Keep reference to last session

        return session

    def get_current_session(self) -> Optional[RecordedSession]:
        """Get the current active session."""
        return self._current_session

    def get_step_count(self) -> int:
        """Get the current step count."""
        return self._step_counter

    def save_session(self, filepath: str, session: Optional[RecordedSession] = None) -> Path:
        """Save a session to JSON file.

        Args:
            filepath: Path to save the file.
            session: Session to save (uses current or last ended session if None).

        Returns:
            Path to the saved file.
        """
        # Use provided session, or current session, or last ended session
        if session is None:
            session = self._current_session
        if session is None and hasattr(self, '_last_session'):
            session = self._last_session
        if not session:
            raise ValueError("No session to save")

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            json.dump(session.to_dict(), f, indent=2)

        return path

    def load_session(self, filepath: str) -> RecordedSession:
        """Load a session from JSON file.

        Args:
            filepath: Path to the session file.

        Returns:
            The loaded RecordedSession.
        """
        with open(filepath, 'r') as f:
            data = json.load(f)

        return RecordedSession.from_dict(data)

    def get_replay_actions(self, session: Optional[RecordedSession] = None) -> List[TranslatedAction]:
        """Get actions for replay.

        Args:
            session: Session to get actions from (uses current if None).

        Returns:
            List of TranslatedActions for replay.
        """
        session = session or self._current_session
        if not session:
            raise ValueError("No session available")

        return session.get_actions_for_replay()

    def export_to_scenario_yaml(
        self,
        filepath: str,
        session: Optional[RecordedSession] = None,
        include_states: bool = False
    ) -> Path:
        """Export session to a scenario YAML file.

        Args:
            filepath: Path to save the YAML file.
            session: Session to export (uses current if None).
            include_states: Whether to include state snapshots in export.

        Returns:
            Path to the saved file.
        """
        import yaml

        session = session or self._current_session
        if not session:
            raise ValueError("No session to export")

        scenario = {
            'name': session.name,
            'description': session.notes or f"Recorded session {session.session_id}",
            'seed': session.seed,
            'character': session.character,
            'ascension': session.ascension,
            'tags': session.tags,
            'steps': [],
        }

        for action in session.actions:
            step = {
                'action': action.action_type,
                'command': action.sim_command,
            }

            if action.params:
                step['params'] = action.params

            if include_states and action.pre_state:
                step['pre_state'] = action.pre_state

            if include_states and action.post_state:
                step['post_state'] = action.post_state

            if action.notes:
                step['notes'] = action.notes

            scenario['steps'].append(step)

        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w') as f:
            yaml.dump(scenario, f, default_flow_style=False, sort_keys=False)

        return path


def replay_session(
    session_path: str,
    orchestrator,  # SyncOrchestrator
    compare: bool = True
) -> 'ScenarioResult':
    """Replay a recorded session using a SyncOrchestrator.

    Args:
        session_path: Path to the recorded session JSON.
        orchestrator: A SyncOrchestrator instance (connected and initialized).
        compare: Whether to compare states during replay.

    Returns:
        ScenarioResult from the replay.
    """
    recorder = ActionRecorder()
    session = recorder.load_session(session_path)

    actions = session.get_actions_for_replay()

    return orchestrator.run_scenario(
        name=session.name,
        actions=actions,
        seed=session.seed,
        character=session.character,
        ascension=session.ascension,
    )
