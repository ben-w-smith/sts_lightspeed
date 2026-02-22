# CLAUDE.md - sts_lightspeed

## What This Is

A high-performance C++ simulator for Slay the Spire with Python bindings. Used for RL training and tree search. The simulator achieves 100% RNG accuracy with the original Java game.

## Quick Start

```bash
# Build
cmake -B build -S . && cmake --build build

# Test (simulator-only, no game needed)
python integration/run_tests.py --quick --no-game --seed 12345
```

## Code Map

| Area | Key Files | Start Here |
|------|-----------|------------|
| Combat | `src/combat/` | `BattleContext.h`, `Actions.cpp` |
| Game State | `src/game/` | `GameContext.h`, `Game.cpp` |
| Python API | `bindings/` | `slaythespire.cpp` |
| Card Logic | `src/combat/` + `include/constants/Cards.h` | Search card name |
| Monster AI | `src/combat/MonsterSpecific.cpp` | `MonsterIds.h` |
| RNG System | `include/game/Random.h` | Both namespaces |

## Key Patterns

- **State machines**: `GameContext` handles overworld, `BattleContext` handles combat. Both have `inputState`/`screenState` for UI flow.
- **RNG accuracy**: `java::Random` and `sts::Random` replicate Java exactly. Never modify RNG logic.

## Multi-Project Bridge Coordination

Three STS projects (`sts_lightspeed`, `sts_ai_factory`, `sts_intelligence`) share one CommunicationMod bridge. Use `sts-bridge` to coordinate access:

```bash
# Check if bridge is locked
sts-bridge lock-status

# View the request queue
sts-bridge queue

# Submit a test (waits for completion)
sts-bridge submit --project my_project -- python integration/run_tests.py --quick --no-game

# Submit async (returns request ID immediately)
sts-bridge submit --async --project my_project -- python test.py

# Check request status
sts-bridge status req-abc123

# Wait for request to complete
sts-bridge wait req-abc123 --timeout 3600
```

**Key files:**
- `integration/harness/bridge_lock.py` - POSIX file locking
- `integration/harness/bridge_coordinator.py` - Queue manager daemon
- `integration/harness/sts_bridge_cli.py` - CLI wrapper

**State directory:** `/tmp/sts_bridge/.coordinator/`

## Deeper Docs

- **[docs/TESTING.md](docs/TESTING.md)** - Integration tests, CommunicationMod setup, scenarios
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Class diagrams, data flow, file organization
- **[.agents/workflows/](.agents/workflows/)** - Character-specific implementation guides

## Code Is Truth

1. Read header files first (`include/`) - they define the data structures
2. Then read source (`src/`) for implementation details
3. Check tests in `integration/` for usage examples

When in doubt, search the code. Comments are sparse but names are descriptive.
