# Testing Guide

## Simulator-Only Tests (No Game Required)

```bash
cd ~/development/sts_lightspeed

# Quick smoke test
python integration/run_tests.py --quick --no-game --seed 12345

# Run a specific scenario
python integration/run_tests.py --scenario integration/scenarios/ironclad/strike_combo.yaml --no-game
```

## Full Integration Tests (Requires Game)

Integration tests sync the simulator with the real Slay the Spire game via CommunicationMod.

### Prerequisites

1. **Mod Setup** - Install via Steam Workshop:
   - ModTheSpire (mod loader)
   - CommunicationMod (API for external control)
   - StSLib, BaseMod (dependencies)

2. **CommunicationMod Config** at `~/Library/Preferences/ModTheSpire/CommunicationMod/config.properties`:
   ```properties
   command=/Users/bensmith/.sts_testing/run_bridge.sh
   runAtGameStart=true
   ```

3. **Bridge Config** at `~/.sts_testing/config`:
   ```bash
   BRIDGE_PATH="/path/to/your/bridge.py"
   ```

### Running Integration Tests

```bash
# 1. Verify bridge config
cat ~/.sts_testing/config

# 2. Launch game with mods
open "~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/ModTheSpire.app"

# 3. Wait for game to load, then run
python integration/run_tests.py --quick --seed 12345
```

## Centralized Config: ~/.sts_testing/

```
~/.sts_testing/
├── config          # Edit BRIDGE_PATH to switch bridges
└── run_bridge.sh   # Wrapper script (don't edit)
```

**To switch between bridges:**
```bash
vim ~/.sts_testing/config
# Change BRIDGE_PATH="/path/to/your/bridge.py"
```

## Game Paths (Mac)

```
Game Root:     ~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/
Mods:          ~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/mods/
Preferences:   ~/Library/Preferences/ModTheSpire/
Saves:         ~/Library/Application Support/SlayTheSpire/
```

## Test Framework Structure

```
integration/
├── harness/           # Core test components
│   ├── game_controller.py   # CommunicationMod interface
│   └── bridge_lock.py       # Bridge synchronization
├── scenarios/         # YAML test scenarios
├── test_cases/        # Python test cases
├── run_tests.py       # Main test runner
└── config.yaml        # Test configuration
```

## Scenario Format

Scenarios are YAML files defining initial state and expected outcomes:

```yaml
name: "Strike Combo"
character: IRONCLAD
ascension: 0
seed: 12345
deck:
  - STRIKE
  - STRIKE
  - STRIKE
  - STRIKE
  - STRIKE
  - DEFEND
  - DEFEND
  - DEFEND
  - DEFEND
  - BASH
encounter: CULTIST
expected_actions:
  - play_card: STRIKE
  - end_turn
```

## Worktrees

This project uses git worktrees for feature development:

```bash
git worktree list
# - main: ~/development/sts_lightspeed
# - feature branches in .worktrees/
```
