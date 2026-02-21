# CLAUDE.md - sts_lightspeed Project

## Project Overview

sts_lightspeed is a high-performance C++ simulator for Slay the Spire, with Python bindings for RL training and testing. The project includes an integration testing framework that synchronizes the simulator with the real game via CommunicationMod.

## Directory Structure

```
sts_lightspeed/
├── src/                    # C++ source code
├── bindings/               # pybind11 Python bindings
├── build/                  # Build output (slaythespire.so)
├── integration/            # Integration testing framework
│   ├── harness/           # Core test components
│   ├── scenarios/         # YAML test scenarios
│   ├── test_cases/        # Python test cases
│   ├── run_tests.py       # Main test runner
│   └── config.yaml        # Test configuration
└── tests/
    └── integration/
        └── harness/        # Additional test utilities
```

## Testing Framework Configuration

### Centralized Config: ~/.sts_testing/

The testing framework uses a centralized configuration at `~/.sts_testing/`:

```
~/.sts_testing/
├── config          # Edit BRIDGE_PATH to switch bridges
└── run_bridge.sh   # Wrapper script (don't edit)
```

**To switch between different bridges:**
```bash
# Edit the config file
vim ~/.sts_testing/config

# Change BRIDGE_PATH to your desired bridge script
BRIDGE_PATH="/path/to/your/bridge.py"
```

### CommunicationMod Setup

CommunicationMod is configured via:
```
~/Library/Preferences/ModTheSpire/CommunicationMod/config.properties
```

The config should reference the wrapper script:
```properties
command=/Users/bensmith/.sts_testing/run_bridge.sh
runAtGameStart=true
```

## Steam/Steam Workshop Setup

### Installed Mods (via Steam Workshop)

1. **ModTheSpire** - Mod loader (required)
   - Location: `~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/mods/ModTheSpire*`

2. **CommunicationMod** - API for external control
   - Location: `~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/mods/CommunicationMod*`
   - Config: `~/Library/Preferences/ModTheSpire/CommunicationMod/config.properties`

3. **StSLib** - Required dependency for many mods
4. **BaseMod** - Required dependency for CommunicationMod

### Launching with Mods

```bash
# Launch via ModTheSpire (recommended)
open "~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/ModTheSpire.app"

# Or via Steam with mods enabled
# Steam will automatically use ModTheSpire if installed
```

### Game Paths (Mac)

```
Game Root:     ~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/
Mods:          ~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/mods/
Preferences:   ~/Library/Preferences/ModTheSpire/
Saves:         ~/Library/Application Support/SlayTheSpire/
```

## Running Tests

### Simulator-Only Tests (No Game Required)

```bash
cd ~/development/sts_lightspeed

# Quick smoke test
python integration/run_tests.py --quick --no-game --seed 12345

# Run a scenario
python integration/run_tests.py --scenario integration/scenarios/ironclad/strike_combo.yaml --no-game
```

### Full Integration Tests (Requires Game)

```bash
# 1. Ensure ~/.sts_testing/config points to correct bridge
cat ~/.sts_testing/config

# 2. Launch game with mods
open "~/Library/Application Support/Steam/steamapps/common/SlayTheSpire/ModTheSpire.app"

# 3. Wait for game to load, then run tests
python integration/run_tests.py --quick --seed 12345
```

## Worktrees

This project uses git worktrees for feature development:

```bash
# List worktrees
git worktree list

# Current worktrees:
# - main: ~/development/sts_lightspeed
# - feature-simulator-game-testing-framework: ~/development/sts_lightspeed/.worktrees/feature-simulator-game-testing-framework
```

## Building

```bash
cd ~/development/sts_lightspeed
cmake -B build -S .
cmake --build build
```

The Python module `slaythespire.cpython-314-darwin.so` will be in `build/`.
