"""Deterministic sync orchestrator for game-simulator execution.

This module provides deterministic execution of actions on both the real game
(via CommunicationMod) and the simulator simultaneously, with step-by-step
validation and state comparison.

Unlike the heuristic-based approach in interactive_sync.py, this orchestrator
drives both game and simulator with known actions, making it suitable for
reliable automated testing.
"""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

from .game_controller import GameController, CommunicationModError
from .state_comparator import StateComparator, ComparisonResult, Discrepancy, DiscrepancySeverity
from .action_translator import ActionTranslator, TranslatedAction, ActionType

# Lazy import for SimulatorController to avoid import errors when not built
SimulatorController = None


def _get_simulator_controller():
    """Get SimulatorController class (lazy import)."""
    global SimulatorController
    if SimulatorController is None:
        from .simulator_controller import SimulatorController as SC
        SimulatorController = SC
    return SimulatorController


@dataclass
class StepResult:
    """Result of a single synchronized step."""
    step_number: int
    action: TranslatedAction
    pre_game_state: Optional[Dict[str, Any]] = None
    pre_sim_state: Optional[Dict[str, Any]] = None
    post_game_state: Optional[Dict[str, Any]] = None
    post_sim_state: Optional[Dict[str, Any]] = None
    comparison: Optional[ComparisonResult] = None
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    action_delay: float = 0.0

    @property
    def passed(self) -> bool:
        """Check if this step passed without critical discrepancies."""
        if self.error:
            return False
        if self.comparison is None:
            return True
        return self.comparison.critical_count == 0

    @property
    def has_discrepancies(self) -> bool:
        """Check if this step has any discrepancies."""
        return self.comparison is not None and not self.comparison.match

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'step_number': self.step_number,
            'action': {
                'type': self.action.action_type.value,
                'game_command': self.action.game_command,
                'sim_command': self.action.sim_command,
                'params': self.action.params,
            },
            'passed': self.passed,
            'error': self.error,
            'timestamp': self.timestamp,
            'action_delay': self.action_delay,
            'discrepancies': [
                {
                    'field': d.field,
                    'game_value': d.game_value,
                    'sim_value': d.sim_value,
                    'severity': d.severity.value,
                    'message': d.message,
                }
                for d in (self.comparison.discrepancies if self.comparison else [])
            ] if self.has_discrepancies else [],
        }


@dataclass
class ScenarioResult:
    """Result of running a complete scenario."""
    scenario_name: str
    seed: int
    character: str
    ascension: int
    steps: List[StepResult] = field(default_factory=list)
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    end_time: Optional[str] = None
    error: Optional[str] = None

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def passed(self) -> bool:
        """Check if all steps passed."""
        return all(s.passed for s in self.steps) and self.error is None

    @property
    def failed_steps(self) -> List[StepResult]:
        """Get list of failed steps."""
        return [s for s in self.steps if not s.passed]

    @property
    def critical_discrepancy_count(self) -> int:
        """Total critical discrepancies across all steps."""
        return sum(
            s.comparison.critical_count if s.comparison else 0
            for s in self.steps
        )

    @property
    def major_discrepancy_count(self) -> int:
        """Total major discrepancies across all steps."""
        return sum(
            s.comparison.major_count if s.comparison else 0
            for s in self.steps
        )

    @property
    def minor_discrepancy_count(self) -> int:
        """Total minor discrepancies across all steps."""
        return sum(
            s.comparison.minor_count if s.comparison else 0
            for s in self.steps
        )

    def finalize(self):
        """Mark the scenario as complete."""
        self.end_time = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            'scenario_name': self.scenario_name,
            'seed': self.seed,
            'character': self.character,
            'ascension': self.ascension,
            'total_steps': self.total_steps,
            'passed': self.passed,
            'critical_discrepancies': self.critical_discrepancy_count,
            'major_discrepancies': self.major_discrepancy_count,
            'minor_discrepancies': self.minor_discrepancy_count,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'error': self.error,
            'steps': [s.to_dict() for s in self.steps],
        }


class SyncOrchestrator:
    """Deterministic execution orchestrator for game-simulator sync.

    This class drives both the game and simulator with known actions,
    capturing pre/post states for each action and comparing them.

    Usage:
        orchestrator = SyncOrchestrator()
        orchestrator.connect_game()
        orchestrator.initialize_simulator()

        # Execute actions deterministically
        result = orchestrator.execute_action(action)
        result = orchestrator.run_scenario(scenario_steps)

        orchestrator.disconnect()
    """

    def __init__(
        self,
        state_dir: str = "/tmp/sts_bridge",
        action_delay: float = 0.1,
        stop_on_critical: bool = True,
        verbose: bool = False,
        state_comparator: Optional[StateComparator] = None,
    ):
        """Initialize the sync orchestrator.

        Args:
            state_dir: Directory for bridge communication.
            action_delay: Delay in seconds after game commands.
            stop_on_critical: Stop scenario on critical discrepancy.
            verbose: Enable verbose output.
            state_comparator: Optional custom state comparator.
        """
        self.state_dir = state_dir
        self.action_delay = action_delay
        self.stop_on_critical = stop_on_critical
        self.verbose = verbose

        self.game: Optional[GameController] = None
        self.sim: Optional[SimulatorController] = None
        self.comparator = state_comparator or StateComparator()
        self.translator = ActionTranslator()

        self._current_scenario: Optional[ScenarioResult] = None
        self._step_counter: int = 0

    def _log(self, message: str, level: str = "INFO"):
        """Log a message if verbose mode is enabled."""
        if self.verbose or level in ("ERROR", "WARNING"):
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] [{level}] {message}")

    def connect_game(
        self,
        project_name: str = "sync_orchestrator",
        timeout: float = 30.0
    ) -> bool:
        """Connect to the game via CommunicationMod.

        Args:
            project_name: Name for bridge lock identification.
            timeout: Connection timeout in seconds.

        Returns:
            True if connection successful.

        Raises:
            CommunicationModError: If connection fails.
        """
        self._log("Connecting to CommunicationMod bridge...")
        self.game = GameController(
            state_dir=self.state_dir,
            timeout=timeout,
            project_name=project_name,
        )
        self.game.connect()
        self._log("Connected to game successfully")
        return True

    def disconnect_game(self):
        """Disconnect from the game."""
        if self.game:
            self.game.disconnect()
            self.game = None
            self._log("Disconnected from game")

    def initialize_simulator(
        self,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0
    ) -> bool:
        """Initialize the simulator with the given parameters.

        Args:
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.

        Returns:
            True if initialization successful.
        """
        self._log(f"Initializing simulator: seed={seed}, character={character}, ascension={ascension}")
        SC = _get_simulator_controller()
        self.sim = SC()
        self.sim.setup_game(seed, character, ascension)
        self._log("Simulator initialized successfully")
        return True

    def sync_simulator_from_game(self) -> Dict[str, Any]:
        """Sync simulator state from the connected game.

        Extracts seed, character, and ascension from the game and
        initializes the simulator to match.

        Returns:
            Dictionary with sync information.
        """
        if not self.game:
            raise RuntimeError("Not connected to game")

        state = self.game.get_state()
        game_state = state.get('game_state', state)

        # Extract seed
        raw_seed = game_state.get('seed', 0)
        if raw_seed > 0x7FFFFFFFFFFFFFFF:
            seed = raw_seed - 0x10000000000000000
        else:
            seed = raw_seed

        # Extract character and ascension
        character = game_state.get('character', 'IRONCLAD').upper()
        ascension = game_state.get('ascension_level', 0)

        self.initialize_simulator(seed, character, ascension)

        return {
            'seed': seed,
            'character': character,
            'ascension': ascension,
            'verified': True,
        }

    def get_game_state(self) -> Optional[Dict[str, Any]]:
        """Get current game state."""
        if not self.game:
            return None
        return self.game.get_state()

    def get_sim_state(self) -> Optional[Dict[str, Any]]:
        """Get current simulator state."""
        if not self.sim:
            return None
        return self.sim.get_state()

    def execute_action(
        self,
        action: TranslatedAction,
        compare: bool = True,
        capture_states: bool = True
    ) -> StepResult:
        """Execute an action on both game and simulator.

        This is the core method that drives both systems with the same
        action and captures the results for comparison.

        Args:
            action: The translated action to execute.
            compare: Whether to compare states after execution.
            capture_states: Whether to capture pre/post states.

        Returns:
            StepResult with execution details and comparison.
        """
        step_number = self._step_counter
        self._step_counter += 1

        self._log(f"Step {step_number}: {action.action_type.value} - "
                  f"game='{action.game_command}' sim='{action.sim_command}'")

        result = StepResult(
            step_number=step_number,
            action=action,
            action_delay=self.action_delay,
        )

        try:
            # Capture pre-states
            if capture_states:
                result.pre_game_state = self.get_game_state()
                result.pre_sim_state = self.get_sim_state()

            # Execute on game first
            if self.game and action.game_command:
                self.game.send_command(action.game_command)
                time.sleep(self.action_delay)

            # Execute on simulator
            if self.sim and action.sim_command:
                self.sim.take_action(action.sim_command)

            # Capture post-states
            if capture_states:
                result.post_game_state = self.get_game_state()
                result.post_sim_state = self.get_sim_state()

            # Compare states
            if compare and result.post_game_state and result.post_sim_state:
                result.comparison = self.comparator.compare(
                    result.post_game_state,
                    result.post_sim_state
                )

                if result.comparison and not result.comparison.match:
                    self._log(
                        f"Discrepancies: {result.comparison.get_summary()}",
                        level="WARNING"
                    )

        except Exception as e:
            result.error = str(e)
            self._log(f"Error executing action: {e}", level="ERROR")

        # Record in current scenario if active
        if self._current_scenario:
            self._current_scenario.steps.append(result)

        return result

    def execute_action_from_string(
        self,
        action_str: str,
        action_type: str = "auto",
        compare: bool = True
    ) -> StepResult:
        """Execute an action from a string command.

        Args:
            action_str: The action string (game or sim format).
            action_type: "game", "sim", or "auto" for auto-detection.
            compare: Whether to compare states after.

        Returns:
            StepResult with execution details.
        """
        if action_type == "game":
            action = self.translator.from_game_to_sim(action_str)
        elif action_type == "sim":
            action = self.translator.from_sim_to_game(action_str)
        else:
            # Try to auto-detect - sim commands are typically numeric
            try:
                int(action_str.split()[0])
                action = self.translator.from_sim_to_game(action_str)
            except (ValueError, IndexError):
                action = self.translator.from_game_to_sim(action_str)

        return self.execute_action(action, compare=compare)

    def start_scenario(
        self,
        name: str,
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0
    ) -> ScenarioResult:
        """Start a new scenario execution.

        Args:
            name: Scenario name.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.

        Returns:
            ScenarioResult to track execution.
        """
        self._current_scenario = ScenarioResult(
            scenario_name=name,
            seed=seed,
            character=character,
            ascension=ascension,
        )
        self._step_counter = 0

        # Initialize simulator if needed
        if not self.sim:
            self.initialize_simulator(seed, character, ascension)

        self._log(f"Started scenario: {name}")
        return self._current_scenario

    def run_scenario(
        self,
        name: str,
        actions: List[TranslatedAction],
        seed: int,
        character: str = 'IRONCLAD',
        ascension: int = 0,
        max_steps: Optional[int] = None
    ) -> ScenarioResult:
        """Run a complete scenario with multiple actions.

        Args:
            name: Scenario name.
            actions: List of actions to execute.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.
            max_steps: Maximum steps to execute (None for all).

        Returns:
            ScenarioResult with complete execution details.
        """
        result = self.start_scenario(name, seed, character, ascension)

        steps_to_execute = actions[:max_steps] if max_steps else actions

        try:
            for action in steps_to_execute:
                step_result = self.execute_action(action)

                # Stop on critical if configured
                if self.stop_on_critical and not step_result.passed:
                    self._log(f"Stopping scenario: critical discrepancy at step {step_result.step_number}")
                    break

        except Exception as e:
            result.error = str(e)
            self._log(f"Scenario error: {e}", level="ERROR")

        result.finalize()
        self._current_scenario = None

        self._log(f"Scenario complete: {name} - {'PASSED' if result.passed else 'FAILED'}")
        return result

    def run_action_strings(
        self,
        actions: List[str],
        action_type: str = "sim",
        name: str = "unnamed_scenario",
        seed: int = 12345,
        character: str = 'IRONCLAD',
        ascension: int = 0
    ) -> ScenarioResult:
        """Run a scenario from a list of action strings.

        Args:
            actions: List of action strings.
            action_type: "game", "sim", or "auto".
            name: Scenario name.
            seed: Game seed.
            character: Character class.
            ascension: Ascension level.

        Returns:
            ScenarioResult with execution details.
        """
        translated_actions = []
        for action_str in actions:
            if action_type == "game":
                action = self.translator.from_game_to_sim(action_str)
            elif action_type == "sim":
                action = self.translator.from_sim_to_game(action_str)
            else:
                try:
                    int(action_str.split()[0])
                    action = self.translator.from_sim_to_game(action_str)
                except (ValueError, IndexError):
                    action = self.translator.from_game_to_sim(action_str)
            translated_actions.append(action)

        return self.run_scenario(name, translated_actions, seed, character, ascension)

    def verify_initial_states(self) -> ComparisonResult:
        """Verify that game and simulator start in matching states.

        Returns:
            ComparisonResult of initial state comparison.
        """
        game_state = self.get_game_state()
        sim_state = self.get_sim_state()

        if not game_state or not sim_state:
            raise RuntimeError("Both game and simulator must be initialized")

        return self.comparator.compare(game_state, sim_state)

    def get_current_step_number(self) -> int:
        """Get the current step number."""
        return self._step_counter

    def disconnect(self):
        """Disconnect from all systems."""
        self.disconnect_game()
        self.sim = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()
        return False
