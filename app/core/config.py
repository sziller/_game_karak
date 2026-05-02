GENERAL = {"max_of_players": 5,
           "room_x_karak_limit": 5,
           "curse_room_trigers": [1, 2, 3]}

PLAYER_FEATURES = {"max_hp": 5,
                   "total_of_scrolls": 3,
                   "total_of_weapons": 2,
                   "total_of_keys": 1}

TURN_RULES = {"total_of_actions": 4}

SKILL_RULES = {
    "skill_acr_02": {
        "total_of_actions_override": 8,
    },
    "skill_wiz_02": {
        "allow_blink_discovered_only": True,
    },
    "skill_bar_02": {
        "dmg_groups": {0: [5], 1: [4, 3], 2: [2, 1]}
    }
}

ALLOW_FIGHT_RETOSS_FOR_TESTING = True
