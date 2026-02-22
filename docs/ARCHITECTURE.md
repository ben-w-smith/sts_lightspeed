# Architecture Overview

sts_lightspeed is a high-performance C++ simulator for Slay the Spire, built for RL training and tree search. The design prioritizes 100% RNG accuracy with the original Java game.

## Core Simulation Loop

```
GameContext (overworld)
     │
     ├── Map navigation, events, shops, rewards
     │
     ▼
BattleContext (combat)
     │
     ├── Card play, monster AI, damage calculation
     │
     ▼
Outcome → back to GameContext
```

- **GameContext** (`include/game/GameContext.h`) - Overworld state: map, deck, relics, gold, HP, screen state
- **BattleContext** (`include/combat/BattleContext.h`) - Combat state: player, monsters, card manager, action queue

## Key Classes

| Class | File | Purpose |
|-------|------|---------|
| `GameContext` | `game/GameContext.h` | Overworld state machine, RNG seeds, deck/relic management |
| `BattleContext` | `combat/BattleContext.h` | Combat state, input handling, action/card queues |
| `Random` | `game/Random.h` | Java-compatible RNG (sts namespace) + Java util.Random (java namespace) |
| `Player` | `combat/Player.h` | HP, block, energy, status effects, orbs, stances |
| `Monster` | `combat/Monster.h` | HP, moves, intents, status effects |
| `CardManager` | `combat/CardManager.h` | Hand, draw pile, discard pile, exhaust pile |
| `ActionQueue` | `combat/ActionQueue.h` | Deferred effect execution (damage, blocks, buffs) |
| `Deck` | `game/Deck.h` | Persistent card collection across floors |

## RNG System

The simulator replicates Java's RNG exactly:

- `java::Random` - Java's `java.util.Random` implementation
- `sts::Random` - Slay the Spire's custom RNG (MurmurHash3-based)

Each context maintains multiple independent RNG streams:
- `shuffleRng`, `cardRandomRng`, `miscRng`, `monsterHpRng`, `potionRng`, `aiRng`

## File Organization

```
include/
├── combat/          # Battle state, player, monsters, actions
├── game/            # Overworld state, map, deck, relics
├── constants/       # Card IDs, monster IDs, relic definitions
├── sim/             # BattleSimulator, agents, search
└── data_structure/  # Fixed-size containers

src/
├── combat/          # Battle logic implementation
├── game/            # Overworld logic
└── sim/             # Simulation and search algorithms

bindings/
└── slaythespire.cpp # pybind11 Python bindings
```

## Navigation Tips

**Finding card implementations:**
1. Check `include/constants/Cards.h` for card IDs
2. Search `src/combat/` for the card name or ID
3. Card effects are typically in `Actions.cpp` or card-specific files

**Finding monster AI:**
1. Check `include/constants/MonsterIds.h` for IDs
2. Look in `src/combat/MonsterSpecific.cpp` for move selection
3. Move damage calculation in `src/combat/MonsterMoveDamage.cpp`

**Understanding state flow:**
1. `BattleContext::inputState` tracks UI state (EXECUTING_ACTIONS, CARD_SELECT, etc.)
2. `ActionQueue` processes deferred effects in order
3. `CardQueue` handles card-specific callbacks (Exordium, etc.)

## Python Bindings

The pybind11 bindings expose:
- Full `GameContext` and `BattleContext` state
- Step-by-step simulation via `battleSimulator`
- Action enumeration for tree search

See `bindings/slaythespire.cpp` for available Python APIs.
