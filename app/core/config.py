GENERAL = {"max_of_players": 5,
           "room_x_karak_limit": 5,
           "curse_room_triggers": [1, 2, 3],
           "game_mode": "purge",    # purge: certain set of monsters are killed at the end of any players turn
                                    # cave_collapse:    at the end of purge, game goes on and players must escape a
                                    #                   collapse style dungeon destruction
                                    # firestorm:        at the end of purge, game goes on and players must escape a
                                    #                   pathing based dungeon destruction
                                    # timed:            game ends after a given time
                                    # turn_based:       game ends after a fixed amount of turns (*nr_of_players)
                                    # on_demand:        game ends once an "END GAME" button is bushed
                                    # never:            gema never ends
           "game_mode_details": {"monsters": ["dragon"], "number_of_monsters": 1, "allow_early_escape": True}}

PLAYER_FEATURES = {"max_hp": 5,
                   "total_of_scrolls": 3,
                   "total_of_weapons": 2,
                   "total_of_keys": 1}

# PvP-specific combat interpretation.
PVP_COMBAT_RULES = {
    # None:
    #   Players have no monster sort in PvP. LIV+1 / UND+1 weapon effects do not apply.
    #
    # "LIV":
    #   Players count as living in PvP. LIV+1 weapon effects apply.
    #
    # "UND":
    #   Players count as undead in PvP. UND+1 weapon effects apply.
    "player_sort_for_weapon_effects": None,
}


TURN_RULES = {"total_of_actions": 4,
              "teleport_action_prices": {"portal": 1,
                                         "skill_bea_02": 1,
                                         "skill_wlk_02": "all",
                                         "skill_bat_02": "all"} }

SKILL_RULES = {"skill_acr_02": {"total_of_actions_override": 8},
               "skill_wiz_02": {"allow_blink_discovered_only": True},
               "skill_bea_01": {"allow_in_arena_pvp": False},
               "skill_bea_02": {"allow_wounded_only": True},
               "skill_bar_02": {"dmg_groups": {0: [5], 1: [4, 3], 2: [2, 1]}}}

ALLOW_FIGHT_RETOSS_FOR_TESTING = True
