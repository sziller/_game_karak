tile_pool = (
    # Rooms
    [{"tile_type": "room", "img_name": "tile_rX", "doors": {"N": True, "S": True, "E": True, "W": True}}] * 16 +
    [{"tile_type": "room", "img_name": "tile_rT", "doors": {"N": True, "E": True, "S": True, "W": False}}] * 17 +  # example 3 exits (N, E, S)
    [{"tile_type": "room", "img_name": "tile_rI", "doors": {"N": True, "S": True, "E": False, "W": False}}] * 13 +  # 2 opposite exits
    [{"tile_type": "room", "img_name": "tile_rL", "doors": {"N": True, "E": True, "S": False, "W": False}}] * 15 +  # 2 neighbor exits

    # XR Special rooms
    [{"tile_type": "room_x", "img_name": "tile_xA", "doors": {"N": True, "S": True, "E": False, "W": False}, "feature": "arena"}] * 6 +
    [{"tile_type": "room_x", "img_name": "tile_xP", "doors": {"N": True, "S": True, "E": True, "W": True}, "feature": "curse"}] * 4 +

    # Corridors
    [{"tile_type": "corridor", "img_name": "tile_cI", "doors": {"N": True, "S": True, "E": False, "W": False}}] * 4 +  # floor straight
    [{"tile_type": "corridor", "img_name": "tile_cL", "doors": {"N": True, "E": True, "S": False, "W": False}}] * 4 +  # floor corner
    [{"tile_type": "corridor", "img_name": "tile_cX", "doors": {"N": True, "S": True, "E": True, "W": True}}] * 7 +  # floor crossroads
    [{"tile_type": "corridor", "img_name": "tile_cT", "doors": {"N": True, "E": True, "S": True, "W": False}}] * 5 +  # floor T-junction (N,E,S)
    [{"tile_type": "corridor", "img_name": "tile_cIt", "doors": {"N": True, "S": True, "E": False, "W": False}, "feature": "teleport"}] * 4 +  # floor straight teleport
    [{"tile_type": "corridor", "img_name": "tile_cLf", "doors": {"N": True, "E": True, "S": False, "W": False}, "feature": "fountain"}] * 2  # floor corner fountain
)

entity_pool = (
    [{"id": "GiantRat", "strength": 5,          "loot_id": "dagger",    "img_file": "GiantRat.png"}] * 8 +
    [{"id": "GiantSpider", "strength": 6,       "loot_id": "heal",      "img_file": "GiantSpider.png"}] * 4 +
    [{"id": "GiantBat", "strength": 6,          "loot_id": "thorn",     "img_file": "GiantBat.png"}] * 6 +
    [{"id": "SkeletonTurnkey", "strength": 8,   "loot_id": "key",       "img_file": "SkeletonTurnkey.png"}] * 12 +
    [{"id": "SkeletonWarrior", "strength": 9,   "loot_id": "sword",     "img_file": "SkeletonWarrior.png"}] * 5 +
    [{"id": "SkeletonKing", "strength": 10,     "loot_id": "axe",       "img_file": "SkeletonKing.png"}] * 3 +
    [{"id": "SkeletalMage", "strength": 11,     "loot_id": "fist",      "img_file": "SkeletalMage.png"}] * 2 +
    [{"id": "Mummy", "strength": 7,             "loot_id": "fireball",  "img_file": "Mummy.png"}] * 8 +
    
    [{"id": "Fallen", "strength": 12,           "loot_id": "treasure",  "img_file": "Fallen.png"}] * 2 +
    [{"id": "Dragon", "strength": 15,           "loot_id": "ruby",      "img_file": "Dragon.png"}] * 1 +
    [{"id": "Chest", "strength": 0,             "loot_id": "treasure",  "img_file": "Chest.png"}] * 10
)

item_features = {"dagger": {"str_mod": 1, "img_file": "dagger.png", "item_type": "weapon"},
                 "sword": {"str_mod": 2, "img_file": "sword.png", "item_type": "weapon"},
                 "axe": {"str_mod": 3, "img_file": "axe.png", "item_type": "weapon"},
                 "heal": {"str_mod": 0, "img_file": "heal.png", "item_type": "scroll"},
                 "thorn": {"str_mod": 0, "img_file": "thorn.png", "item_type": "scroll"},
                 "key": {"str_mod": 0, "img_file": "key.png", "item_type": "key"},
                 "fist": {"str_mod": 2, "img_file": "fist.png", "item_type": "scroll"},
                 "fireball": {"str_mod": 1, "img_file": "fireball.png", "item_type": "scroll"},
                 "treasure": {"str_mod": 0, "img_file": "treasure.png", "item_type": "treasure", "value": 1},
                 "ruby": {"str_mod": 0, "img_file": "ruby.png", "item_type": "treasure", "value": 1.5}
                 }

if __name__ == "__main__":
    print(len([_ for _ in tile_pool if _["tile_type"] == "room" ]))
    print(len(entity_pool))
