"""Test harness components for integration testing."""
from .game_controller import GameController, CommunicationModError
from .state_comparator import StateComparator, ComparisonResult, Discrepancy
from .action_translator import ActionTranslator, TranslatedAction, ActionType
from .reporter import Reporter, TestResult, StepResult

# SimulatorController requires the slaythespire module to be built
# Import it conditionally to allow other components to work without it
try:
    from .simulator_controller import SimulatorController
    _simulator_available = True
except ImportError:
    SimulatorController = None
    _simulator_available = False


def is_simulator_available() -> bool:
    """Check if the simulator module is available.

    Returns:
        True if slaythespire module is built and available.
    """
    return _simulator_available


def get_simulator_controller(*args, **kwargs):
    """Get a SimulatorController instance.

    Raises:
        ImportError: If the slaythespire module is not available.

    Returns:
        SimulatorController instance.
    """
    if not _simulator_available:
        raise ImportError(
            "SimulatorController requires the slaythespire module. "
            "Build it with: cmake --build build"
        )
    return SimulatorController(*args, **kwargs)


__all__ = [
    'GameController',
    'CommunicationModError',
    'SimulatorController',
    'StateComparator',
    'ComparisonResult',
    'Discrepancy',
    'ActionTranslator',
    'TranslatedAction',
    'ActionType',
    'Reporter',
    'TestResult',
    'StepResult',
    'is_simulator_available',
    'get_simulator_controller',
]
