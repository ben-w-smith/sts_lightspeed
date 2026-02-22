"""Translate actions between CommunicationMod and ConsoleSimulator formats."""
from dataclasses import dataclass
from typing import Optional, Tuple
from enum import Enum


class ActionType(Enum):
    """Types of actions that can be performed."""
    PLAY_CARD = "play_card"
    END_TURN = "end_turn"
    USE_POTION = "use_potion"
    DISCARD_POTION = "discard_potion"
    CHOOSE_OPTION = "choose_option"
    MAP_MOVE = "map_move"
    SHOP_BUY = "shop_buy"
    REST = "rest"
    UNKNOWN = "unknown"


@dataclass
class TranslatedAction:
    """Represents a translated action."""
    action_type: ActionType
    game_command: str
    sim_command: str
    params: dict


class ActionTranslator:
    """Translate actions between CommunicationMod and ConsoleSimulator formats.

    CommunicationMod format:
    - play <idx> [target]
    - end
    - potion use <slot> [target]
    - potion discard <slot>
    - choose <idx>

    ConsoleSimulator format:
    - <idx> [target] (for cards)
    - end
    - drink <slot> [target]
    - discard potion <slot>
    - <idx> (for choices)
    """

    @staticmethod
    def from_game_to_sim(game_command: str) -> TranslatedAction:
        """Translate from CommunicationMod format to ConsoleSimulator format.

        Args:
            game_command: Command from CommunicationMod.

        Returns:
            TranslatedAction with both formats and parameters.
        """
        parts = game_command.strip().lower().split()
        if not parts:
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command=game_command,
                sim_command="",
                params={}
            )

        command = parts[0]

        if command == "play":
            return ActionTranslator._translate_play(parts)
        elif command == "end":
            return TranslatedAction(
                action_type=ActionType.END_TURN,
                game_command="end",
                sim_command="end",
                params={}
            )
        elif command == "potion":
            return ActionTranslator._translate_potion(parts)
        elif command == "choose":
            return TranslatedAction(
                action_type=ActionType.CHOOSE_OPTION,
                game_command=game_command,
                sim_command=parts[1] if len(parts) > 1 else "0",
                params={'option_index': int(parts[1]) if len(parts) > 1 else 0}
            )
        elif command == "key":
            # Key press - may not have direct simulator equivalent
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command=game_command,
                sim_command="",
                params={'key': parts[1] if len(parts) > 1 else ''}
            )
        elif command == "click":
            # Mouse click - may not have direct simulator equivalent
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command=game_command,
                sim_command="",
                params={
                    'x': int(parts[1]) if len(parts) > 1 else 0,
                    'y': int(parts[2]) if len(parts) > 2 else 0,
                }
            )
        elif command == "wait":
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command=game_command,
                sim_command="",
                params={'frames': int(parts[1]) if len(parts) > 1 else 1}
            )
        else:
            # Try to interpret as a simple index (for choices)
            try:
                idx = int(command)
                return TranslatedAction(
                    action_type=ActionType.CHOOSE_OPTION,
                    game_command=game_command,
                    sim_command=str(idx),
                    params={'option_index': idx}
                )
            except ValueError:
                return TranslatedAction(
                    action_type=ActionType.UNKNOWN,
                    game_command=game_command,
                    sim_command=game_command,
                    params={}
                )

    @staticmethod
    def _translate_play(parts: list) -> TranslatedAction:
        """Translate 'play' command."""
        card_index = int(parts[1]) if len(parts) > 1 else 0
        target_index = int(parts[2]) if len(parts) > 2 else -1

        # ConsoleSimulator uses just the index (with optional target)
        if target_index >= 0:
            sim_command = f"{card_index} {target_index}"
        else:
            sim_command = str(card_index)

        game_command = f"play {card_index}"
        if target_index >= 0:
            game_command += f" {target_index}"

        return TranslatedAction(
            action_type=ActionType.PLAY_CARD,
            game_command=game_command,
            sim_command=sim_command,
            params={
                'card_index': card_index,
                'target_index': target_index
            }
        )

    @staticmethod
    def _translate_potion(parts: list) -> TranslatedAction:
        """Translate 'potion' command."""
        if len(parts) < 3:
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command="potion",
                sim_command="",
                params={}
            )

        subcommand = parts[1]
        slot = int(parts[2]) if len(parts) > 2 else 0
        target = int(parts[3]) if len(parts) > 3 else -1

        if subcommand == "use":
            if target >= 0:
                sim_command = f"drink {slot} {target}"
                game_command = f"potion use {slot} {target}"
            else:
                sim_command = f"drink {slot}"
                game_command = f"potion use {slot}"

            return TranslatedAction(
                action_type=ActionType.USE_POTION,
                game_command=game_command,
                sim_command=sim_command,
                params={
                    'slot': slot,
                    'target_index': target
                }
            )

        elif subcommand == "discard":
            return TranslatedAction(
                action_type=ActionType.DISCARD_POTION,
                game_command=f"potion discard {slot}",
                sim_command=f"discard potion {slot}",
                params={'slot': slot}
            )

        return TranslatedAction(
            action_type=ActionType.UNKNOWN,
            game_command="potion",
            sim_command="",
            params={}
        )

    @staticmethod
    def from_sim_to_game(sim_command: str) -> TranslatedAction:
        """Translate from ConsoleSimulator format to CommunicationMod format.

        Args:
            sim_command: Command for ConsoleSimulator.

        Returns:
            TranslatedAction with both formats and parameters.
        """
        parts = sim_command.strip().split()
        if not parts:
            return TranslatedAction(
                action_type=ActionType.UNKNOWN,
                game_command="",
                sim_command=sim_command,
                params={}
            )

        command = parts[0].lower()

        # Check for known commands
        if command == "end":
            return TranslatedAction(
                action_type=ActionType.END_TURN,
                game_command="end",
                sim_command="end",
                params={}
            )

        elif command == "drink":
            return ActionTranslator._translate_drink(parts)

        elif command.startswith("discard"):
            return ActionTranslator._translate_discard(parts)

        # Try to parse as numeric (card play or choice)
        try:
            first_num = int(command)
            second_num = int(parts[1]) if len(parts) > 1 else -1

            # Could be a card play or a choice - context dependent
            # Default to card play
            if second_num >= 0:
                return TranslatedAction(
                    action_type=ActionType.PLAY_CARD,
                    game_command=f"play {first_num} {second_num}",
                    sim_command=f"{first_num} {second_num}",
                    params={
                        'card_index': first_num,
                        'target_index': second_num
                    }
                )
            else:
                return TranslatedAction(
                    action_type=ActionType.PLAY_CARD,  # Could also be CHOOSE_OPTION
                    game_command=f"play {first_num}",
                    sim_command=str(first_num),
                    params={'card_index': first_num, 'target_index': -1}
                )
        except ValueError:
            pass

        # Unknown command
        return TranslatedAction(
            action_type=ActionType.UNKNOWN,
            game_command=sim_command,
            sim_command=sim_command,
            params={}
        )

    @staticmethod
    def _translate_drink(parts: list) -> TranslatedAction:
        """Translate 'drink' (potion use) command."""
        slot = int(parts[1]) if len(parts) > 1 else 0
        target = int(parts[2]) if len(parts) > 2 else -1

        if target >= 0:
            game_command = f"potion use {slot} {target}"
            sim_command = f"drink {slot} {target}"
        else:
            game_command = f"potion use {slot}"
            sim_command = f"drink {slot}"

        return TranslatedAction(
            action_type=ActionType.USE_POTION,
            game_command=game_command,
            sim_command=sim_command,
            params={
                'slot': slot,
                'target_index': target
            }
        )

    @staticmethod
    def _translate_discard(parts: list) -> TranslatedAction:
        """Translate 'discard' command."""
        # Format: "discard potion <slot>"
        if len(parts) >= 3 and parts[1].lower() == "potion":
            slot = int(parts[2])
            return TranslatedAction(
                action_type=ActionType.DISCARD_POTION,
                game_command=f"potion discard {slot}",
                sim_command=f"discard potion {slot}",
                params={'slot': slot}
            )

        return TranslatedAction(
            action_type=ActionType.UNKNOWN,
            game_command="",
            sim_command="discard",
            params={}
        )

    @staticmethod
    def parse_screen_actions(screen_text: str) -> list:
        """Parse available actions from ConsoleSimulator screen output.

        Args:
            screen_text: Output from get_screen_text().

        Returns:
            List of available action indices/options.
        """
        actions = []
        for line in screen_text.split('\n'):
            line = line.strip()
            if ':' in line:
                # Format is typically "0: action description"
                parts = line.split(':', 1)
                idx_str = parts[0].strip()
                if idx_str.isdigit():
                    actions.append(int(idx_str))
        return actions
