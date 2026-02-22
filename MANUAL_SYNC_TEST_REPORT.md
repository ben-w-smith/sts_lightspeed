# Manual Sync Verification - Final Test Report

## Test Session Summary
**Date**: 2026-02-21
**Worktree**: `/Users/bensmith/development/sts_lightspeed/.worktrees/test-manual-sync`
**Branch**: `test/manual-sync-verification`

## Setup Completed
1. ✅ Copied `sync_orchestrator.py` to worktree
2. ✅ Copied `manual_sync_play.py` to worktree
3. ✅ Created automated test scripts:
   - `integration/test_manual_sync.py`
   - `integration/comprehensive_sync_test.py`
   - `integration/game_monitor.py`
4. ✅ Cleared bridge queue
5. ✅ Fixed card cost extraction bug in simulator_controller.py

## Issues Found

### Critical Issues

#### STS-COMM-001: CommunicationMod Bridge Command Processing
- **Severity**: Critical
- **Impact**: Cannot send commands to game automatically
- **Workaround**: Manual interaction with game UI
- **Worktree**: `.worktrees/fix-commmod-start`
- **Branch**: `fix/commmod-start-command`

#### STS-COMM-002: Start Command Not Working
- **Severity**: Critical
- **Impact**: Cannot start new game from main menu via bridge
- **Root Cause**: Same as STS-COMM-001
- **Workaround**: User must manually start game

### Major Issues

#### STS-RNG-001: Neow Event RNG Divergence
- **Severity**: Major
- **Impact**: Game and simulator show different Neow options with same seed
- **Example**: Game: "Enemies have 1 HP" vs Simulator: "Transform a card"
- **Result**: Game has 1 HP monsters, simulator has normal HP monsters
- **Worktree**: `.worktrees/fix-neow-sync`
- **Branch**: `fix/neow-rng-sync`

### Minor Issues

#### STS-SIM-001: Card Cost Extraction
- **Severity**: Minor (fixed)
- **Issue**: Deck card costs showing as -1
- **Fix**: Updated `simulator_controller.py` to properly access card attributes
- **Status**: Fixed in this worktree

## Test Results

### Initial State Comparison
```
Game:   Floor 1, HP 80/80, Jaw Worm HP 1/42
Sim:    Floor 1, HP 80/80, Monster HP 42/42
Result: DIVERGED (Neow bonus not applied in sim)
```

### Combat State Sync
```
Field         Game        Simulator   Match
-------------------------------------------
Floor         1           1           ✓
HP            80/80       80/80       ✓
Gold          99          99          ✓
Monster HP    1/42        42/42       ✗
Screen        combat      combat      ✓
```

## Files Created

### New Files
- `integration/harness/sync_orchestrator.py` - Deterministic sync orchestrator
- `integration/manual_sync_play.py` - Interactive sync play
- `integration/test_manual_sync.py` - Automated test script
- `integration/comprehensive_sync_test.py` - Comprehensive sync test
- `integration/game_monitor.py` - Game state monitor

### Issue Files
- `.worktrees/fix-commmod-start-issue.md`
- `.worktrees/fix-neow-sync/issue.md`

## Recommendations

1. **Fix CommunicationMod Bridge**: Implement polling-based command checking
2. **Sync After Neow**: Start sync testing after both game and sim complete Neow
3. **RNG Alignment**: Investigate RNG call differences during initialization
4. **State Injection**: Allow injecting Neow choices into simulator

## Next Steps
1. Fix STS-COMM-001 (bridge command processing)
2. Implement sync after Neow event
3. Test combat sync with matching states
4. Progress to first boss and verify all encounters

## Session Statistics
- Duration: ~20 minutes
- Tests run: 5
- Issues found: 4
- Issues fixed: 1
- Worktrees created: 3

## Learnings from Manual Sync Testing

### Why Real-Time Sync Failed

1. **Bridge Architecture**: The `communication_bridge.py` is *reactive*, not *proactive*. It only checks for commands after receiving state updates from CommunicationMod. This creates unavoidable race conditions.

2. **Command Processing Lag**: By the time a command is:
   - Read from game state → Decided → Written to command file → Processed by bridge
   The game state has often changed, making the command invalid.

3. **High Failure Rate**: Expecting 1 in 5-10 commands to fail, but actual rate was 1 in 1-2 due to timing issues.

### New Approach: Snapshot-Based Testing

Instead of real-time sync, use **snapshot comparison**:

```bash
# Capture game state at key points
python integration/snapshot_sync_test.py capture --name "post_neow"

# List captured snapshots
python integration/snapshot_sync_test.py list

# Compare snapshot with simulator (no time pressure)
python integration/snapshot_sync_test.py compare --name "post_neow"

# Test all snapshots
python integration/snapshot_sync_test.py test-all
```

### Benefits of Snapshot Approach

1. **No timing issues**: Compare states without race conditions
2. **Reproducible**: Same snapshot always produces same comparison
3. **Isolated testing**: Focus on specific state transitions
4. **Easier debugging**: Can analyze mismatches at leisure

### Recommended Workflow

1. **Play manually**: Control the game through CommunicationMod UI
2. **Capture at key points**: After Neow, after combat, at shops, etc.
3. **Compare offline**: Run snapshot comparisons when done playing
4. **Document divergences**: Create issues for systematic mismatches

### Snapshot Captured This Session

- `floor2_combat_reward` - Floor 2, HP 80/80, Gold 112, at reward screen

## Gameplay Recording System

### Overview

Instead of real-time sync, use passive recording:

1. **Record**: Play normally while recorder captures states
2. **Replay**: Run recordings through simulator
3. **Compare**: Verify alignment at each step

### Files Created

| File | Purpose |
|------|---------|
| `gameplay_recorder.py` | Passive recorder - watches game state |
| `recording_replayer.py` | Replays in simulator, compares states |
| `snapshot_sync_test.py` | Manual snapshot capture/comparison |

### Recommended Workflow

```bash
# Terminal 1: Start recording (before you start playing)
python integration/gameplay_recorder.py record --run-name "ironclad_1" --description "First test run"

# ... Play the game normally (die or complete, doesn't matter) ...

# Press Ctrl+C to stop recording

# Terminal: Replay and compare
python integration/recording_replayer.py replay --run-name "ironclad_1" --verbose

# Generate detailed report
python integration/recording_replayer.py report --run-name "ironclad_1" --output report.md
```

### Recommended: 5 Games

| Run | Goal | Coverage |
|-----|------|----------|
| 1-2 | Short (Act 1 death) | Early game, Neow, first combats |
| 3-4 | Medium (Act 2-3) | Mid-game, elites, shops, events |
| 5 | Long (if lucky) | Boss mechanics, late-game cards |

This yields ~200-300 testable state transitions.

## spirecomm-Based Auto-Sync (NEW - 2026-02-22)

### Overview

Uses the `spirecomm` library from ForgottenArbiter for reliable CommunicationMod integration.

**Key insight**: spirecomm's Coordinator is designed to be run BY CommunicationMod (via stdin/stdout), ensuring reliable command processing without race conditions.

### Files Created

| File | Purpose |
|------|---------|
| `integration/spirecomm_sync.py` | SyncAgent that plays both game and simulator |
| `integration/run_sync_test.py` | Entry point for CommunicationMod |
| `integration/auto_sync.py` | Recording replay and live sync |

### Quick Start

1. **Configure CommunicationMod** to use the sync agent:

```bash
# Edit your STS install directory's ModTheSpire.json
# OR set the command in CommunicationMod config

# Point to the sync agent:
python3 /Users/bensmith/development/sts_lightspeed/.worktrees/test-manual-sync/integration/run_sync_test.py --character IRONCLAD --ascension 0
```

2. **Launch Slay the Spire with ModTheSpire**

3. **The agent will**:
   - Start a new game automatically
   - Play both game and simulator in parallel
   - Log all divergences to `integration/sync_reports/`
   - Save detailed report when done

### Running a Sync Test

```bash
# With game running and CommunicationMod configured:
# The agent starts automatically when the game loads

# Check results:
ls integration/sync_reports/
cat integration/sync_reports/sync_report_*.json | jq '.divergences'
```

### What Gets Compared

| Field | Game | Simulator |
|-------|------|-----------|
| Floor | game_state.floor | gc.floor_num |
| HP | game_state.current_hp | gc.cur_hp |
| Max HP | game_state.max_hp | gc.max_hp |
| Gold | game_state.gold | gc.gold |

### Replay a Recording

```bash
# Replay a previously recorded game
python -m integration.auto_sync --replay integration/recordings/sync_test_5.json --verbose
```

### Architecture

```
CommunicationMod
       │
       ▼ (stdin/stdout)
┌─────────────────────┐
│  spirecomm_sync.py  │
│  (SyncAgent)        │
│                     │
│  ┌─────────────┐    │
│  │ Coordinator │────┼────▶ Game (via stdout)
│  └─────────────┘    │
│         │           │
│         ▼           │
│  ┌─────────────┐    │
│  │   Compare   │    │
│  │   States    │    │
│  └─────────────┘    │
│         │           │
│         ▼           │
│  ┌─────────────┐    │
│  │ Simulator   │    │
│  │ (sts module)│    │
│  └─────────────┘    │
└─────────────────────┘
```

### spirecomm Installation

```bash
# Install from GitHub (not on PyPI)
pip3 install --break-system-packages git+https://github.com/ForgottenArbiter/spirecomm.git
```

## Next Steps with spirecomm

1. ✅ spirecomm installed and working
2. ✅ SyncAgent created
3. ⏳ Test with real game
4. ⏳ Analyze first divergences
5. ⏳ Fix simulator issues iteratively
