import random

# --- Dice handling ---
def roll_dice_pair():
    return [random.randint(1, 6), random.randint(1, 6)]

def skill_extended_tie_margin_as_sum(dice, monster_strength, tie_margin=2):
    """Treat ties more leniently: returning a fake monster_strength if needed."""
    player_sum = sum(dice)
    if monster_strength - tie_margin <= player_sum < monster_strength:
        return monster_strength  # Fake it to exactly match monster strength
    return player_sum

def skill_none(dice, monster_strength=None):
    return sum(dice)

def skill_add_one(dice, monster_strength=None):
    return sum(dice) + 1

def skill_add_if_tie(dice, monster_strength):
    player_sum = sum(dice)
    if player_sum == monster_strength:
        return player_sum + 1
    return player_sum

def skill_reroll_if_loss(dice, monster_strength, is_aggressive=False):
    player_sum = sum(dice)

    needs_reroll = (player_sum < monster_strength) or (is_aggressive and player_sum == monster_strength)

    if not needs_reroll:
        return player_sum

    dice = roll_dice_pair()  # Reroll both dice
    return sum(dice)


def skill_reroll_one_if_loss(dice, monster_strength, is_aggressive=False):
    player_sum = sum(dice)

    needs_reroll = (player_sum < monster_strength) or (is_aggressive and player_sum == monster_strength)

    if not needs_reroll:
        return player_sum

    idx = 0 if dice[0] <= dice[1] else 1  # reroll the smaller die
    dice[idx] = random.randint(1, 6)
    return sum(dice)

def skill_dinovadasz(dice, monster_strength=None):
    """
    Dinóvadász:
    +2 strength if:
        - both dice show the same value
        - or the difference between dice is exactly 1
    """
    d1, d2 = dice

    if abs(d1 - d2) == 0 or abs(d1 - d2) == 1:
        return d1 + d2 + 2

    return d1 + d2

def skill_reroll_ones(dice, monster_strength=None):
    dice = [random.randint(1, 6) if d == 1 else d for d in dice]
    return sum(dice)

def skill_reroll_ones_recursive(dice, monster_strength=None):
    while 1 in dice:
        dice = [random.randint(1, 6) if d == 1 else d for d in dice]
    return sum(dice)


def skill_ones_are_sixes(dice, monster_strength=None):
    dice = [6 if d == 1 else d for d in dice]
    return sum(dice)

# --- Simulation with full outcome breakdown ---

def simulate_combat(skill_fn, monster_strength, trials=10000, **skill_kwargs):
    win = tie = loss = 0
    for _ in range(trials):
        player_dice = roll_dice_pair()
        player_total = skill_fn(player_dice, monster_strength=monster_strength, **skill_kwargs)

        if player_total > monster_strength:
            win += 1
        elif player_total == monster_strength:
            tie += 1
        else:
            loss += 1

    return {
        "win": win / trials,
        "tie": tie / trials,
        "loss": loss / trials,
    }


def print_table(results):
    # Sort by win chance descending
    results_sorted = sorted(results, key=lambda x: x[2]['win'], reverse=True)

    header = f"+{'-'*29}+{'-'*29}+{'-'*8}+{'-'*8}+{'-'*8}+"
    print(header)
    print(f"| {'Hero':<27} | {'Skill':<27} | {'Win %':>6} | {'Tie %':>6} | {'Loss %':>6} |")
    print(header)
    for hero_name, skill_label, outcome in results_sorted:
        print(f"| {hero_name:<27} | {skill_label:<27} | {outcome['win']*100:6.2f} | {outcome['tie']*100:6.2f} | {outcome['loss']*100:6.2f} |")
    print(header)


if __name__ == "__main__":
    monster_strengths = [14, 13, 12, 11, 10, 9, 8, 7, 6, 5]
    trials = 50_000

    for ms in monster_strengths:
        print(f"\nChances against a Monster(!) with net strength:                       < {ms:>2} >")
        all_results = list()
        all_results.append(("Magus,Jos,Keses,Kardmester", "Normal",
                            simulate_combat(skill_none, ms, trials)))
        all_results.append(("Vadasz,Jos(1),Warlock", "Add +1",
                            simulate_combat(skill_add_one, ms, trials)))
        all_results.append(("Tolvaj", "Add +1 if tie",
                            simulate_combat(skill_add_if_tie, ms, trials)))

        all_results.append(("Dinovadasz", "+2 if double or diff=1",
                            simulate_combat(skill_dinovadasz, ms, trials)))
        
        all_results.append(("Pancelos", "Reroll (if loss)",
                            simulate_combat(skill_reroll_if_loss, ms, trials, is_aggressive=False)))
        all_results.append(("Pancelos", "Reroll (aggressive)",
                            simulate_combat(skill_reroll_if_loss, ms, trials, is_aggressive=True)))
        all_results.append(("Ketkardos", "Reroll one die (if loss)",
                            simulate_combat(skill_reroll_one_if_loss, ms, trials, is_aggressive=False)))
        all_results.append(("Ketkardos", "Reroll one die (aggressive)",
                            simulate_combat(skill_reroll_one_if_loss, ms, trials, is_aggressive=True)))
        # all_results.append(("Reroll (1)-s",simulate_combat(skill_reroll_ones, ms, trials)))
        all_results.append(("Legios", "Reroll (1)-s (recursive)",
                            simulate_combat(skill_reroll_ones_recursive, ms, trials)))
        all_results.append(("Medvelany", "(1)-s count as (6)-s",
                            simulate_combat(skill_ones_are_sixes, ms, trials)))
        all_results.append(("Alchimista", "Marginal loss ties",
                            simulate_combat(skill_extended_tie_margin_as_sum, ms, trials, tie_margin=2)))

        print_table(all_results)

'''
0       1   2   3   4   5   6

1       2   3   4   5   6   7
2       3   4   5   6   7   8
3       4   5   6   7   8   9
4       5   6   7   8   9   10
5       6   7   8   9   10  11
6       7   8   9   10  11  12
'''

# 5     -> loss: 6,     tie: 4,     win: 26         16.66   11.11   72.22
# 6     -> loss: 10,    tie: 5,     win: 21         58.33   13.88   58.33
# 7     -> loss: 15,    tie: 6,     win: 15         41.66   16.66   41.66
# 8     -> loss: 21,    tie: 5,     win: 10         58.33   13.88   27.77
# 9     -> loss: 26,    tie: 4,     win: 6          72.22   11.11   16.66
# 10    -> loss: 30,    tie: 3,     win: 3          83.33   8.33    8.33
# 11    -> loss: 33,    tie: 2,     win: 1          91.66   5.55    2.77


''' expected value = 7 (general)
0       1   2   3   4   5   6

1       2   3   4   5   6   7
2       3   4   5   6   7   8
3       4   5   6   7   8   9
4       5   6   7   8   9   10
5       6   7   8   9   10  11
6       7   8   9   10  11  12
'''

''' expected value = 8.66 (BearGirl)
0       1   2   3   4   5   6

1       12  8   9   10  11  12
2       8   4   5   6   7   8
3       9   5   6   7   8   9
4       10  6   7   8   9   10
5       11  7   8   9   10  11
6       12  8   9   10  11  12
'''

''' expected value = 8 (Victorius)
0       2   3   4   5   6

2       4   5   6   7   8
3       5   6   7   8   9
4       6   7   8   9   10
5       7   8   9   10  11
6       8   9   10  11  12
'''

''' expected value = 8.88 (Taya*)
0       1   2   3   4   5   6

1       3   4   5   6   7   8
2       4   5   6   7   8   9
3       5   6   7   8   9   10
4       6   7   8   9   10  11
5       7   8   9   10  11  12
6       8   9   10  11  12  13
'''

''' expected value = 7.88 (Darius)
0       1   2   3   4   5   6

1       4   5   4   5   6   7
2       5   6   7   6   7   8
3       4   7   8   9   8   9
4       5   6   9   10  11  10
5       6   7   8   11  12  13
6       7   8   9   10  13  14
'''

# 
