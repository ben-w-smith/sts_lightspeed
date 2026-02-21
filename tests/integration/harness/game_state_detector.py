"""Game state detection utility.

This module provides utilities for detecting the current game state
from CommunicationMod output.
"""
from typing import Dict, Any, Optional
from enum import Enum


class GameState(Enum):
    """Possible game states."""
    UNKNOWN = "unknown"
    LOADING = "loading"
    MAIN_MENU = "main_menu"
    CHARACTER_SELECT = "character_select"
    GAME_PLAYING = "game_playing"  # On map, not in combat
    COMBAT = "combat"
    COMBAT_REWARD = "combat_reward"
    CARD_REWARD = "card_reward"
    RELIC_REWARD = "relic_reward"
    BOSS_RELIC = "boss_relic"
    MAP = "map"
    EVENT = "event"
    SHOP = "shop"
    REST = "rest"
    TREASURE = "treasure"
    GAME_OVER = "game_over"
    VICTORY = "victory"


class GameStateDetector:
    """Detects the current game state from CommunicationMod state."""

    # Mapping from CommunicationMod screen types to GameState
    SCREEN_TYPE_MAP = {
        'NONE': GameState.GAME_PLAYING,
        'MAIN_MENU': GameState.MAIN_MENU,
        'CHARACTER_SELECT': GameState.CHARACTER_SELECT,
        'GAME_DECK_VIEW': GameState.GAME_PLAYING,
        'REWARDS': GameState.COMBAT_REWARD,
        'CARD_REWARD': GameState.CARD_REWARD,
        'BOSS_CARD_REWARD': GameState.CARD_REWARD,
        'COMBAT_REWARD': GameState.COMBAT_REWARD,
        'RELIC_REWARD': GameState.RELIC_REWARD,
        'BOSS_RELIC_REWARD': GameState.BOSS_RELIC,
        'MAP': GameState.MAP,
        'GAME_ROOM': GameState.GAME_PLAYING,
        'SHOP': GameState.SHOP,
        'REST': GameState.REST,
        'TREASURE': GameState.TREASURE,
        'EVENT': GameState.EVENT,
        'GAME_OVER': GameState.GAME_OVER,
        'VICTORY': GameState.VICTORY,
    }

    # Mapping from room phases to GameState
    ROOM_PHASE_MAP = {
        'COMBAT': GameState.COMBAT,
        'EVENT': GameState.EVENT,
        'COMPLETE': GameState.GAME_PLAYING,
    }

    @staticmethod
    def detect(state: Dict[str, Any]) -> GameState:
        """Detect the current game state from CommunicationMod state.

        Args:
            state: State dictionary from CommunicationMod.

        Returns:
            Detected GameState.
        """
        if not state:
            return GameState.UNKNOWN

        game_state = state.get('game_state', state)

        # Check for loading state
        if not game_state:
            return GameState.LOADING

        # Check room phase first (most reliable for combat)
        room_phase = game_state.get('room_phase', '')
        if room_phase == 'COMBAT':
            return GameState.COMBAT

        # Check screen type
        screen_type = game_state.get('screen_type', 'NONE')
        screen_name = game_state.get('screen_name', '')

        # Combine screen_type and screen_name for more precise detection
        combined = f"{screen_type}_{screen_name}".upper()

        # Check combined key first
        if combined in GameStateDetector.SCREEN_TYPE_MAP:
            return GameStateDetector.SCREEN_TYPE_MAP[combined]

        # Check screen type
        if screen_type in GameStateDetector.SCREEN_TYPE_MAP:
            return GameStateDetector.SCREEN_TYPE_MAP[screen_type]

        # Check screen name
        if screen_name:
            screen_upper = screen_name.upper()
            if 'REWARD' in screen_upper:
                if 'CARD' in screen_upper:
                    return GameState.CARD_REWARD
                elif 'RELIC' in screen_upper or 'BOSS' in screen_upper:
                    return GameState.BOSS_RELIC
                return GameState.COMBAT_REWARD
            elif 'MAP' in screen_upper:
                return GameState.MAP
            elif 'SHOP' in screen_upper:
                return GameState.SHOP
            elif 'REST' in screen_upper:
                return GameState.REST
            elif 'EVENT' in screen_upper:
                return GameState.EVENT
            elif 'TREASURE' in screen_upper:
                return GameState.TREASURE

        # Check room phase
        if room_phase in GameStateDetector.ROOM_PHASE_MAP:
            return GameStateDetector.ROOM_PHASE_MAP[room_phase]

        # Check for game over / victory
        if game_state.get('is_game_over', False):
            return GameState.GAME_OVER

        if game_state.get('is_victory', False):
            return GameState.VICTORY

        # Check floor/act to determine if in game
        floor = game_state.get('floor')
        if floor is not None and floor > 0:
            return GameState.GAME_PLAYING

        return GameState.UNKNOWN

    @staticmethod
    def is_in_combat(state: Dict[str, Any]) -> bool:
        """Check if currently in combat.

        Args:
            state: State dictionary.

        Returns:
            True if in combat.
        """
        return GameStateDetector.detect(state) == GameState.COMBAT

    @staticmethod
    def is_interactive(state: Dict[str, Any]) -> bool:
        """Check if in an interactive state (can take actions).

        Args:
            state: State dictionary.

        Returns:
            True if can take actions.
        """
        game_state = GameStateDetector.detect(state)
        interactive_states = {
            GameState.COMBAT,
            GameState.MAP,
            GameState.EVENT,
            GameState.SHOP,
            GameState.REST,
            GameState.CARD_REWARD,
            GameState.COMBAT_REWARD,
            GameState.BOSS_RELIC,
            GameState.TREASURE,
        }
        return game_state in interactive_states

    @staticmethod
    def get_action_type(state: Dict[str, Any]) -> Optional[str]:
        """Get the type of actions available in current state.

        Args:
            state: State dictionary.

        Returns:
            Action type string: 'combat', 'map', 'event', 'reward', etc.
        """
        game_state = GameStateDetector.detect(state)

        if game_state == GameState.COMBAT:
            return 'combat'
        elif game_state == GameState.MAP:
            return 'map'
        elif game_state == GameState.EVENT:
            return 'event'
        elif game_state in {GameState.CARD_REWARD, GameState.COMBAT_REWARD,
                           GameState.BOSS_RELIC, GameState.RELIC_REWARD}:
            return 'reward'
        elif game_state == GameState.SHOP:
            return 'shop'
        elif game_state == GameState.REST:
            return 'rest'

        return None

    @staticmethod
    def state_to_string(state: GameState) -> str:
        """Convert GameState to human-readable string.

        Args:
            state: GameState enum value.

        Returns:
            Human-readable string.
        """
        return state.value

    @staticmethod
    def get_state_description(state: Dict[str, Any]) -> str:
        """Get a human-readable description of the current state.

        Args:
            state: State dictionary.

        Returns:
            Description string.
        """
        game_state = GameStateDetector.detect(state)
        game_state_dict = state.get('game_state', state)

        parts = [f"State: {game_state.value}"]

        # Add relevant details
        floor = game_state_dict.get('floor')
        if floor:
            parts.append(f"Floor: {floor}")

        act = game_state_dict.get('act')
        if act:
            parts.append(f"Act: {act}")

        if game_state == GameState.COMBAT:
            combat = game_state_dict.get('combat_state', {})
            turn = combat.get('turn')
            if turn:
                parts.append(f"Turn: {turn}")

            player = combat.get('player', {})
            hp = player.get('cur_hp')
            max_hp = player.get('max_hp')
            if hp is not None and max_hp is not None:
                parts.append(f"HP: {hp}/{max_hp}")

            monsters = combat.get('monsters', [])
            if monsters:
                alive = sum(1 for m in monsters if not m.get('is_dying', False))
                parts.append(f"Monsters: {alive}")

        return " | ".join(parts)
