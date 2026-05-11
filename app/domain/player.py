from __future__ import annotations

from core.config import PLAYER_FEATURES
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Literal


# ============================================================
# Types
# ============================================================

ItemId = str
SkillId = str
SlotGroup = Literal["weapon", "scroll", "key"]

# ============================================================
# Config helpers
# ============================================================

def player_feature_int(key: str) -> int:
    value = PLAYER_FEATURES[key]
    if not isinstance(value, int):
        raise TypeError(f"PLAYER_FEATURES[{key!r}] must be int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"PLAYER_FEATURES[{key!r}] must be >= 0, got {value}")
    return value


def empty_item_slots(feature_key: str) -> List[Optional[ItemId]]:
    return [None for _ in range(player_feature_int(feature_key))]


DEFAULT_PLAYER_MAX_HP = player_feature_int("max_hp")

# ============================================================
# Inventory (strict slot model, extensible)
# ============================================================

@dataclass
class Inventory:
    """
    Slot-based inventory.

    Current configuration:
    - 2 weapon slots
    - 1 key slot (extensible)
    - 3 scroll slots

    Rules:
    - 1 item per slot
    - treasure is a counter (not a slot)
    """
    weapon_slots: List[Optional[ItemId]] = field(
        default_factory=lambda: empty_item_slots("total_of_weapons")
    )
    key_slots: List[Optional[ItemId]] = field(
        default_factory=lambda: empty_item_slots("total_of_keys")
    )
    scroll_slots: List[Optional[ItemId]] = field(
        default_factory=lambda: empty_item_slots("total_of_scrolls")
    )
    treasure: float = 0.0

    def __post_init__(self) -> None:
        if not self.weapon_slots:
            raise ValueError("weapon_slots must not be empty")
        if not self.key_slots:
            raise ValueError("key_slots must not be empty")
        if not self.scroll_slots:
            raise ValueError("scroll_slots must not be empty")
        if self.treasure < 0:
            raise ValueError("treasure must be >= 0")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weapon_slots": list(self.weapon_slots),
            "key_slots": list(self.key_slots),
            "scroll_slots": list(self.scroll_slots),
            "treasure": self.treasure,
        }

    def first_empty_weapon_slot(self) -> Optional[int]:
        for i, item in enumerate(self.weapon_slots):
            if item is None:
                return i
        return None

    def first_empty_scroll_slot(self) -> Optional[int]:
        for i, item in enumerate(self.scroll_slots):
            if item is None:
                return i
        return None

    def first_empty_key_slot(self) -> Optional[int]:
        for i, item in enumerate(self.key_slots):
            if item is None:
                return i
        return None

    def is_weapon_full(self) -> bool:
        return self.first_empty_weapon_slot() is None

    def is_scroll_full(self) -> bool:
        return self.first_empty_scroll_slot() is None

    def is_key_full(self) -> bool:
        return self.first_empty_key_slot() is None
    
# ============================================================
# Player (runtime entity)
# ============================================================

@dataclass
class Player:
    """=== Class ===
    Runtime representation of a player.

    IMPORTANT:
    - Contains ONLY persistent state
    - Contains NO game rules
    - Contains NO fight logic
    ============================================================================================== by Sziller ==="""

    # =====================================================
    # Identity / Presentation / Position
    # =====================================================
    player_id: int
    display_name: str = ""
    profession: Optional[str] = None
    character_name: Optional[str] = None
    image_path: Optional[str] = None        # fullscreen display
    tableau_path: Optional[str] = None      # large ui field
    icon_path: Optional[str] = None         # list style representation
    figurine_path: Optional[str] = None     # in board depiction
    x: int = 0
    y: int = 0

    # =====================================================
    # Health
    # =====================================================
    max_hp: int = DEFAULT_PLAYER_MAX_HP
    hp: int = DEFAULT_PLAYER_MAX_HP

    # =====================================================
    # Mechanics (CORE)
    # =====================================================
    skills: Set[SkillId] = field(default_factory=set)  # raw/base skills only
    # Curse:
    # - global mark
    # - suppresses all skills unless suppressed by NO_CURSE item
    is_cursed: bool = False
    # Poison:
    # - per-player, per-skill suppression
    # - does not relocate
    # - may affect multiple skills on the same player
    poisoned_skill_ids: Set[SkillId] = field(default_factory=set)
    is_evil: bool = False

    # =====================================================
    # Inventory
    # =====================================================
    inventory: Inventory = field(default_factory=Inventory)

    def __post_init__(self) -> None:
        if self.player_id < 0:
            raise ValueError("player_id must be >= 0")
        if self.max_hp <= 0:
            raise ValueError("max_hp must be > 0")
        if not (0 <= self.hp <= self.max_hp):
            raise ValueError("hp must be between 0 and max_hp")

    # =====================================================
    # Derived state
    # =====================================================
    @property
    def is_conscious(self) -> bool:
        """A player is conscious if HP > 0."""
        return self.hp > 0

    # =====================================================
    # Health management (safe setter)
    # =====================================================
    def set_hp(self, value: int) -> None:
        """Clamp HP into valid range [0, max_hp]."""
        self.hp = max(0, min(value, self.max_hp))

    # =====================================================
    # Transformation
    # =====================================================
    def turn_evil(self) -> None:
        """
        One-time irreversible transformation.

        NOTE:
        - Does NOT modify skills directly
        - Evil behavior is handled by engine-level logic
        """
        if self.is_evil:
            raise RuntimeError("Player has already turned evil")
        self.is_evil = True
        # TODO: use game level function, referring to parameters: nr_of_players and skillset in the game

    def is_skill_active(self, skill_id: str) -> bool:
        if skill_id not in self.skills:
            return False

        # Orange amulet / NO_CURSE:
        # Curse and poison marks may still exist, but they do not suppress
        # skills while this passive item is held.
        if self.has_no_curse_protection_item():
            return True

        # Curse suppresses all skills.
        if getattr(self, "is_cursed", False) or getattr(self, "cursed", False):
            return False

        # Poison suppresses only selected skills.
        if skill_id in self.poisoned_skill_ids:
            return False

        return True
    
    # =====================================================
    # Inventory queries (tiny helpers for testing / callers)
    # =====================================================
    def get_weapon(self, slot_index: int) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.weapon_slots):
            return self.inventory.weapon_slots[slot_index]
        return None

    def get_scroll(self, slot_index: int) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.scroll_slots):
            return self.inventory.scroll_slots[slot_index]
        return None

    def get_key(self, slot_index: int = 0) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.key_slots):
            return self.inventory.key_slots[slot_index]
        return None
    
    def has_any_key(self) -> bool:
        return any(item is not None for item in self.inventory.key_slots)
    
    def has_item_id(self, item_id: ItemId) -> bool:
        return (
            item_id in self.inventory.weapon_slots
            or item_id in self.inventory.scroll_slots
            or item_id in self.inventory.key_slots
        )

    def has_no_curse_protection_item(self) -> bool:
        """
        Orange amulet / amulet_o.

        This is intentionally item-id based because Player does not import
        ITEM_FEATURES. The engine still owns the real item-effect dispatch.
        """
        return self.has_item_id("amulet_o")
    
    def is_poisoned(self) -> bool:
        return bool(self.poisoned_skill_ids)

    def is_skill_poisoned(self, skill_id: SkillId) -> bool:
        return skill_id in self.poisoned_skill_ids

    def poison_skill(self, skill_id: SkillId) -> bool:
        """
        Add poison mark to one owned skill.

        Returns:
        - True if newly poisoned
        - False if already poisoned
        """
        if skill_id not in self.skills:
            raise ValueError("Cannot poison a skill the player does not own.")

        already_poisoned = skill_id in self.poisoned_skill_ids
        self.poisoned_skill_ids.add(skill_id)
        return not already_poisoned

    def clear_poison(self) -> bool:
        """
        Remove all poison marks from this player.

        Returns True if anything was removed.
        """
        had_poison = bool(self.poisoned_skill_ids)
        self.poisoned_skill_ids.clear()
        return had_poison
    
    def get_slot_item(self, slot_group: SlotGroup, slot_index: int) -> Optional[ItemId]:
        if slot_group == "weapon":
            return self.get_weapon(slot_index)
        if slot_group == "scroll":
            return self.get_scroll(slot_index)
        if slot_group == "key":
            return self.get_key(slot_index)
        return None

    # =====================================================
    # Inventory helpers (LOW LEVEL ONLY)
    # =====================================================
    # NOTE:
    # - NO rule validation here
    # - NO skill checks here
    # - Engine must validate legality before calling

    def place_weapon(self, item_id: ItemId, slot_index: int) -> bool:
        if 0 <= slot_index < len(self.inventory.weapon_slots) and self.inventory.weapon_slots[slot_index] is None:
            self.inventory.weapon_slots[slot_index] = item_id
            return True
        return False

    def place_scroll(self, item_id: ItemId, slot_index: int) -> bool:
        if 0 <= slot_index < len(self.inventory.scroll_slots) and self.inventory.scroll_slots[slot_index] is None:
            self.inventory.scroll_slots[slot_index] = item_id
            return True
        return False

    def place_key(self, item_id: ItemId, slot_index: int = 0) -> bool:
        if 0 <= slot_index < len(self.inventory.key_slots) and self.inventory.key_slots[slot_index] is None:
            self.inventory.key_slots[slot_index] = item_id
            return True
        return False

    def remove_weapon(self, slot_index: int) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.weapon_slots):
            item = self.inventory.weapon_slots[slot_index]
            self.inventory.weapon_slots[slot_index] = None
            return item
        return None

    def remove_scroll(self, slot_index: int) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.scroll_slots):
            item = self.inventory.scroll_slots[slot_index]
            self.inventory.scroll_slots[slot_index] = None
            return item
        return None

    def remove_key(self, slot_index: int = 0) -> Optional[ItemId]:
        if 0 <= slot_index < len(self.inventory.key_slots):
            item = self.inventory.key_slots[slot_index]
            self.inventory.key_slots[slot_index] = None
            return item
        return None
    
    def consume_one_key(self) -> Optional[ItemId]:
        for i, item in enumerate(self.inventory.key_slots):
            if item is not None:
                self.inventory.key_slots[i] = None
                return item
        return None

    def add_treasure(self, value: float) -> None:
        if value < 0:
            raise ValueError("treasure increment must be >= 0")
        self.inventory.treasure += value
    
    # =====================================================
    # Inventory queries (HIGHER LEVEL, still state-only)
    # =====================================================
    def has_free_weapon_slot(self) -> bool:
        return self.inventory.first_empty_weapon_slot() is not None

    def has_free_scroll_slot(self) -> bool:
        return self.inventory.first_empty_scroll_slot() is not None

    def has_free_key_slot(self) -> bool:
        return self.inventory.first_empty_key_slot() is not None

    def get_all_items(self) -> Dict[str, List[Optional[ItemId]]]:
        return {
            "weapon_slots": list(self.inventory.weapon_slots),
            "scroll_slots": list(self.inventory.scroll_slots),
            "key_slots": list(self.inventory.key_slots),
        }

    def get_total_weapon_strength_mod(self, item_features: Dict[str, Dict[str, Any]]) -> int:
        total = 0
        for item_id in self.inventory.weapon_slots:
            if item_id is None:
                continue
            feat = item_features.get(item_id)
            if feat:
                total += int(feat.get("str_mod", 0))
        return total
    
    def try_store_item(
        self,
        *,
        item_id: ItemId,
        item_type: str,
        value: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Store an item using inventory shape only.

        IMPORTANT:
        - No game-rule validation here
        - No skill exceptions here
        - Caller must pass correct item_type/value
        """
        if item_type == "treasure":
            self.add_treasure(float(value or 0.0))
            return {
                "stored": True,
                "storage": "treasure",
                "slot_index": None,
                "item_id": item_id,
            }

        if item_type == "weapon":
            idx = self.inventory.first_empty_weapon_slot()
            if idx is None:
                return {"stored": False, "reason": "weapon_slots_full", "item_id": item_id}
            self.inventory.weapon_slots[idx] = item_id
            return {
                "stored": True,
                "storage": "weapon",
                "slot_index": idx,
                "item_id": item_id,
            }

        if item_type == "scroll":
            idx = self.inventory.first_empty_scroll_slot()
            if idx is None:
                return {"stored": False, "reason": "scroll_slots_full", "item_id": item_id}
            self.inventory.scroll_slots[idx] = item_id
            return {
                "stored": True,
                "storage": "scroll",
                "slot_index": idx,
                "item_id": item_id,
            }

        if item_type == "key":
            idx = self.inventory.first_empty_key_slot()
            if idx is None:
                return {"stored": False, "reason": "key_slots_full", "item_id": item_id}
            self.inventory.key_slots[idx] = item_id
            return {
                "stored": True,
                "storage": "key",
                "slot_index": idx,
                "item_id": item_id,
            }

        return {"stored": False, "reason": f"unsupported_item_type:{item_type}", "item_id": item_id}
        
    def drop_item_from_slot(self, slot_group: SlotGroup, slot_index: int) -> Optional[ItemId]:
        if slot_group == "weapon":
            return self.remove_weapon(slot_index)
        if slot_group == "scroll":
            return self.remove_scroll(slot_index)
        if slot_group == "key":
            return self.remove_key(slot_index)
        return None
    
    def place_item_into_slot(self, slot_group: SlotGroup, slot_index: int, item_id: ItemId) -> bool:
        if slot_group == "weapon":
            return self.place_weapon(item_id, slot_index)
        if slot_group == "scroll":
            return self.place_scroll(item_id, slot_index)
        if slot_group == "key":
            return self.place_key(item_id, slot_index)
        return False
    
    def is_item_type_compatible_with_slot(self, item_type: str, slot_group: SlotGroup) -> bool:
        mapping = {
            "weapon": "weapon",
            "scroll": "scroll",
            "key": "key",
        }
        return mapping.get(item_type) == slot_group
    
    # =====================================================
    # Serialization (BASE VIEW ONLY)
    # =====================================================
    def to_dict(self) -> Dict[str, Any]:
        """
        Base serialization.

        IMPORTANT:
        - 'skills' here are RAW skills (not effective!)
        - Engine/UI layer should override with effective skills if needed
        """
        return {"player_id": self.player_id,
                "display_name": self.display_name,
                "profession": self.profession,
                "character_name": self.character_name,
                "image_path": self.image_path,
                "tableau_path": self.tableau_path,
                "icon_path": self.icon_path,
                "figurine_path": self.figurine_path,
                "position": {"x": self.x,
                             "y": self.y},
                "status": {"is_evil": self.is_evil,
                           "is_cursed": self.is_cursed,
                           "is_poisoned": self.is_poisoned(),
                           "poisoned_skill_ids": sorted(self.poisoned_skill_ids),
                           "is_conscious": self.is_conscious},
                "hp": {"current": self.hp,
                       "max": self.max_hp},
                "skills": sorted(self.skills),
                "poisoned_skill_ids": sorted(self.poisoned_skill_ids),
                "inventory": self.inventory.to_dict(),
                "inventory_view": {
                    "weapon_slots": list(self.inventory.weapon_slots),
                    "scroll_slots": list(self.inventory.scroll_slots),
                    "key_slots": list(self.inventory.key_slots),
                    "treasure": self.inventory.treasure}
                }


if __name__ == "__main__":
    p = Player(player_id=0, x=0, y=0)
    print(p.to_dict())
    
