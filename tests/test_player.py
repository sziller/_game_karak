import pytest

from player import Player, Inventory


def test_player_defaults():
    p = Player(player_id=0, x=1, y=2)

    assert p.player_id == 0
    assert p.x == 1
    assert p.y == 2
    assert p.max_hp == 5
    assert p.hp == 5
    assert p.is_conscious is True
    assert p.is_evil is False
    assert p.is_cursed is False
    assert p.inventory.weapon_slots == [None, None]
    assert p.inventory.key_slots == [None]
    assert p.inventory.scroll_slots == [None, None, None]
    assert p.inventory.treasure == 0.0


def test_invalid_player_hp_raises():
    with pytest.raises(ValueError):
        Player(player_id=0, x=0, y=0, max_hp=6, hp=7)


def test_set_hp_clamps_into_range():
    p = Player(player_id=0, x=0, y=0)

    p.set_hp(4)
    assert p.hp == 4
    assert p.is_conscious is True

    p.set_hp(-3)
    assert p.hp == 0
    assert p.is_conscious is False

    p.set_hp(999)
    assert p.hp == 5
    assert p.is_conscious is True


def test_turn_evil_once_only():
    p = Player(player_id=0, x=0, y=0)

    p.turn_evil()
    assert p.is_evil is True

    with pytest.raises(RuntimeError):
        p.turn_evil()


def test_place_and_remove_weapon():
    p = Player(player_id=0, x=0, y=0)

    assert p.place_weapon("sword", 0) is True
    assert p.get_weapon(0) == "sword"

    assert p.place_weapon("axe", 0) is False
    assert p.get_weapon(0) == "sword"

    removed = p.remove_weapon(0)
    assert removed == "sword"
    assert p.get_weapon(0) is None


def test_place_and_remove_scroll():
    p = Player(player_id=0, x=0, y=0)

    assert p.place_scroll("heal", 2) is True
    assert p.get_scroll(2) == "heal"

    removed = p.remove_scroll(2)
    assert removed == "heal"
    assert p.get_scroll(2) is None


def test_place_and_remove_key():
    p = Player(player_id=0, x=0, y=0)

    assert p.place_key("key", 0) is True
    assert p.get_key(0) == "key"

    assert p.place_key("other_key", 0) is False

    removed = p.remove_key(0)
    assert removed == "key"
    assert p.get_key(0) is None


def test_invalid_slot_indexes_fail_safely():
    p = Player(player_id=0, x=0, y=0)

    assert p.place_weapon("sword", -1) is False
    assert p.place_weapon("sword", 99) is False

    assert p.place_scroll("heal", -1) is False
    assert p.place_scroll("heal", 99) is False

    assert p.place_key("key", -1) is False
    assert p.place_key("key", 99) is False

    assert p.remove_weapon(99) is None
    assert p.remove_scroll(99) is None
    assert p.remove_key(99) is None


def test_add_treasure():
    p = Player(player_id=0, x=0, y=0)

    p.add_treasure(1.5)
    p.add_treasure(1.0)

    assert p.inventory.treasure == 2.5

    with pytest.raises(ValueError):
        p.add_treasure(-1.0)


def test_to_dict_shape():
    p = Player(player_id=3, x=5, y=7, skills={"skill_b", "skill_a"})
    p.place_weapon("sword", 0)
    p.place_key("key", 0)
    p.place_scroll("heal", 1)
    p.add_treasure(1.5)

    data = p.to_dict()

    assert data["player_id"] == 3
    assert data["position"] == {"x": 5, "y": 7}
    assert data["status"]["is_conscious"] is True
    assert data["skills"] == ["skill_a", "skill_b"]
    assert data["inventory"]["weapon_slots"] == ["sword", None]
    assert data["inventory"]["key_slots"] == ["key"]
    assert data["inventory"]["scroll_slots"] == [None, "heal", None]
    assert data["inventory"]["treasure"] == 1.5
    
