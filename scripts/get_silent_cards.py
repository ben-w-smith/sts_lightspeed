import re

with open('include/constants/Cards.h', 'r') as f:
    lines = f.readlines()

cards = []
for line in lines:
    if "static constexpr const char* cardEnumStrings" in line:
        enum_match = re.search(r'\{(.*?)\}', line).group(1)
        enum_names = [x.strip().strip('"') for x in enum_match.split(',')]
    if "static constexpr CardColor cardColors" in line:
        color_match = re.search(r'\{(.*?)\}', line).group(1)
        colors = [x.strip() for x in color_match.split(',')]
    if "static constexpr CardType cardTypes" in line:
        type_match = re.search(r'\{(.*?)\}', line).group(1)
        types = [x.strip() for x in type_match.split(',')]

attacks = []
skills = []
powers = []

for i in range(len(enum_names)):
    if enum_names[i] == "INVALID" or i >= len(colors):
        continue
    if "GREEN" in colors[i]:
        ctype = types[i]
        card = enum_names[i]
        if "ATTACK" in ctype:
            attacks.append(card)
        elif "SKILL" in ctype:
            skills.append(card)
        elif "POWER" in ctype:
            powers.append(card)

print("ATTACKS:")
for c in attacks:
    print(c)
print("\nSKILLS:")
for c in skills:
    print(c)
print("\nPOWERS:")
for c in powers:
    print(c)
