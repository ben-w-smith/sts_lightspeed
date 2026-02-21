import sys

attacks = ["ALL_FOR_ONE", "BALL_LIGHTNING", "BARRAGE", "BEAM_CELL", "BLIZZARD", "BRILLIANCE", "BULLSEYE", "CLAW", "COLD_SNAP", "CORE_SURGE", "DOOM_AND_GLOOM", "FTL", "GO_FOR_THE_EYES", "HYPERBEAM", "MELTER", "METEOR_STRIKE", "REBOUND", "RIP_AND_TEAR", "SCRAPE", "STREAMLINE", "STRIKE_BLUE", "SUNDER", "SWEEPING_BEAM", "THUNDER_STRIKE"]

skills = ["AGGREGATE", "AMPLIFY", "AUTO_SHIELDS", "BOOT_SEQUENCE", "CHAOS", "CHARGE_BATTERY", "CHILL", "COLLECT", "CONSUME", "COOLHEADED", "DARKNESS", "DEFEND_BLUE", "DOUBLE_ENERGY", "DUALCAST", "EQUILIBRIUM", "FISSION", "FORCE_FIELD", "FUSION", "GENETIC_ALGORITHM", "GLACIER", "HOLOGRAM", "LEAP", "MULTI_CAST", "OVERCLOCK", "RAINBOW", "REBOOT", "RECURSION", "RECYCLE", "REINFORCED_BODY", "REPROGRAM", "SEEK", "SKIM", "STACK", "STEAM_BARRIER", "TEMPEST", "TURBO", "WHITE_NOISE", "ZAP"]

powers = ["BIASED_COGNITION", "CAPACITOR", "CREATIVE_AI", "DEFRAGMENT", "ECHO_FORM", "ELECTRODYNAMICS", "HEATSINKS", "HELLO_WORLD", "LOOP", "MACHINE_LEARNING", "SELF_REPAIR", "STATIC_DISCHARGE", "STORM"]


def print_cases(cards):
    for c in cards:
        print(f"        case CardId::{c}: {{\n            // TODO\n            break;\n        }}\n")

if sys.argv[1] == "attacks":
    print_cases(attacks)
elif sys.argv[1] == "skills":
    print_cases(skills)
elif sys.argv[1] == "powers":
    print_cases(powers)
