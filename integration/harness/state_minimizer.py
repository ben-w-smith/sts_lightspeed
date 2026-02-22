"""State minimizer for finding minimal bug reproduction steps.

This module provides functionality to reduce a sequence of actions
to the minimal set that still reproduces a bug, using binary search
and other techniques.
"""
import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Callable, Any, Tuple

from .action_translator import ActionTranslator, TranslatedAction, ActionType


@dataclass
class MinimizationResult:
    """Result of a minimization attempt."""
    original_actions: List[TranslatedAction]
    minimized_actions: List[TranslatedAction]
    original_count: int
    minimized_count: int
    reduction_percentage: float
    iterations: int = 0
    successful: bool = False
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'original_count': self.original_count,
            'minimized_count': self.minimized_count,
            'reduction_percentage': round(self.reduction_percentage, 1),
            'iterations': self.iterations,
            'successful': self.successful,
            'error': self.error,
            'timestamp': self.timestamp,
            'original_actions': [
                {'game': a.game_command, 'sim': a.sim_command}
                for a in self.original_actions
            ],
            'minimized_actions': [
                {'game': a.game_command, 'sim': a.sim_command}
                for a in self.minimized_actions
            ],
        }


class StateMinimizer:
    """Minimizes action sequences to find minimal reproduction steps.

    Uses binary search and other techniques to find the smallest
    subset of actions that still reproduces a bug.

    Usage:
        minimizer = StateMinimulator(reproduction_check=check_func)

        # Minimize a sequence of actions
        result = minimizer.minimize(actions)

        print(f"Reduced from {result.original_count} to {result.minimized_count} actions")
    """

    def __init__(
        self,
        reproduction_check: Optional[Callable[[List[TranslatedAction]], bool]] = None,
        setup_func: Optional[Callable[[], Any]] = None,
        teardown_func: Optional[Callable[[], Any]] = None,
        max_iterations: int = 100,
        verbose: bool = False
    ):
        """Initialize the state minimizer.

        Args:
            reproduction_check: Function that takes a list of actions and
                               returns True if the bug is reproduced.
            setup_func: Optional function to call before each test.
            teardown_func: Optional function to call after each test.
            max_iterations: Maximum number of minimization iterations.
            verbose: Enable verbose output.
        """
        self.reproduction_check = reproduction_check
        self.setup_func = setup_func
        self.teardown_func = teardown_func
        self.max_iterations = max_iterations
        self.verbose = verbose
        self.translator = ActionTranslator()

    def _log(self, message: str):
        """Log a message if verbose mode is enabled."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"[{timestamp}] {message}")

    def minimize(
        self,
        actions: List[TranslatedAction],
        strategy: str = "binary"
    ) -> MinimizationResult:
        """Minimize an action sequence.

        Args:
            actions: List of actions to minimize.
            strategy: Minimization strategy ("binary", "linear", "ddmin").

        Returns:
            MinimizationResult with the minimized sequence.
        """
        if not actions:
            return MinimizationResult(
                original_actions=[],
                minimized_actions=[],
                original_count=0,
                minimized_count=0,
                reduction_percentage=0.0,
                successful=True,
            )

        original_count = len(actions)

        # Verify original sequence reproduces the bug
        if self.reproduction_check and not self._check_reproduction(actions):
            return MinimizationResult(
                original_actions=actions,
                minimized_actions=actions,
                original_count=original_count,
                minimized_count=original_count,
                reduction_percentage=0.0,
                successful=False,
                error="Original sequence does not reproduce the bug",
            )

        # Apply minimization strategy
        if strategy == "binary":
            minimized = self._minimize_binary(actions)
        elif strategy == "ddmin":
            minimized = self._minimize_ddmin(actions)
        else:
            minimized = self._minimize_linear(actions)

        minimized_count = len(minimized)
        reduction = ((original_count - minimized_count) / original_count) * 100 if original_count > 0 else 0

        return MinimizationResult(
            original_actions=actions,
            minimized_actions=minimized,
            original_count=original_count,
            minimized_count=minimized_count,
            reduction_percentage=reduction,
            successful=True,
        )

    def _check_reproduction(self, actions: List[TranslatedAction]) -> bool:
        """Check if an action sequence reproduces the bug.

        Args:
            actions: Actions to test.

        Returns:
            True if bug is reproduced.
        """
        if self.reproduction_check is None:
            return True

        try:
            if self.setup_func:
                self.setup_func()

            result = self.reproduction_check(actions)

            if self.teardown_func:
                self.teardown_func()

            return result

        except Exception as e:
            self._log(f"Error checking reproduction: {e}")
            if self.teardown_func:
                try:
                    self.teardown_func()
                except Exception:
                    pass
            return False

    def _minimize_linear(self, actions: List[TranslatedAction]) -> List[TranslatedAction]:
        """Linear minimization - try removing each action one at a time.

        This is simple but can be slow for large sequences.
        """
        self._log(f"Starting linear minimization with {len(actions)} actions")

        current = list(actions)
        i = 0
        iterations = 0

        while i < len(current) and iterations < self.max_iterations:
            iterations += 1

            # Try removing action at index i
            test_sequence = current[:i] + current[i+1:]

            if self._check_reproduction(test_sequence):
                self._log(f"Removed action {i}: {current[i].game_command}")
                current = test_sequence
                # Don't increment i, try same index again
            else:
                i += 1

        self._log(f"Linear minimization complete: {len(actions)} -> {len(current)}")
        return current

    def _minimize_binary(self, actions: List[TranslatedAction]) -> List[TranslatedAction]:
        """Binary search minimization - try removing halves.

        This is faster for large sequences but may not find the absolute minimum.
        """
        self._log(f"Starting binary minimization with {len(actions)} actions")

        current = list(actions)
        changed = True
        iterations = 0

        while changed and iterations < self.max_iterations:
            changed = False
            iterations += 1

            # Try removing first half
            mid = len(current) // 2
            first_half = current[:mid]
            second_half = current[mid:]

            if self._check_reproduction(second_half):
                self._log(f"Removed first half ({len(first_half)} actions)")
                current = second_half
                changed = True
                continue

            if self._check_reproduction(first_half):
                self._log(f"Removed second half ({len(second_half)} actions)")
                current = first_half
                changed = True
                continue

            # Binary didn't work, try finer-grained
            # Try removing quarters
            quarter = len(current) // 4
            if quarter > 0:
                for start in range(0, len(current), quarter):
                    end = min(start + quarter, len(current))
                    test_sequence = current[:start] + current[end:]

                    if len(test_sequence) > 0 and self._check_reproduction(test_sequence):
                        self._log(f"Removed quarter ({end - start} actions)")
                        current = test_sequence
                        changed = True
                        break

        # Final pass with linear to clean up
        current = self._minimize_linear(current)

        self._log(f"Binary minimization complete: {len(actions)} -> {len(current)}")
        return current

    def _minimize_ddmin(self, actions: List[TranslatedAction]) -> List[TranslatedAction]:
        """Delta Debugging minimization algorithm.

        This is the classic ddmin algorithm that systematically reduces
        the test case while maintaining the failure.
        """
        self._log(f"Starting ddmin minimization with {len(actions)} actions")

        current = list(actions)
        n = 2
        iterations = 0

        while len(current) >= 2 and iterations < self.max_iterations:
            iterations += 1
            subset_size = max(1, len(current) // n)
            changed = False

            # Try each subset
            for i in range(n):
                start = i * subset_size
                end = start + subset_size if i < n - 1 else len(current)

                # Remove this subset
                test_sequence = current[:start] + current[end:]

                if len(test_sequence) > 0 and self._check_reproduction(test_sequence):
                    self._log(f"ddmin: removed subset {i} ({end - start} actions)")
                    current = test_sequence
                    n = 2
                    changed = True
                    break

            if not changed:
                if n >= len(current):
                    break
                n = min(n * 2, len(current))

        self._log(f"ddmin minimization complete: {len(actions)} -> {len(current)}")
        return current

    def minimize_from_strings(
        self,
        commands: List[str],
        command_type: str = "sim"
    ) -> Tuple[List[str], MinimizationResult]:
        """Minimize a sequence of command strings.

        Args:
            commands: List of command strings.
            command_type: "sim" or "game" format.

        Returns:
            Tuple of (minimized_commands, MinimizationResult).
        """
        # Convert to TranslatedActions
        actions = []
        for cmd in commands:
            if command_type == "game":
                action = self.translator.from_game_to_sim(cmd)
            else:
                action = self.translator.from_sim_to_game(cmd)
            actions.append(action)

        result = self.minimize(actions)

        # Extract minimized commands
        if command_type == "game":
            minimized = [a.game_command for a in result.minimized_actions]
        else:
            minimized = [a.sim_command for a in result.minimized_actions]

        return minimized, result


def create_minimizer_with_orchestrator(
    orchestrator,  # SyncOrchestrator
    bug_check_func: Callable[[Any], bool],
    seed: int,
    character: str = 'IRONCLAD',
    ascension: int = 0,
    verbose: bool = False
) -> StateMinimizer:
    """Create a StateMinimizer configured to work with a SyncOrchestrator.

    Args:
        orchestrator: The SyncOrchestrator to use for reproduction checks.
        bug_check_func: Function that takes a ComparisonResult and returns
                       True if the bug is detected.
        seed: Game seed for setup.
        character: Character class.
        ascension: Ascension level.
        verbose: Enable verbose output.

    Returns:
        Configured StateMinimizer.
    """
    def setup():
        orchestrator.initialize_simulator(seed, character, ascension)

    def teardown():
        pass  # Orchestrator handles cleanup

    def check(actions: List[TranslatedAction]) -> bool:
        """Check if actions reproduce the bug."""
        try:
            result = orchestrator.run_scenario(
                name="minimization_test",
                actions=actions,
                seed=seed,
                character=character,
                ascension=ascension,
            )

            # Check if any step has the bug
            for step in result.steps:
                if step.comparison and bug_check_func(step.comparison):
                    return True

            return False

        except Exception:
            return False

    return StateMinimizer(
        reproduction_check=check,
        setup_func=setup,
        teardown_func=teardown,
        verbose=verbose,
    )
