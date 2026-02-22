//
// Created by gamerpuppy on 7/4/2021.
//

#include "combat/BattleContext.h"
#include "game/GameContext.h"
#include "game/Game.h"

using namespace sts;

namespace sts {
    thread_local BattleContext *g_debug_bc;
}


// assume all bc fields have just been initialized by in class member initializers
void BattleContext::init(const GameContext &gc) {
    init(gc, gc.info.encounter);
}

void BattleContext::init(const GameContext &gc, MonsterEncounter encounterToInit) {
    undefinedBehaviorEvoked = false;
    haveUsedDiscoveryAction = false;
    seed = gc.seed;
    floorNum = gc.floorNum;
    encounter = encounterToInit;

    auto startRandom = Random(gc.seed+gc.floorNum);
    aiRng = startRandom;
    monsterHpRng = startRandom;
    shuffleRng = startRandom;
    cardRandomRng = startRandom;
    miscRng = gc.miscRng;
    potionRng = gc.potionRng;

    ascension = gc.ascension;
    outcome = Outcome::UNDECIDED;
    inputState = InputState::EXECUTING_ACTIONS;
    miscBits.reset();

    monsterTurnIdx = 6;
    skipMonsterTurn = false;
    turnHasEnded = false;
    isBattleOver = false;

    actionQueue.clear();
    cardQueue.clear();

    potionCount = gc.potionCount;
    potionCapacity = gc.potionCapacity;
    potions = gc.potions;

    player.curHp = gc.curHp;
    player.maxHp = gc.maxHp;
    player.gold = gc.gold;

    monsters.init(*this, encounterToInit);
    if (gc.map.burningEliteX == gc.curMapNodeX && gc.map.burningEliteY == gc.curMapNodeY) {
        monsters.applyEmeraldEliteBuff(*this, gc.map.burningEliteBuff, gc.act);
    }

    player.cardDrawPerTurn = 5;
    if (gc.hasRelic(R::SNECKO_EYE)) {
        player.cardDrawPerTurn += 2;
    }
    if (gc.relics.has(R::RING_OF_THE_SERPENT)) {
        player.cardDrawPerTurn += 1;
    }
    //addToBot(Actions::DrawCards(player.cardDrawPerTurn));

    cards.init(gc, *this);

    initRelics(gc);
    player.energy += player.energyPerTurn;

    executeActions();
}

// this doesnt apply powers in order, so if that matters in the future all relics will have to be sorted
void BattleContext::initRelics(const GameContext &gc) {
    player.relicBits0 = gc.relics.relicBits0;
    player.relicBits1 = gc.relics.relicBits1;

    fixed_list<RelicId, 4> atBattleStartPreDraw;
    fixed_list<RelicId, 8> atBattleStart;
    fixed_list<RelicId, 2> atTurnStartPostDraw;

    auto room = gc.curRoom;

    auto &p = player;

    for (const auto &r : gc.relics.relics) {
        switch (r.id) {

            case R::HOLY_WATER:
            case R::NINJA_SCROLL:
            case R::PURE_WATER:
            case R::TOOLBOX:
                atBattleStartPreDraw.push_back(r.id);
                break;

            case R::BAG_OF_MARBLES:
            case R::BAG_OF_PREPARATION:
            case R::CLOCKWORK_SOUVENIR:
            case R::GREMLIN_VISAGE:
            case R::RED_MASK:
            case R::RING_OF_THE_SNAKE:
            case R::TWISTED_FUNNEL:
                atBattleStart.push_back(r.id);
                break;

            case R::MARK_OF_PAIN:
                ++p.energyPerTurn;
                atBattleStart.push_back(r.id);
                break;

            case R::GAMBLING_CHIP:
            case R::WARPED_TONGS:
                atTurnStartPostDraw.push_back(r.id);
                break;

            case R::AKABEKO:
                p.buff<PS::VIGOR>(8);
                break;

            case R::BRIMSTONE:
                p.buff<PS::STRENGTH>(2);
                for (int i = 0; i < monsters.monsterCount; ++i) {
                    Monster &m = monsters.arr[i];
                    if (m.isTargetable()) {
                        m.buff<MS::STRENGTH>(1);
                    }
                }
                break;

            case R::ECTOPLASM:
                p.energyPerTurn++;
                break;

            case R::ENCHIRIDION: {
                const auto cardId = getTrulyRandomCardInCombat(cardRandomRng, p.cc, CardType::POWER);
                CardInstance c(cardId);
                c.setCostForTurn(0);
                addToBot( Actions::MakeTempCardInHand(c) );
                break;
            }

            case R::HAPPY_FLOWER:
                player.happyFlowerCounter = r.data + 1;
                if (player.happyFlowerCounter == 3) {
                    ++player.energy;
                    player.happyFlowerCounter = 0;
                }
                break;

            case R::INCENSE_BURNER:
                p.incenseBurnerCounter = r.data;
                if (++p.incenseBurnerCounter == 6) {
                    p.incenseBurnerCounter = 0;
                    p.buff<PS::INTANGIBLE>(1);
                }
                break;

            case R::INK_BOTTLE:
                p.inkBottleCounter = r.data;
                break;

            case R::INSERTER:
                if (r.data) {
                    p.inserterCounter = 0;
                    p.increaseOrbSlots(1);
                } else {
                    p.inserterCounter = 1;
                }
                break;

            case R::LIZARD_TAIL:
                p.setHasRelic<R::LIZARD_TAIL>(r.data);
                break;

            case R::NUNCHAKU:
                p.nunchakuCounter = r.data;
                break;

            case R::OMAMORI:
                p.setHasRelic<R::OMAMORI>(r.data);
                break;

            case R::PEN_NIB:
                if (r.data == 9) {
                    p.buff<PS::PEN_NIB>(1);
                    p.penNibCounter = -1;
                } else {
                    p.penNibCounter = r.data;
                }
                break;

            case R::PHILOSOPHERS_STONE:
                for (int i = 0; i < monsters.monsterCount; ++i) {
                    auto &m = monsters.arr[i];
                    m.buff<MS::STRENGTH>(1);
                }
                p.energyPerTurn++;
                break;

            case R::RUNIC_DOME:
                p.energyPerTurn++;
                break;

            case R::SNECKO_EYE:
                p.debuff<PS::CONFUSED>(1);
                break;

            case R::SOZU:
                p.energyPerTurn++;
                break;

            case R::SUNDIAL:
                p.sundialCounter = r.data;
                break;

            case R::VELVET_CHOKER:
                p.energyPerTurn++;
                break;

            case R::ANCHOR:
                p.block += 10;
                break;

            case R::ANCIENT_TEA_SET:
                if (gc.lastRoom == Room::REST) {
                    p.gainEnergy(2);
                }
                break;

            case R::BLOOD_VIAL:
                p.heal(2); // todo not correct
                break;

            case R::BRONZE_SCALES:
                p.buff<PS::THORNS>(3);
                break;

            case R::BUSTED_CROWN:
                p.energyPerTurn++;
                break;

            case R::COFFEE_DRIPPER:
                p.energyPerTurn++;
                break;

            case R::CRACKED_CORE:
                p.channelOrb(*this, Orb::LIGHTNING);
                break;

            case R::CURSED_KEY:
                p.energyPerTurn++;
                break;

            case R::DAMARU:
                p.buff<PS::MANTRA>(1);
                break;

            case R::DATA_DISK:
                p.buff<PS::FOCUS>(1);
                break;

            case R::DU_VU_DOLL:
                p.buff<PS::STRENGTH>(r.data);
                break;

            case R::FOSSILIZED_HELIX:
                p.buff<PS::BUFFER>(1);
                break;

            case R::FUSION_HAMMER:
                p.energyPerTurn++;
                break;

            case R::GIRYA:
                p.buff<PS::STRENGTH>(r.data);
                break;

            case R::LANTERN:
                p.gainEnergy(1);
                break;

            case R::MUTAGENIC_STRENGTH: // this appears to be applied before clockwork if it was acquired first
                p.buff<PS::STRENGTH>(3);
                p.debuff<PS::LOSE_STRENGTH>(3);
                break;

            case R::NEOWS_LAMENT: // remember to decrement somewhere else
                if (r.data > 0) {
                    for (int i = 0; i < monsters.monsterCount; ++i) {
                        Monster &m = monsters.arr[i];
                        m.curHp = 1;
                    }
                }
                break;

            case R::NUCLEAR_BATTERY:
                p.channelOrb(*this, Orb::PLASMA);
                break;

            case R::ODDLY_SMOOTH_STONE:
                p.buff<PS::DEXTERITY>(1);
                break;

            case R::PANTOGRAPH:
                if (room == Room::BOSS) {
                    p.heal(25);
                }
                break;

            case R::PRESERVED_INSECT:
                if (room == Room::ELITE) {
                    for (int i = 0; i < monsters.monsterCount; ++i) {
                        Monster &m = monsters.arr[i];
                        m.curHp = static_cast<int>(m.maxHp * .75);
                    }
                }
                break;

            case R::RING_OF_THE_SERPENT:
                // now handled in battlecontext init
//                p.cardDrawPerTurn++;
                break;

            case R::RUNIC_CAPACITOR:
                p.increaseOrbSlots(3);
                break;

            case R::SLAVERS_COLLAR:
                if (room == Room::ELITE || room == Room::BOSS) { // todo this needs to be set by eliteTrigger maybe?
                    p.energyPerTurn++;
                }
                break;

            case R::SLING_OF_COURAGE:
                if (room == Room::ELITE) {
                    p.buff<PS::STRENGTH>(2);
                }
                break;

            case R::SYMBIOTIC_VIRUS:
                p.channelOrb(*this, Orb::DARK);
                break;

            case R::TEARDROP_LOCKET:
                p.changeStance<Stance::CALM>();
                break;

            case R::THREAD_AND_NEEDLE:
                p.buff<PS::PLATED_ARMOR>(4);
                break;

            case R::VAJRA:
                p.buff<PS::STRENGTH>(1);
                break;

            default:
                break;
        }
    }

    // todo maybe move this to proper place -nvm drawCards is added below this
    for (auto r : atBattleStartPreDraw) {
        switch (r) {
            case R::HOLY_WATER:
                addToBot(Actions::MakeTempCardInHand(CardId::MIRACLE, false, 3));
                break;

            case R::NINJA_SCROLL:
                addToBot(Actions::MakeTempCardInHand(CardId::SHIV, false, 3) );
                break;

            case R::PURE_WATER:
                addToBot(Actions::MakeTempCardInHand(CardId::MIRACLE, false, 1));
                break;

            case R::TOOLBOX:
                addToBot( Actions::ToolboxAction() );
                break;

            default:
                break;
        }
    }

    addToBot( Actions::DrawCards(p.cardDrawPerTurn) );

    for (auto r : atBattleStart) {
        switch (r) {
            case R::BAG_OF_MARBLES:
                addToBot( Actions::DebuffAllEnemy<MS::VULNERABLE>(1, false) );
                break;

            case R::BAG_OF_PREPARATION:
                addToBot( Actions::DrawCards(2) );
                break;

            case R::CLOCKWORK_SOUVENIR:
                addToBot( Actions::BuffPlayer<PS::ARTIFACT>(1) );
                break;

            case R::GREMLIN_VISAGE:
                p.debuff<PS::WEAK>(1);
                break;

            case R::MARK_OF_PAIN:
                addToBot( Actions::MakeTempCardInDrawPile( {CardId::WOUND}, 2, true) );
                break;

            case R::RED_MASK:
                addToBot( Actions::DebuffAllEnemy<MS::WEAK>(1) );
                break;

            case R::RING_OF_THE_SNAKE:
                addToBot( Actions::DrawCards(2) );
                break;

            case R::TWISTED_FUNNEL:
                addToBot( Actions::DebuffAllEnemy<MS::POISON>(4) );
                break;

            default:
                break;
        }
    }

    if (gc.hasRelic(R::MERCURY_HOURGLASS)) {
        addToBot( Actions::DamageAllEnemy(3) );
    }

    if (gc.hasRelic(R::RED_SKULL) && gc.curHp <= gc.maxHp / 2) {
        p.buff<PS::STRENGTH>(3);
    }

    for (auto r : atTurnStartPostDraw) {
        switch (r) {
            case R::GAMBLING_CHIP:
                addToBot( Actions::GambleAction() );
                break;

            case R::WARPED_TONGS:
                addToBot( Actions::UpgradeRandomCardAction() );
                break;

            default:
                break;
        }
    }

    // ** OnStartOfTurn ** ORBS todo
    //RelicCables -> OnStartOfTurn again for orb 0
}

void BattleContext::exitBattle(GameContext &g) const {
    // do this first so that darkstone periapt is overridden by curHp and maxHp are set afterwards
    const auto &m = monsters.arr[0];
    if (m.id == MonsterId::WRITHING_MASS && m.miscInfo) {
        if (player.hasRelic<R::OMAMORI>()) {
            --g.relics.getRelicValueRef(RelicId::OMAMORI);
        } else {
            g.deck.obtain(g, CardId::PARASITE);

        }
    }

    g.potionCount = potionCount;
    g.potions = potions;

    // not sure its really necessary to sync these every time, (i believe colosseum is the only time two battles occur on the same floor)
    g.aiRng = aiRng;
    g.cardRandomRng = cardRandomRng;
    g.miscRng = miscRng;
    g.monsterHpRng = monsterHpRng;
    g.potionRng = potionRng;
    g.shuffleRng = shuffleRng;

    g.curHp = player.curHp;
    g.maxHp = player.maxHp;
    g.gold = player.gold;


    // todo lesson learned bitset

    // relic counters
    updateRelicsOnExit(g);

    // cards
    updateCardsOnExit(g.deck);

    g.info.stolenGold = 0;
    if (requiresStolenGoldCheck()) {
        for (int i = 0; i < monsters.monsterCount; ++i) {
            const auto &m = monsters.arr[i];

            const bool canHaveStolenGold = m.id == MonsterId::LOOTER || m.id == MonsterId::MUGGER;
            const bool escaped = m.curHp > 0 && (m.moveHistory[0] == MMID::LOOTER_ESCAPE ||
                                                 m.moveHistory[0] == MMID::MUGGER_ESCAPE);

            if (canHaveStolenGold && !escaped) {
                g.info.stolenGold += m.miscInfo;
            }
        }
    }

    if (outcome == Outcome::PLAYER_LOSS) {
        g.outcome = GameOutcome::PLAYER_LOSS;
    } else {
        // player victory
        g.regainControl();
    }

    BattleContext::sum += g.curHp + g.maxHp + g.gold + g.act
            + g.ascension + g.floorNum + potionRng.counter + cardRandomRng.counter;
}

void BattleContext::updateRelicsOnExit(GameContext &g) const {
    for (auto &r : g.relics.relics) {
        switch (r.id) {
            case RelicId::HAPPY_FLOWER:
                r.data = player.happyFlowerCounter;
                break;

            case RelicId::INCENSE_BURNER:
                r.data = player.incenseBurnerCounter;
                break;

            case RelicId::INK_BOTTLE:
                r.data = player.inkBottleCounter;
                break;

            case RelicId::INSERTER:
                r.data = player.inserterCounter;
                break;

            case RelicId::NEOWS_LAMENT:
                if (r.data > 0) {
                    --r.data;
                }
                break;

            case RelicId::NUNCHAKU:
                r.data = player.nunchakuCounter;
                break;

            case RelicId::PEN_NIB:
                // possible bug
                if (player.penNibCounter == -1) {
                    r.data = 9;
                } else {
                    r.data = player.penNibCounter;
                }
                break;

            case RelicId::SUNDIAL:
                r.data = player.sundialCounter;
                break;

            case RelicId::LIZARD_TAIL:
                if (!player.hasRelic<R::LIZARD_TAIL>()) {
                    r.data = 0;
                }
                break;

            case RelicId::BURNING_BLOOD:
                if (outcome == Outcome::PLAYER_VICTORY) {
                    g.playerHeal(6);
                }
                break;

            case RelicId::BLACK_BLOOD:
                if (outcome == Outcome::PLAYER_VICTORY) {
                    g.playerHeal(12);
                }
                break;

            case RelicId::MEAT_ON_THE_BONE:
                if (outcome == Outcome::PLAYER_VICTORY && g.curHp <= g.maxHp / 2) {
                    g.playerHeal(12);
                }
                break;

            default:
                break;
        }

    }
}

void cardOnExit(const CardInstance &c, Deck &deck) {
    const auto isDeckCard = c.uniqueId < deck.size();
    if (!isDeckCard) {
        return;
    }

    const auto deckIdx = c.uniqueId;
    auto &deckCard = deck.cards[deckIdx];

    if (c.getId() == CardId::RITUAL_DAGGER) {
        deckCard.misc = c.specialData;
    }

    // todo
//    if (c.getId() == CardId::GENETIC_ALGORITHM) {
//        deckCard.misc = c.specialData;
//    }
}

void BattleContext::updateCardsOnExit(Deck &deck) const {
    for (const auto &c : cards.drawPile) {
        cardOnExit(c, deck);
    }

    for (const auto &c : cards.discardPile) {
        cardOnExit(c, deck);
    }

    for (const auto &c : cards.exhaustPile) {
        cardOnExit(c, deck);
    }

    for (int i = 0; i < cards.cardsInHand; ++i) {
        cardOnExit(cards.hand[i], deck);
    }

//    if (curCardQueueItem)

}


void BattleContext::setRequiresStolenGoldCheck(bool value) {
    miscBits.set(0, value);
}

bool BattleContext::requiresStolenGoldCheck() const {
    return miscBits.test(0);
}

int BattleContext::getMonsterTurnNumber() const {
    return turn+1; // todo;
}

void BattleContext::setState(InputState s) {
    inputState = s;
}

void BattleContext::addToTop(const Action &a) {
    actionQueue.pushFront(a);
}

void BattleContext::addToBot(const Action &a) {
    actionQueue.pushBack(a);
}

// todo remove or replace other method that does this
void BattleContext::addToTopCard(CardQueueItem item) {
    cardQueue.pushFront(item);
}

void BattleContext::addToBotCard(CardQueueItem item) {
    cardQueue.pushBack(item);
}

void BattleContext::checkCombat() {
    if (outcome == Outcome::PLAYER_VICTORY) {
        clearPostCombatActions();
    }
}

void BattleContext::clearPostCombatActions() {
    // todo?
    cleanCardQueue(); // this is actually done when monsters are damaged but we can do here?
//    actionQueue.clearOnCombatVictory();

    int curIdx = actionQueue.front;
    int placeIdx = actionQueue.front;

    int oldsize = actionQueue.size;
    for (int i = 0; i < oldsize; ++i) {
        if (curIdx >= actionQueue.getCapacity()) {
            curIdx = 0;
        }
        const bool shouldClear = actionQueue.bits[curIdx];

        if (shouldClear) {
            --actionQueue.size;
        } else {
            if (placeIdx >= actionQueue.getCapacity()) {
                placeIdx = 0;
            }

            actionQueue.arr[placeIdx] = actionQueue.arr[curIdx];
            actionQueue.bits[placeIdx] = actionQueue.bits[curIdx];
            ++placeIdx;
        }
        ++curIdx;
    }
}

void BattleContext::cleanCardQueue() {
    // todo
    // not sure where this matters, as we don't queue more than 1 item at a time in the hand
}

bool BattleContext::isCardPlayAllowed() const {
    if (player.hasRelic<R::VELVET_CHOKER>() && player.cardsPlayedThisTurn >= 6) {
        return false;
    }

    if (cards.handNormalityCount && player.cardsPlayedThisTurn >= 3) {
        return false;
    }

    return true;
}

void BattleContext::executeActions() {
    // todo find a place for checking where card queue is empty and player doesn't have control for calling onEndingTurn
    ++sum;
    g_debug_bc = this;

    while (true)
    {
        if (++loopCount > 1000000 || monsters.monstersAlive < 0 || turn > 500) {
            // something went wrong
            if (turn > 500) {
                outcome = Outcome::PLAYER_LOSS;
                break;
            }

            std::cerr << seed << std::endl;
            std::cout << *this << '\n';
            assert(false);
        }

        if (inputState != InputState::EXECUTING_ACTIONS) {
            break;
        }

        if (outcome == Outcome::PLAYER_LOSS) {
            break;
        }

        if (!actionQueue.isEmpty()) {
            // do a action
            auto a = std::move(actionQueue.popFront());
            a(*this);
            continue;
        }

        if (outcome != Outcome::UNDECIDED) {
            break;
        }

        if (!cardQueue.isEmpty()) {
            // play a card queue item
            auto item = cardQueue.popFront();
            playCardQueueItem(item);
            continue;
        }

        // can't win check
        if (cards.cardsInHand + cards.discardPile.size() + cards.drawPile.size() == 0) {
            bool hasDamageWithoutCards = player.hasStatus<PS::OMEGA>() ||
                    player.hasStatus<PS::THORNS>() ||
                    player.bomb1 ||
                    player.bomb2 ||
                    player.bomb3;

            if (!hasDamageWithoutCards && monsters.arr[0].id != MonsterId::TRANSIENT) {
                outcome = Outcome::PLAYER_LOSS;
                break;
            }
        }

        if (outcome != Outcome::UNDECIDED) {
            break;
        }

        if (monsterTurnIdx < monsters.monsterCount) {
            // do a monster turn
            monsters.doMonsterTurn(*this);
            continue;
        }
        monsters.skipTurn.reset();

        if (outcome != Outcome::UNDECIDED) {
            break;
        }

        if (turnHasEnded) {
            // after all monster turns
            afterMonsterTurns();
            continue;

        }

        if (endTurnQueued) {
            endTurnQueued = false;
            onTurnEnding();
            continue;

        }

        if (player.hasRelic<R::UNCEASING_TOP>()) {
            // turn cannot have ended here
#ifdef sts_asserts
            assert(!endTurnQueued);
            assert(actionQueue.isEmpty());
            assert(cardQueue.isEmpty());
#endif

            if (cards.cardsInHand == 0) {
                drawCards(1);
            }
        }

        setState(InputState::PLAYER_NORMAL);
        break;
    }
}

void BattleContext::playCardQueueItem(CardQueueItem playItem) {
    // if c is null callEndOfTurnActions()
    // if cardQueueSize is 1 and carditem is endTurnAutoplay diable unceasing top

    curCardQueueItem = playItem;
    auto &item = curCardQueueItem;
    auto &c = item.card;

    if (item.isEndTurn) {
        // the game removes this card from limbo - don't think necessary
        callEndOfTurnActions();
        return;
    }


    // if cardQueueItem random target, assign a target
    if (item.randomTarget) {
        item.target = monsters.getRandomMonsterIdx(cardRandomRng);
    }

//    bool canPlayCard = false; // not really sure what this is used for
    const bool canUseCard = item.purgeOnUse || (item.triggerOnUse && c.canUse(*this, item.target, item.autoplay) && (!c.requiresTarget() || monsters.arr[item.target].isTargetable()));
    if (canUseCard) { // not sure if this is correct,
//        canPlayCard = true; // what is this for......

        if (c.isFreeToPlay(*this)) { // what the fuck
            c.freeToPlayOnce = true;
        }

        if (c.requiresTarget()) {
            player.lastTargetedMonster = item.target;
        }

        if (!c.requiresTarget() || monsters.arr[item.target].isTargetable()) { // this is redundant right???? -> no i think echo form abilities can queue a card with invalid target
            useCard();
        }

    }

    if (!item.triggerOnUse) {
        useNoTriggerCard(); // for burn, decay, doubt, regret and shame,
    }
}

void BattleContext::useCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    item.exhaustOnUse |= c.doesExhaust();
    ++player.cardsPlayedThisTurn;

    switch (c.getType()) {
        case CardType::ATTACK:
            useAttackCard();
            onUseAttackCard();
            break;

        case CardType::SKILL:
            useSkillCard();
            onUseSkillCard();
            if (player.hasStatus<PS::CORRUPTION>()) {
                item.exhaustOnUse = true;
            }
            break;

        case CardType::POWER:
            usePowerCard();
            onUsePowerCard();
            break;

        case CardType::STATUS:
        case CardType::CURSE:
            onUseStatusOrCurseCard();
            break;

        default:
            // unreachable
            break;
    }

    addToBot(Actions::OnAfterCardUsed());
    triggerOnOtherCardPlayed(c);

    if (!item.purgeOnUse) { // todo change to checking the card queue item
        cards.removeFromHandById(c.uniqueId);
        if (c.costForTurn > 0 && !c.isFreeToPlay(*this) && !item.autoplay && !(player.hasStatus<PS::CORRUPTION>() && c.getType() == CardType::SKILL)) {
            player.useEnergy(c.costForTurn);
        }
    }
}

void BattleContext::useNoTriggerCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    switch (c.id) {
        case CardId::BURN:
            addToTop( Actions::DamagePlayer(c.isUpgraded() ? 4 : 2, true));
            break;

        case CardId::DECAY:
            addToTop( Actions::DamagePlayer(2, true));
            break;

        case CardId::DOUBT:
            player.debuff<PS::WEAK>(1, true);
            break;

        case CardId::REGRET:
            addToTop( Actions::PlayerLoseHp(item.regretCardCount, true));
            break;

        case CardId::SHAME:
            // todo this is fixed just test -> this and doubt are bugged if you are already weak i think. because the apply power action does not create a new power and justapplied is not set to true
            player.debuff<PS::FRAIL>(1, true);
            break;


        default:
            // this can actually be called on any card now because of time warp power

//#ifdef sts_asserts
//            assert(false);
//#endif // sts_asserts
            break;
    }

    cards.removeFromHandById(c.uniqueId);
    addToBot(Actions::DiscardNoTriggerCard()); // todo what if havoc plays one of these
}

void BattleContext::useAttackCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    const auto t = item.target;
    const bool up = c.isUpgraded();

    // todo test vigor with multi attacks and necro/double tap
    switch (c.getId()) {
        case CardId::STRIKE_RED:
        case CardId::STRIKE_BLUE:
        case CardId::STRIKE_GREEN:
        case CardId::STRIKE_PURPLE: {
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 9 : 6)) );
            break;
        }

        case CardId::ANGER:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 8 : 6)) );
            addToBot( Actions::MakeTempCardInDiscard( CardInstance(CardId::ANGER, up), 1) );
            break;

        case CardId::BASH:
            // technically calculate attack damage is called first, keep note if we optimize addToBot later
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 10 : 8)) );
            addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(t, up ? 3 : 2, false) );
            break;

        case CardId::BITE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 8 : 7)) );
            addToBot( Actions::HealPlayer(up ? 3 : 2) );
            break;

        case CardId::BODY_SLAM:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, player.block)) );
            break;

        case CardId::BLOOD_FOR_BLOOD:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 22 : 18)) );
            break;

        case CardId::BLUDGEON:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 42 : 32)) );
            break;

        case CardId::CARNAGE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 28 : 20)) );
            break;

        case CardId::CLASH:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 18 : 14)) );
            break;

        case CardId::CLEAVE:  {
            int baseDamage = (up ? 11 : 8) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::AttackAllEnemy(baseDamage) );
            break;
        }

        case CardId::CLOTHESLINE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 14 : 12)) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 3 : 2, false) );
            break;

        case CardId::DRAMATIC_ENTRANCE: {
            int baseDamage = (up ? 12 : 8) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::AttackAllEnemy(baseDamage) );
            break;
        }

        case CardId::DROPKICK:
            addToBot( Actions::DropkickAction(t) );
            break;

        case CardId::FEED:
            addToBot( Actions::FeedAction(t, calculateCardDamage(c, t, up ? 12 : 10), up) );
            break;

        case CardId::FIEND_FIRE:
            addToBot( Actions::FiendFireAction(t, calculateCardDamage(c, t, up ? 10 : 7)) );
            break;

        case CardId::FLASH_OF_STEEL:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 6 : 3)) );
            addToBot( Actions::DrawCards(1) );
            break;

        case CardId::HAND_OF_GREED:
            addToBot( Actions::HandOfGreedAction(t, calculateCardDamage(c, t, up ? 25 : 20), up) );
            break;

        case CardId::HEADBUTT:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 12 : 9)) );
            addToBot( Actions::HeadbuttAction() );
            break;

        case CardId::HEAVY_BLADE: {
            const int dmg1 = 14 + ((up ? 4 : 2) * player.getStatus<PS::STRENGTH>());
            const int dmg2 = calculateCardDamage(c, t, dmg1);
            addToBot( Actions::AttackEnemy(t, dmg2) );
            break;
        }

        case CardId::HEMOKINESIS:
            //  attack enemy should recalculate damage, because we can lose hp and therefore gain strength before the dmg, need to test
           // actually no i dont think that is true ^^
            addToBot( Actions::PlayerLoseHp(2, true) );
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 20 : 15)) );
            break;

        case CardId::IMMOLATE: {
            int baseDamage = (up ? 28 : 21) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::AttackAllEnemy(baseDamage) );
            addToBot( Actions::MakeTempCardInDiscard({CardId::BURN}, 1) );
            break;
        }

        case CardId::IRON_WAVE: {
            addToBot( Actions::GainBlock(calculateCardBlock(calculateCardBlock(up  ? 7 : 5))) );
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 7 : 5)) );
            break;
        }

        case CardId::MIND_BLAST: {
            const auto damage = calculateCardDamage(c, t, static_cast<int>(cards.drawPile.size()));
            addToBot( Actions::AttackEnemy(t, damage) );
            break;
        }

        case CardId::PERFECTED_STRIKE: {
            // hack because we calculate strikeCount while non purge cards are still in hand.
            const int strikeDmg = cards.strikeCount * (up ? 3 : 2);
            const int baseDamage = 6 + strikeDmg;
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, baseDamage)) );
            break;
        }

        case CardId::POMMEL_STRIKE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 10 : 9)) );
            addToBot( Actions::DrawCards(up  ? 2 : 1) );
            break;

        case CardId::PUMMEL: {
            const auto attackCount = up ? 5 : 4;
            const auto damage = calculateCardDamage(c, t, 2);
            for (int i = 0; i < attackCount; ++i) {
                addToBot( Actions::AttackEnemy(t, damage) );
            }
            break;
        }

        case CardId::RAMPAGE: { // todo doubled card damage is changed by the first
            const int damage = calculateCardDamage(c, t, 8+c.specialData);
            addToBot( Actions::AttackEnemy(t, damage) );

            if (item.purgeOnUse) {
                cards.findAndUpgradeSpecialData(c.uniqueId, up ? 8 : 5);
            }
            c.specialData += up ? 8 : 5;

            break;
        }

        case CardId::REAPER: {
            const auto baseDamage = (up ? 5 : 4) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::ReaperAction(baseDamage) );
            break;
        }

        case CardId::RECKLESS_CHARGE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 10 : 7)) );
            addToBot( Actions::MakeTempCardInDrawPile({CardId::DAZED}, 1, true) );
            break;

        case CardId::RITUAL_DAGGER:
            addToBot( Actions::RitualDaggerAction(t, calculateCardDamage(c, t, c.specialData)) );
            break;

        case CardId::SEARING_BLOW: {
            const int n = c.getUpgradeCount();
            const int baseDmg = n * (n+7) / 2 + 12;
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, baseDmg)) );
            break;
        }

        case CardId::SEVER_SOUL: // another example of damage being calculated after an action, maybe need a new action to calculate damage later...
            addToBot( Actions::SeverSoulExhaustAction() );
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 22 : 16)) );
            break;

        case CardId::SWIFT_STRIKE:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 10 : 7)) );
            break;

        case CardId::SWORD_BOOMERANG:
            for (int i = 0; i < (up ? 4 : 3); ++i) {
                addToBot(Actions::SwordBoomerangAction(3+player.getStatus<PS::VIGOR>())); // vigor is removed afterwards so this is a necessary (maybe not 100% accurate) hack
            }
            break;

        case CardId::THUNDERCLAP: {
            int baseDamage = (up ? 7 : 4) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::AttackAllEnemy(baseDamage));
            addToBot( Actions::DebuffAllEnemy<MS::VULNERABLE>(1, false) );
            break;
        }

        case CardId::TWIN_STRIKE: { // todo test with breaking block on first hit and drill relic
            const int dmg = calculateCardDamage(c, t, up ? 7 : 5);
            addToBot(Actions::AttackEnemy(t, dmg));
            addToBot(Actions::AttackEnemy(t, dmg));
            break;
        }

        case CardId::UPPERCUT:
            addToBot( Actions::AttackEnemy(t, calculateCardDamage(c, t, 13)) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false) );
            addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(t, up ? 2 : 1, false) );
            break;

        case CardId::WHIRLWIND: {
            if (!item.ignoreEnergyTotal && player.energy < item.energyOnUse) {
                item.energyOnUse = player.energy;
            }
            const auto baseDamage = (up ? 8 : 5) + player.getStatus<PS::VIGOR>();
            addToBot( Actions::WhirlwindAction(baseDamage, item.energyOnUse, !(item.freeToPlay || c.freeToPlayOnce)));
            break;
        }

        case CardId::WILD_STRIKE:
            addToBot(Actions::AttackEnemy(t, calculateCardDamage(c, t, up ? 17 : 12)));
            addToBot( Actions::MakeTempCardInDrawPile( CardInstance(CardId::WOUND), 1, true) );
            break;


        // ********************* SILENT ATTACKS *********************

        case CardId::ALL_OUT_ATTACK: {
            const int dmg = calculateCardDamage(c, -1, up ? 14 : 10);
            addToBot( Actions::AttackAllEnemy(dmg) );
            addToBot( Actions::DiscardAction(1, true, false, false) );
            break;
        }

        case CardId::BANE: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                if (b.monsters.arr[t].hasStatus<MS::POISON>()) {
                    b.addToTop( Actions::AttackEnemy(t, dmg) );
                }
            }) );
            break;
        }
        
        case CardId::CHOKE: {
            const int dmg = calculateCardDamage(c, t, up ? 17 : 12);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::CHOKED>(t, up ? 5 : 3, false) );
            break;
        }

        case CardId::DAGGER_SPRAY: {
            const int dmg = calculateCardDamage(c, -1, up ? 6 : 4);
            addToBot( Actions::AttackAllEnemy(dmg) );
            addToBot( Actions::AttackAllEnemy(dmg) );
            break;
        }

        case CardId::DAGGER_THROW: {
            const int dmg = calculateCardDamage(c, t, up ? 12 : 9);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DrawCards(1) );
            addToBot( Actions::DiscardAction(1, false, false, false) );
            break;
        }

        case CardId::DASH: {
            const int b = calculateCardBlock(up ? 13 : 10);
            const int d = calculateCardDamage(c, t, up ? 13 : 10);
            addToBot( Actions::GainBlock(b) );
            addToBot( Actions::AttackEnemy(t, d) );
            break;
        }

        case CardId::DIE_DIE_DIE: {
            const int dmg = calculateCardDamage(c, -1, up ? 17 : 13);
            addToBot( Actions::AttackAllEnemy(dmg) );
            break;
        }

        case CardId::ENDLESS_AGONY: {
            const int dmg = calculateCardDamage(c, t, up ? 6 : 4);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::EVISCERATE: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::FINISHER: {
            const int dmg = calculateCardDamage(c, t, up ? 8 : 6);
            int count = player.cardsPlayedThisTurn; 
            for (int i=0; i<count; ++i) { // actually should only be attacks played. Needs to track attack count, but this works for now. 
               addToBot( Actions::AttackEnemy(t, dmg) );
            }
            break;
        }

        case CardId::FLECHETTES: {
            const int dmg = calculateCardDamage(c, t, up ? 6 : 4);
            addToBot( Action([&](BattleContext &b) {
                int count = 0;
                for (int i=0; i<b.cards.cardsInHand; ++i) {
                    if (b.cards.hand[i].getType() == CardType::SKILL) count++;
                }
                for (int i=0; i<count; ++i) {
                    b.addToTop( Actions::AttackEnemy(t, dmg) );
                }
            }) );
            break;
        }

        case CardId::FLYING_KNEE: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::BuffPlayer<PS::ENERGIZED>(1) );
            break;
        }

        case CardId::GLASS_KNIFE: {
            int d = c.misc == 0 ? (up ? 12 : 8) : c.misc;
            if (c.misc == 0) c.misc = d;
            const int dmg = calculateCardDamage(c, t, c.misc);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                for(int i=0; i<b.cards.cardsInHand; ++i) {
                    if (b.cards.hand[i].uniqueId == c.uniqueId) {
                        b.cards.hand[i].misc -= 2;
                    }
                }
            }) );
            break;
        }

        case CardId::GRAND_FINALE: {
            const int dmg = calculateCardDamage(c, -1, up ? 60 : 50);
            addToBot( Actions::AttackAllEnemy(dmg) );
            break;
        }

        case CardId::HEEL_HOOK: {
            const int dmg = calculateCardDamage(c, t, up ? 8 : 5);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                if (b.monsters.arr[t].hasStatus<MS::WEAK>()) {
                    b.addToTop( Actions::DrawCards(1) );
                    b.addToTop( Actions::GainEnergy(1) );
                }
            }) );
            break;
        }

        case CardId::MASTERFUL_STAB: {
            const int dmg = calculateCardDamage(c, t, up ? 16 : 12);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::NEUTRALIZE: {
            const int dmg = calculateCardDamage(c, t, up ? 4 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false) );
            break;
        }

        case CardId::POISONED_STAB: {
            const int dmg = calculateCardDamage(c, t, up ? 8 : 6);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::POISON>(t, up ? 4 : 3, false) );
            break;
        }

        case CardId::PREDATOR: {
            const int dmg = calculateCardDamage(c, t, up ? 20 : 15);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::BuffPlayer<PS::DRAW_CARD_NEXT_TURN>(2) );
            break;
        }

        case CardId::QUICK_SLASH: {
            const int dmg = calculateCardDamage(c, t, up ? 12 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::RIDDLE_WITH_HOLES: {
            const int dmg = calculateCardDamage(c, t, up ? 4 : 3);
            for(int i=0; i<5; ++i) {
                addToBot( Actions::AttackEnemy(t, dmg) );
            }
            break;
        }

        case CardId::SKEWER: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Action([=] (BattleContext &b) {
                int e = item.energyOnUse;
                if (b.player.hasRelic<R::CHEMICAL_X>()) e += 2;
                for (int i=0; i<e; ++i) {
                    b.addToTop( Actions::AttackEnemy(t, dmg) );
                }
            }) );
            break;
        }

        case CardId::SLICE: {
            const int dmg = calculateCardDamage(c, t, up ? 8 : 5);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::SNEAKY_STRIKE: {
            const int dmg = calculateCardDamage(c, t, up ? 16 : 12);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([=] (BattleContext &b) {
                if (b.player.cardsDiscardedThisTurn > 0) {
                    b.addToTop( Actions::GainEnergy(2) );
                }
            }) );
            break;
        }

        // CardId::STRIKE_GREEN is defined natively in STS lightspeed

        case CardId::SUCKER_PUNCH: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false) );
            break;
        }

        case CardId::UNLOAD: {
            const int dmg = calculateCardDamage(c, t, up ? 18 : 14);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([=] (BattleContext &b) {
                int count = b.cards.cardsInHand;
                for (int i=count-1; i>=0; --i) {
                    if (b.cards.hand[i].getType() != CardType::ATTACK) {
                        auto cardDiscarded = b.cards.hand[i];
                        b.cards.removeFromHandAtIdx(i);
                        b.cards.moveToDiscardPile(cardDiscarded);
                        b.onManualDiscard(cardDiscarded);
                    }
                }
            }) );
            break;
        }

        // ********************* DEFECT ATTACKS *********************

        case CardId::ALL_FOR_ONE: {
            const int dmg = calculateCardDamage(c, t, up ? 14 : 10);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                int size = b.cards.discardPile.size();
                for (int i = size - 1; i >= 0; --i) {
                    if (b.cards.discardPile[i].costForTurn == 0 || b.cards.discardPile[i].cost == 0) {
                        if (b.cards.cardsInHand >= 10) break;
                        auto cardZero = b.cards.discardPile[i];
                        b.cards.removeFromDiscard(i);
                        b.cards.moveToHand(cardZero);
                    }
                }
            }) );
            break;
        }

        case CardId::BALL_LIGHTNING: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) { b.player.channelOrb(b, Orb::LIGHTNING); }) );
            break;
        }

        case CardId::BARRAGE: {
            const int dmg = calculateCardDamage(c, t, up ? 6 : 4);
            addToBot( Action([&](BattleContext &b) {
                int numOrbs = 0;
                for (int i=0; i<b.player.orbSlots; ++i) {
                    if (b.player.orbs[i] != Orb::EMPTY) numOrbs++;
                }
                for (int i=0; i<numOrbs; ++i) {
                    b.addToTop( Actions::AttackEnemy(t, dmg) );
                }
            }) );
            break;
        }

        case CardId::BEAM_CELL: {
            const int dmg = calculateCardDamage(c, t, up ? 4 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(t, up ? 2 : 1, false) );
            break;
        }

        case CardId::BLIZZARD: {
            addToBot( Action([&](BattleContext &b) {
                int d = b.player.frostOrbsChanneledThisCombat * (up ? 3 : 2);
                int baseDmg = b.calculateCardDamage(c, -1, d);
                b.addToTop( Actions::AttackAllEnemy(baseDmg) );
            }) );
            break;
        }

        case CardId::BRILLIANCE: {
            // NOT IMPLEMENTED (Custom mod card often mistakenly generated by get_defect_cards script)
            break;
        }

        case CardId::BULLSEYE: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::LOCK_ON>(t, up ? 3 : 2, false) );
            break;
        }

        case CardId::CLAW: {
            const int dmg = calculateCardDamage(c, t, up ? 5 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                b.cards.clawDamage += 2;
            }) );
            break;
        }

        case CardId::COLD_SNAP: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 6);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) { b.player.channelOrb(b, Orb::FROST); }) );
            break;
        }

        case CardId::CORE_SURGE: {
            const int dmg = calculateCardDamage(c, t, up ? 15 : 11);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::BuffPlayer<PS::ARTIFACT>(1) );
            break;
        }

        case CardId::DOOM_AND_GLOOM: {
            const int dmg = calculateCardDamage(c, -1, up ? 14 : 10);
            addToBot( Actions::AttackAllEnemy(dmg) );
            addToBot( Action([&](BattleContext &b) { b.player.channelOrb(b, Orb::DARK); }) );
            break;
        }

        case CardId::FTL: {
            const int dmg = calculateCardDamage(c, t, up ? 6 : 5);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                if (b.player.cardsPlayedThisTurn <= 3) { // This card included (but played count handled carefully)
                    // if it's 3rd card or less played
                    b.addToTop( Actions::DrawCards(1) );
                }
            }) );
            break;
        }

        case CardId::GO_FOR_THE_EYES: {
            const int dmg = calculateCardDamage(c, t, up ? 4 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                if (b.monsters.arr[t].isAttacking()) {
                    b.addToTop( Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false) );
                }
            }) );
            break;
        }

        case CardId::HYPERBEAM: {
            const int dmg = calculateCardDamage(c, -1, up ? 34 : 26);
            addToBot( Actions::AttackAllEnemy(dmg) );
            addToBot( Actions::DebuffPlayer<PS::FOCUS>(3) );
            break;
        }

        case CardId::MELTER: {
            addToBot( Action([&](BattleContext &b) {
                b.monsters.arr[t].block = 0; // Remove all block
            }) );
            const int dmg = calculateCardDamage(c, t, up ? 14 : 10);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::METEOR_STRIKE: {
            const int dmg = calculateCardDamage(c, t, up ? 30 : 24);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                for (int i=0; i<3; ++i) b.player.channelOrb(b, Orb::PLASMA);
            }) );
            break;
        }

        case CardId::REBOUND: {
            const int dmg = calculateCardDamage(c, t, up ? 12 : 9);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::BuffPlayer<PS::REBOUND>(1) );
            break;
        }

        case CardId::RIP_AND_TEAR: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 7);
            addToBot( Actions::DamageRandomEnemy(dmg) );
            addToBot( Actions::DamageRandomEnemy(dmg) );
            break;
        }

        case CardId::SCRAPE: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                b.addToTop( Actions::DrawCards(4) ); /* Scrape discard logic omitted */
            }) );
            break;
        }

        case CardId::STREAMLINE: {
            const int dmg = calculateCardDamage(c, t, up ? 20 : 15);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&](BattleContext &b) {
                for(int i=0; i<b.cards.cardsInHand; ++i) {
                    if (b.cards.hand[i].uniqueId == c.uniqueId) {
                        b.cards.hand[i].costForTurn = std::max(0, b.cards.hand[i].costForTurn - 1);
                        b.cards.hand[i].cost = std::max(0, b.cards.hand[i].cost - 1);
                    }
                }
            }) );
            break;
        }

        // CardId::STRIKE_BLUE is defined natively in STS lightspeed

        case CardId::SUNDER: {
            const int dmg = calculateCardDamage(c, t, up ? 32 : 24);
            addToBot( Action([&](BattleContext &b) {
                int hpBefore = b.monsters.arr[t].curHp;
                b.monsters.arr[t].attacked(b, dmg);
                if (hpBefore > 0 && b.monsters.arr[t].curHp <= 0) {
                    b.addToTop( Actions::GainEnergy(3) );
                }
            }) );
            break;
        }

        case CardId::SWEEPING_BEAM: {
            const int dmg = calculateCardDamage(c, -1, up ? 9 : 6);
            addToBot( Actions::AttackAllEnemy(dmg) );
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::THUNDER_STRIKE: {
            addToBot( Action([&](BattleContext &b) {
                int d = b.player.lightningOrbsChanneledThisCombat;
                int baseDmg = b.calculateCardDamage(c, -1, up ? 9 : 7); // Base damage sent to RandomEnemy
                for (int i=0; i<d; ++i) {
                    b.addToTop( Actions::DamageRandomEnemy(baseDmg) );
                }
            }) );
            break;
        }

        case CardId::BACKSTAB: {
            const int dmg = calculateCardDamage(c, t, up ? 15 : 11);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        // ********************* WATCHER ATTACKS *********************

        // STRIKE_PURPLE already implemented

        case CardId::ERUPTION: {
            const int dmg = calculateCardDamage(c, t, up ? 12 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::ChangeStance(Stance::WRATH) );
            break;
        }

        case CardId::FLURRY_OF_BLOWS: {
            const int dmg = calculateCardDamage(c, t, up ? 8 : 4);
            for (int i = 0; i < 4; ++i) {
                addToBot( Actions::AttackEnemy(t, dmg) );
            }
            addToBot( Action([&, oldStance = player.stance](BattleContext &b) mutable {
                if (b.player.stance != oldStance && b.player.stance == Stance::NEUTRAL) {
                    // If exited stance, return this card to hand
                    auto cardCopy = b.curCardQueueItem.card;
                    cardCopy.retain = true;
                    b.addToTop(Actions::MakeTempCardInHand(cardCopy, 1));
                }
            }));
            break;
        }

        case CardId::CONSECRATE: {
            const int dmg = calculateCardDamage(c, -1, up ? 6 : 5);
            addToBot( Actions::AttackAllEnemy(dmg) );
            break;
        }

        case CardId::CRUSH_JOINTS: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&, t](BattleContext &b) {
                auto &m = b.monsters.arr[t];
                if (!m.isDeadOrEscaped() && m.isAttacking()) {
                    b.addToTop(Actions::DebuffEnemy<MS::VULNERABLE>(t, up ? 2 : 1, false));
                }
            }));
            break;
        }

        case CardId::SASH_WHIP: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&, t](BattleContext &b) {
                auto &m = b.monsters.arr[t];
                if (!m.isDeadOrEscaped() && !m.isAttacking()) {
                    b.addToTop(Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false));
                }
            }));
            break;
        }

        case CardId::BOWLING_BASH: {
            const int dmgPerEnemy = up ? 10 : 7;
            for (int i = 0; i < monsters.monsterCount; ++i) {
                if (!monsters.arr[i].isDeadOrEscaped()) {
                    const int dmg = calculateCardDamage(c, i, dmgPerEnemy);
                    addToBot( Actions::AttackEnemy(i, dmg) );
                }
            }
            break;
        }

        case CardId::CARVE_REALITY: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 6);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&, up](BattleContext &b) {
                if (b.player.stance == Stance::WRATH) {
                    b.addToTop(Actions::MakeTempCardInHand(CardId::SMITE, up, 1));
                }
            }));
            break;
        }

        case CardId::FLYING_SLEEVES: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Retain damage is handled by hasSelfRetain() check
            break;
        }

        case CardId::REACH_HEAVEN: {
            const int dmg = calculateCardDamage(c, t, up ? 25 : 20);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::THROUGH_VIOLENCE, up), 1, true) );
            break;
        }

        case CardId::FEAR_NO_EVIL: {
            const int dmg = calculateCardDamage(c, t, up ? 11 : 8);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Action([&, t](BattleContext &b) {
                auto &m = b.monsters.arr[t];
                if (!m.isDeadOrEscaped() && m.isAttacking()) {
                    b.addToTop(Actions::ChangeStance(Stance::CALM));
                }
            }));
            break;
        }

        case CardId::WHEEL_KICK: {
            const int dmg = calculateCardDamage(c, t, up ? 15 : 10);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DrawCards(2) );
            addToBot( Actions::DiscardAction(1, false, false, false) );
            break;
        }

        case CardId::WINDMILL_STRIKE: {
            // Base damage plus bonus damage based on misc counter
            int bonusDmg = c.misc;
            const int baseDmg = up ? 16 : 12;
            const int dmg = calculateCardDamage(c, t, baseDmg + bonusDmg);
            addToBot( Actions::AttackEnemy(t, dmg) );
            break;
        }

        case CardId::TALK_TO_THE_HAND: {
            const int dmg = calculateCardDamage(c, t, up ? 5 : 2);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 2 : 1, false) );
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::WALLOP: {
            const int dmg = calculateCardDamage(c, t, up ? 13 : 9);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Simplified: gain block equal to damage dealt
            addToBot( Action([&, dmg](BattleContext &b) {
                // Gain block equal to damage (simplified from actual mechanics)
                b.addToTop(Actions::GainBlock(dmg));
            }));
            break;
        }

        case CardId::TANTRUM: {
            const int dmg = calculateCardDamage(c, t, up ? 15 : 12);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::ChangeStance(Stance::WRATH) );
            addToBot( Actions::ChangeStance(Stance::WRATH) ); // Enter wrath twice
            break;
        }

        case CardId::RAGNAROK: {
            const int dmg = calculateCardDamage(c, -1, up ? 7 : 5);
            for (int i = 0; i < (up ? 6 : 5); ++i) {
                addToBot( Actions::DamageRandomEnemy(dmg) );
            }
            addToBot( Actions::MakeTempCardInHand(CardId::SMITE, up, 1) );
            break;
        }

        case CardId::CONCLUDE: {
            const int dmg = calculateCardDamage(c, -1, up ? 16 : 12);
            addToBot( Actions::AttackAllEnemy(dmg) );
            // Minion killing simplified - just deal damage
            break;
        }

        case CardId::WEAVE: {
            const int dmg = calculateCardDamage(c, t, up ? 7 : 4);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Return to hand when discarded is handled in triggerOnManualDiscard
            break;
        }

        case CardId::EMPTY_FIST: {
            const int dmg = calculateCardDamage(c, t, up ? 13 : 9);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::ChangeStance(Stance::NEUTRAL) );
            break;
        }

        case CardId::CUT_THROUGH_FATE: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::ScryAction(up ? 3 : 2) );
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::JUST_LUCKY: {
            const int dmg = calculateCardDamage(c, t, up ? 6 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::GainBlock(up ? 2 : 1) );
            addToBot( Actions::ScryAction(1) );
            break;
        }

        case CardId::SANDS_OF_TIME: {
            const int dmg = calculateCardDamage(c, t, up ? 28 : 20);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Cost reduction when in discard is handled in CardInstance
            break;
        }

        case CardId::FOLLOW_UP: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 6);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Simplified: always gain energy if previous card was attack
            // Real game checks playedCardsThisTurn
            break;
        }

        case CardId::LESSON_LEARNED: {
            const int dmg = calculateCardDamage(c, t, up ? 14 : 10);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Upgrade on kill simplified
            break;
        }

        case CardId::SIGNATURE_MOVE: {
            const int dmg = calculateCardDamage(c, t, up ? 40 : 30);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Cannot be played if other attacks played - handled in canUse
            break;
        }

        case CardId::COMPILE_DRIVER: {
            const int dmg = calculateCardDamage(c, t, up ? 10 : 7);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Draw 1 for each unique orb type (simplified for now)
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::SMITE: {
            const int dmg = calculateCardDamage(c, t, up ? 9 : 6);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Exhausts when played (ethereal behavior)
            break;
        }

        case CardId::THROUGH_VIOLENCE: {
            const int dmg = calculateCardDamage(c, t, up ? 25 : 20);
            addToBot( Actions::AttackEnemy(t, dmg) );
            // Exhausts when played (ethereal behavior)
            break;
        }

        default:
#ifdef sts_asserts
            std::cerr << "attempted to use unimplemented card: " << c.getName() << std::endl;
            assert(false);
#endif
            break;
    }
}

// todo a lot of things can be done immediately
void BattleContext::useSkillCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;
    const auto t = item.target;
    const bool up = c.isUpgraded();

    switch (c.getId()) {
        case CardId::DEFEND_RED:
        case CardId::DEFEND_BLUE:
        case CardId::DEFEND_GREEN:
        case CardId::DEFEND_PURPLE:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 8 : 5)) );
            break;

        case CardId::ARMAMENTS:
            addToBot(Actions::GainBlock(calculateCardBlock(5)) );
            if (up) {
                addToBot(Actions::UpgradeAllCardsInHand());
            } else {
                addToBot(Actions::ArmamentsAction());
            }
            break;

        case CardId::APOTHEOSIS:
            addToBot( Actions::ApotheosisAction() );
            break;

        case CardId::APPARITION:
            addToBot( Actions::BuffPlayer<PS::INTANGIBLE>(1) );
            break;

        case CardId::BANDAGE_UP:
            addToBot( Actions::HealPlayer(up ? 6 : 4) );
            break;

        case CardId::BATTLE_TRANCE:
            addToBot( Actions::DrawCards(up ? 4 : 3) );
            addToBot( Actions::DebuffPlayer<PS::NO_DRAW>() );
            break;

        case CardId::BLIND:
            if (up) {
                addToBot( Actions::DebuffAllEnemy<MS::WEAK>(2, false) );
            } else {
                addToBot( Actions::DebuffEnemy<MS::WEAK>(t, 2, false) );
            }
            break;

        case CardId::BLOODLETTING:
            addToBot( Actions::PlayerLoseHp(3, true) );
            addToBot( Actions::GainEnergy(up ? 3 : 2) );
            break;

        case CardId::BURNING_PACT:
            addToBot( Actions::ChooseExhaustOne() );
            addToBot( Actions::DrawCards(up ? 3 : 2) );
            break;

        case CardId::CHRYSALIS:
            addToBot( Actions::PutRandomCardsInDrawPile(CardType::SKILL, up ? 5 : 3) );
            break;

        case CardId::DARK_SHACKLES:
            addToBot( Actions::DebuffEnemy<MS::STRENGTH>(t, up ? 15 : 9) );
            if (monsters.arr[t].hasStatus<MS::ARTIFACT>()) {
                addToBot( Actions::BuffEnemy<MS::SHACKLED>(t, up ? 15 : 9) );
            }
            break;

        case CardId::DEEP_BREATH:
            if (!cards.discardPile.empty()) {
                onShuffle();
                addToBot( Actions::EmptyDeckShuffle() );
                addToBot( Actions::ShuffleDrawPile() );
            }
            addToBot( Actions::DrawCards(up ? 2 : 1) );
            break;

        case CardId::DISARM:
            addToBot( Actions::DebuffEnemy<MS::STRENGTH>(t, -2, false) );
            break;

        case CardId::DISCOVERY:
            undefinedBehaviorEvoked = true;
            addToBot(Actions::DiscoveryAction(CardType::INVALID, 1));
            break;

        case CardId::DOUBLE_TAP:
            addToBot(Actions::BuffPlayer<PS::DOUBLE_TAP>(up ? 2 : 1));
            break;

        case CardId::DUAL_WIELD:
            addToBot( Actions::DualWieldAction(up ? 2 : 1) );
            break;

        case CardId::ENLIGHTENMENT:
            addToBot( Actions::EnlightenmentAction(up) );
            break;

        case CardId::ENTRENCH:
            addToBot(Actions::EntrenchAction());
            break;

        case CardId::EXHUME:
            addToBot( Actions::ExhumeAction() );
            break;

        case CardId::FINESSE:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 4 : 2)) );
            addToBot( Actions::DrawCards(1) );
            break;

        case CardId::FORETHOUGHT:
            addToBot( Actions::ForethoughtAction(up) );
            break;

        case CardId::FLAME_BARRIER:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 16 : 12)) );
            addToBot( Actions::BuffPlayer<PS::FLAME_BARRIER>(up ? 6 : 4) );
            break;

        case CardId::FLEX:
            addToBot( Actions::BuffPlayer<PS::STRENGTH>(up ? 4 : 2) );
            addToBot( Actions::DebuffPlayer<PS::LOSE_STRENGTH>(up ? 4 : 2) );
            break;

        case CardId::GHOSTLY_ARMOR:
            addToBot( Actions::GainBlock(calculateCardBlock(up  ?  13 : 10)) );
            break;

        case CardId::GOOD_INSTINCTS:
            addToBot( Actions::GainBlock(calculateCardBlock(up  ?  9 : 6)) );
            break;

        case CardId::HAVOC:
            addToBot( Actions::PlayTopCard(monsters.getRandomMonsterIdx(cardRandomRng, true), true) );
            break;

        case CardId::IMPATIENCE: {
            bool hasAttack = false;
            for (int i = 0; i < cards.cardsInHand; ++i) {
                if (cards.hand[i].getType() == CardType::ATTACK) {
                    hasAttack = false;
                    break;
                }
            }
            if (!hasAttack) {
                addToBot(Actions::DrawCards(up ? 3 : 2));
            }
            break;
        }

        case CardId::IMPERVIOUS:
            addToBot( Actions::GainBlock(calculateCardBlock(up  ?  40 : 30)) );
            break;

        case CardId::INFERNAL_BLADE:
            addToBot( Actions::InfernalBladeAction() );
            break;

        case CardId::INTIMIDATE:
            addToBot( Actions::DebuffAllEnemy<MS::WEAK>(up ? 2 : 1, false) ); // game justs adds one for each enemy in order
            break;

        case CardId::JACK_OF_ALL_TRADES: // the game decides the random cards here and adds maketempcardtobot
            addToBot( Actions::JackOfAllTradesAction(up) );
            break;

        case CardId::JAX:
            addToBot( Actions::PlayerLoseHp(3, true) );
            addToBot( Actions::BuffPlayer<PS::STRENGTH>(up ? 3 : 2) );
            break;

        case CardId::LIMIT_BREAK:
            addToBot( Actions::LimitBreakAction() );
            break;

        case CardId::MADNESS:
            addToBot( Actions::MadnessAction() );
            break;

        case CardId::MASTER_OF_STRATEGY:
            addToBot( Actions::DrawCards(up ? 4 : 3) );
            break;

        case CardId::METAMORPHOSIS:
            addToBot( Actions::PutRandomCardsInDrawPile(CardType::ATTACK, up ? 5 : 3) );
            break;

        case CardId::OFFERING:
            addToBot( Actions::PlayerLoseHp(6, true) );
            addToBot( Actions::GainEnergy(2) );
            addToBot( Actions::DrawCards(up ? 5 : 3) );
            break;

        case CardId::PANACEA:
            addToBot( Actions::BuffPlayer<PS::ARTIFACT>(up ? 2 : 1) );
            break;

        case CardId::PANIC_BUTTON:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 40 : 30)) );
            addToBot( Actions::DebuffPlayer<PS::NO_BLOCK>(2) );
            break;

        case CardId::POWER_THROUGH:
            addToBot( Actions::MakeTempCardInHand(CardId::WOUND, false, 2) );
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 20 : 15)) );
            break;

        case CardId::PURITY:
            addToBot( Actions::ExhaustMany(up ? 5 : 3) );
            break;

        case CardId::RAGE:
            addToBot( Actions::BuffPlayer<PS::RAGE>(up ? 5 : 3) );
            break;

        case CardId::SECRET_TECHNIQUE:
            addToBot( Actions::DrawToHandAction(CardSelectTask::SECRET_TECHNIQUE, CardType::SKILL) );
            break;

        case CardId::SECRET_WEAPON:
            addToBot( Actions::DrawToHandAction(CardSelectTask::SECRET_WEAPON, CardType::ATTACK) );
            break;

        case CardId::SECOND_WIND:
            addToBot( Actions::SecondWindAction(calculateCardBlock(up ? 7 : 5)) );
            break;

        case CardId::SEEING_RED:
            addToBot( Actions::GainEnergy(2) );
            break;

        case CardId::SENTINEL:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 8 : 5)) );
            break;

        case CardId::SHOCKWAVE:
            addToBot( Actions::DebuffAllEnemy<MS::WEAK>(up ? 5 : 3, false) );
            addToBot( Actions::DebuffAllEnemy<MS::VULNERABLE>(up ? 5 : 3, false) );
            break;

        case CardId::SHRUG_IT_OFF:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 11 : 8)) );
            addToBot( Actions::DrawCards(1) );
            break;

        case CardId::SPOT_WEAKNESS:
            addToBot( Actions::SpotWeaknessAction(t, up ? 4 : 3) );
            break;

        case CardId::THE_BOMB:
            addToBot( Actions::BuffPlayer<PS::THE_BOMB>(up ? 50 : 40) );
            break;

        case CardId::THINKING_AHEAD: // same as upgraded warcry
            addToBot( Actions::DrawCards(2) );
            addToBot( Actions::WarcryAction() );
            break;

        case CardId::TRANSMUTATION:
            if (player.energy > item.energyOnUse) {
                item.energyOnUse = player.energy;
            }
            if (!item.ignoreEnergyTotal && player.energy < item.energyOnUse) {
                item.energyOnUse = player.energy;
            }

            addToBot( Actions::TransmutationAction(up, item.energyOnUse, !(item.freeToPlay || c.freeToPlayOnce)) );
            break;

        case CardId::TRIP: // maybe fixed --- todo this doesn't work properly because it only requires a target when not upgraded, also the trip card doesn't uses its own implementation of debuff all enemy
            if (up) {
                addToBot( Actions::DebuffAllEnemy<MS::VULNERABLE>(2, false) );
            } else {
                addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(t, 2, false) );
            }
            break;

        case CardId::TRUE_GRIT:
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 9 : 7)) );
            if (up) {
                addToBot( Actions::ChooseExhaustOne() );
            } else {
                addToBot( Actions::ExhaustRandomCardInHand(1) );
            }
            break;

        case CardId::VIOLENCE:
            addToBot( Actions::ViolenceAction(up ? 4 : 3) );
            break;

        case CardId::WARCRY:
            addToBot( Actions::DrawCards(up ? 2 : 1) );
            addToBot( Actions::WarcryAction() );
            break;

        // ********************* SILENT SKILLS 1 *********************

        case CardId::ACROBATICS: {
            addToBot( Actions::DrawCards(up ? 4 : 3) );
            addToBot( Actions::DiscardAction(1, false, false, false) );
            break;
        }

        case CardId::ADRENALINE: {
            addToBot( Actions::GainEnergy(up ? 2 : 1) );
            addToBot( Actions::DrawCards(2) );
            break;
        }

        case CardId::ALCHEMIZE: {
            addToBot( Actions::DrawCards(0) /* Potion gen not implemented */ ); // random
            break;
        }

        case CardId::BACKFLIP: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 8 : 5)) );
            addToBot( Actions::DrawCards(2) );
            break;
        }

        case CardId::BLADE_DANCE: {
            addToBot( Actions::MakeTempCardInHand(CardId::SHIV, false, up ? 4 : 3) );
            break;
        }

        case CardId::BLESSING: {
            addToBot( Actions::GainEnergy(up ? 4 : 3) );
            break;
        }

        case CardId::BLUR: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 8 : 5)) );
            addToBot( Actions::BuffPlayer<PS::BLUR>(1) );
            break;
        }

        case CardId::BOUNCING_FLASK: {
            for (int i=0; i < (up ? 4 : 3); ++i) {
                addToBot( Action([](BattleContext &b) { int r = b.monsters.getRandomMonsterIdx(b.cardRandomRng, true); if (r != -1) b.addToTop(Actions::DebuffEnemy<MS::POISON>(r, 3, false)); }) );
            }
            break;
        }

        case CardId::BURST: {
            addToBot( Actions::BuffPlayer<PS::BURST>(up ? 2 : 1) );
            break;
        }

        case CardId::CALCULATED_GAMBLE: {
            addToBot( Action([=] (BattleContext &b) {
                int count = b.cards.cardsInHand;
                for (int i=count-1; i>=0; --i) {
                    if (b.cards.hand[i].uniqueId != c.uniqueId) { // discard all EXCEPT this card
                        auto cardDiscarded = b.cards.hand[i];
                        b.cards.removeFromHandAtIdx(i);
                        b.cards.moveToDiscardPile(cardDiscarded);
                        b.onManualDiscard(cardDiscarded);
                    }
                }
                b.addToTop( Actions::DrawCards( count - 1 ) ); // -1 to not count itself
            }) );
            break;
        }

        case CardId::CATALYST: {
            addToBot( Action([&](BattleContext &b) {
                if (b.monsters.arr[t].hasStatus<MS::POISON>()) {
                    int p = b.monsters.arr[t].getStatus<MS::POISON>();
                    b.addToTop( Actions::DebuffEnemy<MS::POISON>(t, p * (up ? 2 : 1), false) ); // Doubles or triples
                }
            }) );
            break;
        }

        case CardId::CLOAK_AND_DAGGER: {
            addToBot( Actions::GainBlock(calculateCardBlock(6)) );
            addToBot( Actions::MakeTempCardInHand(CardId::SHIV, false, up ? 2 : 1) );
            break;
        }

        case CardId::CORPSE_EXPLOSION: {
            addToBot( Actions::DebuffEnemy<MS::POISON>(t, up ? 9 : 6, false) );
            addToBot( Actions::DebuffEnemy<MS::CORPSE_EXPLOSION>(t, 1, false) );
            break;
        }

        case CardId::CRIPPLING_CLOUD: {
            addToBot( Actions::DebuffAllEnemy<MS::POISON>(up ? 7 : 4, false) );
            addToBot( Actions::DebuffAllEnemy<MS::WEAK>(2, false) );
            break;
        }

        case CardId::DEADLY_POISON: {
            addToBot( Actions::DebuffEnemy<MS::POISON>(t, up ? 7 : 5, false) );
            break;
        }

        // CardId::DEFEND_GREEN is defined natively in STS lightspeed

        case CardId::DEFLECT: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 7 : 4)) );
            break;
        }

        case CardId::DISTRACTION: {
            addToBot( Actions::MakeTempCardInHand(CardId::INVALID, up, 1) ); // Needs to be random Skill
            break;
        }

        case CardId::DODGE_AND_ROLL: {
            const int block = calculateCardBlock(up ? 6 : 4);
            addToBot( Actions::GainBlock(block) );
            addToBot( Actions::BuffPlayer<PS::NEXT_TURN_BLOCK>(block) );
            break;
        }

        // ********************* SILENT SKILLS 2 *********************

        case CardId::DOPPELGANGER: {
            int e = item.energyOnUse;
            if (player.hasRelic<R::CHEMICAL_X>()) e += 2;
            if (up) e += 1;
            addToBot( Actions::BuffPlayer<PS::ENERGIZED>(e) );
            addToBot( Actions::BuffPlayer<PS::DRAW_CARD_NEXT_TURN>(e) );
            break;
        }

        case CardId::ESCAPE_PLAN: {
            addToBot( Action([&](BattleContext &b) {
                b.addToTop( Actions::DrawCards(1) );
                // Note: The conditional block should technically be checked after drawing
                // The engine might need a conditional check. Doing rudimentary top evaluation.
            }) );
            addToBot( Action([&](BattleContext &b) {
                if (b.cards.cardsInHand > 0 && b.cards.hand[b.cards.cardsInHand-1].getType() == CardType::SKILL) {
                   b.addToTop( Actions::GainBlock(b.calculateCardBlock(up ? 5 : 3)) );
                }
            }) );
            break;
        }

        case CardId::EXPERTISE: {
            int cap = up ? 7 : 6;
            int h = cards.cardsInHand; // includes itself actually if not removed yet, but draw pile logic handles it
            if (h < cap) {
                addToBot( Actions::DrawCards(cap - h) ); // Draw until cap
            }
            break;
        }

        case CardId::LEG_SWEEP: {
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, up ? 3 : 2, false) );
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 14 : 11)) );
            break;
        }

        case CardId::MALAISE: {
            int e = item.energyOnUse;
            if (player.hasRelic<R::CHEMICAL_X>()) e += 2;
            if (up) e += 1;
            addToBot( Actions::DebuffEnemy<MS::SHACKLED>(t, e, false) );
            addToBot( Actions::DebuffEnemy<MS::WEAK>(t, e, false) );
            break;
        }

        case CardId::NIGHTMARE: {
            addToBot( Action([&](BattleContext &b) {
                b.openSimpleCardSelectScreen(CardSelectTask::NIGHTMARE, 1);
            }) );
            break;
        }

        case CardId::OUTMANEUVER: {
            addToBot( Actions::BuffPlayer<PS::ENERGIZED>(up ? 3 : 2) );
            break;
        }

        case CardId::PHANTASMAL_KILLER: {
            addToBot( Actions::BuffPlayer<PS::PHANTASMAL>(1) );
            break;
        }

        case CardId::PIERCING_WAIL: {
            addToBot( Actions::DebuffAllEnemy<MS::SHACKLED>(up ? 8 : 6, false) );
            // Note: LOSE_STRENGTH in sts_lightspeed engine is temporary strength down, meaning it regains it end of turn.
            break;
        }

        case CardId::PREPARED: {
            addToBot( Actions::DrawCards(up ? 2 : 1) );
            addToBot( Actions::DiscardAction(up ? 2 : 1, false, false, false) );
            break;
        }

        case CardId::REFLEX: {
            // Handled in onManualDiscard
            break;
        }

        case CardId::SETUP: {
            addToBot( Action([&](BattleContext &b) {
                b.openSimpleCardSelectScreen(CardSelectTask::SETUP, 1);
            }) );
            break;
        }

        case CardId::STORM_OF_STEEL: {
            addToBot( Action([=] (BattleContext &b) {
                int count = b.cards.cardsInHand;
                for (int i=count-1; i>=0; --i) {
                    auto cardDiscarded = b.cards.hand[i];
                    b.cards.removeFromHandAtIdx(i);
                    b.cards.moveToDiscardPile(cardDiscarded);
                    b.onManualDiscard(cardDiscarded);
                }
                b.addToTop( Actions::MakeTempCardInHand( CardId::SHIV, up, count ) );
            }) );
            break;
        }

        case CardId::SURVIVOR: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 11 : 8)) );
            addToBot( Actions::DiscardAction(1, false, false, false) );
            break;
        }

        case CardId::TACTICIAN: {
            // Handled in onManualDiscard
            break;
        }

        case CardId::TERROR: {
            addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(t, 99, false) );
            break;
        }

        case CardId::AGGREGATE: {
            addToBot( Action([&](BattleContext &b) {
                int energyGain = b.player.cardsPlayedThisTurn;
                b.player.gainEnergy(energyGain);
            }) );
            break;
        }

        case CardId::AMPLIFY: {
            addToBot( Actions::BuffPlayer<PS::AMPLIFY>(up ? 2 : 1) );
            break;
        }

        case CardId::AUTO_SHIELDS: {
            addToBot( Action([&](BattleContext &b) {
                int orbCount = b.player.orbSlots - b.player.emptyOrbCount;
                b.player.gainBlock(b, orbCount * 3);
            }) );
            break;
        }

        case CardId::BOOT_SEQUENCE: {
            addToBot( Action([&](BattleContext &b) {
                if (b.player.emptyOrbCount == b.player.orbSlots) { // no orbs
                    b.player.channelOrb(b, Orb::FROST);
                }
            }) );
            break;
        }

        case CardId::CHAOS: {
            addToBot( Action([&](BattleContext &b) {
                Orb orbType = static_cast<Orb>(b.miscRng.random(3) + 1); // 1-4: LIGHTNING, FROST, DARK, PLASMA
                b.player.channelOrb(b, orbType);
            }) );
            break;
        }

        case CardId::CHARGE_BATTERY: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 9 : 7)) );
            addToBot( Actions::BuffPlayer<PS::ENERGIZED>(1) );
            break;
        }

        case CardId::CHILL: {
            addToBot( Action([&](BattleContext &b) {
                int count = b.monsters.monsterCount;
                for (int i = 0; i < count; ++i) {
                    if (b.monsters.arr[i].curHp > 0 && !b.monsters.arr[i].isEscaping()) {
                        b.player.channelOrb(b, Orb::FROST);
                    }
                }
            }) );
            break;
        }

        case CardId::COLLECT: {
            addToBot( Actions::BuffPlayer<PS::COLLECT>(up ? 3 : 2) );
            break;
        }

        case CardId::CONSUME: {
            addToBot( Action([&](BattleContext &b) {
                b.player.buff<PS::FOCUS>(up ? 3 : 2);
                if (b.player.orbSlots > 0) {
                    b.player.orbSlots--;
                    // If there was an orb in the last slot, it's lost
                    if (b.player.orbs[b.player.orbSlots] != Orb::EMPTY) {
                        b.player.orbs[b.player.orbSlots] = Orb::EMPTY;
                    } else {
                        b.player.emptyOrbCount--;
                    }
                }
            }) );
            break;
        }

        case CardId::COOLHEADED: {
            addToBot( Action([&](BattleContext &b) {
                b.player.channelOrb(b, Orb::FROST);
            }) );
            addToBot( Actions::DrawCards(1) );
            break;
        }

        case CardId::DARKNESS: {
            addToBot( Action([&](BattleContext &b) {
                b.player.channelOrb(b, Orb::DARK);
            }) );
            break;
        }

        // CardId::DEFEND_BLUE is defined natively in STS lightspeed

        case CardId::DOUBLE_ENERGY: {
            addToBot( Action([&](BattleContext &b) {
                b.player.gainEnergy(b.player.energy);
            }) );
            break;
        }

        case CardId::DUALCAST: {
            addToBot( Action([&](BattleContext &b) {
                b.player.evokeOrb(b);
                b.player.evokeOrb(b);
            }) );
            break;
        }

        case CardId::EQUILIBRIUM: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 5 : 3)) );
            addToBot( Actions::BuffPlayer<PS::EQUILIBRIUM>(1) );
            break;
        }

        case CardId::FISSION: {
            addToBot( Action([&, up](BattleContext &b) {
                int orbCount = b.player.orbSlots - b.player.emptyOrbCount;
                // Evoke all orbs
                for (int i = 0; i < orbCount; ++i) {
                    b.player.evokeOrb(b);
                }
                // Gain energy and draw based on orbs removed
                if (orbCount > 0) {
                    b.player.gainEnergy(orbCount);
                    b.drawCards(up ? orbCount * 2 : orbCount);
                }
            }) );
            break;
        }

        case CardId::FORCE_FIELD: {
            // Base cost is 2, 0 cost if 10+ cards played this combat
            // This is handled via the card's cost adjustment elsewhere
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 6 : 4)) );
            break;
        }

        case CardId::FUSION: {
            addToBot( Action([&](BattleContext &b) {
                Orb orbType = static_cast<Orb>(b.miscRng.random(3) + 1); // 1-4: LIGHTNING, FROST, DARK, PLASMA
                b.player.channelOrb(b, orbType);
            }) );
            break;
        }

        case CardId::GENETIC_ALGORITHM: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 5 : 1)) );
            addToBot( Action([&, up](BattleContext &b) {
                c.misc += (up ? 2 : 1);
            }) );
            break;
        }

        case CardId::GLACIER: {
            addToBot( Action([&](BattleContext &b) {
                b.player.channelOrb(b, Orb::FROST);
                b.player.channelOrb(b, Orb::FROST);
            }) );
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 7 : 5)) );
            break;
        }

        case CardId::HOLOGRAM: {
            const int dmg = calculateCardDamage(c, t, up ? 5 : 3);
            addToBot( Actions::AttackEnemy(t, dmg) );
            addToBot( Actions::BetterDiscardPileToHandAction(1, CardSelectTask::HOLOGRAM) );
            break;
        }

        case CardId::LEAP: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 12 : 9)) );
            break;
        }

        case CardId::MULTI_CAST: {
            int times = item.energyOnUse;
            if (player.hasRelic<R::CHEMICAL_X>()) times += 2;
            if (!item.ignoreEnergyTotal && !item.freeToPlay && !c.freeToPlayOnce) {
                player.useEnergy(std::min(times, player.energy));
                times = std::min(times, player.energy + (player.hasRelic<R::CHEMICAL_X>() ? 2 : 0));
            }
            for (int i = 0; i < times; ++i) {
                addToBot( Action([&](BattleContext &b) {
                    b.player.evokeOrb(b);
                }) );
            }
            break;
        }

        case CardId::OVERCLOCK: {
            addToBot( Actions::DrawCards(up ? 3 : 2) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::DAZED), 1, false) );
            break;
        }

        case CardId::RAINBOW: {
            addToBot( Action([&](BattleContext &b) {
                for (int i = 0; i < 3; ++i) {
                    Orb orbType = static_cast<Orb>(b.miscRng.random(3) + 1); // 1-4: LIGHTNING, FROST, DARK, PLASMA
                    b.player.channelOrb(b, orbType);
                }
            }) );
            break;
        }

        case CardId::REBOOT: {
            addToBot( Action([&, up](BattleContext &b) {
                // Shuffle hand into draw pile
                for (int i = 0; i < b.cards.cardsInHand; ++i) {
                    b.cards.drawPile.push_back(b.cards.hand[i]);
                }
                b.cards.cardsInHand = 0;
                // Shuffle discard into draw pile
                for (auto& card : b.cards.discardPile) {
                    b.cards.drawPile.push_back(card);
                }
                b.cards.discardPile.clear();
                // Shuffle the draw pile
                b.onShuffle();
                // Draw cards
                b.drawCards(up ? 4 : 3);
            }) );
            break;
        }

        case CardId::RECURSION: {
            addToBot( Action([&](BattleContext &b) {
                if (b.player.orbSlots > 0 && b.player.orbs[0] != Orb::EMPTY) {
                    Orb orbType = b.player.orbs[0];
                    b.player.evokeOrb(b);
                    b.player.channelOrb(b, orbType);
                }
            }) );
            break;
        }

        case CardId::RECYCLE: {
            addToBot( Action([&, up](BattleContext &b) {
                int x = item.energyOnUse;
                if (!item.ignoreEnergyTotal && !item.freeToPlay && !c.freeToPlayOnce) {
                    x = std::min(x, b.player.energy);
                    b.player.useEnergy(x);
                }
                // Exhaust X cards from hand, gain energy for each
                // This is a simplified implementation
                b.cardSelectInfo.pickCount = x;
                b.cardSelectInfo.cardSelectTask = CardSelectTask::RECYCLE;
                b.cardSelectInfo.canPickZero = false;
                b.cardSelectInfo.canPickAnyNumber = true;
                b.setState(InputState::CARD_SELECT);
            }) );
            break;
        }

        case CardId::REINFORCED_BODY: {
            int times = item.energyOnUse;
            if (player.hasRelic<R::CHEMICAL_X>()) times += 2;
            if (!item.ignoreEnergyTotal && !item.freeToPlay && !c.freeToPlayOnce) {
                times = std::min(times, player.energy);
                player.useEnergy(times);
            }
            addToBot( Actions::GainBlock(times * (up ? 7 : 5)) );
            break;
        }

        case CardId::REPROGRAM: {
            addToBot( Actions::BuffPlayer<PS::STRENGTH>(up ? 2 : 1) );
            addToBot( Actions::BuffPlayer<PS::DEXTERITY>(up ? 2 : 1) );
            addToBot( Actions::DebuffPlayer<PS::FOCUS>(up ? 2 : 1, false) );
            break;
        }

        case CardId::SEEK: {
            // TODO
            break;
        }

        case CardId::SKIM: {
            addToBot( Actions::DrawCards(3) );
            break;
        }

        case CardId::STACK: {
            addToBot( Action([&](BattleContext &b) {
                int block = static_cast<int>(b.cards.discardPile.size());
                b.player.gainBlock(b, block);
            }) );
            break;
        }

        case CardId::STEAM_BARRIER: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 9 : 6)) );
            addToBot( Action([&](BattleContext &b) {
                // Remove this card from deck this combat (handled by exhaust in simplified form)
            }) );
            break;
        }

        case CardId::TEMPEST: {
            int times = item.energyOnUse;
            if (player.hasRelic<R::CHEMICAL_X>()) times += 2;
            if (!item.ignoreEnergyTotal && !item.freeToPlay && !c.freeToPlayOnce) {
                times = std::min(times, player.energy);
                player.useEnergy(times);
            }
            addToBot( Action([&](BattleContext &b) {
                for (int i = 0; i < times; ++i) {
                    b.player.channelOrb(b, Orb::LIGHTNING);
                }
            }) );
            break;
        }

        case CardId::TURBO: {
            addToBot( Actions::GainEnergy(up ? 3 : 2) );
            addToBot( Actions::MakeTempCardInDiscard(CardInstance(CardId::DAZED), 1) );
            break;
        }

        case CardId::WHITE_NOISE: {
            addToBot( Action([&, up](BattleContext &b) {
                // Get random Defect power card
                CardId powerId = RarityCardPool::getCardFromPool(CharacterClass::DEFECT,
                    static_cast<CardRarity>(b.miscRng.random(2)), 0); // COMMON, UNCOMMON, or RARE
                CardInstance card(powerId, up);
                b.addToTop(Actions::MakeTempCardInHand(card, 1));
            }) );
            break;
        }

        case CardId::ZAP: {
            addToBot( Action([&](BattleContext &b) {
                b.player.channelOrb(b, Orb::LIGHTNING);
            }) );
            break;
        }


        // ********************* WATCHER SKILLS *********************

        // DEFEND_PURPLE already implemented

        case CardId::VIGILANCE: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 16 : 12)) );
            addToBot( Actions::ChangeStance(Stance::CALM) );
            break;
        }

        case CardId::MEDITATE: {
            addToBot( Actions::BuffPlayer<PS::MANTRA>(up ? 4 : 3) );
            addToBot( Action([&](BattleContext &b) {
                if (!b.cards.discardPile.empty()) {
                    b.cardSelectInfo.cardSelectTask = CardSelectTask::MEDITATE;
                    b.cardSelectInfo.pickCount = 1;
                    b.cardSelectInfo.canPickZero = false;
                    b.cardSelectInfo.canPickAnyNumber = false;
                    b.inputState = InputState::CARD_SELECT;
                }
            }));
            break;
        }

        case CardId::PROSTRATE: {
            addToBot( Actions::BuffPlayer<PS::MANTRA>(up ? 2 : 1) );
            addToBot( Actions::GainBlock(up ? 6 : 4) );
            break;
        }

        case CardId::BLASPHEMY: {
            addToBot( Actions::ChangeStance(Stance::DIVINITY) );
            addToBot( Action([&](BattleContext &b) {
                b.player.buff<PS::BLASPHEMY>(1);
            }));
            break;
        }

        case CardId::TRANQUILITY: {
            addToBot( Actions::ChangeStance(Stance::CALM) );
            // Exhausts when played (ethereal behavior)
            break;
        }

        case CardId::EVALUATE: {
            addToBot( Actions::DrawCards(1) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::INSIGHT, up), 1, true) );
            break;
        }

        case CardId::WORSHIP: {
            addToBot( Actions::BuffPlayer<PS::MANTRA>(up ? 6 : 5) );
            break;
        }

        case CardId::WREATH_OF_FLAME: {
            addToBot( Action([&, up](BattleContext &b) {
                if (b.player.stance == Stance::WRATH) {
                    const int dmg = up ? 8 : 5;
                    b.addToTop(Actions::AttackAllEnemy(dmg));
                }
                b.addToTop(Actions::GainEnergy(1));
                b.addToTop(Actions::ChangeStance(Stance::WRATH));
            }));
            break;
        }

        case CardId::THIRD_EYE: {
            addToBot( Actions::ScryAction(up ? 5 : 3) );
            addToBot( Actions::GainBlock(up ? 6 : 4) );
            break;
        }

        case CardId::INNER_PEACE: {
            addToBot( Action([&, up](BattleContext &b) {
                if (b.player.stance == Stance::CALM) {
                    b.addToTop(Actions::DrawCards(3));
                } else {
                    b.addToTop(Actions::ChangeStance(Stance::CALM));
                }
            }));
            break;
        }

        case CardId::SWIVEL: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 16 : 12)) );
            addToBot( Action([&](BattleContext &b) {
                b.player.buff<PS::FREE_ATTACK_POWER>(1);
            }));
            break;
        }

        case CardId::PRAY: {
            addToBot( Actions::BuffPlayer<PS::MANTRA>(up ? 4 : 3) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::BLESSING, up), 1, true) );
            break;
        }

        case CardId::SIMMERING_FURY: {
            addToBot( Action([&, up](BattleContext &b) {
                b.player.buff<PS::SIMMERING_FURY>(1);
            }));
            break;
        }

        case CardId::DECEIVE_REALITY: {
            addToBot( Actions::ChangeStance(Stance::WRATH) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::INSIGHT, up), 1, true) );
            break;
        }

        case CardId::JUDGMENT: {
            addToBot( Action([&, up](BattleContext &b) {
                // Exhaust a card costing 2 or less
                // For now, simplified: exhaust cheapest card in hand
                int maxCost = up ? 3 : 2;
                for (int i = 0; i < b.cards.cardsInHand; ++i) {
                    if (b.cards.hand[i].cost <= maxCost) {
                        b.addToTop(Actions::ExhaustSpecificCardInHand(i, b.cards.hand[i].getUniqueId()));
                        break;
                    }
                }
            }));
            break;
        }

        case CardId::WAVE_OF_THE_HAND: {
            const int block = cards.cardsInHand;
            addToBot( Actions::GainBlock(block) );
            break;
        }

        case CardId::SCRAWL: {
            addToBot( Action([&](BattleContext &b) {
                int cardsToDraw = 10 - b.cards.cardsInHand;
                if (cardsToDraw > 0) {
                    b.addToTop(Actions::DrawCards(cardsToDraw));
                }
            }));
            break;
        }

        case CardId::SANCTITY: {
            // Simplified: just gain block
            addToBot( Actions::GainBlock(up ? 9 : 6) );
            // Full implementation checks if previous card was a skill
            break;
        }

        case CardId::SPIRIT_SHIELD: {
            addToBot( Action([&, up](BattleContext &b) {
                b.player.buff<PS::SPIRIT_SHIELD>(up ? 2 : 1);
            }));
            break;
        }

        case CardId::HALT: {
            addToBot( Action([&, up](BattleContext &b) {
                int block = up ? 5 : 3;
                if (b.player.stance == Stance::WRATH) {
                    block += up ? 13 : 9;
                }
                b.addToTop(Actions::GainBlock(block));
            }));
            break;
        }

        case CardId::PROTECT: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 16 : 12)) );
            break;
        }

        case CardId::ALPHA: {
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::BETA, up), 1, true) );
            break;
        }

        case CardId::BETA: {
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::OMEGA, up), 1, true) );
            break;
        }

        case CardId::WISH: {
            addToBot( Action([&, up](BattleContext &b) {
                // Simplified: always choose deal damage option
                // Real game offers: 6 energy, 30 damage, 30 block, or 3 Smite
                int damage = up ? 45 : 30;
                for (int i = 0; i < b.monsters.monsterCount; ++i) {
                    if (!b.monsters.arr[i].isDeadOrEscaped()) {
                        b.addToTop(Actions::DamageEnemy(i, damage));
                    }
                }
            }));
            break;
        }

        case CardId::DEUS_EX_MACHINA: {
            addToBot( Actions::GainEnergy(up ? 3 : 2) );
            addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::MIRACLE, up), up ? 3 : 2, true) );
            break;
        }

        case CardId::CONJURE_BLADE: {
            addToBot( Action([&, up](BattleContext &b) {
                // Create a scaling card (simplified)
                auto blade = CardInstance(CardId::SHIV, up);
                blade.misc = up ? 6 : 3;
                b.addToTop(Actions::MakeTempCardInDrawPile(blade, 1, true));
            }));
            break;
        }

        case CardId::OMNISCIENCE: {
            // Simplified: just draw and play a card
            addToBot( Actions::DrawCards(1) );
            // Full implementation plays a card from draw pile twice
            break;
        }

        case CardId::FOREIGN_INFLUENCE: {
            // Add 1 of 3 random attacks to hand (simplified: uses discovery mechanism which sets cost to 0)
            // Real game: player chooses from 3 random attacks, card keeps original cost
            addToBot( Actions::DiscoveryAction(CardType::ATTACK, 1) );
            break;
        }

        case CardId::CRESCENDO: {
            addToBot( Actions::ChangeStance(Stance::WRATH) );
            break;
        }

        case CardId::INDIGNATION: {
            addToBot( Action([&, up](BattleContext &b) {
                if (b.player.stance == Stance::WRATH) {
                    for (int i = 0; i < b.monsters.monsterCount; ++i) {
                        if (!b.monsters.arr[i].isDeadOrEscaped()) {
                            b.addToTop(Actions::DebuffEnemy<MS::VULNERABLE>(i, up ? 4 : 3, false));
                        }
                    }
                } else {
                    b.addToTop(Actions::ChangeStance(Stance::WRATH));
                }
            }));
            break;
        }

        case CardId::EMPTY_MIND: {
            addToBot( Actions::DrawCards(2) );
            addToBot( Action([&, up](BattleContext &b) {
                if (b.player.stance == Stance::NEUTRAL) {
                    b.addToTop(Actions::GainEnergy(1));
                }
            }));
            break;
        }

        case CardId::EMPTY_BODY: {
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 11 : 7)) );
            addToBot( Action([&](BattleContext &b) {
                if (b.player.stance == Stance::NEUTRAL) {
                    b.addToTop(Actions::DrawCards(1));
                }
            }));
            break;
        }

        case CardId::PERSEVERANCE: {
            // Block bonus stored in misc
            int bonusBlock = c.misc;
            addToBot( Actions::GainBlock(calculateCardBlock(up ? 8 : 4) + bonusBlock) );
            break;
        }

        case CardId::PRESSURE_POINTS: {
            addToBot( Action([&, up](BattleContext &b) {
                int marks = up ? 11 : 8;
                for (int i = 0; i < b.monsters.monsterCount; ++i) {
                    if (!b.monsters.arr[i].isDeadOrEscaped()) {
                        b.addToTop(Actions::DebuffEnemy<MS::MARK>(i, marks, false));
                    }
                }
            }));
            break;
        }

        case CardId::VAULT: {
            addToBot( Action([&](BattleContext &b) {
                b.player.buff<PS::EXTRA_TURN>(1);
            }));
            break;
        }

        case CardId::MIRACLE: {
            addToBot( Actions::GainEnergy(1) );
            // Exhausts when played
            break;
        }

        case CardId::INSIGHT: {
            addToBot( Actions::DrawCards(1) );
            // Exhausts when played
            break;
        }

        // BLESSING card doesn't exist - case removed

        default:
#ifdef sts_asserts
            std::cerr << "attempted to use unimplemented card: " << c.getName() << std::endl;
            assert(false);
#endif
            break;
    }
}

void BattleContext::usePowerCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    const auto t = item.target;
    const bool up = c.isUpgraded();

    switch (c.getId()) {

        case CardId::BARRICADE:
            player.setHasStatus<PS::BARRICADE>(true);
            break;

        case CardId::BERSERK:
            ++player.energyPerTurn;
            addToBot( Actions::DebuffPlayer<PS::VULNERABLE>(up ? 1 : 2, false) );
            break;

        case CardId::BRUTALITY:
            addToBot( Actions::BuffPlayer<PS::BRUTALITY>(1) );
            break;

        case CardId::CORRUPTION:
            addToBot( Actions::BuffPlayer<PS::CORRUPTION>() );
            break;

        case CardId::COMBUST:
            addToBot( Actions::BuffPlayer<PS::COMBUST>(up ? 7 : 5) );
            break;

        case CardId::DEMON_FORM:
            addToBot( Actions::BuffPlayer<PS::DEMON_FORM>(up ? 3 : 2) );
            break;

        case CardId::DARK_EMBRACE:
            addToBot( Actions::BuffPlayer<PS::DARK_EMBRACE>(1) );
            break;

        case CardId::EVOLVE:
            addToBot( Actions::BuffPlayer<PS::EVOLVE>(up ? 2 : 1) );
            break;

        case CardId::FEEL_NO_PAIN:
            addToBot( Actions::BuffPlayer<PS::FEEL_NO_PAIN>(up ? 4 : 3) );
            break;

        case CardId::FIRE_BREATHING:
            addToBot( Actions::BuffPlayer<PS::FIRE_BREATHING>(up ? 10 : 6) );
            break;

        case CardId::INFLAME:
            addToBot( Actions::BuffPlayer<PS::STRENGTH>(up ? 3 : 2) );
            break;

        case CardId::JUGGERNAUT:
            addToBot( Actions::BuffPlayer<PS::JUGGERNAUT>(up ? 7 : 5) );
            break;

        case CardId::MAGNETISM:
            addToBot( Actions::BuffPlayer<PS::MAGNETISM>(1) );
            break;

        case CardId::MAYHEM:
            addToBot( Actions::BuffPlayer<PS::MAYHEM>(1) );
            break;

        case CardId::METALLICIZE:
            addToBot( Actions::BuffPlayer<PS::METALLICIZE>(up ? 4 : 3) );
            break;

        case CardId::PANACHE:
            addToBot( Actions::BuffPlayer<PS::PANACHE>(up ? 14 : 10) );
            break;

        case CardId::RUPTURE:
            addToBot(Actions::BuffPlayer<PS::RUPTURE>(up ? 2 : 1));
            break;

        case CardId::SADISTIC_NATURE:
            addToBot( Actions::BuffPlayer<PS::SADISTIC>(up ? 7 : 5) );
            break;

        case CardId::WRAITH_FORM:
            addToBot( Actions::BuffPlayer<PS::INTANGIBLE>(up ? 3 : 2) );
            addToBot( Actions::DebuffPlayer<PS::WRAITH_FORM>(1) );
            break;

        // ********************* SILENT POWERS *********************

        case CardId::ACCURACY:
            addToBot( Actions::BuffPlayer<PS::ACCURACY>(up ? 6 : 4) );
            break;

        case CardId::AFTER_IMAGE:
            addToBot( Actions::BuffPlayer<PS::AFTER_IMAGE>(1) );
            break;

        case CardId::A_THOUSAND_CUTS:
            addToBot( Actions::BuffPlayer<PS::THOUSAND_CUTS>(up ? 2 : 1) );
            break;

        case CardId::CALTROPS:
            addToBot( Actions::BuffPlayer<PS::THORNS>(up ? 5 : 3) );
            break;

        case CardId::ENVENOM:
            addToBot( Actions::BuffPlayer<PS::ENVENOM>(1) );
            break;

        case CardId::FOOTWORK:
            addToBot( Actions::BuffPlayer<PS::DEXTERITY>(up ? 3 : 2) );
            break;

        case CardId::INFINITE_BLADES:
            addToBot( Actions::BuffPlayer<PS::INFINITE_BLADES>(1) );
            break;

        case CardId::NOXIOUS_FUMES:
            addToBot( Actions::BuffPlayer<PS::NOXIOUS_FUMES>(up ? 3 : 2) );
            break;

        case CardId::TOOLS_OF_THE_TRADE:
            addToBot( Actions::BuffPlayer<PS::TOOLS_OF_THE_TRADE>(1) );
            break;

        case CardId::WELL_LAID_PLANS:
            addToBot( Actions::BuffPlayer<PS::RETAIN_CARDS>(up ? 2 : 1) );
            break;

        // CardId::WRAITH_FORM is defined natively in STS lightspeed

        case CardId::BIASED_COGNITION: {
            addToBot( Actions::BuffPlayer<PS::FOCUS>(up ? 5 : 4) );
            addToBot( Actions::BuffPlayer<PS::BIAS>(1) );
            break;
        }

        case CardId::CAPACITOR: {
            addToBot( Action([&](BattleContext &b) {
                b.player.increaseOrbSlots(up ? 3 : 2);
            }) );
            break;
        }

        case CardId::CREATIVE_AI: {
            addToBot( Actions::BuffPlayer<PS::CREATIVE_AI>(1) );
            break;
        }

        case CardId::DEFRAGMENT: {
            addToBot( Actions::BuffPlayer<PS::FOCUS>(up ? 2 : 1) );
            break;
        }

        case CardId::ECHO_FORM: {
            addToBot( Actions::BuffPlayer<PS::ECHO_FORM>(1) );
            break;
        }

        case CardId::ELECTRODYNAMICS: {
            addToBot( Actions::BuffPlayer<PS::ELECTRO>(1) );
            addToBot( Action([&](BattleContext &b) {
                for (int i = 0; i < (up ? 3 : 2); ++i) {
                    b.player.channelOrb(b, Orb::LIGHTNING);
                }
            }) );
            break;
        }

        case CardId::HEATSINKS: {
            addToBot( Actions::BuffPlayer<PS::HEATSINKS>(up ? 2 : 1) );
            break;
        }

        case CardId::HELLO_WORLD: {
            addToBot( Actions::BuffPlayer<PS::HELLO_WORLD>(1) );
            break;
        }

        case CardId::LOOP: {
            addToBot( Actions::BuffPlayer<PS::LOOP>(1) );
            break;
        }

        case CardId::MACHINE_LEARNING: {
            addToBot( Actions::BuffPlayer<PS::MACHINE_LEARNING>(up ? 2 : 1) );
            break;
        }

        case CardId::SELF_REPAIR: {
            addToBot( Actions::BuffPlayer<PS::SELF_REPAIR>(up ? 10 : 7) );
            break;
        }

        case CardId::STATIC_DISCHARGE: {
            addToBot( Actions::BuffPlayer<PS::STATIC_DISCHARGE>(up ? 2 : 1) );
            break;
        }

        case CardId::STORM: {
            addToBot( Actions::BuffPlayer<PS::STORM>(up ? 2 : 1) );
            break;
        }


        // ********************* WATCHER POWERS *********************

        case CardId::DEVOTION: {
            player.buff<PS::DEVOTION>(up ? 3 : 2);
            break;
        }

        case CardId::NIRVANA: {
            player.buff<PS::NIRVANA>(up ? 2 : 1);
            break;
        }

        case CardId::RUSHDOWN: {
            player.buff<PS::RUSHDOWN>(1);
            break;
        }

        case CardId::MENTAL_FORTRESS: {
            player.buff<PS::MENTAL_FORTRESS>(up ? 4 : 3);
            break;
        }

        case CardId::ESTABLISHMENT: {
            player.buff<PS::ESTABLISHMENT>(1);
            break;
        }

        case CardId::FORESIGHT: {
            player.buff<PS::FORESIGHT>(up ? 4 : 3);
            break;
        }

        case CardId::BATTLE_HYMN: {
            player.buff<PS::BATTLE_HYMN>(up ? 2 : 1);
            break;
        }

        case CardId::FASTING: {
            player.buff<PS::FASTING>(up ? 4 : 3);
            break;
        }

        case CardId::LIKE_WATER: {
            player.buff<PS::LIKE_WATER>(up ? 7 : 5);
            break;
        }

        case CardId::MASTER_REALITY: {
            player.buff<PS::MASTER_REALITY>(1);
            break;
        }

        case CardId::DEVA_FORM: {
            player.buff<PS::DEVA>(1);
            break;
        }

        case CardId::STUDY: {
            player.buff<PS::STUDY>(up ? 2 : 1);
            break;
        }

        case CardId::BUFFER: {
            player.buff<PS::BUFFER>(up ? 2 : 1);
            break;
        }

        case CardId::OMEGA: {
            player.buff<PS::OMEGA>(1);
            break;
        }

        default:
#ifdef sts_asserts
            std::cerr << "attempted to use unimplemented card: " << c.getName() << std::endl;
            assert(false);
#endif
            break;
    }

}


void BattleContext::onUseAttackCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    auto &p = player;
    ++p.attacksPlayedThisTurn;

    // ********* Powers onUseCard *********

    if (p.hasStatus<PS::AFTER_IMAGE>()) {
        addToBot(Actions::GainBlock(p.getStatus<PS::AFTER_IMAGE>()));
    }

    if (!item.purgeOnUse && p.hasStatus<PS::DOUBLE_TAP>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::DOUBLE_TAP>();
    }

    if (!item.purgeOnUse && p.hasStatus<PS::DUPLICATION>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::DUPLICATION>();
    }

    const auto echoForm = p.getStatus<PS::ECHO_FORM>();
    if (!item.purgeOnUse && echoForm) {
        const bool echoFormActive = player.cardsPlayedThisTurn - player.echoFormCardsDoubled <= echoForm;
        if (echoFormActive) {
            ++player.echoFormCardsDoubled;
            queuePurgeCard(c, item.target);
        }
    }

    if (p.hasStatus<PS::PANACHE>() && --p.panacheCounter <= 0) {
        addToBot( Actions::DamageAllEnemy(p.getStatus<PS::PANACHE>()) );
    }

    if (p.hasStatus<PS::RAGE>()) {
        addToBot( Actions::GainBlock(p.getStatus<PS::RAGE>()) );
    }

    if (p.hasStatus<PS::VIGOR>()) {
        p.removeStatus<PS::VIGOR>();
    }

    if (p.hasStatus<PS::FREE_ATTACK_POWER>()) {
        p.decrementStatus<PS::FREE_ATTACK_POWER>();
    }

    if (p.hasStatus<PS::PEN_NIB>()) {
        // todo does this need to be added to bot?
        addToBot( Actions::RemoveStatus<PS::PEN_NIB>() );
    }

    // ********* Relics onUseCard *********
    // todo order of relics

    if (p.hasRelic<R::INK_BOTTLE>()) {
        p.inkBottleCounter++;
        if (p.inkBottleCounter == 10) {
            p.inkBottleCounter = 0;
            addToBot( Actions::DrawCards(1) );
        }
    }

    if (p.hasRelic<R::KUNAI>() && p.attacksPlayedThisTurn % 3 == 0) {
        addToBot( Actions::BuffPlayer<PS::DEXTERITY>(1) );
    }

    if (p.hasRelic<R::ORANGE_PELLETS>()) {
        p.orangePelletsCardTypesPlayed.set(static_cast<int>(CardType::ATTACK), true); // set bit 0 true
        if (p.orangePelletsCardTypesPlayed.all()) {
            p.orangePelletsCardTypesPlayed.reset();
            addToBot(Actions::RemovePlayerDebuffs());
        }
    }

    if (p.hasRelic<R::ORNAMENTAL_FAN>() && p.attacksPlayedThisTurn % 3 == 0) {
        addToBot( Actions::GainBlock(4) );
    }

    if (p.hasRelic<R::SHURIKEN>() && p.attacksPlayedThisTurn % 3 == 0) {
        addToBot( Actions::BuffPlayer<PS::STRENGTH>(1) );
    }

    if (p.hasRelic<R::NECRONOMICON>() && !p.haveUsedNecronomiconThisTurn && !item.freeToPlay && !item.purgeOnUse &&
        (c.costForTurn >= 2 || c.isXCost() && item.energyOnUse >= 2)) {
        queuePurgeCard(c, item.target);
        p.haveUsedNecronomiconThisTurn = true;
    }

    if (p.hasRelic<R::PEN_NIB>()) {
        ++p.penNibCounter;
        if (p.penNibCounter == 9) {
            addToBot( Actions::BuffPlayer<PS::PEN_NIB>(1) );
            p.penNibCounter = -1; // take note of this
        }
    }

    if (p.hasRelic<R::DUALITY>()) {
        addToBot(Actions::DualityAction());
    }

    if (p.hasRelic<R::NUNCHAKU>()) {
        if (++p.nunchakuCounter >= 10) {
            addToBot(Actions::GainEnergy(1));
            p.nunchakuCounter = 0;
        }
    }

    /*
     *  for each card in hand : TriggerOnCardPlayed
     *  for each card in discardPile : TriggerOnCardPlayed
     *  for each card in drawPile : TriggerOnCardPlayed
     */

    // ********* Enemy Powers onUseCard *********

    // todo Choke Power

    auto &m = monsters.arr[0];
    if (m.hasStatus<MS::SHARP_HIDE>()) {
        addToBot( Actions::DamagePlayer(m.getStatus<MS::SHARP_HIDE>()));
    }

}

void BattleContext::onUseSkillCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    auto &p = player;
    ++p.skillsPlayedThisTurn;

    // ********* Powers onUseCard *********

    if (p.hasStatus<PS::AFTER_IMAGE>()) {
        addToBot(Actions::GainBlock(p.getStatus<PS::AFTER_IMAGE>()));
    }

    if (!item.purgeOnUse && p.hasStatus<PS::BURST>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::BURST>();
    }

    if (!item.purgeOnUse && p.hasStatus<PS::DUPLICATION>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::DUPLICATION>();
    }

    const auto echoForm = p.getStatus<PS::ECHO_FORM>();
    if (!item.purgeOnUse && echoForm) {
        const bool echoFormActive = player.cardsPlayedThisTurn - player.echoFormCardsDoubled <= echoForm;
        if (echoFormActive) {
            ++player.echoFormCardsDoubled;
            queuePurgeCard(c, item.target);
        }
    }

    if (p.hasStatus<PS::HEX>()) {
        addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::DAZED), 1, true) );
    }

    if (p.hasStatus<PS::PANACHE>() && --p.panacheCounter <= 0) {
        addToBot( Actions::DamageAllEnemy(p.getStatus<PS::PANACHE>()) );
    }

    // todo Storm
    // todo Heatsinks
    // todo BirdFacedUrn

    // ********* Relics onUseCard *********
    // todo ink bottle/ ornamental fan need to be ordered i believe

    if (p.hasRelic<R::INK_BOTTLE>()) {
        p.inkBottleCounter++;
        if (p.inkBottleCounter == 10) {
            p.inkBottleCounter = 0;
            addToBot( Actions::DrawCards(1) );
        }
    }

    if (p.hasRelic<R::ORANGE_PELLETS>()) {
        p.orangePelletsCardTypesPlayed.set(static_cast<int>(CardType::SKILL), true); // set bit 0 true
        if (p.orangePelletsCardTypesPlayed.all()) {
            p.orangePelletsCardTypesPlayed.reset();
            addToBot(Actions::RemovePlayerDebuffs());
        }
    }

    if (p.hasRelic<R::LETTER_OPENER>()) {
        if (p.skillsPlayedThisTurn >= 3 &&  p.skillsPlayedThisTurn % 3 == 0) {
            addToBot(Actions::DamageAllEnemy(5));
        }
    }

    if (p.hasRelic<R::MUMMIFIED_HAND>()) {
        // todo
    }

    /*
     *  for each card in hand : TriggerOnCardPlayed
     *  for each card in discardPile : TriggerOnCardPlayed
     *  for each card in drawPile : TriggerOnCardPlayed
     */

    // ********* Enemy Powers onUseCard *********
    // todo Choke Power

    auto &m = monsters.arr[0];
    if (m.hasStatus<MS::ENRAGE>()) {
        m.buff<MS::STRENGTH>(m.getStatus<MS::ENRAGE>());
    }
}

void BattleContext::onUsePowerCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;
    auto &p = player;

    if (p.hasStatus<PS::AFTER_IMAGE>()) {
        addToBot(Actions::GainBlock(p.getStatus<PS::AFTER_IMAGE>()));
    }

    if (!item.purgeOnUse && p.hasStatus<PS::DUPLICATION>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::DUPLICATION>();
    }

    const auto echoForm = p.getStatus<PS::ECHO_FORM>();
    if (!item.purgeOnUse && echoForm) {
        const bool echoFormActive = player.cardsPlayedThisTurn - player.echoFormCardsDoubled <= echoForm;
        if (echoFormActive) {
            ++player.echoFormCardsDoubled;
            queuePurgeCard(c, item.target);
        }
    }

    if (p.hasStatus<PS::HEX>()) {
        addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::DAZED), 1, true) );
    }

    if (p.hasStatus<PS::PANACHE>() && --p.panacheCounter <= 0) {
        addToBot( Actions::DamageAllEnemy(p.getStatus<PS::PANACHE>()) );
    }

    // ********* Relics onUseCard *********

    if (p.hasRelic<R::BIRD_FACED_URN>()) {
        p.heal(2);
    }

    if (p.hasRelic<R::INK_BOTTLE>()) {
        p.inkBottleCounter++;
        if (p.inkBottleCounter == 10) {
            p.inkBottleCounter = 0;
            addToBot( Actions::DrawCards(1) );
        }
    }

    if (p.hasRelic<R::ORANGE_PELLETS>()) {
        p.orangePelletsCardTypesPlayed.set(static_cast<int>(CardType::POWER), true); // set bit 0 true
        if (p.orangePelletsCardTypesPlayed.all()) {
            p.orangePelletsCardTypesPlayed.reset();
            addToBot(Actions::RemovePlayerDebuffs());
        }
    }

    if (p.hasRelic<R::MUMMIFIED_HAND>()) {
        mummifiedHandOnUsePower();
    }

//    auto &m = monsters.optionMap[2];
//    if (m.hasStatusInternal<MS::CURIOSITY>()) {
//        m.buff<MS::STRENGTH>(m.getStatus<MS::CURIOSITY>());
//    }
}

void BattleContext::onUseStatusOrCurseCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;
    auto &p = player;

    if (p.hasStatus<PS::AFTER_IMAGE>()) {
        addToBot(Actions::GainBlock(p.getStatus<PS::AFTER_IMAGE>()));
    }

    if (!item.purgeOnUse && p.hasStatus<PS::DUPLICATION>()) {
        queuePurgeCard(c, item.target);
        p.decrementStatus<PS::DUPLICATION>();
    }

    const auto echoForm = p.getStatus<PS::ECHO_FORM>();
    if (!item.purgeOnUse && echoForm) {
        const bool echoFormActive = player.cardsPlayedThisTurn - player.echoFormCardsDoubled <= echoForm;
        if (echoFormActive) {
            ++player.echoFormCardsDoubled;
            queuePurgeCard(c, item.target);
        }
    }

    if (p.hasStatus<PS::HEX>()) {
        addToBot( Actions::MakeTempCardInDrawPile(CardInstance(CardId::DAZED), 1, true) );
    }

    if (p.hasStatus<PS::PANACHE>() && --p.panacheCounter <= 0) {
        addToBot( Actions::DamageAllEnemy(p.getStatus<PS::PANACHE>()) );
    }

    if (c.getType() == CardType::CURSE) {
        if (p.hasRelic<R::BLUE_CANDLE>()) {
            addToBot( Actions::PlayerLoseHp(1, true) );
            item.exhaustOnUse = true;
        }

    } else if (c.getType() == CardType::STATUS) {
        if (p.hasRelic<R::MEDICAL_KIT>()) {
            item.exhaustOnUse = true;
        }
    }

    if (p.hasRelic<R::INK_BOTTLE>()) {
        p.inkBottleCounter++;
        if (p.inkBottleCounter == 10) {
            p.inkBottleCounter = 0;
            addToBot( Actions::DrawCards(1) );
        }
    }

}

void BattleContext::onAfterUseCard() {
    auto &item = curCardQueueItem;
    auto &c = item.card;

    if (item.triggerOnUse) {
        auto &m = monsters.arr[0];
        if (m.hasStatus<MS::TIME_WARP>()) {
            auto timeWarp = m.getStatus<MS::TIME_WARP>();
            if (timeWarp == 11) {
                m.setStatus<MS::TIME_WARP>(0);
                m.buff<MS::STRENGTH>(2);
                callEndTurnEarlySequence();

            } else {
                m.setStatus<MS::TIME_WARP>(timeWarp + 1);
                ++timeWarp;
            }
        }
        if (m.hasStatus<MS::SLOW>()) {
            m.buff<MS::SLOW>(1);
        }
        if (m.hasStatus<MS::BEAT_OF_DEATH>()) {
            addToBot( Actions::DamagePlayer(m.getStatus<MS::BEAT_OF_DEATH>()) );
        }
    }

    if (item.purgeOnUse) {
        return;
    }

    bool rebound = false;
    c.freeToPlayOnce = false;

    if (c.getType() == CardType::POWER) {
        c.id = CardId::INVALID;
        return;
    }

    if (player.hasStatus<PS::REBOUND>()) {
        if (player.getStatus<PS::REBOUND>() == 1) {
            rebound = true;
            player.setHasStatus<PS::REBOUND>(false);

        } else {
            player.setStatusValueNoChecks<PS::REBOUND>(1);
        }
    }

    bool spoonProc = false;
    if (item.exhaustOnUse && player.hasRelic<R::STRANGE_SPOON>()) {
        spoonProc = cardRandomRng.randomBoolean();
    }

    if (item.exhaustOnUse && !spoonProc) {
        triggerAndMoveToExhaustPile(c);

    } else {
        // targetCard.exhaustOnUseOnce = false;
        // targetCard.dontTriggerOnUseCard = false;
        // this.addToBot(new HandCheckAction());

        if (rebound) { // these methods all call resetCardBeforeMoving but it looks unnecessary
            cards.moveToDrawPileTop(c);

        } else if (c.id == CardId::TANTRUM) {
            cards.shuffleIntoDrawPile(cardRandomRng, c);

        } else {
            // The game calls OnCardDrawOrDiscard here which only does two things:
            // 1. sets the damage on all shivs in hand if you have accuracy power,
            // 2. sets the cost of all skills in hand to -9 if you have corruption
            // we will handle these tasks elsewhere
            cards.moveToDiscardPile(c);
        }
    }
    // TODO these must be done in the cards method itself
    // todo make Accuracy part of calculateBaseDamage

    // this.targetCard.exhaustOnUseOnce = false;
    //            this.targetCard.dontTriggerOnUseCard = false;
    //            this.addToBot(new HandCheckAction());
}

// **********************

void BattleContext::endTurn() {
#ifdef sts_assert
    assert(!endTurnQueued);
#endif //sts_assert
    // todo probably dont need a card queue item for this
    energyWasted += player.energy;
    cardQueue.pushBack(CardQueueItem::endTurnItem());
    endTurnQueued = true;
}

void BattleContext::callEndOfTurnActions() {

    // ********************* Player Relics OnPlayerEndTurn *********************

    if (player.hasRelic<R::CLOAK_CLASP>()) {
        addToBot( Actions::GainBlock(cards.cardsInHand) );
    }

    if (player.hasRelic<R::FROZEN_CORE>()) {
        if (player.hasEmptyOrb()) {
            player.channelOrb(*this, Orb::FROST);
        }
    }

    if (player.hasRelic<R::NILRYS_CODEX>()) {
        addToBot(Actions::CodexAction());
    }

    if (player.hasRelic<R::ORICHALCUM>()) {
        if (player.block <= 0) {
            addToTop(Actions::GainBlock(6));
        }
    }

    if (player.hasRelic<R::STONE_CALENDAR>()) {
        if (turn == 6) {
            addToBot(Actions::DamageAllEnemy(52));
        }
    }

    // ********************* Player Powers AtEndOfTurnPreEndTurnCards *********************

    if (player.hasStatus<PS::METALLICIZE>()) {
        addToBot( Actions::GainBlock( player.getStatus<PS::METALLICIZE>()) );
    }

    if (player.hasStatus<PS::PLATED_ARMOR>()) {
        addToBot( Actions::GainBlock(player.getStatus<PS::PLATED_ARMOR>()) );
    }

    if (player.hasStatus<PS::LIKE_WATER>() && player.stance == Stance::CALM) {
        addToBot( Actions::GainBlock(player.getStatus<PS::LIKE_WATER>()) );
    }

    if (player.orbSlots) {
        addToBot(Actions::TriggerEndOfTurnOrbsAction());
    }

    // todo for cards in hand call triggerOnEndOfTurnForPlayingCard

    for (int i = 0; i < cards.cardsInHand; ++i) {

        const auto &c = cards.hand[i];

        switch (c.id) {
            case CardId::BURN:
            case CardId::DECAY:
            case CardId::DOUBT:
            case CardId::SHAME:
            case CardId::REGRET: {
                CardQueueItem item;
                item.triggerOnUse = false;
                item.regretCardCount = cards.cardsInHand;
                item.card = c;
                addToBotCard(item);
                break;
            }
            default:
                break;
        }
    }

    // todo stance onEndOfTurn
}

void BattleContext::onTurnEnding() {
    // AbstractRoom endTurn()

    // ********************* Player Powers atEndOfTurn *********************
    player.applyEndOfTurnPowers(*this);
    addToBot(Actions::ClearCardQueue());
    addToBot(Actions::DiscardAtEndOfTurn());

    // todo reset card attributes here in draw, discard and hand
    cards.resetAttributesAtEndOfTurn();

    addToBot(Actions::UnnamedEndOfTurnAction());
}

void BattleContext::callEndTurnEarlySequence() {
    while (!cardQueue.isEmpty()) {
        auto item = cardQueue.popFront();
        if (item.autoplay && !item.purgeOnUse) {
            addToBot( Actions::TimeEaterPlayCardQueueItem(item) );
        }
    }
    addToTopCard(CardQueueItem::endTurnItem());
    endTurnQueued = true;
}

void BattleContext::applyEndOfRoundPowers() {
    for (int i = 0; i < monsters.monsterCount; i++) {
        auto &m = monsters.arr[i];
        if (m.isDying() || m.isEscaping()) {
            continue;
        }
        m.applyEndOfTurnTriggers(*this);
    }

    player.applyAtEndOfRoundPowers();

    for (int i = 0; i < monsters.monsterCount; i++) {
        auto &m = monsters.arr[i];
        if (m.isDying() || m.isEscaping()) {
            continue;
        }
        m.applyEndOfRoundPowers(*this);
    }
}

void BattleContext::afterMonsterTurns() {
    // ********* Enemy powers atEndOfRound *********
    if (!skipMonsterTurn) {
        applyEndOfRoundPowers();
    }

    ++turn;
    skipMonsterTurn = false;
    turnHasEnded = false;

    // player stance atStartOfTurn
    if (player.stance == Stance::DIVINITY) {
        addToBot(Actions::ChangeStance(Stance::NEUTRAL));
    }

    player.applyStartOfTurnRelics(*this);

    // player applyStartOfTurnPreDrawCards() // no cards implement this
    // player.applyStartOfTurnCards() // only Eviscerate implements this

    player.applyStartOfTurnPowers(*(this));

    // player.applyStartOfTurnOrbs()
    //for each orb : OnStartOfTurn
    //if have relic cables: apply orb[0].OnStartOfTurn again

    if (player.hasStatus<PS::BARRICADE>()) {

    } else if (player.hasStatus<PS::BLUR>()) {
        player.decrementStatus<PS::BLUR>();

    } else if (player.hasRelic<R::CALIPERS>()) {
        player.block = std::max(0, player.block-15);

    } else {
        player.block = 0;
    }

    if (isBattleOver) {
        return;
    }

    addToBot(Actions::DrawCards(player.cardDrawPerTurn)); // in this action, an effect queue item is added to rechard energy lol

    if (player.hasStatus<PS::DRAW_REDUCTION>()) {
        if (player.wasJustApplied<PS::DRAW_REDUCTION>()) {
            player.setJustApplied<PS::DRAW_REDUCTION>(false);
        } else {
            player.removeStatus<PS::DRAW_REDUCTION>();
            ++player.cardDrawPerTurn;
        }
    }

    player.applyStartOfTurnPostDrawRelics(*this);
    player.applyStartOfTurnPostDrawPowers(*this);

    // this has to be here because some relics check this info.
    player.cardsPlayedThisTurn = 0;
    player.attacksPlayedThisTurn = 0;
    player.skillsPlayedThisTurn = 0;
    player.cardsDiscardedThisTurn = 0;

    player.rechargeEnergy(*this); // this is called by the PlayerTurnEffect in game, I think it can be done here
}

void BattleContext::obtainPotion(Potion p) {
    if (potionCount == potionCapacity || player.hasRelic<R::SOZU>()) {
        return; // no empty potion slots
    }

    for (int i = 0; i < potionCapacity; ++i) {
        if (potions[i] == Potion::EMPTY_POTION_SLOT) {
            ++potionCount;
            potions[i] = p;
            return;
        }
    }

//  todo prevent this, do nothing for now
//    assert(false); // unreachable
}

void BattleContext::discardPotion(int idx) {
    potions[idx] = Potion::EMPTY_POTION_SLOT;
    --potionCount;
}

void BattleContext::drinkPotion(int idx, int target) {
    const bool hasBark = player.hasRelic<R::SACRED_BARK>();
    const Potion p = potions[idx];
    discardPotion(idx);

    // todo - dont need to add to bot because always will have nothing in actionQueue?

    switch (p) {
        case Potion::AMBROSIA:
            addToBot(Actions::ChangeStance(Stance::DIVINITY));
            break;

        case Potion::ANCIENT_POTION:
            addToBot(Actions::BuffPlayer<PS::ARTIFACT>(hasBark ? 2 : 1));
            break;

        case Potion::ATTACK_POTION:
            addToBot(Actions::DiscoveryAction(CardType::ATTACK, hasBark ? 2 : 1));
            break;

        case Potion::BLESSING_OF_THE_FORGE:
            addToBot(Actions::UpgradeAllCardsInHand());
            break;

        case Potion::BLOCK_POTION:
            addToBot(Actions::GainBlock(hasBark ? 24 : 12));
            break;


        case Potion::BLOOD_POTION: {
            int healAmt = static_cast<int>((static_cast<float>(player.maxHp * (hasBark ? 20 : 40)) / 100.0f));
            addToBot(Actions::HealPlayer(healAmt));
            break;
        }

        case Potion::BOTTLED_MIRACLE:
            addToBot(Actions::MakeTempCardInHand(CardId::MIRACLE, false, hasBark ? 4 : 2));
            break;

        case Potion::COLORLESS_POTION:
            addToBot( Actions::DiscoveryAction(CardType::STATUS, hasBark ? 2 : 1) ); // status card type is being used to indicate colorless
            break;

        case Potion::CULTIST_POTION:
            addToBot(Actions::BuffPlayer<PS::RITUAL>(hasBark ? 2 : 1));
            break;

        case Potion::CUNNING_POTION:
            addToBot(Actions::MakeTempCardInHand(CardId::SHIV, true, hasBark ? 6 : 3));
            break;

        case Potion::DEXTERITY_POTION:
            addToBot(Actions::BuffPlayer<PS::DEXTERITY>(hasBark ? 4 : 2));
            break;

        case Potion::DISTILLED_CHAOS: {
            const auto cardsToPlay = hasBark ? 6 : 3;
            for (int i = 0; i < cardsToPlay; ++i) {
                addToBot( Actions::PlayTopCard(monsters.getRandomMonsterIdx(cardRandomRng), false) );
            }
            break;
        }

        case Potion::DUPLICATION_POTION:
            addToBot(Actions::BuffPlayer<PS::DUPLICATION>(hasBark ? 2 : 1));
            break;

        case Potion::ELIXIR_POTION:
            addToBot( Actions::ExhaustMany(10) );
            break;

        case Potion::ENERGY_POTION:
            addToBot(Actions::GainEnergy(hasBark ? 4 : 2));
            break;

        case Potion::ENTROPIC_BREW: {
            for (int i = 0; i < potionCapacity; ++i) {
                Potion randomPotion = returnRandomPotion(potionRng, player.cc, true);
                obtainPotion(randomPotion);
            }
            break;
        }

        case Potion::ESSENCE_OF_DARKNESS:
            addToBot( Actions::EssenceOfDarkness(hasBark ? 2 : 1) );
            break;

        case Potion::ESSENCE_OF_STEEL:
            addToBot( Actions::BuffPlayer<PS::PLATED_ARMOR>(hasBark ? 8 : 4) );
            break;

        case Potion::EXPLOSIVE_POTION: {
            const auto damage = hasBark ? 20 : 10;
            addToBot( Actions::DamageAllEnemy(damage) ); // todo does not having player be owner here matter?
            break;
        }

        case Potion::FEAR_POTION:
            addToBot( Actions::DebuffEnemy<MS::VULNERABLE>(target, hasBark ? 6 : 3, false) );
            break;

        case Potion::FIRE_POTION:
            addToBot( Actions::DamageEnemy(target, hasBark ? 40 : 20) );
            break;

        case Potion::FLEX_POTION:
            addToBot( Actions::BuffPlayer<PS::STRENGTH>(hasBark ? 10 : 5) );
            addToBot( Actions::DebuffPlayer<PS::LOSE_STRENGTH>(hasBark ? 10 : 5) );
            break;

        case Potion::FOCUS_POTION:
            addToBot(Actions::BuffPlayer<PS::FOCUS>(hasBark ? 4 : 2));
            break;

        case Potion::FRUIT_JUICE:
            player.increaseMaxHp(hasBark ? 10 : 5);
            break;

        case Potion::GAMBLERS_BREW:
            addToBot( Actions::GambleAction() );
            break;

        case Potion::GHOST_IN_A_JAR:
            addToBot(Actions::BuffPlayer<PS::INTANGIBLE>(hasBark ? 2 : 1));
            break;

        case Potion::HEART_OF_IRON:
            addToBot(Actions::BuffPlayer<PS::METALLICIZE>(hasBark ? 12 : 6));
            break;

        case Potion::LIQUID_BRONZE:
            addToBot(Actions::BuffPlayer<PS::THORNS>(hasBark ? 6 : 3));
            break;

        case Potion::LIQUID_MEMORIES:
            addToBot( Actions::BetterDiscardPileToHandAction(hasBark ? 2 : 1, CardSelectTask::LIQUID_MEMORIES_POTION) );
            break;

        case Potion::POISON_POTION:
            addToBot( Actions::DebuffEnemy<MS::POISON>(target, hasBark ? 12 : 6) );
            break;

        case Potion::POTION_OF_CAPACITY:
            addToBot( Actions::IncreaseOrbSlots(hasBark ? 4 : 2) );
            break;

        case Potion::POWER_POTION:
            haveUsedDiscoveryAction = true;
            addToBot( Actions::DiscoveryAction(CardType::POWER, hasBark ? 2 : 1) );
            break;

        case Potion::REGEN_POTION:
            addToBot(Actions::BuffPlayer<PS::REGEN>(hasBark ? 10 : 5));
            break;

        case Potion::SKILL_POTION:
            addToBot(Actions::DiscoveryAction(CardType::SKILL, hasBark ? 2 : 1));
            break;

        case Potion::SMOKE_BOMB:
            // todo
            break;

        case Potion::SNECKO_OIL:
            addToBot(Actions::DrawCards(hasBark ? 10 : 5));
            addToBot(Actions::RandomizeHandCost());
            break;

        case Potion::SPEED_POTION:
            addToBot(Actions::BuffPlayer<PS::DEXTERITY>(hasBark ? 10 : 5));
            addToBot(Actions::DebuffPlayer<PS::LOSE_DEXTERITY>(hasBark ? 10 : 5));
            break;

        case Potion::STANCE_POTION:
            addToBot(Actions::SetState(InputState::CHOOSE_STANCE_ACTION));
            break;

        case Potion::STRENGTH_POTION:
            addToBot(Actions::BuffPlayer<PS::STRENGTH>(hasBark ? 4 : 2));
            break;

        case Potion::SWIFT_POTION:
            addToBot(Actions::DrawCards(hasBark ? 6 : 3));
            break;

        case Potion::WEAK_POTION:
            addToBot(Actions::DebuffEnemy<MS::WEAK>(target, hasBark ? 6 : 3, false));
            break;

        case Potion::INVALID:
        case Potion::EMPTY_POTION_SLOT:
        case Potion::FAIRY_POTION:
        default:
            std::cerr << seed << "invalid drink potion: " << static_cast<int>(p) << std::endl;
            assert(false);
            break;
    }

}

void BattleContext::drawCards(int count) {
    if (count <= 0 ||
        player.hasStatus<PS::NO_DRAW>() ||
         cards.drawPile.size() + cards.discardPile.size() == 0 ||
         cards.cardsInHand == 10 ) {
        return;
    }

    int amountToDraw = std::min(10-cards.cardsInHand, count);

    if (cards.drawPile.size() < amountToDraw) {
        const auto temp = amountToDraw-static_cast<int>(cards.drawPile.size());
        addToTop( Actions::DrawCards(temp) );
        onShuffle();
        addToTop( Actions::EmptyDeckShuffle() );

        if (!cards.drawPile.empty()) {
            drawCards(static_cast<int>(cards.drawPile.size())); // the game adds this to top
        }
        return;
    }

    cardsDrawn += amountToDraw; // statistic for monte carlo search
    cards.draw(*this, amountToDraw);
}

void BattleContext::discardAtEndOfTurn() {
    int retainCount = 0;
    for (int i = 0; i < cards.cardsInHand; ++i) {
        auto c = cards.hand[i];
        if (c.hasSelfRetain() || c.retain) {
            cards.limbo[retainCount++] = c;
        }
    }
    if (retainCount > 0) {
        addToTop(Actions::RestoreRetainedCards(retainCount));

        int placeIdx = 0;
        for (int i = 0; i < cards.cardsInHand; ++i) {
            auto c = cards.hand[i];
            if (c.hasSelfRetain() || c.retain) {
                continue;
            } else {
                cards.hand[placeIdx++] = cards.hand[i];
            }
        }
        cards.cardsInHand -= retainCount;
    }

    if (!player.hasRelic<R::RUNIC_PYRAMID>() && !player.hasStatus<PS::EQUILIBRIUM>()) {
        addToTop(Actions::DiscardAtEndOfTurnHelper());
    }

    for (int i = 0; i < cards.cardsInHand; ++i) {
        const auto &c = cards.hand[i];
        if (c.isEthereal()) {
            addToTop(Actions::ExhaustSpecificCardInHand(i, c.uniqueId)); // c.triggerOnEndOfPlayerTurn
        }
    }

}

void BattleContext::discardAtEndOfTurnHelper() {
    if (outcome != Outcome::UNDECIDED) {
        return;
    }

    int temp = cards.cardsInHand;
    for (int i = temp-1; i >= 0; --i) {
        cards.notifyRemoveFromHand(cards.hand[i]);
        cards.moveToDiscardPile(cards.hand[i]);
        ++player.cardsDiscardedThisTurn;
    }
    cards.cardsInHand = 0;
}

void BattleContext::chooseSetupCard(int handIdx) {
    auto c = cards.hand[handIdx];
    cards.removeFromHandAtIdx(handIdx);
    c.costForTurn = 0;
    cards.drawPile.push_back(c);
}

void BattleContext::chooseDiscardCards(const fixed_list<int,10> &idxs) {
    for (int i=0; i<idxs.size(); ++i) {
        auto c = cards.hand[idxs[i]];
        cards.removeFromHandAtIdx(idxs[i]);
        cards.moveToDiscardPile(c);
        onManualDiscard(c);
    }
}

void BattleContext::playTopCardInDrawPile(int monsterTargetIdx, bool exhausts) {
    if (cards.drawPile.empty()) {
        if (!cards.discardPile.empty()) {
            addToTop( Actions::PlayTopCard(monsterTargetIdx, exhausts) );
            addToTop( Actions::EmptyDeckShuffle() );
        }
        return;
    }

    CardQueueItem item(cards.popFromDrawPile(), monsterTargetIdx, player.energy);
    item.exhaustOnUse = exhausts;
    item.autoplay = true;
    item.freeToPlay = true; // todo remove the autoplay boolean? added this instead
    addToTopCard(item);
}

void BattleContext::moveToHandHelper(CardInstance c) {
    if (cards.cardsInHand < 10) {
        if (player.hasStatus<PS::CORRUPTION>() && c.getType() == CardType::SKILL) {
            c.setCostForTurn(-9);
        }
        cards.moveToHand(c);
    } else {
        cards.moveToDiscardPile(c);
    }
}

void BattleContext::exhaustSpecificCardInHand(int idx, std::int16_t uniqueId) {

    int foundIdx = -1;

    if (idx < cards.cardsInHand && cards.hand[idx].uniqueId == uniqueId) {
        foundIdx = idx;
    } else {
        for (int i = 0; i < cards.cardsInHand; ++i) {
            if (cards.hand[idx].uniqueId == uniqueId) {
               foundIdx = i;
               break;
            }
        }
    }

    if (foundIdx == -1) {
        std::cerr << "exhaustSpecificCardInHand: card not found in hand\n";
        return;
    }

    cards.notifyRemoveFromHand(cards.hand[foundIdx]);
    triggerAndMoveToExhaustPile(cards.hand[foundIdx]);
    --cards.cardsInHand;

    for (int i = foundIdx; i < cards.cardsInHand; ++i) {
        cards.hand[i] = cards.hand[i+1];
    } // todo fixed the cached variables in cardmanager
}

void BattleContext::restoreRetainedCards(int count) {
    for (int i = 0; i < count; ++i) {
        auto &c = cards.limbo[i];
        // check that c retained or self retained?
        c.retain = false;
        cards.hand[cards.cardsInHand++] = c;
    }
}

void BattleContext::exhaustTopCardInHand() {
    if (cards.cardsInHand <= 0) {
        std::cerr << "exhaustTopCardInHand: no cards in hand";
        return;
    }

    auto &c = cards.hand[--cards.cardsInHand];
    cards.notifyRemoveFromHand(c);
    triggerAndMoveToExhaustPile(c);
}

//void BattleContext::incrementDiscard() { // not for end of turn
//    player.cardsDiscardedThisTurn++;
//    if (!turnHasEnded) {
//        // todo
//    }
//
////    ++totalDiscardedThisTurn;
////    if (!AbstractDungeon.actionManager.turnHasEnded && !endOfTurn) {
////        AbstractDungeon.player.updateCardsOnDiscard();
////        Iterator var1 = AbstractDungeon.player.relics.iterator();
////
////        while(var1.hasNext()) {
////            AbstractRelic r = (AbstractRelic)var1.next();
////            r.onManualDiscard();
////        }
////    }
//}

void BattleContext::triggerOnEndOfTurnForPlayingCards() {
//
//    bool foundCurse;
//    do {
//        foundCurse = false;
//
//        for (int i = 0; i <= hand.size(); ++i) {
//            switch (hand[i].id) {
//                case CardId::DECAY:
//                    addToTop(Actions::DamagePlayer(2));
//                    foundCurse = true;
//                    break;
//
//                case CardId::DOUBT:
//                    addToTop( Actions::DebuffPlayer<PS::WEAK>(1) );
//                    foundCurse = true;
//                    break;
//
//                case CardId::SHAME:
//                    addToTop( Actions::DebuffPlayer<PS::FRAIL>(1) );
//                    foundCurse = true;
//                    break;
//
//                case CardId::REGRET:
//                    addToTop( Actions::PlayerLoseHp(hand.size(), true) );
//                    foundCurse = true;
//                    break;
//
//                case CardId::BURN:
//                    addToTop( Actions::DamagePlayer(hand[i].upgraded ? 4 : 2) );
//                    foundCurse = true;
//                    break;
//
//                default:
//                    break;
//            }
//
//            if (foundCurse) {
//                hand.removeCardAtIdx(i);
//            }
//
//        }
//
//    } while (foundCurse);

}

void BattleContext::triggerOnOtherCardPlayed(const CardInstance &usedCard) {
    int painCount = cards.handPainCount;
    if (usedCard.getId() == CardId::PAIN) {
        --painCount;
    }
    for (int i = 0; i < painCount; ++i) {
        addToTop(Actions::PlayerLoseHp(1));
    }

    const auto thousandCuts = player.getStatus<PS::THOUSAND_CUTS>();
    if (thousandCuts) {
        addToBot(Actions::DamageAllEnemy(thousandCuts));
    }
}

int BattleContext::calculateCardDamage(const CardInstance &card, int targetIdx, int baseDamage) const {

    auto damage = static_cast<float>(baseDamage);

    // ****** Player Relics AtDamageModify ******

    if (player.hasRelic<R::STRIKE_DUMMY>() && card.isStrikeCard()) {
        damage += 3;
    }

    if (player.hasRelic<R::WRIST_BLADE>() && card.costForTurn == 0) {
        damage += 4;
    }


    // ****** Player Powers AtDamageGive ******

    damage += static_cast<float>(player.getStatus<PS::STRENGTH>());

    if (player.hasStatus<PS::VIGOR>()) {
        damage += static_cast<float>(player.getStatus<PS::VIGOR>());
    }

    if (player.hasStatus<PS::DOUBLE_DAMAGE>()) {
        damage *= 2;
    }

    if (player.hasStatus<PS::PEN_NIB>()) {
        damage *= 2;
    }

    if (player.hasStatus<PS::WEAK>()) {
        damage *= .75f;
    }

    // ****** Stance AtDamageGive ******

    if (player.stance == Stance::WRATH) {
        damage *= 2;
    } else if (player.stance == Stance::DIVINITY) {
        damage *= 3;
    }

    // ****** Enemy Powers AtDamageReceive ******
    const Monster &monster = monsters.arr[targetIdx];

    if (monster.hasStatus<MS::SLOW>()) {
        damage *= 1 + static_cast<float>(monster.getStatus<MS::SLOW>()) * 0.1f;
    }

    if (monster.hasStatus<MS::VULNERABLE>()) {
        if (player.hasRelic<R::PAPER_PHROG>()) {
            damage *= 1.75f;
        } else {
            damage *= 1.5f;
        }
    }


    // ****** Player Powers AtDamageGiveFinal ****** (none ?)
    // ****** Monster Powers AtDamageReceiveFinal ******

    if (monster.hasStatus<MS::FLIGHT>()) {
        damage *= .5;
    }

    if (monster.hasStatus<MS::INTANGIBLE>()) {
        damage = std::max(damage, 1.0f);
    }

    return std::max(0, static_cast<int>(damage));
}

int BattleContext::calculateCardBlock(int baseBlock) const {
    if (player.hasStatus<PS::NO_BLOCK>()) {
        return 0;
    }

    int block = baseBlock;
    if (player.hasStatus<PS::DEXTERITY>()) {
        block = std::max(0, block + player.getStatus<PS::DEXTERITY>());
    }

    if (player.hasStatus<PS::FRAIL>()) {
        return block * 3 / 4;
    }

    return block;
}

void BattleContext::queuePurgeCard(const CardInstance &c, int target) {
    CardQueueItem item;
    item.card = c;
    item.purgeOnUse = true;
    item.target = target;
    item.energyOnUse = curCardQueueItem.energyOnUse;
    item.ignoreEnergyTotal = true;
    item.autoplay = true;
    addPurgeCardToCardQueue(item);
}

void BattleContext::addPurgeCardToCardQueue(const CardQueueItem &item) {
    if (cardQueue.size > 0) {
        auto temp = cardQueue.front();
        cardQueue.front() = item;
        cardQueue.pushFront(temp);
    } else {
        cardQueue.pushFront(item);
    }

}

void BattleContext::noOpRollMove() {
    aiRng.random(99);
}

void BattleContext::onManualDiscard(const CardInstance &c) {
    if (c.getId() == CardId::TACTICIAN) {
        player.gainEnergy(c.isUpgraded() ? 2 : 1);
    } else if (c.getId() == CardId::REFLEX) {
        addToBot( Actions::DrawCards(c.isUpgraded() ? 3 : 2) );
    }
}

void BattleContext::onShuffle() {
    if (player.hasRelic<R::THE_ABACUS>()) {
        addToBot( Actions::GainBlock(6) );
    }

    if (player.hasRelic<R::MELANGE>()) {
//        addToBot(Actions::SetState(InputState::SCRY, 3) ); // TODO SCRY Action
    }

    if (player.hasRelic<R::SUNDIAL>()) {
        if (player.sundialCounter == 2) {
            player.sundialCounter = 0;
            addToBot( Actions::GainEnergy(2) );
        } else {
            ++player.sundialCounter;
        }
    }
}

void BattleContext::triggerAndMoveToExhaustPile(CardInstance c) {
    // player relics onExhaust
    // player powers onExhaust
    // (the card).triggerOnExhaust

    if (player.hasRelic<R::CHARONS_ASHES>()) {
        addToTop(Actions::DamageAllEnemy(3));
    }

    if (player.hasRelic<R::DEAD_BRANCH>()){
        CardId id = getTrulyRandomCardInCombat(cardRandomRng, player.cc);
        addToBot(Actions::MakeTempCardInHand(id));
    }

    if (player.hasStatus<PS::DARK_EMBRACE>()) {
        addToBot(Actions::DrawCards(player.getStatus<PS::DARK_EMBRACE>()));
    }

    if (player.hasStatus<PS::FEEL_NO_PAIN>()) {
        addToBot(Actions::GainBlock(player.getStatus<PS::FEEL_NO_PAIN>()));
    }

    if (c.getId() == CardId::NECRONOMICURSE) {
        addToBot(Actions::MakeTempCardInHand(CardId::NECRONOMICURSE));
    }

    if (c.getId() == CardId::SENTINEL) {
        player.gainEnergy(c.isUpgraded() ? 3 : 2); // the game adds to bot here
    }

    cards.moveToExhaustPile(c);
}

void BattleContext::mummifiedHandOnUsePower() {
    fixed_list<int,10> matchingIdxList;

    for (int i = 0; i < cards.cardsInHand; ++i) {
        const auto &c = cards.hand[i];
        bool canPick = c.cost > 0 && c.costForTurn > 0 && !c.freeToPlayOnce;
        if (canPick) {
            matchingIdxList.push_back(i);
        }
    }

    if (matchingIdxList.empty()) {
        return;
    }

    for (int i = matchingIdxList.size()-1; i >= 0; --i) {
        const auto uniqueId = cards.hand[matchingIdxList[i]].getUniqueId();
        if (cardQueue.containsCardWithId(uniqueId)) {
            matchingIdxList.remove(i);
        }
    }

    if (matchingIdxList.empty()) {
        return;
    }

    const int selectedListIdx = cardRandomRng.random(0,matchingIdxList.size()-1);
    const int selectedHandIdx = matchingIdxList[selectedListIdx];
    cards.hand[selectedHandIdx].setCostForTurn(0);
}

void BattleContext::openDiscoveryScreen(std::array<CardId, 3> discoveryCards, int copyCount) {
    inputState = InputState::CARD_SELECT;
    cardSelectInfo.cardSelectTask = CardSelectTask::DISCOVERY;
    cardSelectInfo.pickCount = 1;
    cardSelectInfo.canPickAnyNumber = false;
    cardSelectInfo.canPickZero = false;
    cardSelectInfo.cards = discoveryCards;
    cardSelectInfo.discovery_CopyCount() = copyCount;
}

void BattleContext::openSimpleCardSelectScreen(CardSelectTask task, int count) {
    inputState = InputState::CARD_SELECT;
    cardSelectInfo.cardSelectTask = task;
    cardSelectInfo.pickCount = count;
    cardSelectInfo.canPickAnyNumber = false;
    cardSelectInfo.canPickZero = false;
}



void BattleContext::chooseArmamentsCard(int handIdx) {
    // todo cleaner solution

    fixed_list<CardInstance,10> validCards;
    fixed_list<CardInstance,10> invalidCards;
    for (int i = 0; i < cards.cardsInHand; ++i) {
        const auto &c = cards.hand[i];
        if (i == handIdx) {
            continue;
        }
        if (c.canUpgrade()) {
            validCards.push_back(c);
        } else {
            invalidCards.push_back(c);
        }
    }

    CardInstance cardToUpgrade = cards.hand[handIdx];
    cardToUpgrade.upgrade();

    int i = 0;
    for (auto c : validCards) {
        cards.hand[i++] = c;
    }
    cards.hand[i++] = cardToUpgrade;
    for (auto c : invalidCards) {
        cards.hand[i++] = c;
    }

}

void BattleContext::chooseCodexCard(CardId id) {
    CardInstance c(id);
    c.uniqueId = static_cast<std::int16_t>(cards.nextUniqueCardId++);
    cards.notifyAddCardToCombat(c);
    cards.shuffleIntoDrawPile(cardRandomRng, c);
}

void BattleContext::chooseDualWieldCard(int handIdx) {

    // ISSUE-001: Dual Wield + Ritual Dagger interaction is inconsistent
    // See docs/KNOWN_ISSUES.md for details
    // - When no choice on which card to pick: first one changes card in deck
    // - When there IS a choice: neither changes the card in deck

    const int copyCount = cardSelectInfo.dualWield_CopyCount();
    CardInstance dualWieldCard = cards.hand[handIdx];

    // todo cleaner solution

    fixed_list<CardInstance,10> validCards;
    fixed_list<CardInstance,10> invalidCards;
    for (int i = 0; i < cards.cardsInHand; ++i) {
        const auto &c = cards.hand[i];
        if (i == handIdx) {
            continue;
        }
        if (c.getType() == CardType::ATTACK || c.getType() == CardType::POWER) {
            validCards.push_back(c);
        } else {
            invalidCards.push_back(c);
        }
    }


    int i = 0;
    for (auto c : validCards) {
        cards.hand[i++] = c;
    }
    for (auto c : invalidCards) {
        cards.hand[i++] = c;
    }

    dualWieldCard.uniqueId = static_cast<std::int16_t>(cards.nextUniqueCardId++); // dual wield buggy
    cards.hand[i++] = dualWieldCard;

    for (int x = 0; x < copyCount; ++x) {
        if (cards.cardsInHand + 1 <= CardManager::MAX_HAND_SIZE) {
            cards.createTempCardInHand(dualWieldCard);

        } else {
            cards.createTempCardInDiscard(dualWieldCard);

        }
    }

}

void BattleContext::chooseDiscardToHandCard(int discardIdx, bool forZeroCost) {
    CardInstance c = cards.discardPile[discardIdx];
    cards.removeFromDiscard(discardIdx);
    if (cardSelectInfo.cardSelectTask == CardSelectTask::LIQUID_MEMORIES_POTION) {
        c.setCostForTurn(0);
    }
    moveToHandHelper(c);
}

void BattleContext::chooseDiscoveryCard(CardId id) {
    const auto discoveryAmount = cardSelectInfo.data0;
    CardInstance c(id);
    c.setCostForTurn(0);

    for (int i = 0; i < discoveryAmount; ++i) {
        if (cards.cardsInHand + 1 <= CardManager::MAX_HAND_SIZE) {
            if (player.hasStatus<PS::CORRUPTION>() && c.getType() == CardType::SKILL) {
                c.setCostForTurn(-9);
            }
            cards.createTempCardInHand(c);

        } else {
            cards.createTempCardInDiscard(c);
        }
    }
}

void BattleContext::chooseExhaustOneCard(int handIdx) {
    auto c = cards.hand[handIdx];
    cards.removeFromHandAtIdx(handIdx);
    triggerAndMoveToExhaustPile(c);
}


void BattleContext::chooseExhumeCard(int exhaustIdx) {
    // todo game handles corruption here
    auto c = cards.exhaustPile[exhaustIdx];
    cards.removeFromExhaustPile(exhaustIdx);
    cards.notifyAddCardToCombat(c);

    moveToHandHelper(c);
}

void BattleContext::chooseForethoughtCard(int handIdx) {
    if (cards.hand[handIdx].cost > 0) {
        cards.hand[handIdx].freeToPlayOnce = true;
    }

    cards.insertToDrawPile(0, cards.hand[handIdx]);
    cards.removeFromHandAtIdx(handIdx);
}

void BattleContext::chooseHeadbuttCard(int discardIdx) {
#ifdef sts_asserts
    assert(discardIdx >= 0 && discardIdx < cards.discardPile.size());
#endif
    cards.moveToDrawPileTop(cards.discardPile[discardIdx]);
    cards.removeFromDiscard(discardIdx);
}

void BattleContext::chooseRecycleCard(int handIdx) {
    // todo
}

void BattleContext::chooseWarcryCard(int handIdx) {
#ifdef sts_asserts
    assert(handIdx >= 0 && handIdx < cards.cardsInHand);
#endif
    cards.moveToDrawPileTop(cards.hand[handIdx]);
    cards.removeFromHandAtIdx(handIdx);
}

void BattleContext::chooseDrawToHandCards(const int *idxs, int cardCount) {
    for (int i = 0; i < cardCount; ++i) {
        const auto drawIdx = idxs[i];
        auto c = cards.drawPile[drawIdx];
        cards.removeFromDrawPileAtIdx(drawIdx);
        moveToHandHelper(c);
    }
}

void BattleContext::chooseExhaustCards(const fixed_list<int, 10> &idxs) {
    if (idxs.empty()) {
        return;
    }
    auto listCopy = idxs;
    std::sort(listCopy.begin(), listCopy.end(), [](auto a, auto b) { return b < a; });

    // assume idxs is sorted in descending order
    for (const auto handIdx : listCopy) {
        auto c = cards.hand[handIdx];
        cards.removeFromHandAtIdx(handIdx);
        triggerAndMoveToExhaustPile(c);
    }
}

void BattleContext::chooseScryCards(const fixed_list<int, 10> &idxs) {
    // Move selected cards to discard, keep others on top of draw pile
    for (int i = static_cast<int>(idxs.size()) - 1; i >= 0; --i) {
        int drawIdx = idxs[i];
        if (drawIdx < static_cast<int>(cards.drawPile.size())) {
            auto c = cards.drawPile[cards.drawPile.size() - 1 - drawIdx];
            cards.drawPile.erase(cards.drawPile.begin() + (cards.drawPile.size() - 1 - drawIdx));
            cards.moveToDiscardPile(c);
        }
    }
    setState(InputState::EXECUTING_ACTIONS);
}

void BattleContext::chooseGambleCards(const fixed_list<int, 10> &idxs) {
    if (idxs.empty()) {
        return;
    }
    auto listCopy = idxs;
    std::sort(listCopy.begin(), listCopy.end(), [](auto a, auto b) { return b < a; });

    // assume idxs is sorted in descending order
    addToTop( Actions::DrawCards(listCopy.size()) );
    for (const auto handIdx : listCopy) {
        auto c = cards.hand[handIdx];
        cards.removeFromHandAtIdx(handIdx);
        cards.moveToDiscardPile(c);
        onManualDiscard(c);
    }
}


namespace sts {


    void printRngCounters(std::ostream &os, const BattleContext &bc) {
        const std::string separator = " ";
        os << '\t';

        os << "aiRng: " << bc.aiRng.counter << separator;
        os << "cardRandomRng: " << bc.cardRandomRng.counter << separator;
        os << "shuffleRng: " << bc.shuffleRng.counter << separator;
        os << "miscRng: " << bc.miscRng.counter << separator;
        os << "monsterHpRng: " << bc.monsterHpRng.counter << separator;
        os << "potionRng: " << bc.potionRng.counter << separator;

        os << '\n';
    }

    void printPotions(std::ostream &os, const BattleContext &bc) {
        const auto s = "\n\t";
        os << "\t" << "potionCount: " << bc.potionCount;
        os << s << "potionCapacity: " << bc.potionCapacity;

        os << s << "{ ";
        for (int i = 0; i < bc.potionCapacity; ++i) {
            os << getPotionName(bc.potions[i]) << ", ";
        }
        os << "}\n";
    }

    std::ostream& operator<<(std::ostream &os, const BattleContext &bc) {
        os << "BattleContext: {\n";
        printPotions(os, bc);
        printRngCounters(os, bc);

        os << "\tactionQueueSize: " << bc.actionQueue.size
            << ", cardQueueSize: " << bc.cardQueue.size
            << ", turn: " << bc.turn
            << ", ascension " << bc.ascension
            << ", loopCount: " << bc.loopCount
            << ", sum: " << bc.sum
            << ", seed: " << bc.seed
            << "\n";

        os << bc.monsters;
        os << bc.player;
        os << bc.cards;
        os << "}\n";
        return os;
    }


}
