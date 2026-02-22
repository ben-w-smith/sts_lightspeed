# Known Issues

This document tracks known bugs and limitations in the simulator that need investigation or fixes.

## Combat Bugs

### ISSUE-001: Dual Wield + Ritual Dagger Interaction
**Location:** `src/combat/BattleContext.cpp:4725`
**Severity:** Medium
**Status:** Open

**Description:**
When using Dual Wield on Ritual Dagger, the behavior is inconsistent:
- When there is no choice on which card to pick, the first one will change the card in the deck
- When there IS a choice on which card to pick, neither will change the card in the deck

**Expected Behavior:**
Dual Wield copies should consistently update the original card's stats when the copy is played.

**Notes:**
This may affect other cards with "on play" deck modifications.

---

### ISSUE-002: Exhume Card Selection Edge Case
**Location:** `src/combat/Actions.cpp:852`
**Severity:** Low
**Status:** Open

**Description:**
The Exhume action has a bug where the selected card cannot be Exhume itself. While this is intentional logic, there may be edge cases where the exhaust pile contains only Exhume cards or where the selection logic fails.

**Expected Behavior:**
Exhume should gracefully handle cases where no valid cards exist in the exhaust pile.

**Notes:**
Current workaround: Returns early if exhaust pile is empty or hand is full.

---

### ISSUE-003: Intangible Status vs Potion Damage
**Location:** `src/combat/Monster.cpp:477`
**Severity:** Low
**Status:** Open

**Description:**
The INTANGIBLE status check in `Monster::damage()` may not correctly handle potion damage. INTANGIBLE reduces all damage to 1, but potion damage mechanics might differ from the game.

**Expected Behavior:**
Verify that potion damage interacts with INTANGIBLE the same way as in the original game.

**Notes:**
Needs testing with Fire Potion, Explosion Potion, etc. against monsters with INTANGIBLE.

---

## Disabled Features

The following features are intentionally disabled pending implementation:

| Feature | Location | Constant |
|---------|----------|----------|
| Colosseum Event | `include/game/GameContext.h` | `disableColosseum` |
| Match and Keep | `include/game/GameContext.h` | `disableMatchAndKeep` |
| Prismatic Shard | `include/game/GameContext.h` | `disablePrismaticShard` |

---

## Build Issues

### Pre-existing Compilation Errors
Several pre-existing compilation errors exist in the codebase (not introduced by recent changes):

1. `BattleContext.cpp:2483` - `isEscaping` should be called as function
2. `BattleContext.cpp:2546` - `PS::EQUIV` doesn't exist (should be different status)
3. `BattleContext.cpp:2681` - `CardSelectInfo` constructor signature mismatch
4. `BattleContext.cpp:2682` - `InputState::SELECT_CARDS_HAND` doesn't exist
5. `BattleContext.cpp:2755` - `getCardFromPool` signature mismatch
6. `BattleContext.cpp:3253` - `PS::HEATSINK` should be `PS::HEATSINKS`

---

## Coverage Gaps

See the project audit for detailed test coverage gaps:
- Characters: Only Ironclad (25%)
- Cards: ~2% tested
- Relics: 0% tested
- Events: 0% tested
- Ascension: 0% tested

---

*Last updated: 2026-02-21*
*Generated from project audit*
