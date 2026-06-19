const KARAK_BASE_URL = window.KARAK_BASE_URL || "";
const KARAK_STATIC_URL = window.KARAK_STATIC_URL || `${KARAK_BASE_URL}/static`;

function karakPath(path) {
    if (!path) {
        return KARAK_BASE_URL || "/";
    }
    if (/^(https?:)?\/\//.test(path)) {
        return path;
    }
    if (KARAK_BASE_URL && path.startsWith(`${KARAK_BASE_URL}/`)) {
        return path;
    }
    return `${KARAK_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function karakStaticAsset(path) {
    if (!path) {
        return "";
    }
    if (/^(https?:)?\/\//.test(path)) {
        return path;
    }

    const normalized = String(path).replace(/^\/+/, "");

    if (normalized.startsWith("static/")) {
        return `${KARAK_STATIC_URL}/${normalized.slice("static/".length)}`;
    }
    if (normalized.startsWith("media/")) {
        return `${KARAK_STATIC_URL}/${normalized}`;
    }

    return karakPath(path);
}

const gameApi = (p) => karakPath("/api/game" + (p.startsWith("/") ? p : "/" + p));
const lobbyApi = (p) => karakPath("/api/lobby" + (p.startsWith("/") ? p : "/" + p));

let latestPlayers = null;
let latestMap = null;
let latestFight = null;
let selectedCurseTargetPlayerId = null;
let selectedPoisonTargetPlayerId = null;
let selectedPoisonTargetSkillId = null;

let selectedArenaOpponentPlayerId = null;
let selectedArenaLootChoice = null;
// Shape:
// {
//   steal_kind: "slot_item" | "treasure_value",
//   source_slot_group?: "weapon" | "scroll" | "key",
//   source_slot_index?: number,
//   label?: string
// }

let selectedScoutPocketTileIndex = null;
let skillUiState = {};
let pendingTeleportSkillId = null;
let pendingTeleportTargetMode = null; // null | "coordinates" | "player"
let selectedTeleportTargetPlayerId = null;
let pendingItemUse = null;
let latestItemRefsById = {};
// Example:
// {
//   item_id: "heal",
//   effect: "TP_HEAL",
//   slot_group: "scroll",
//   slot_index: 0,
//   phase: "select_player", // then "select_fountain"
//   target_player_id: null
// }

/* =========================================================
   MAP RENDERER (adapted from existing map_viewer.html)
   ========================================================= */
let RENDER_MODE = "image";
const TILE_SIZE = 96;
const TILE_SCALE = 0.75;

/* =========================================================
   MAP VIEWPORT STATE
   mapViewportOffsetX/Y are frontend-only pan offsets in pixels.
   Positive X moves the rendered map to the right.
   Positive Y moves the rendered map downward.
   ========================================================= */
let mapViewportOffsetX = 0;
let mapViewportOffsetY = 0;

const MAP_PAN_STEP_PX = 96;

const TILE_VARIANTS = {
    tile_rX: 1,
    tile_rT: 3,
    tile_rI: 1,
    tile_rL: 1,
    tile_xA: 1,
    tile_xP: 1,
    tile_cI: 2,
    tile_cL: 2,
    tile_cX: 2,
    tile_cT: 3,
    tile_cIt: 4,
    tile_cLf: 1,
    entrance: 1,
};

const tileVariantCounters = {};
const tileVariantMap = {};

function getTileVariant(tile, x, y) {
    const key = `${x},${y}`;

    if (tileVariantMap[key] !== undefined) {
        return tileVariantMap[key];
    }

    const base = tile.img_base;
    const max = TILE_VARIANTS[base] ?? 1;

    if (!tileVariantCounters[base]) {
        tileVariantCounters[base] = 1;
    }

    const idx = tileVariantCounters[base];
    tileVariantCounters[base] = (tileVariantCounters[base] % max) + 1;
    tileVariantMap[key] = idx;
    return idx;
}

const PLAYER_TOKEN_COLORS = [
    "#ff5555", // 1 red
    "#5599ff", // 2 blue
    "#55cc55", // 3 green
    "#ffff55", // 4 yellow
    "#ff9933", // 5 orange
];

function tileMiniImagePathFromBase(imgBase) {
    if (!imgBase) {
        return "";
    }

    const max = TILE_VARIANTS[imgBase] ?? 1;
    const variant = 1;

    // Entrance is not expected in Scout pocket, but this keeps the helper safe.
    if (imgBase === "entrance") {
        return `${KARAK_STATIC_URL}/media/tiles/entrance.png`;
    }

    return `${KARAK_STATIC_URL}/media/tiles/${imgBase}-${variant}.png`;
}

function getPlayerById(playerId) {
    const players = latestPlayers?.players || [];
    return players.find(p => Number(p.player_id) === Number(playerId)) || null;
}

function getScoutPocketForPlayer(playerId) {
    const player = getPlayerById(playerId);

    return player?.scout_pocket || {
        capacity: 3,
        count: 0,
        tiles: []
    };
}

function isScoutPocketTileSelected(index) {
    return (
        selectedScoutPocketTileIndex !== null &&
        selectedScoutPocketTileIndex !== undefined &&
        Number(selectedScoutPocketTileIndex) === Number(index)
    );
}

function renderScoutPocketMiniSlots(playerId) {
    const pocket = getScoutPocketForPlayer(playerId);
    const capacity = Number(pocket.capacity ?? 3);
    const tiles = Array.isArray(pocket.tiles) ? pocket.tiles : [];
    const scoutSkillAvailable = isSkillAvailableForActivePlayer("skill_sco_02");

    const tilesByIndex = new Map();

    tiles.forEach(tile => {
        tilesByIndex.set(Number(tile.index), tile);
    });

    let html = `<div class="scout-pocket-box" title="Scout pocket">`;

    for (let i = 0; i < capacity; i++) {
        const tile = tilesByIndex.get(i);

        if (!tile) {
            html += `
                <button
                    type="button"
                    class="scout-pocket-slot empty"
                    data-index="${i}"
                    disabled
                    title="Empty Scout pocket slot"
                    onclick="event.stopPropagation();"
                ></button>
            `;
            continue;
        }

        const selected = isScoutPocketTileSelected(i);
        const imgSrc = tileMiniImagePathFromBase(tile.img_base);

        const title = selected
            ? `${tile.archetype_id || "tile"} (${tile.tile_type || "unknown"}) — selected. Click again to cancel.`
            : `${tile.archetype_id || "tile"} (${tile.tile_type || "unknown"}) — click to use for next reveal.`;

        html += `
            <button
                type="button"
                class="scout-pocket-slot filled ${selected ? "selected" : ""} ${scoutSkillAvailable ? "" : "blocked"}"
                data-index="${i}"
                title="${title}"
                ${scoutSkillAvailable ? "" : "disabled"}
                onclick="selectScoutPocketTile(event, ${playerId}, ${i})"
            >
                <img
                    src="${imgSrc}"
                    alt="${tile.archetype_id || "Scout pocket tile"}"
                >
            </button>
        `;
    }

    html += `</div>`;

    return html;
}

function selectScoutPocketTile(event, playerId, index) {
    if (event) {
        event.stopPropagation();
    }

    const activePlayerId = latestPlayers?.active_player?.player_id;

    if (Number(playerId) !== Number(activePlayerId)) {
        showError("Only the active player's Scout pocket can be selected.");
        return;
    }

    if (!isSkillAvailableForActivePlayer("skill_sco_02")) {
        selectedScoutPocketTileIndex = null;
        renderPlayers(latestPlayers);

        showError("Scout pocket cannot be used because skill_sco_02 is currently blocked.");
        return;
    }

    const pocket = getScoutPocketForPlayer(playerId);
    const tiles = Array.isArray(pocket.tiles) ? pocket.tiles : [];

    const tile = tiles.find(t => Number(t.index) === Number(index));

    if (!tile) {
        showError("This Scout pocket slot is empty.");
        return;
    }

    // Clicking the already-selected pocket tile deselects it.
    // The next hidden reveal will fall back to normal pile draw.
    if (isScoutPocketTileSelected(index)) {
        selectedScoutPocketTileIndex = null;
        renderPlayers(latestPlayers);

        showMessage(
            "Scout pocket tile deselected. Next hidden reveal will draw from the pile.",
            "info",
            "Scout pocket"
        );

        return;
    }

    selectedScoutPocketTileIndex = Number(index);

    renderPlayers(latestPlayers);

    showMessage(
        `Selected Scout pocket tile ${Number(index) + 1}: ${tile.archetype_id || "unknown tile"}. Click it again to cancel and draw from pile.`,
        "info",
        "Scout pocket"
    );
}

function getPlayerTokenColor(playerId, index) {
    const n = Number.isInteger(playerId) ? playerId : index;
    return PLAYER_TOKEN_COLORS[n % PLAYER_TOKEN_COLORS.length];
}

function getActivePlayerMapPosition() {
    const activePlayer = latestPlayers?.active_player || null;

    if (!activePlayer?.position) {
        return null;
    }

    const x = Number(activePlayer.position.x);
    const y = Number(activePlayer.position.y);

    if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return null;
    }

    return {x, y};
}

function resetMapViewportOffset() {
    mapViewportOffsetX = 0;
    mapViewportOffsetY = 0;
}

function centerMapOnActivePlayerAndRender() {
    resetMapViewportOffset();
    renderMapVisual();
}

function panMapViewport(direction) {
    if (direction === "up") {
        mapViewportOffsetY += MAP_PAN_STEP_PX;
    } else if (direction === "down") {
        mapViewportOffsetY -= MAP_PAN_STEP_PX;
    } else if (direction === "left") {
        mapViewportOffsetX += MAP_PAN_STEP_PX;
    } else if (direction === "right") {
        mapViewportOffsetX -= MAP_PAN_STEP_PX;
    } else {
        return;
    }

    renderMapVisual();
}

function renderMapVisual() {
    const mapDiv = document.getElementById("mapCanvas");
    mapDiv.innerHTML = "";

    const currentTiles = latestMap?.tiles || {};
    const players = latestPlayers?.players || [];
    const activeIdx = latestPlayers?.active_player_idx ?? 0;

    let xs = [], ys = [];
    for (const key in currentTiles) {
        const [x, y] = key.split(",").map(Number);
        xs.push(x);
        ys.push(y);
    }

    if (xs.length === 0) {
        mapDiv.innerHTML = `<div class="muted" style="padding-top:40px;">(no discovered tiles)</div>`;
        return;
    }

    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);


    const size = TILE_SIZE * TILE_SCALE;

    const activePos = getActivePlayerMapPosition();

    const centerX = activePos
        ? activePos.x
        : (minX + maxX) / 2;

    const centerY = activePos
        ? activePos.y
        : (minY + maxY) / 2;

    const rect = mapDiv.getBoundingClientRect();

    const screenCX = (rect.width / 2) + mapViewportOffsetX;
    const screenCY = (rect.height / 2) + mapViewportOffsetY;


    for (const key in currentTiles) {
        const [x, y] = key.split(",").map(Number);
        const tile = currentTiles[key];

        const px = (x - centerX) * size + screenCX;
        const py = (centerY - y) * size + screenCY;

        const tileBox = document.createElement("div");
        tileBox.style.position = "absolute";
        tileBox.style.left = `${px - size / 2}px`;
        tileBox.style.top = `${py - size / 2}px`;
        tileBox.style.width = `${size}px`;
        tileBox.style.height = `${size}px`;
        tileBox.style.pointerEvents = "none";

        const baseImg = document.createElement("img");

        if (tile.collapse_state === "collapsed") {
            baseImg.src =
                karakStaticAsset(tile.collapsed_tile_image_path) ||
                karakStaticAsset(latestMap?.world_event?.collapsed_tile_image_path) ||
                `${KARAK_STATIC_URL}/media/tiles/tile_start-back.png`;
        } else if (tile.archetype_id === "entrance") {
            baseImg.src = `${KARAK_STATIC_URL}/media/tiles/entrance.png`;
        } else {
            const variant = getTileVariant(tile, x, y);
            baseImg.src = `${KARAK_STATIC_URL}/media/tiles/${tile.img_base}-${variant}.png`;
        }

        baseImg.className = "tile-base-img";
        baseImg.style.transform = `rotate(${tile.rotation_q * 90}deg)`;
        tileBox.appendChild(baseImg);

        if (tile.will_collapse_next && tile.collapse_state !== "collapsed") {
            tileBox.classList.add("tile-collapse-warning");
        }

        if (tile.collapse_state === "collapsed") {
            tileBox.classList.add("tile-collapsed");
        }

        if (tile.collapse_state !== "collapsed" && tile.entity_id) {
            const img = document.createElement("img");
            img.src = `${KARAK_STATIC_URL}/media/tile-content/${tile.entity_id}.png`;
            img.alt = tile.entity_id;
            img.className = "map-content-icon";
            tileBox.appendChild(img);
        } else if (tile.object_item) {
            const img = document.createElement("img");
            img.src = itemImagePath(tile.object_item);
            img.alt = tile.object_item.item_id || "";
            img.className = "map-content-icon";
            tileBox.appendChild(img);
        }

        mapDiv.appendChild(tileBox);
    }

    /* ---------------------------------------------------------
       Overlay all players
       --------------------------------------------------------- */
    const indexedPlayers = players.map((p, idx) => ({p, idx}));

    // draw non-active first, active last
    indexedPlayers.sort((a, b) => {
        const aActive = a.idx === activeIdx ? 1 : 0;
        const bActive = b.idx === activeIdx ? 1 : 0;
        return aActive - bActive;
    });

    indexedPlayers.forEach(({p, idx}) => {
        const pos = p.position || {x: 0, y: 0};
        const px = (pos.x - centerX) * size + screenCX;
        const py = (centerY - pos.y) * size + screenCY;
        const isActive = idx === activeIdx;

        const figurineSize = isActive ? 56 : 48;  /* 48 - 42 */

        const marker = document.createElement("div");
        marker.className = "map-player-figurine" + (isActive ? " active" : "");

        marker.style.left = `${px - figurineSize / 2}px`;
        marker.style.top = `${py - figurineSize / 2}px`;
        marker.style.width = `${figurineSize}px`;
        marker.style.height = `${figurineSize}px`;
        marker.style.zIndex = isActive ? "60" : "40";

        if (p.figurine_path) {
            const img = document.createElement("img");
            img.src = karakStaticAsset(p.figurine_path);
            img.alt = p.display_name || "player";
            img.title = p.display_name || "player";
            marker.appendChild(img);
        } else {
            // Fallback if figurine_path is missing.
            marker.classList.add("map-player-figurine-fallback");
            marker.style.background = getPlayerTokenColor(p.player_id, idx);
            marker.textContent = String(p.player_id ?? "?");
        }

        mapDiv.appendChild(marker);
    });
}

function prettySkillLabel(skillId) {
    if (!skillId) return "-";
    return skillId.replace("skill_", "").replaceAll("_", " ").toUpperCase();
}

function renderSkillChip(skill, playerId) {
    const label =
        skill.name ||
        (skill.label && !skill.label.startsWith("skill_") ? skill.label : null) ||
        prettySkillLabel(skill.skill_id);

    const isAvailable = skill.is_available !== false;
    const isUsableNow = skill.is_usable_now !== false;

    const isPassive = !!skill.is_passive;
    const controlType = skill.control_type || "passive";
    const description = skill.description || "";
    const isSelected = !!skill.selected;
    const value = skill.value;

    const isPoisoned = skill.blocked_reason === "poisoned";
    const isCursedBlocked = skill.blocked_reason === "cursed";

    const bg = isAvailable ? (isSelected ? "#223322" : "#1b2a1b") : "#2a1b1b";
    const border = isAvailable ? (isSelected ? "#88ff88" : "#55cc55") : "#cc5555";
    const text = isAvailable ? "#d8ffd8" : "#ffd8d8";

    let stateText = "active";

    if (!isAvailable) {
        stateText = "blocked";
    } else if (!isUsableNow && !isPassive) {
        stateText = "not usable now";
    } else if (isPassive) {
        stateText = "passive";
    }

    let controlHtml = "";

    if (controlType === "toggle") {
        if (skill.skill_id === "skill_sco_02") {
            // Scout pocket draw is an Action, not a toggle.
            controlHtml = `
                <div style="display:flex; align-items:center; gap:6px;">
                    <button
                        type="button"
                        ${isUsableNow ? "" : "disabled"}
                        onclick="event.stopPropagation(); scoutPullTile(${playerId});"
                        title="Draw one tile into Scout pocket"
                    >draw</button>
                </div>
            `;
        } else {
            controlHtml = `
                <label style="display:flex; align-items:center; gap:6px; margin-top:4px;">
                    <input
                        type="checkbox"
                        ${isSelected ? "checked" : ""}
                        ${isUsableNow ? "" : "disabled"}
                        onchange="toggleSkillUiSelection(${playerId}, '${skill.skill_id}')"
                    >
                    <span>toggle</span>
                </label>
            `;
        }
    } else if (controlType === "button") {
        let buttonLabel = "use";
        let onclick = `pulseSkillUiButton(${playerId}, '${skill.skill_id}')`;

        if (isTeleportSkill(skill.skill_id)) {
            buttonLabel = "target";
        }

        if (skill.skill_id === "skill_thi_02" || skill.skill_id === "skill_pri_02") {
            buttonLabel = "fight";
            onclick = "fightStart()";
        }

        controlHtml = `
        <div style="margin-top:4px;">
            <button
                type="button"
                ${isUsableNow ? "" : "disabled"}
                onclick="event.stopPropagation(); ${onclick}"
            >${buttonLabel}</button>
        </div>
    `;
    } else if (controlType === "number_stepper") {
        const shownValue = (value != null) ? value : "?";
        const confirmHtml = skill.skill_id === "skill_bar_01"
            ? `
                <button
                    type="button"
                    ${isUsableNow ? "" : "disabled"}
                    onclick="event.stopPropagation(); confirmHealingChoice()"
                >confirm</button>
            `
            : "";

        controlHtml = `
            <div style="display:flex; align-items:center; gap:4px; margin-top:4px;">
                <button
                    type="button"
                    ${isUsableNow ? "" : "disabled"}
                    onclick="event.stopPropagation(); stepSkillUiValue(${playerId}, '${skill.skill_id}', -1)"
                >-</button>
                <span style="min-width:24px; text-align:center;">${shownValue}</span>
                <button
                    type="button"
                    ${isUsableNow ? "" : "disabled"}
                    onclick="event.stopPropagation(); stepSkillUiValue(${playerId}, '${skill.skill_id}', 1)"
                >+</button>
                ${confirmHtml}
            </div>
        `;
    } else if (controlType === "choice_set") {
        controlHtml = `
            <div style="margin-top:4px; opacity:${isAvailable ? "1" : "0.6"};">
                <span>choices...</span>
            </div>
        `;
    } else {
        controlHtml = `
            <div style="margin-top:4px; opacity:0.8;">
                <span>—</span>
            </div>
        `;
    }

    const scoutPocketHtml = skill.skill_id === "skill_sco_02"
        ? renderScoutPocketMiniSlots(playerId)
        : "";

    const skillTargetClick = `
        onclick="handleSkillChipClick(event, ${playerId}, '${skill.skill_id}')"
    `;

    return `
        <div ${skillTargetClick} class="skill-chip skill-${skill.skill_id}" style="
            border:1px solid ${border};
            background:${bg};
            color:${text};
            padding:4px 6px;
            min-width:120px;
            font-size:11px;
            line-height:1.25;
            border-radius:4px;
            cursor:pointer;
        " title="${description}">
            <div class="skill-chip-title">
                ${isPoisoned ? `<span class="skill-poison-icon" title="Poisoned">☣</span>` : ""}
                ${isCursedBlocked ? `<span class="skill-curse-icon" title="Blocked by curse">☠</span>` : ""}
                <b>${label}</b>
            </div>

            <div style="opacity:0.9;">
                ${stateText}${controlType ? ` | ${controlType}` : ""}
            </div>

            <div class="skill-chip-control-row">
                <div class="skill-chip-control-main">
                    ${controlHtml}
                </div>
                ${scoutPocketHtml}
            </div>
        </div>
    `;
}

/* =========================================================
   COMPACT READ-ONLY PLAYER INVENTORY
   Used in the Players panel for hotseat/full-disclosure play.
   ========================================================= */
function rememberItemRef(item) {
    if (!item || !item.item_id) {
        return;
    }

    latestItemRefsById[item.item_id] = item;
}

function rememberInventoryItemRefsFromSlotList(slots) {
    if (!Array.isArray(slots)) {
        return;
    }

    slots.forEach(slot => {
        if (slot?.item) {
            rememberItemRef(slot.item);
        }
    });
}

function rememberInventoryItemRefs(data) {
    if (!data) {
        return;
    }

    // Active inventory API shape:
    // data.slots.weapon / data.slots.key / data.slots.scroll
    const slots = data.slots || {};

    rememberInventoryItemRefsFromSlotList(slots.weapon || []);
    rememberInventoryItemRefsFromSlotList(slots.key || []);
    rememberInventoryItemRefsFromSlotList(slots.scroll || []);

    // Ground item can also teach us an item ref.
    if (data.ground_item) {
        rememberItemRef(data.ground_item);
    }
}

function resolveItemForMiniInventory(itemId) {
    if (!itemId) {
        return null;
    }

    return latestItemRefsById[itemId] || null;
}

function miniItemIdFromSlot(slot) {
    if (slot == null) {
        return null;
    }

    // Shape 1: direct item id string, e.g. "sword", "heal"
    if (typeof slot === "string") {
        return slot;
    }

    // Shape 2: slot object from inventory API, e.g.
    // { item_id: "heal", item: {...}, slot_index: 0 }
    if (slot.item_id) {
        return slot.item_id;
    }

    // Shape 3: nested item object, e.g.
    // { item: { item_id: "heal" } }
    if (slot.item?.item_id) {
        return slot.item.item_id;
    }

    // Shape 4: object itself is item-like
    if (slot.id) {
        return slot.id;
    }

    return null;
}

function miniSlotLabel(slot) {
    const itemId = miniItemIdFromSlot(slot);

    if (!itemId) {
        return "·";
    }

    return String(itemId)
        .replace("sword_", "sw:")
        .replace("scroll_", "sc:")
        .replace("amulet_", "am:")
        .replace("dagger", "dag")
        .replace("fireball", "fire")
        .replace("heal", "heal")
        .replace("key", "key");
}

function normalizeMiniInventory(player) {
    const inv = player?.inventory || null;

    if (!inv) {
        return null;
    }

    /*
       Expected possible shapes:

       Shape A:
       inventory: {
           weapon_slots: [...],
           key_slots: [...],
           scroll_slots: [...],
           treasure: 0
       }

       Shape B:
       inventory: {
           weapons: [...],
           keys: [...],
           scrolls: [...],
           treasure: 0
       }
    */

    const weaponSlots = inv.weapon_slots || inv.weapons || [];
    const keySlots = inv.key_slots || inv.keys || [];
    const scrollSlots = inv.scroll_slots || inv.scrolls || [];

    return {
        weapons: weaponSlots,
        keys: keySlots,
        scrolls: scrollSlots,
        treasure: inv.treasure ?? 0
    };
}

function renderMiniInventoryColumnRow(player, label, slotGroup, slotsOrValue, isTreasure = false) {
    if (isTreasure) {
        const playerId = player?.player_id;
        const treasureValue = slotsOrValue ?? 0;

        const canStealTreasure =
            isAwaitingArenaLootChoice() &&
            isArenaLootLoser(playerId) &&
            !!getArenaStealableTreasureOption();

        const isSelected =
            selectedArenaLootChoice &&
            selectedArenaLootChoice.steal_kind === "treasure_value" &&
            isArenaLootLoser(playerId);

        return `
            <div
                class="mini-inv-row mini-inv-row-treasure ${canStealTreasure ? "arena-loot-clickable" : ""} ${isSelected ? "arena-loot-selected" : ""}"
                ${canStealTreasure ? `onclick="event.stopPropagation(); selectArenaLootTreasure(${playerId});"` : ""}
                title="${canStealTreasure ? "Click to steal treasure" : ""}"
            >
                <span class="mini-inv-label">${label}</span>
                <span class="mini-inv-treasure-value">${treasureValue}</span>
            </div>
        `;
    }

    const slots = Array.isArray(slotsOrValue) ? slotsOrValue : [];

    return `
        <div class="mini-inv-row">
            <span class="mini-inv-label">${label}</span>
            <span class="mini-inv-slots">
                ${slots.map((slot, index) =>
        renderMiniInventorySlot(player, slotGroup, slot, index)
    ).join("")}
            </span>
        </div>
    `;
}

function renderMiniInventorySlot(player, slotGroup, slot, slotIndex) {
    const itemId = miniItemIdFromSlot(slot);
    const playerId = player?.player_id;

    if (!itemId) {
        return `
            <span class="mini-inv-slot mini-inv-slot-empty">
                <span class="mini-inv-empty-dot">·</span>
            </span>
        `;
    }

    const item = resolveItemForMiniInventory(itemId);

    const canStealThis =
        isAwaitingArenaLootChoice() &&
        isArenaLootLoser(playerId) &&
        !!findArenaStealableSlotOption(slotGroup, slotIndex);

    const isSelected =
        selectedArenaLootChoice &&
        selectedArenaLootChoice.steal_kind === "slot_item" &&
        selectedArenaLootChoice.source_slot_group === slotGroup &&
        Number(selectedArenaLootChoice.source_slot_index) === Number(slotIndex);

    const clickAttr = canStealThis
        ? `onclick="event.stopPropagation(); selectArenaLootSlot(${playerId}, '${slotGroup}', ${slotIndex}, '${itemId}')"`
        : "";

    const title = canStealThis
        ? `Steal ${itemId}`
        : itemId;

    if (!item) {
        return `
            <span
                class="mini-inv-slot mini-inv-slot-missing ${canStealThis ? "arena-loot-clickable" : ""} ${isSelected ? "arena-loot-selected" : ""}"
                title="${title}"
                ${clickAttr}
            >
                ?
            </span>
        `;
    }

    return `
        <span
            class="mini-inv-slot ${canStealThis ? "arena-loot-clickable" : ""} ${isSelected ? "arena-loot-selected" : ""}"
            title="${title}"
            ${clickAttr}
        >
            <img
                class="mini-inv-icon"
                src="${itemImagePath(item)}"
                alt="${itemId}"
            >
        </span>
    `;
}

function renderMiniInventoryGroup(label, slotsOrValue, isTreasure = false) {
    let valueText = "";

    if (isTreasure) {
        valueText = String(slotsOrValue ?? 0);
    } else {
        const slots = Array.isArray(slotsOrValue) ? slotsOrValue : [];
        valueText = slots.map(miniSlotLabel).join(" ");
    }

    const isEmpty = !valueText || valueText === "·" || valueText.replaceAll("·", "").trim() === "";

    return `
        <span class="mini-inv-group">
            <span class="mini-inv-label">${label}</span>
            <span class="mini-inv-value ${isEmpty ? "empty" : ""}">
                ${valueText || "·"}
            </span>
        </span>
    `;
}

function renderCompactPlayerInventory(player) {
    const miniInv = normalizeMiniInventory(player);

    if (!miniInv) {
        return `
            <div class="player-mini-inventory player-mini-inventory-empty">
                <div class="mini-inv-row">
                    <span class="mini-inv-label">Inv</span>
                    <span class="mini-inv-value">—</span>
                </div>
            </div>
        `;
    }

    return `
        <div class="player-mini-inventory">
            ${renderMiniInventoryColumnRow(player, "W", "weapon", miniInv.weapons)}
            ${renderMiniInventoryColumnRow(player, "K", "key", miniInv.keys)}
            ${renderMiniInventoryColumnRow(player, "S", "scroll", miniInv.scrolls)}
            ${renderMiniInventoryColumnRow(player, "T", "treasure", miniInv.treasure, true)}
        </div>
    `;
}

function renderSkillRows(player) {
    const rows = player.skills_ui || [];
    if (rows.length) {
        const flatSkills = rows.flat();

        return flatSkills.map(skill => `
    <div class="player-skill-line">
        ${renderSkillChip(skill, player.player_id)}
    </div>
`).join("");
    }

    const plainSkills = Array.isArray(player.skills) ? player.skills : [];
    if (!plainSkills.length) {
        return `<div style="margin-top:4px; font-size:11px; color:#888;">no skills</div>`;
    }

    const normalized = plainSkills.map(skillId => ({
        skill_id: skillId,
        label: prettySkillLabel(skillId),
        is_available: true,
        is_passive: true,
        control_type: "passive",
    }));

    const chunks = [];
    for (let i = 0; i < normalized.length; i += 2) {
        chunks.push(normalized.slice(i, i + 2));
    }

    return chunks.map(row => `
        <div style="display:flex; gap:6px; flex-wrap:nowrap; margin-top:4px;">
            ${row.map(skill => renderSkillChip(skill, player.player_id)).join("")}
        </div>
    `).join("");
}

/* =========================================================
   ARENA HELPERS UI
   ========================================================= */

function getCurrentTurn() {
    return latestMap?.turn || latestPlayers?.turn || null;
}

function getActiveActor() {
    return latestMap?.active_actor || latestPlayers?.active_actor || null;
}

function getTurnActors() {
    return latestMap?.turn_actors || latestPlayers?.turn_actors || [];
}

function isDungeonActor(actor) {
    return actor?.kind === "game_master" && actor?.actor_id === "__dungeon__";
}

function getTurnActorsInDisplayOrder() {
    const actors = getTurnActors();

    if (!Array.isArray(actors) || !actors.length) {
        return [];
    }

    const activeIndex = actors.findIndex(actor => actor.active === true);

    if (activeIndex < 0) {
        return actors.map((actor, index) => ({
            actor,
            originalIdx: index,
            displayIdx: index,
            isActive: false,
        }));
    }

    const ordered = [];

    for (let offset = 0; offset < actors.length; offset += 1) {
        const originalIdx = (activeIndex + offset) % actors.length;

        ordered.push({
            actor: actors[originalIdx],
            originalIdx,
            displayIdx: offset,
            isActive: offset === 0,
        });
    }

    return ordered;
}

function getPlayerActorPlayer(actor) {
    if (!actor || actor.kind !== "player") {
        return null;
    }

    return getPlayerById(actor.player_id);
}

function formatTurnActor(actor) {
    if (!actor) {
        return "?";
    }

    if (actor.kind === "player") {
        return `P${actor.player_id}`;
    }

    if (isDungeonActor(actor)) {
        return "Dungeon";
    }

    return actor.display_name || actor.kind || "?";
}

function isDungeonInserted() {
    return getTurnActors().some(isDungeonActor);
}

function isAwaitingArenaTargetChoice() {
    const turn = getCurrentTurn();
    return !!turn && turn.mode === "awaiting_arena_target_choice";
}

function isAwaitingArenaLootChoice() {
    const turn = getCurrentTurn();
    return !!turn && turn.mode === "awaiting_arena_loot_choice";
}

function getPendingArenaPvp() {
    const turn = getCurrentTurn();
    return turn?.pending_arena_pvp || null;
}

function getPendingArenaLootChoice() {
    const turn = getCurrentTurn();
    return turn?.pending_arena_loot_choice || null;
}

function getArenaLootLoserPlayerId() {
    const pending = getPendingArenaLootChoice();
    return pending?.loser_player_id ?? null;
}

function getArenaLootWinnerPlayerId() {
    const pending = getPendingArenaLootChoice();
    return pending?.winner_player_id ?? null;
}

function isArenaLootLoser(playerId) {
    const loserId = getArenaLootLoserPlayerId();
    return loserId != null && Number(playerId) === Number(loserId);
}

function findArenaStealableSlotOption(slotGroup, slotIndex) {
    const pending = getPendingArenaLootChoice();
    const slotItems = pending?.stealable?.slot_items || [];

    return slotItems.find(option =>
        option.steal_kind === "slot_item" &&
        option.source_slot_group === slotGroup &&
        Number(option.source_slot_index) === Number(slotIndex)
    ) || null;
}

function getArenaStealableTreasureOption() {
    const pending = getPendingArenaLootChoice();
    return pending?.stealable?.treasure || null;
}


/* =========================================================
   PLAYERS UI
   ========================================================= */
function isAwaitingCurseChoice() {
    const turn =
        latestPlayers?.turn ||
        latestMap?.turn ||
        null;

    return !!turn && turn.mode === "awaiting_curse_choice";
}

function isAwaitingPoisonChoice() {
    const turn =
        latestPlayers?.turn ||
        latestMap?.turn ||
        null;

    return !!turn && turn.mode === "awaiting_poison_choice";
}

function getPlayersInDisplayOrder(players, activeIdx) {
    if (!Array.isArray(players) || !players.length) {
        return [];
    }

    const safeActiveIdx =
        Number.isInteger(activeIdx) &&
        activeIdx >= 0 &&
        activeIdx < players.length
            ? activeIdx
            : 0;

    const ordered = [];

    for (let offset = 0; offset < players.length; offset += 1) {
        const originalIdx = (safeActiveIdx + offset) % players.length;
        ordered.push({
            player: players[originalIdx],
            originalIdx: originalIdx,
            displayIdx: offset,
            isActive: offset === 0,
        });
    }

    return ordered;
}

function renderTurnActorStrip() {
    const actors = getTurnActors();

    if (!actors.length) {
        return "";
    }

    return `
        <div class="turn-actor-strip">
            <div class="turn-actor-strip-title">Turn sequence</div>
            <div class="turn-actor-track">
                ${actors.map((actor, index) => {
        const isDungeon = isDungeonActor(actor);
        const isActive = !!actor.active;
        const isNext = !isActive && index === 1;

        const label = isDungeon
            ? "Dungeon"
            : (actor.display_name || `P${actor.player_id}`);

        const detail = isDungeon
            ? (actor.game_master?.world_event_label || actor.game_master?.world_event_mode || "")
            : "";

        return `
                        <div
                            class="turn-actor-chip ${isActive ? "active" : ""} ${isNext ? "next" : ""} ${isDungeon ? "dungeon" : "player"}"
                            title="${detail ? `${label} — ${detail}` : label}"
                        >
                            <span class="turn-actor-chip-icon">${isDungeon ? "⛰" : "●"}</span>
                            <span class="turn-actor-chip-label">${label}</span>
                            ${detail ? `<span class="turn-actor-chip-detail">${detail}</span>` : ""}
                        </div>
                    `;
    }).join("")}
            </div>
        </div>
    `;
}

function renderGameMasterPlayerRow(actor, isActive) {
    const gm = actor?.game_master || {};
    const label = gm.display_name || actor.display_name || "Dungeon";
    const modeLabel =
        gm.world_event_label ||
        gm.world_event_mode ||
        "World event";

    const row = document.createElement("div");

    row.className =
        "player-row virtual-player-row dungeon-player-row" +
        (isActive ? " active" : "");

    row.onclick = () => {
        showMessage(
            `${label}: ${modeLabel}`,
            "waiting",
            "Dungeon event"
        );
    };

    const left = document.createElement("div");
    left.className = "player-left";

    const portraitWrap = document.createElement("div");
    portraitWrap.className = "player-portrait-wrap";

    const portrait = document.createElement("div");
    portrait.className = "player-portrait virtual-player-portrait";

    if (gm.icon_path) {
        const img = document.createElement("img");
        img.src = karakStaticAsset(gm.icon_path);
        img.alt = label;
        portrait.appendChild(img);
    } else {
        const ph = document.createElement("div");
        ph.className = "player-portrait-placeholder virtual-player-symbol";
        ph.textContent = "⛰";
        portrait.appendChild(ph);
    }

    const nameUnderPortrait = document.createElement("div");
    nameUnderPortrait.className = "player-name-under-portrait";
    nameUnderPortrait.textContent = label;

    const hpUnderPortrait = document.createElement("div");
    hpUnderPortrait.className = "player-hp-under-portrait virtual-player-state";
    hpUnderPortrait.innerHTML = `
        <span class="player-hp-value">EVT</span>
    `;

    const coordsUnderPortrait = document.createElement("div");
    coordsUnderPortrait.className = "player-coordinates-under-portrait";
    coordsUnderPortrait.textContent = "world";

    portraitWrap.appendChild(portrait);
    portraitWrap.appendChild(nameUnderPortrait);
    portraitWrap.appendChild(hpUnderPortrait);
    portraitWrap.appendChild(coordsUnderPortrait);

    const textWrap = document.createElement("div");
    textWrap.className = "player-text";

    const skillsBlock = document.createElement("div");
    skillsBlock.className = "player-skills-column virtual-player-text";
    skillsBlock.innerHTML = `
        <div class="virtual-event-title">${modeLabel}</div>
        <div class="virtual-event-sub">
            Dungeon world-event actor. This is not a player and cannot be targeted.
        </div>
    `;

    textWrap.appendChild(skillsBlock);

    left.appendChild(portraitWrap);
    left.appendChild(textWrap);

    const miniInventoryBlock = document.createElement("div");
    miniInventoryBlock.className = "player-mini-inventory-wrap virtual-player-mini";
    miniInventoryBlock.innerHTML = `
        <div class="player-mini-inventory">
            <div class="mini-inv-row">
                <span class="mini-inv-label">R</span>
                <span class="mini-inv-treasure-value">${gm.turn_nr ?? 0}</span>
            </div>
            <div class="mini-inv-row">
                <span class="mini-inv-label">M</span>
                <span class="mini-inv-treasure-value">EV</span>
            </div>
        </div>
    `;

    row.appendChild(left);
    row.appendChild(miniInventoryBlock);

    return row;
}

function renderPlayers(data) {
    const box = document.getElementById("players-box");
    if (!box) return;

    box.innerHTML = "";

    const players = data?.players || [];
    const activeIdx = data?.active_player_idx ?? 0;

    box.insertAdjacentHTML("beforeend", renderTurnActorStrip());

    const awaitingCurse = isAwaitingCurseChoice();
    const awaitingPoison = isAwaitingPoisonChoice();

    const awaitingArenaTarget = isAwaitingArenaTargetChoice();
    const awaitingArenaLoot = isAwaitingArenaLootChoice();
    const pendingArenaPvp = getPendingArenaPvp();
    const pendingArenaLoot = getPendingArenaLootChoice();

    const arenaEligibleTargetIds = new Set(
        (pendingArenaPvp?.eligible_targets || []).map(t => Number(t.player_id))
    );

    if (!players.length) {
        box.textContent = "(no runtime players)";
        return;
    }

    const orderedActors = getTurnActorsInDisplayOrder();

    const displayRows = orderedActors.length
        ? orderedActors
        : getPlayersInDisplayOrder(players, activeIdx).map(row => ({
            actor: {
                kind: "player",
                player_id: row.player.player_id,
                display_name: row.player.display_name,
                active: row.isActive,
            },
            originalIdx: row.originalIdx,
            displayIdx: row.displayIdx,
            isActive: row.isActive,
        }));

    displayRows.forEach(({actor, originalIdx: idx, displayIdx, isActive}) => {
        if (isDungeonActor(actor)) {
            const dungeonRow = renderGameMasterPlayerRow(actor, isActive);
            box.appendChild(dungeonRow);
            return;
        }

        const p = getPlayerActorPlayer(actor);

        if (!p) {
            return;
        }
        const isCursed = !!(p.status?.is_cursed || p.is_cursed || p.cursed);
        const isEvil = !!(p.status?.is_evil || p.is_evil);
        const hasQuitGame = !!(
            p.status?.has_quit_game ||
            p.escape?.has_quit_game ||
            p.has_quit_game
        );

        const row = document.createElement("div");
        row.className =
            "player-row" +
            (isActive ? " active" : "") +
            (hasQuitGame ? " player-left-game" : "");

        // --------------------------------------------------------
        // Selection / targeting highlight
        // --------------------------------------------------------
        if (awaitingCurse && p.player_id === selectedCurseTargetPlayerId) {
            row.classList.add("curse-selected");
        }

        if (awaitingPoison && p.player_id === selectedPoisonTargetPlayerId) {
            row.classList.add("curse-selected");
        }

        if (
            pendingTeleportSkillId &&
            pendingTeleportTargetMode === "player" &&
            p.player_id === selectedTeleportTargetPlayerId
        ) {
            row.classList.add("curse-selected");
        }

        if (
            pendingItemUse &&
            pendingItemUse.target_player_id === p.player_id
        ) {
            row.classList.add("curse-selected");
        }

        if (
            awaitingArenaTarget &&
            Number(p.player_id) === Number(selectedArenaOpponentPlayerId)
        ) {
            row.classList.add("curse-selected");
        }

        if (
            awaitingArenaLoot &&
            Number(p.player_id) === Number(pendingArenaLoot?.loser_player_id)
        ) {
            row.classList.add("curse-selected");
        }

        const isTeleportPlayerTargeting =
            !!pendingTeleportSkillId &&
            pendingTeleportTargetMode === "player";

        const isItemPlayerTargeting =
            !!pendingItemUse &&
            pendingItemUse.phase === "select_player";

        const canSelectForCurse =
            awaitingCurse &&
            !hasQuitGame;

        const canSelectForPoison =
            awaitingPoison &&
            !hasQuitGame;

        const canSelectForTeleport =
            isTeleportPlayerTargeting &&
            !hasQuitGame;

        const canSelectForItemUse =
            isItemPlayerTargeting &&
            !hasQuitGame;

        const canSelectForArenaOpponent =
            awaitingArenaTarget &&
            !hasQuitGame &&
            arenaEligibleTargetIds.has(Number(p.player_id));

        const canSelectForArenaLoot =
            awaitingArenaLoot &&
            !hasQuitGame &&
            Number(p.player_id) === Number(pendingArenaLoot?.loser_player_id);

        row.style.cursor = (
            canSelectForCurse ||
            canSelectForPoison ||
            canSelectForTeleport ||
            canSelectForItemUse ||
            canSelectForArenaOpponent ||
            canSelectForArenaLoot
        )
            ? "pointer"
            : "default";

        // --------------------------------------------------------
        // Player row click behavior
        // --------------------------------------------------------
        row.onclick = () => {

            // ----------------------------------------------------
            // Escaped / quit player guard.
            //
            // Player remains visible on the board/list for statistics,
            // but must not be selectable for interactions.
            // ----------------------------------------------------
            if (hasQuitGame) {
                showError("This player has already left the dungeon.");
                return;
            }

            // ----------------------------------------------------
            // Arena opponent selection
            // ----------------------------------------------------
            if (canSelectForArenaOpponent) {
                selectedArenaOpponentPlayerId = p.player_id;

                renderPlayers(latestPlayers);
                renderArenaOpponentConfirmArea();
                renderWaitingInstructionMessage();

                return;
            }

            // ----------------------------------------------------
            // Item-use player targeting
            // ----------------------------------------------------
            if (canSelectForItemUse) {
                const activePlayerId = latestPlayers?.active_player?.player_id;

                if (pendingItemUse.effect === "LIFESTEAL" && p.player_id === activePlayerId) {
                    showError("You cannot target yourself with Thorn.");
                    return;
                }

                pendingItemUse.target_player_id = p.player_id;

                // Healing scroll:
                // player target first, then fountain coordinates.
                if (pendingItemUse.effect === "TP_HEAL") {
                    pendingItemUse.phase = "select_fountain";

                    const label = document.getElementById("teleport-mode-label");
                    const xInput = document.getElementById("teleport-x");
                    const yInput = document.getElementById("teleport-y");
                    const cancelBtn = document.getElementById("teleport-cancel-btn");

                    if (label) {
                        label.textContent = itemUseLabel(pendingItemUse);
                    }

                    if (xInput) {
                        xInput.disabled = false;
                        xInput.value = "";
                        xInput.focus();
                    }

                    if (yInput) {
                        yInput.disabled = false;
                        yInput.value = "";
                    }

                    if (cancelBtn) {
                        cancelBtn.disabled = false;
                    }

                    renderPlayers(latestPlayers);
                    updateActionAvailability();
                    renderWaitingInstructionMessage();

                    return;
                }

                // Thorn / LIFESTEAL:
                // player target is enough; resolve immediately.
                if (pendingItemUse.effect === "LIFESTEAL") {
                    const itemUse = pendingItemUse;

                    useInventoryItem({
                        slot_group: itemUse.slot_group,
                        slot_index: itemUse.slot_index,
                        target_player_id: itemUse.target_player_id,
                        target_x: null,
                        target_y: null,
                        successMessage: "Thorn used."
                    });

                    return;
                }

                showError(`Unsupported item effect: ${pendingItemUse.effect}`);
                return;
            }

            // ----------------------------------------------------
            // Poison target player selection
            // ----------------------------------------------------
            if (canSelectForPoison) {
                selectedPoisonTargetPlayerId = p.player_id;
                selectedPoisonTargetSkillId = null;

                renderPlayers(latestPlayers);
                renderPoisonConfirmArea();
                renderWaitingInstructionMessage();

                return;
            }

            // ----------------------------------------------------
            // Teleport target player selection
            // ----------------------------------------------------
            if (canSelectForTeleport) {
                const activePlayerId = latestPlayers?.active_player?.player_id;

                if (p.player_id === activePlayerId) {
                    showError("You must select another player.");
                    return;
                }

                if (pendingTeleportSkillId === "skill_bea_02") {
                    const hp = Number(p.hp?.current ?? 0);
                    const maxHp = Number(p.hp?.max ?? 0);

                    if (maxHp > 0 && hp >= maxHp) {
                        showError("Beasthunter can only teleport to a wounded player.");
                        return;
                    }
                }

                selectedTeleportTargetPlayerId = p.player_id;

                renderPlayers(latestPlayers);
                renderTeleportConfirmArea();
                renderWaitingInstructionMessage();

                return;
            }

            // ----------------------------------------------------
            // Curse target player selection
            // ----------------------------------------------------
            if (canSelectForCurse) {
                selectedCurseTargetPlayerId = p.player_id;

                renderPlayers(latestPlayers);
                renderCurseConfirmArea();
                renderWaitingInstructionMessage();

                return;
            }

            // ----------------------------------------------------
            // Arena loot target display.
            //
            // Currently this row is only visually selected. Actual steal
            // options are handled by the Arena loot confirm area.
            // ----------------------------------------------------
            if (canSelectForArenaLoot) {
                renderPlayers(latestPlayers);
                renderArenaLootConfirmArea();
                renderWaitingInstructionMessage();
                return;
            }
        };

        // --------------------------------------------------------
        // Left side: portrait block + skill column
        // --------------------------------------------------------
        const left = document.createElement("div");
        left.className = "player-left";

        const portraitWrap = document.createElement("div");
        portraitWrap.className = "player-portrait-wrap";

        const portrait = document.createElement("div");
        portrait.className = "player-portrait";
        portrait.style.borderColor = getPlayerTokenColor(p.player_id, idx);
        portrait.style.borderWidth = "4px";

        if (p.icon_path) {
            const img = document.createElement("img");
            img.src = karakStaticAsset(p.icon_path);
            img.alt = p.display_name || "Player";
            portrait.appendChild(img);
        } else {
            const ph = document.createElement("div");
            ph.className = "player-portrait-placeholder";
            ph.textContent = "no image";
            portrait.appendChild(ph);
        }

        const playerNameUnderPortrait = document.createElement("div");
        playerNameUnderPortrait.className = "player-name-under-portrait";
        playerNameUnderPortrait.textContent = p.display_name || "(unnamed)";

        const hpUnderPortrait = document.createElement("div");
        hpUnderPortrait.className = "player-hp-under-portrait";
        hpUnderPortrait.innerHTML = `
            <span class="player-hp-value">${p.hp?.current ?? "?"}</span>
            ${hasQuitGame ? `<span class="player-status-icon" title="Left dungeon">🚪</span>` : ""}
            ${isCursed ? `<span class="player-status-icon player-curse-icon" title="Cursed">☠</span>` : ""}
            ${isEvil ? `<span class="player-status-icon player-evil-icon" title="Karak">◆</span>` : ""}
        `;

        const playerCoordsUnderPortrait = document.createElement("div");
        playerCoordsUnderPortrait.className = "player-coordinates-under-portrait";
        playerCoordsUnderPortrait.textContent = p.position
            ? `(${p.position.x}, ${p.position.y})`
            : "(?, ?)";

        portraitWrap.appendChild(portrait);
        portraitWrap.appendChild(playerNameUnderPortrait);
        portraitWrap.appendChild(hpUnderPortrait);
        portraitWrap.appendChild(playerCoordsUnderPortrait);

        const textWrap = document.createElement("div");
        textWrap.className = "player-text";

        const skillsBlock = document.createElement("div");
        skillsBlock.className = "player-skills-column";
        skillsBlock.innerHTML = renderSkillRows(p);

        textWrap.appendChild(skillsBlock);

        left.appendChild(portraitWrap);
        left.appendChild(textWrap);

        // --------------------------------------------------------
        // Right side: compact read-only inventory
        // --------------------------------------------------------
        const miniInventoryBlock = document.createElement("div");
        miniInventoryBlock.className = "player-mini-inventory-wrap";
        miniInventoryBlock.innerHTML = renderCompactPlayerInventory(p);

        row.appendChild(left);
        row.appendChild(miniInventoryBlock);

        box.appendChild(row);
    });
}


// Development helper only.
// Normal hotseat turn flow should use endTurn(), not manual active-player selection.
async function debugInsertDungeonActor() {
    clearError();

    const r = await karakFetch(gameApi("/debug/insert_dungeon_actor"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Failed to insert Dungeon actor.");
        return;
    }

    await refreshAll();

    showMessage("Dungeon actor inserted after active player.", "info", "Debug");
}

async function debugInsertDungeonActor() {
    clearError();

    const r = await karakFetch(gameApi("/debug/insert_dungeon_actor"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Failed to insert Dungeon actor.");
        return;
    }

    await refreshAll();

    showMessage("Dungeon actor inserted after active player.", "info", "Debug");
}

function getSkillUiForActivePlayer(skillId) {
    const activePlayer = latestPlayers?.active_player || null;
    const rows = activePlayer?.skills_ui || [];

    for (const row of rows) {
        for (const skill of row) {
            if (skill.skill_id === skillId) {
                return skill;
            }
        }
    }

    return null;
}

function isSkillAvailableForActivePlayer(skillId) {
    const skill = getSkillUiForActivePlayer(skillId);
    return !!skill && skill.is_available !== false;
}

function isSkillSelectedForActivePlayer(skillId) {
    const activePlayer = latestPlayers?.active_player || null;
    const rows = activePlayer?.skills_ui || [];

    for (const row of rows) {
        for (const skill of row) {
            if (skill.skill_id === skillId) {
                return !!skill.selected;
            }
        }
    }

    return false;
}

async function move(direction) {
    clearError();

    const usePeek = isSkillSelectedForActivePlayer("skill_ran_02");

    const scoutSkillAvailable = isSkillAvailableForActivePlayer("skill_sco_02");
    const hasSelectedPocketTile = selectedScoutPocketTileIndex !== null;

    const usePocketTile =
        hasSelectedPocketTile &&
        scoutSkillAvailable;

    const payload = {
        direction: direction,
        is_mage: false,
        reveal_kind: usePeek ? "peek" : "discover",
        tile_source: usePocketTile ? "pocket" : "pile",
        pocket_tile_index: usePocketTile ? selectedScoutPocketTileIndex : null
    };

    const r = await karakFetch(gameApi("/move"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Move failed.");
        return;
    }

    // Pocket selection is a soft frontend preference.
    // Clear it after any successful navigation/reveal action.
    selectedScoutPocketTileIndex = null;

    await refreshAll();

    if (hasSelectedPocketTile && !scoutSkillAvailable) {
        showMessage(
            "Scout pocket tile was ignored because skill_sco_02 is currently blocked. Drew from pile instead.",
            "warning",
            "Scout pocket"
        );
    }
}


function renderActivePlayer(data) {
    const box = document.getElementById("active-player-box");
    if (!box) return;

    box.textContent = JSON.stringify(data.active_player || null, null, 2);
}

function renderMapJson(data) {
    const box = document.getElementById("map-box");
    if (!box) return;

    box.textContent = JSON.stringify(data, null, 2);
}

function renderDiagnostics(playersData, mapData) {
    const box = document.getElementById("diag-box");
    if (!box) return;

    const lines = [];

    lines.push(`Players initialized: ${(playersData.players || []).length}`);
    lines.push(`Active player index: ${playersData.active_player_idx ?? "-"}`);

    const activeActor = mapData?.active_actor || playersData?.active_actor || null;
    const turnActors = mapData?.turn_actors || playersData?.turn_actors || [];

    if (activeActor) {
        lines.push(
            `Active actor: ${activeActor.kind}:${activeActor.player_id ?? activeActor.actor_id ?? "-"}`
        );
    } else {
        lines.push("Active actor: -");
    }

    if (turnActors.length) {
        lines.push(
            "Turn actors: " + turnActors.map(formatTurnActor).join(" → ")
        );
    } else {
        lines.push("Turn actors: -");
    }

    if (mapData.player) {
        lines.push(`Compat player position: (${mapData.player.x}, ${mapData.player.y})`);
    }

    lines.push(`Tiles left: ${mapData.tiles_left}`);
    lines.push(`Entities left: ${mapData.entities_left}`);
    lines.push(`Room X discovered: ${mapData.room_x_discovered ?? 0}`);
    lines.push(`Karak triggered: ${mapData.karak_triggered ? "yes" : "no"}`);

    if (mapData.last_karak_event?.triggered) {
        lines.push(`Karak player: #${mapData.last_karak_event.selected_player_id}`);
        lines.push(`Karak score: ${mapData.last_karak_event.selected_player_score}`);
    }

    box.textContent = lines.join("\n");
}

function renderCurseRoomToss(mapData) {
    const box = document.getElementById("curse-toss-box");
    const dieEl = document.getElementById("curse-toss-die");

    if (!box || !dieEl) {
        return;
    }

    const event = mapData?.last_room_x_event || null;

    box.classList.remove("counter-triggered", "counter-neutral");

    if (!event || event.kind !== "curse_room") {
        dieEl.textContent = "-";
        box.classList.add("counter-neutral");
        return;
    }

    const die = event.die ?? "-";
    const triggered = !!event.triggered;

    dieEl.textContent = String(die);
    box.classList.add(triggered ? "counter-triggered" : "counter-neutral");
}

function renderActionCounter() {
    console.log("renderActionCounter() called");

    const box = document.getElementById("action-counter-box");
    const valueEl = document.getElementById("action-counter-value");

    console.log("action counter elements:", {
        boxFound: !!box,
        valueFound: !!valueEl
    });

    if (!box || !valueEl) {
        return;
    }

    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;

    console.log("turn object for action counter:", turn);

    const actionsLeft =
        turn?.actions_left ??
        turn?.action_left ??
        turn?.actionsLeft ??
        turn?.moves_left ??
        turn?.movement_left ??
        null;

    const actionsTotal =
        turn?.actions_total ??
        turn?.action_total ??
        turn?.actionsTotal ??
        turn?.moves_total ??
        turn?.movement_total ??
        4;

    box.classList.remove("action-low", "action-empty");

    if (actionsLeft == null) {
        valueEl.textContent = "? / ?";
        return;
    }

    valueEl.textContent = `${actionsLeft} / ${actionsTotal}`;

    if (Number(actionsLeft) <= 0) {
        box.classList.add("action-empty");
    } else if (Number(actionsLeft) === 1) {
        box.classList.add("action-low");
    }
}

function renderRoomXCounter(mapData) {
    const box = document.getElementById("room-x-counter-box");
    const valueEl = document.getElementById("room-x-counter-value");

    if (!box || !valueEl) {
        return;
    }

    const value = Number(mapData?.room_x_discovered ?? 0);
    const limit = Number(mapData?.room_x_karak_limit ?? 5);

    valueEl.textContent = String(value);

    box.classList.remove("counter-triggered", "counter-neutral");

    if (value >= limit) {
        box.classList.add("counter-triggered");
    } else {
        box.classList.add("counter-neutral");
    }
}

function getPendingDiscoveryTarget() {
    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;

    const pd = turn?.pending_discovery || null;

    if (!pd) {
        return null;
    }

    const x = Number(pd.target_x);
    const y = Number(pd.target_y);

    if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return null;
    }

    return {x, y};
}

function getActivePlayerCurrentTile() {
    const activePlayer = latestPlayers?.active_player || null;
    const tiles = latestMap?.tiles || {};

    if (!activePlayer?.position) {
        return null;
    }

    const key = `${activePlayer.position.x},${activePlayer.position.y}`;
    return tiles[key] || null;
}

function entityImagePath(entityId) {
    if (!entityId) {
        return null;
    }

    return `${KARAK_STATIC_URL}/media/tile-content/${entityId}.png`;
}

async function loadPlayers() {
    const r = await karakFetch(gameApi("/players"));
    const data = await r.json();

    if (!r.ok) {
        throw new Error(data.detail || "Failed to load runtime players.");
    }

    latestPlayers = data;

    // Do not render here.
    // renderPlayers() depends on latestMap.turn for Arena / curse / poison / teleport modes.
    // refreshAll() renders players after both latestPlayers and latestMap are up to date.
}

async function loadMap() {
    const r = await karakFetch(gameApi("/map"));
    const data = await r.json();
    if (!r.ok) {
        throw new Error(data.detail || "Failed to load map.");
    }

    latestMap = data;
}

function renderCurseConfirmArea() {
    const box = document.getElementById("curse-confirm-box");
    if (!box) return;

    if (!isAwaitingCurseChoice()) {
        box.style.display = "none";
        box.innerHTML = "";
        return;
    }

    box.style.display = "block";

    const players = latestPlayers?.players || [];
    const selected = players.find(p => p.player_id === selectedCurseTargetPlayerId);

    if (!selected) {
        box.innerHTML = `
            <div class="muted">Select a player to receive the curse.</div>
        `;
        return;
    }

    box.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <div>Selected: <b>${selected.display_name || ("Player #" + selected.player_id)}</b></div>
            <button onclick="confirmCurseSelection()">☠️ Confirm Curse</button>
            <button onclick="clearCurseSelection()">Reset</button>
        </div>
    `;
}

function renderArenaOpponentConfirmArea() {
    const box = document.getElementById("curse-confirm-box");
    if (!box) return;

    if (!isAwaitingArenaTargetChoice()) {
        // Do not clear the box if another mode owns it.
        return;
    }

    box.style.display = "block";

    const players = latestPlayers?.players || [];
    const selected = players.find(
        p => Number(p.player_id) === Number(selectedArenaOpponentPlayerId)
    );

    if (!selected) {
        box.innerHTML = `
            <div class="muted">Arena activated. Select one opponent from the player list.</div>
        `;
        return;
    }

    box.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <div>
                Arena opponent:
                <b>${selected.display_name || ("Player #" + selected.player_id)}</b>
            </div>
            <button onclick="confirmArenaOpponentSelection()">⚔️ Confirm Challenge</button>
            <button onclick="clearArenaOpponentSelection()">Reset</button>
        </div>
    `;
}

function clearArenaOpponentSelection() {
    selectedArenaOpponentPlayerId = null;
    renderPlayers(latestPlayers);
    renderArenaOpponentConfirmArea();
    renderWaitingInstructionMessage();
}

async function confirmArenaOpponentSelection() {
    if (selectedArenaOpponentPlayerId == null) {
        showError("No Arena opponent selected.");
        return;
    }

    await chooseArenaOpponent(selectedArenaOpponentPlayerId);

    selectedArenaOpponentPlayerId = null;
}

function renderArenaLootConfirmArea() {
    const box = document.getElementById("curse-confirm-box");
    if (!box) return;

    if (!isAwaitingArenaLootChoice()) {
        return;
    }

    box.style.display = "block";

    const pending = getPendingArenaLootChoice();

    if (!pending) {
        box.innerHTML = `<div class="muted">No pending Arena loot choice.</div>`;
        return;
    }

    const winner = getPlayerById(pending.winner_player_id);
    const loser = getPlayerById(pending.loser_player_id);

    const winnerName = winner?.display_name || `Player #${pending.winner_player_id}`;
    const loserName = loser?.display_name || `Player #${pending.loser_player_id}`;

    if (!selectedArenaLootChoice) {
        box.innerHTML = `
            <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
                <div>
                    Arena loot:
                    <b>${winnerName}</b> may steal from <b>${loserName}</b>.
                    Click an item or treasure in the loser’s mini-inventory.
                </div>
                <button onclick="chooseArenaLootSkip()">Skip</button>
            </div>
        `;
        return;
    }

    box.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <div>
                Selected loot:
                <b>${selectedArenaLootChoice.label || selectedArenaLootChoice.steal_kind}</b>
            </div>
            <button onclick="confirmArenaLootSelection()">Steal</button>
            <button onclick="chooseArenaLootSkip()">Skip</button>
            <button onclick="clearArenaLootSelection()">Reset</button>
        </div>
    `;
}

function clearArenaLootSelection() {
    selectedArenaLootChoice = null;
    renderPlayers(latestPlayers);
    renderArenaLootConfirmArea();
    renderWaitingInstructionMessage();
}

async function confirmArenaLootSelection() {
    if (!selectedArenaLootChoice) {
        showError("No Arena loot selected.");
        return;
    }

    await chooseArenaLoot(selectedArenaLootChoice);

    selectedArenaLootChoice = null;
}

function selectArenaLootSlot(playerId, slotGroup, slotIndex, itemId) {
    if (!isAwaitingArenaLootChoice()) {
        return;
    }

    if (!isArenaLootLoser(playerId)) {
        showError("Arena loot can only be stolen from the loser.");
        return;
    }

    const option = findArenaStealableSlotOption(slotGroup, slotIndex);

    if (!option) {
        showError("This item cannot be stolen now. The winner may have no compatible free slot.");
        return;
    }

    selectedArenaLootChoice = {
        steal_kind: "slot_item",
        source_slot_group: slotGroup,
        source_slot_index: Number(slotIndex),
        label: itemId || option.item_id || `${slotGroup}[${slotIndex}]`
    };

    renderPlayers(latestPlayers);
    renderArenaLootConfirmArea();
    renderWaitingInstructionMessage();
}

function selectArenaLootTreasure(playerId) {
    if (!isAwaitingArenaLootChoice()) {
        return;
    }

    if (!isArenaLootLoser(playerId)) {
        showError("Arena treasure can only be stolen from the loser.");
        return;
    }

    const option = getArenaStealableTreasureOption();

    if (!option) {
        showError("This player has no stealable treasure.");
        return;
    }

    selectedArenaLootChoice = {
        steal_kind: "treasure_value",
        label: `Treasure (${option.value ?? "?"})`
    };

    renderPlayers(latestPlayers);
    renderArenaLootConfirmArea();
    renderWaitingInstructionMessage();
}

function getPendingEntityChoice() {
    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;

    return turn?.pending_entity_choice || null;
}

async function confirmEntityCandidate(candidateIndex) {
    clearError();

    const r = await karakFetch(gameApi("/entity/confirm_candidate"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({candidate_index: candidateIndex})
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Entity confirmation failed.");
        return;
    }

    await refreshAll();
}

async function redrawEntityCandidate() {
    clearError();

    const r = await karakFetch(gameApi("/entity/redraw_candidate"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Entity redraw failed.");
        return;
    }

    await refreshAll();
}


function renderEncounterPanel() {
    const box = document.getElementById("entity-choice-box");

    if (!box) {
        console.error("entity-choice-box not found");
        return;
    }

    // --------------------------------------------------------
    // Arena opponent choice
    // Selection happens in the player list, not in this panel.
    // --------------------------------------------------------
    if (isAwaitingArenaTargetChoice()) {
        box.classList.remove(
            "panel-placeholder",
            "encounter-entity-choice-box",
            "encounter-arena-loot-box"
        );
        box.classList.add("encounter-box", "encounter-arena-choice-box");

        box.innerHTML = `
        <div class="encounter-active-player">
            <div style="font-size:18px; font-weight:bold;">
                ⚔ Arena
            </div>
        </div>

        <div class="encounter-target">
            <div class="encounter-target-empty">player target</div>
        </div>
    `;

        return;
    }

    if (isAwaitingArenaLootChoice()) {
        box.classList.remove(
            "panel-placeholder",
            "encounter-entity-choice-box",
            "encounter-arena-choice-box"
        );
        box.classList.add("encounter-box", "encounter-arena-loot-box");

        box.innerHTML = `
        <div class="encounter-active-player">
            <div style="font-size:18px; font-weight:bold;">
                🏆 Loot
            </div>
        </div>

        <div class="encounter-target">
            <div class="encounter-target-empty">mini-inventory</div>
        </div>
    `;

        return;
    }

    const activePlayer = latestPlayers?.active_player || null;
    const currentTile = getActivePlayerCurrentTile();
    const pendingChoice = getPendingEntityChoice();

    const tableauPath = karakStaticAsset(
        activePlayer?.tableau_path ||
        activePlayer?.image_path ||
        activePlayer?.icon_path ||
        null
    );

    // --------------------------------------------------------
    // Pending Oracle / Alchemist entity choice
    // --------------------------------------------------------
    if (pendingChoice) {
        const candidates = Array.isArray(pendingChoice.candidates)
            ? pendingChoice.candidates
            : [];

        const confirmable = new Set(
            (pendingChoice.confirmable_indices || []).map(Number)
        );

        const canRedraw = !!pendingChoice.has_alc_02;

        box.classList.remove(
            "panel-placeholder",
            "encounter-arena-choice-box",
            "encounter-arena-loot-box"
        );
        box.classList.add("encounter-box", "encounter-entity-choice-box");

        box.innerHTML = `
            <div class="encounter-active-player">
                ${
            tableauPath
                ? `<img class="encounter-tableau-img" src="${tableauPath}" alt="active player">`
                : `<div class="encounter-tableau-placeholder">no tableau</div>`
        }
            </div>

            <div class="encounter-entity-choice">
                <div class="entity-choice-candidates">
                    ${
            candidates.length
                ? candidates.map((m, i) => {
                    const isConfirmable = confirmable.has(i);
                    const entityId = m.entity_id || "?";
                    const imgPath = karakStaticAsset(m.image_path) || entityImagePath(entityId);

                    return `
                                    <button
                                        type="button"
                                        class="entity-choice-card ${isConfirmable ? "confirmable" : "not-confirmable"}"
                                        ${isConfirmable ? "" : "disabled"}
                                        onclick="confirmEntityCandidate(${i})"
                                        title="${entityId}"
                                    >
                                        <img src="${imgPath}" alt="${entityId}">
                                        <span>${entityId}</span>
                                    </button>
                                `;
                }).join("")
                : `<div class="encounter-target-empty">no candidates</div>`
        }
                </div>

                <div class="entity-choice-actions">
                    <button
                        type="button"
                        onclick="redrawEntityCandidate()"
                        ${canRedraw ? "" : "disabled"}
                        title="Alchemist redraw: costs 1 Action and 1 HP"
                    >redraw</button>
                </div>
            </div>
        `;

        return;
    }

    // --------------------------------------------------------
    // Default encounter display: active player + current entity
    // --------------------------------------------------------
    const entityId = currentTile?.entity_id || null;
    const entityPath = entityImagePath(entityId);

    console.log("ENCOUNTER DEBUG", {
        activePlayer,
        tableauPath,
        currentTile,
        entityId,
        entityPath
    });

    box.classList.remove(
        "panel-placeholder",
        "encounter-entity-choice-box",
        "encounter-arena-choice-box",
        "encounter-arena-loot-box"
    );
    box.classList.add("encounter-box");

    box.innerHTML = `
        <div class="encounter-active-player">
            ${
        tableauPath
            ? `<img class="encounter-tableau-img" src="${tableauPath}" alt="active player">`
            : `<div class="encounter-tableau-placeholder">no tableau</div>`
    }
        </div>

        <div class="encounter-target">
            ${
        entityId
            ? `<img class="encounter-entity-img" src="${entityPath}" alt="${entityId}">`
            : `<div class="encounter-target-empty">no entity</div>`
    }
        </div>
    `;
}

function renderPoisonConfirmArea() {
    const box = document.getElementById("poison-confirm-box");
    if (!box) return;

    if (!isAwaitingPoisonChoice()) {
        box.style.display = "none";
        box.innerHTML = "";
        return;
    }

    box.style.display = "block";

    const players = latestPlayers?.players || [];
    const selectedPlayer = players.find(p => p.player_id === selectedPoisonTargetPlayerId);

    if (!selectedPlayer) {
        box.innerHTML = `
            <div class="muted">Select a player to receive poison.</div>
        `;
        return;
    }

    if (!selectedPoisonTargetSkillId) {
        box.innerHTML = `
            <div>
                Selected player:
                <b>${selectedPlayer.display_name || ("Player #" + selectedPlayer.player_id)}</b>
            </div>
            <div class="muted" style="margin-top:4px;">
                Now click one of this player's skill chips.
            </div>
            <div style="margin-top:6px;">
                <button onclick="clearPoisonSelection()">Reset</button>
            </div>
        `;
        return;
    }

    box.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <div>
                Selected:
                <b>${selectedPlayer.display_name || ("Player #" + selectedPlayer.player_id)}</b>
                /
                <b>${prettySkillLabel(selectedPoisonTargetSkillId)}</b>
            </div>
            <button onclick="confirmPoisonSelection()">☣️ Confirm Poison</button>
            <button onclick="clearPoisonSelection()">Reset</button>
        </div>
    `;
}

function renderTeleportConfirmArea() {
    const box = document.getElementById("teleport-confirm-box");
    if (!box) return;

    if (!pendingTeleportSkillId || pendingTeleportTargetMode !== "player") {
        box.style.display = "none";
        box.innerHTML = "";
        return;
    }

    box.style.display = "block";

    const players = latestPlayers?.players || [];
    const selected = players.find(p => p.player_id === selectedTeleportTargetPlayerId);

    if (!selected) {
        box.innerHTML = `
            <div class="muted">
                ${teleportSkillLabel(pendingTeleportSkillId)}.
                Click exactly one player row.
            </div>
            <div style="margin-top:6px;">
                <button onclick="cancelTeleportTargeting()">Cancel</button>
            </div>
        `;
        return;
    }

    const actionLabel = pendingTeleportSkillId === "skill_bea_02"
        ? "Confirm Heal Teleport"
        : "Confirm Swap";

    box.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
            <div>
                Selected:
                <b>${selected.display_name || ("Player #" + selected.player_id)}</b>
                <span class="muted">
                    (${selected.position?.x ?? "?"}, ${selected.position?.y ?? "?"})
                </span>
            </div>
            <button onclick="confirmPlayerTargetTeleport()">${actionLabel}</button>
            <button onclick="clearTeleportTargetSelection()">Reset</button>
            <button onclick="cancelTeleportTargeting()">Cancel</button>
        </div>
    `;
}

function clearTeleportTargetSelection() {
    selectedTeleportTargetPlayerId = null;
    renderPlayers(latestPlayers);
    renderTeleportConfirmArea();
    renderWaitingInstructionMessage();
}

function showKarakCreatedMessage(confirmData) {
    const karak = confirmData?.discovery?.karak || null;

    if (!karak || !karak.triggered) {
        return false;
    }

    const players =
        confirmData.players ||
        latestPlayers?.players ||
        [];

    const scores = karak.all_player_scores || {};
    const selectedPlayerId = karak.selected_player_id;

    const lines = [];

    lines.push("Karak has appeared.");
    lines.push("");
    lines.push("Inventory value calculation:");

    Object.entries(scores).forEach(([playerIdRaw, score]) => {
        const playerId = Number(playerIdRaw);
        const player = players.find(p => Number(p.player_id) === playerId);

        const name =
            player?.display_name ||
            player?.character_name ||
            `Player #${playerId}`;

        const marker = playerId === Number(selectedPlayerId) ? "  ← KARAK" : "";

        lines.push(`${name}: ${score}${marker}`);
    });

    showMessage(lines.join("\n"), "error", "Karak created");

    return true;
}

async function refreshAll() {
    try {
        // --------------------------------------------------------
        // Load map FIRST.
        //
        // The map payload is the safest global source for:
        // - game_scope
        // - game_over
        // - redirect_to
        // - turn
        //
        // If the game has already entered results, do not load
        // inventory afterward, because inventory requires active turn.
        // --------------------------------------------------------
        await loadMap();

        if (handleGameOverRedirect(latestMap)) {
            return;
        }

        await loadPlayers();

        if (handleGameOverRedirect(latestPlayers)) {
            return;
        }

        await loadInventory();

        // --------------------------------------------------------
        // If inventory load indirectly discovered game-over, stop.
        // This is defensive; normally map already catches it.
        // --------------------------------------------------------
        if (handleGameOverRedirect(latestMap) || handleGameOverRedirect(latestPlayers)) {
            return;
        }

        // --------------------------------------------------------
        // Clear local item-use targeting if turn changed.
        // This prevents target-picking state from leaking into
        // the next player's turn.
        // --------------------------------------------------------
        if (typeof clearPendingItemUseIfTurnChanged === "function") {
            clearPendingItemUseIfTurnChanged();
        }

        renderPlayers(latestPlayers);

        if (!isSkillAvailableForActivePlayer("skill_sco_02")) {
            selectedScoutPocketTileIndex = null;
        }

        if (!latestPlayers?.players?.length) {
            skillUiState = {};
        }

        if (!isAwaitingCurseChoice()) {
            selectedCurseTargetPlayerId = null;
        }

        if (!isAwaitingPoisonChoice()) {
            selectedPoisonTargetPlayerId = null;
            selectedPoisonTargetSkillId = null;
        }

        if (!isAwaitingArenaTargetChoice()) {
            selectedArenaOpponentPlayerId = null;
        }

        if (!isAwaitingArenaLootChoice()) {
            selectedArenaLootChoice = null;
        }

        if (!pendingTeleportSkillId) {
            selectedTeleportTargetPlayerId = null;
            pendingTeleportTargetMode = null;
        }

        renderMapVisual();
        renderEncounterPanel();
        renderActionCounter();
        renderRoomXCounter(latestMap);
        renderCurseRoomToss(latestMap);
        renderCurseConfirmArea();
        renderPoisonConfirmArea();
        renderTeleportConfirmArea();
        renderArenaOpponentConfirmArea();
        renderArenaLootConfirmArea();

        const turn = latestMap?.turn || latestPlayers?.turn || null;

        if (turn?.mode === "fight") {
            try {
                const r = await karakFetch(gameApi("/fight/state"));
                const data = await r.json();

                if (handleGameOverRedirect(data)) {
                    return;
                }

                if (r.ok) {
                    renderFight(data);
                } else {
                    openFightModal();

                    const box = document.getElementById("fight-box");
                    if (box) {
                        box.innerHTML = `
                            <div class="message-box message-error">
                                <b>Fight state unavailable</b>
                                <pre>${data.detail || "Backend says turn is in fight mode, but fight/state could not be loaded."}</pre>
                            </div>
                        `;
                    }
                }
            } catch (fightError) {
                console.error("fight/state refresh failed:", fightError);

                openFightModal();

                const box = document.getElementById("fight-box");
                if (box) {
                    box.innerHTML = `
                        <div class="message-box message-error">
                            <b>Fight render failed</b>
                            <pre>${String(fightError)}</pre>
                        </div>
                    `;
                }
            }
        } else {
            renderFight(null);
        }

        const waitingMessageShown = renderWaitingInstructionMessage();

        if (!waitingMessageShown) {
            showMessage("Phase 3 state refreshed.", "info", "Info");
        }

        updateActionAvailability();

    } catch (e) {
        console.error("refreshAll failed:", e);

        const message = String(e?.message || e);

        // --------------------------------------------------------
        // If anything failed because the backend has no active turn,
        // reload map and let map/results redirect decide.
        // --------------------------------------------------------
        if (message.includes("No active turn")) {
            try {
                await loadMap();

                if (handleGameOverRedirect(latestMap)) {
                    return;
                }
            } catch (mapError) {
                console.error("refreshAll recovery loadMap failed:", mapError);
            }
        }

        showError(message);
        updateActionAvailability();
    }
}

async function confirmHealingChoice() {
    clearError();

    const activePlayer = latestPlayers?.active_player || null;
    const skillsUi = activePlayer?.skills_ui || [];

    let barSkill = null;

    for (const row of skillsUi) {
        for (const skill of row) {
            if (skill.skill_id === "skill_bar_01") {
                barSkill = skill;
                break;
            }
        }
        if (barSkill) break;
    }

    const targetHp = barSkill?.value;

    if (targetHp == null) {
        showError("No Barbarian healing target selected.");
        return;
    }

    const r = await karakFetch(gameApi("/healing/choose_target"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target_hp: targetHp})
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Healing choice failed.");
        return;
    }

    await refreshAll();
    showMessage("Healing choice confirmed. Turn ended.", "info", "Info");
}

async function confirmTeleport() {
    clearError();

    const x = parseInt(document.getElementById("teleport-x").value, 10);
    const y = parseInt(document.getElementById("teleport-y").value, 10);

    if (isNaN(x) || isNaN(y)) {
        showError("Invalid teleport coordinates.");
        return;
    }

    // --------------------------------------------------------
    // KO reaction fountain choice
    // Used by skill_wrr_02.
    //
    // This is not a normal teleport Action.
    // It resolves a pending forced fountain teleport.
    // --------------------------------------------------------
    if (isAwaitingKoReactionChoice()) {
        const r = await karakFetch(gameApi("/ko_reaction/choose_fountain"), {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({x, y})
        });

        const data = await r.json();

        if (!r.ok) {
            showError(data.detail || "KO reaction failed.");
            return;
        }

        document.getElementById("teleport-x").value = "";
        document.getElementById("teleport-y").value = "";

        pendingTeleportSkillId = null;
        pendingTeleportTargetMode = null;
        selectedTeleportTargetPlayerId = null;
        pendingItemUse = null;

        const label = document.getElementById("teleport-mode-label");
        const cancelBtn = document.getElementById("teleport-cancel-btn");

        if (label) {
            label.textContent = "Portal teleport";
        }

        if (cancelBtn) {
            cancelBtn.disabled = true;
        }

        renderTeleportConfirmArea();

        await refreshAll();
        showMessage("KO reaction resolved.", "info", "Info");
        return;
    }

    // --------------------------------------------------------
    // Item-use coordinate confirmation.
    // Healing scroll uses the coordinate box to choose fountain.
    // This is not a normal teleport Action.
    //
    // Thorn / LIFESTEAL does NOT arrive here, because it resolves
    // immediately after selecting a target player.
    // --------------------------------------------------------
    if (pendingItemUse) {
        if (pendingItemUse.effect !== "TP_HEAL") {
            showError(`Unsupported coordinate-based item effect: ${pendingItemUse.effect}`);
            return;
        }

        if (pendingItemUse.phase !== "select_fountain") {
            showError("Healing scroll requires selecting a player first.");
            return;
        }

        if (pendingItemUse.target_player_id == null) {
            showError("No healing scroll target player selected.");
            return;
        }

        const itemUse = pendingItemUse;

        await useInventoryItem({
            slot_group: itemUse.slot_group,
            slot_index: itemUse.slot_index,
            target_player_id: itemUse.target_player_id,
            target_x: x,
            target_y: y,
            successMessage: "Healing scroll used."
        });

        return;
    }

    // --------------------------------------------------------
    // Player-targeted teleports are confirmed through the
    // player target box, not through coordinate confirmation.
    // --------------------------------------------------------
    if (pendingTeleportSkillId && pendingTeleportTargetMode === "player") {
        showError("This teleport requires selecting a player, not coordinates.");
        return;
    }

    let endpoint = "/teleport";
    let payload = {x, y};

    // --------------------------------------------------------
    // Coordinate-targeted skill teleport.
    // Currently:
    // - skill_bat_02
    // --------------------------------------------------------
    if (pendingTeleportSkillId) {
        if (pendingTeleportSkillId === "skill_bat_02") {
            endpoint = "/skills/bat_02/teleport";
            payload = {x, y};
        } else {
            showError(`Unsupported coordinate-targeted teleport skill: ${pendingTeleportSkillId}`);
            return;
        }
    }

    const usedSkill = pendingTeleportSkillId;

    const r = await karakFetch(gameApi(endpoint), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Teleport failed.");
        return;
    }

    document.getElementById("teleport-x").value = "";
    document.getElementById("teleport-y").value = "";

    pendingTeleportSkillId = null;
    pendingTeleportTargetMode = null;
    selectedTeleportTargetPlayerId = null;
    pendingItemUse = null;

    const label = document.getElementById("teleport-mode-label");
    const cancelBtn = document.getElementById("teleport-cancel-btn");

    if (label) {
        label.textContent = "Portal teleport";
    }

    if (cancelBtn) {
        cancelBtn.disabled = true;
    }

    renderTeleportConfirmArea();

    await refreshAll();

    if (usedSkill) {
        showMessage(`Teleport skill used: ${prettySkillLabel(usedSkill)}`, "info", "Info");
    } else {
        showMessage("Portal teleport used.", "info", "Info");
    }
}

async function confirmPlayerTargetTeleport() {
    clearError();

    if (!pendingTeleportSkillId || pendingTeleportTargetMode !== "player") {
        showError("No player-targeted teleport is pending.");
        return;
    }

    if (selectedTeleportTargetPlayerId == null) {
        showError("No target player selected.");
        return;
    }

    let endpoint = null;

    if (pendingTeleportSkillId === "skill_bea_02") {
        endpoint = "/skills/bea_02/teleport";
    } else if (pendingTeleportSkillId === "skill_wlk_02") {
        endpoint = "/skills/wlk_02/teleport";
    } else {
        showError(`Unsupported player-targeted teleport skill: ${pendingTeleportSkillId}`);
        return;
    }

    const usedSkill = pendingTeleportSkillId;
    const targetPlayerId = selectedTeleportTargetPlayerId;

    const r = await karakFetch(gameApi(endpoint), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            target_player_id: targetPlayerId
        })
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Teleport skill failed.");
        return;
    }

    pendingTeleportSkillId = null;
    pendingTeleportTargetMode = null;
    selectedTeleportTargetPlayerId = null;

    renderTeleportConfirmArea();

    await refreshAll();

    showMessage(
        `Teleport skill used: ${prettySkillLabel(usedSkill)}`,
        "info",
        "Info"
    );
}

async function fight() {
    await fightStart();
}

async function rotateTile(direction) {
    const target = getPendingDiscoveryTarget();

    if (!target) {
        showError("No pending tile target to rotate.");
        return;
    }

    const r = await karakFetch(gameApi("/rotate_tile"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            x: target.x,
            y: target.y,
            direction
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Rotate failed.");
        return;
    }

    await refreshAll();
}

function itemImagePath(item) {
    if (!item || !item.image_path) {
        throw new Error("Missing item.image_path in API response.");
    }

    return karakStaticAsset(item.image_path);
}

function renderGround(data) {
    const box = document.getElementById("ground-box");
    if (!box) return;

    const groundItem = data?.ground_item || null;
    const groundItemId = data?.ground_item_id || groundItem?.item_id || null;
    const groundItemDesc = groundItem?.desc || "";

    const activationUi = data?.ground_activation_ui || {};
    const activationEnabled = !!activationUi.activation_enabled;
    const activationLabel = activationUi.activation_label || "activate";
    const activationEffect = activationUi.activation_effect || null;
    const activationReason = activationUi.activation_reason || "";

    box.innerHTML = `
        <div class="ground-title">Ground</div>
        <div class="ground-slot">
            <div class="ground-image">
                ${groundItem
        ? `<img class="item-icon" src="${itemImagePath(groundItem)}" alt="${groundItemId || ""}">`
        : `<span class="muted">(empty)</span>`}
            </div>

            <div class="ground-text">
                <div class="ground-id">${groundItemId || "-"}</div>
                <div class="ground-desc">${groundItemDesc || ""}</div>
                ${
        groundItem
            ? `
                <button
                    type="button"
                    class="ground-activate-btn ${activationEnabled ? "" : "inventory-btn-placeholder"}"
                    onclick="activateGroundObject()"
                    ${activationEnabled ? "" : "disabled"}
                    title="${activationEnabled ? activationEffect : activationReason}"
                >${activationEnabled ? activationLabel : ""}</button>
            `
            : ""
    }
            </div>
        </div>
    `;
}

function slotActionLabel(slot) {
    if (!slot || slot.available_action === "inactive") {
        return "";
    }

    return slot.available_action || "";
}

function slotActionDisabled(slot) {
    return !slot || slot.available_action === "inactive";
}

function renderSingleSlotCard(slotGroup, slot) {
    const item = slot?.item || null;
    const itemId = slot?.item_id || item?.item_id || null;
    const slotIndex = slot?.slot_index ?? 0;

    // --------------------------------------------------------
    // Explicit USE button
    // Examples:
    // - TP_HEAL
    // - LIFESTEAL
    // - PURGE
    // - KEY_ENTITY_DAMAGE
    // --------------------------------------------------------
    const canUse = !!slot?.can_use_slot_item;
    const useEffect = slot?.use_effect || null;
    const useDisabled = !canUse || !itemId || !useEffect;

    // --------------------------------------------------------
    // Slot action button
    //
    // This is NOT only "drop".
    // It may be:
    // - pickup  : empty slot + compatible ground item
    // - drop    : occupied slot + empty ground
    // - swap    : occupied slot + compatible ground item
    // - inactive
    //
    // Backend is the source of truth through available_action.
    // --------------------------------------------------------
    const availableAction = slot?.available_action || "inactive";
    const actionReason = slot?.action_reason || slot?.drop_reason || slot?.pickup_reason || slot?.swap_reason || "";

    const actionEnabled =
        availableAction === "pickup" ||
        availableAction === "drop" ||
        availableAction === "swap";

    const actionLabel = actionEnabled ? availableAction : "";
    const actionDisabled = !actionEnabled;

    const iconHtml = item
        ? `
            <img
                class="inventory-card-img"
                src="${itemImagePath(item)}"
                alt="${itemId || ""}"
                title="${item?.desc || itemId || ""}"
            >
        `
        : ``;

    return `
        <div class="inventory-card ${item ? "inventory-card-filled" : "inventory-card-empty"}">

            <div class="inventory-card-image">
                ${iconHtml}
            </div>

            <button
                class="inventory-use-btn ${useDisabled ? "inventory-btn-placeholder" : ""}"
                onclick="beginItemUse('${slotGroup}', ${slotIndex}, '${itemId || ""}', '${useEffect || ""}')"
                ${useDisabled ? "disabled" : ""}
                title="${useDisabled ? "" : "Use item"}"
            >${useDisabled ? "" : "USE"}</button>

            <button
                class="inventory-action-btn ${actionDisabled ? "inventory-btn-placeholder" : ""}"
                onclick="inventorySlotAction('${slotGroup}', ${slotIndex})"
                ${actionDisabled ? "disabled" : ""}
                title="${actionDisabled ? actionReason : actionLabel}"
            >${actionDisabled ? "" : actionLabel}</button>

        </div>
    `;
}


function renderWeaponKeyRow(weaponSlots, keySlots) {
    const allSlots = [
        ...(weaponSlots || []).map(slot => ({slotGroup: "weapon", slot})),
        ...(keySlots || []).map(slot => ({slotGroup: "key", slot})),
    ];

    let html = `
        <div class="inventory-section inventory-section-weapons">
            <div class="inventory-card-grid">
    `;

    allSlots.forEach(({slotGroup, slot}) => {
        html += renderSingleSlotCard(slotGroup, slot);
    });

    html += `
            </div>
        </div>
    `;

    return html;
}

function renderSlotRow(label, slotGroup, slots) {
    let html = `
        <div class="inventory-section inventory-section-${slotGroup}">
            <div class="inventory-card-grid">
    `;

    (slots || []).forEach((slot) => {
        html += renderSingleSlotCard(slotGroup, slot);
    });

    html += `
            </div>
        </div>
    `;

    return html;
}

function renderInventory(data) {
    const box = document.getElementById("inventory-box");
    if (!box) return;

    if (!data || !data.inventory) {
        box.textContent = "(no inventory)";
        return;
    }

    const inv = data.inventory;
    const slots = data.slots || {};


    let html = "";

    html += renderWeaponKeyRow(slots.weapon || [], slots.key || []);
    html += renderSlotRow("Scrolls", "scroll", slots.scroll || []);

    const treasureUi = data.treasure_ui || {};
    const treasurePickupEnabled = !!treasureUi.pickup_enabled;
    const treasurePickupLabel = treasureUi.pickup_label || "pick up";

    html += `
    <div class="inventory-treasure-row">
        <div class="inventory-treasure-value">
            T ${inv.treasure ?? 0}
        </div>

        <button
            class="inventory-treasure-btn ${treasurePickupEnabled ? "" : "inventory-btn-placeholder"}"
            onclick="pickupTreasure()"
            ${treasurePickupEnabled ? "" : "disabled"}
        >${treasurePickupEnabled ? treasurePickupLabel : ""}</button>
    </div>
`;

    box.innerHTML = html;
}

function renderFightRows(rows, role, editableRole) {
    if (!rows || !rows.length) {
        return `<div class="muted">(no rows)</div>`;
    }
    const roleArg = role || "challenged";
    const isEditableRole = !editableRole || editableRole === roleArg;

    let html = `
        <table style="width:100%; border-collapse:collapse; margin-top:8px;">
            <thead>
                <tr style="border-bottom:1px solid #333;">
                    <th style="text-align:left; padding:6px;">Row</th>
                    <th style="text-align:left; padding:6px;">Text</th>
                    <th style="text-align:left; padding:6px;">Action</th>
                    <th style="text-align:right; padding:6px;">Value</th>
                </tr>
            </thead>
            <tbody>
    `;

    rows.forEach((row) => {
        const isSummary = row.kind === "summary";
        const bg = isSummary ? "#1b1b2a" : "transparent";

        let actionHtml = "";

        if (row.buttons && row.buttons.length) {
            actionHtml = row.buttons.map((btn) => {
                const activeStyle = btn.is_active
                    ? "outline:2px solid #55cc55; background:#1f2a1f;"
                    : "outline:1px solid #333; background:#151515;";

                // --------------------------------------------------------
                // Combat scroll toggle buttons
                // --------------------------------------------------------
                if (btn.action === "fight_toggle_scroll") {
                    const slotId = btn.payload?.slot_id || btn.button_id;

                    return `
                        <button
                            onclick="fightToggleScroll('${slotId}', '${roleArg}')"
                            ${btn.enabled && isEditableRole ? "" : "disabled"}
                            style="margin-right:6px; ${activeStyle}"
                            title="${btn.label || slotId || ""}"
                        >
                            ${btn.image_path
                        ? `<img class="item-icon" src="${karakStaticAsset(btn.image_path)}" alt="${btn.label || slotId || ""}">`
                        : (btn.label || slotId || "scroll")}
                        </button>
                    `;
                }

                // --------------------------------------------------------
                // Manual combat skill toggle buttons
                // Currently used by:
                // - skill_wlk_01
                // --------------------------------------------------------
                if (btn.action === "fight_toggle_skill") {
                    const skillId = btn.payload?.skill_id || btn.button_id;
                    const warning = btn.payload?.warning || btn.label || skillId || "";

                    return `
                        <button
                            onclick="fightToggleSkill('${skillId}', '${roleArg}')"
                            ${btn.enabled && skillId && isEditableRole ? "" : "disabled"}
                            style="margin-right:6px; ${activeStyle}"
                            title="${warning}"
                        >
                            ${btn.label || skillId || "skill"}
                        </button>
                    `;
                }

                // --------------------------------------------------------
                // One-die reroll buttons
                // Currently used by:
                // - skill_swo_01
                // - skill_pri_01
                // --------------------------------------------------------
                if (btn.action === "fight_reroll_die") {
                    const dieIndex = btn.payload?.die_index;
                    const skillId = btn.payload?.skill_id;

                    return `
                        <button
                            onclick="fightRerollDie(${dieIndex}, '${skillId}', '${roleArg}')"
                            ${btn.enabled && dieIndex && skillId && isEditableRole ? "" : "disabled"}
                            style="margin-right:6px; ${activeStyle}"
                            title="${btn.label || ("reroll die " + dieIndex)}"
                        >
                            ${btn.label || ("reroll die " + dieIndex)}
                        </button>
                    `;
                }

                // --------------------------------------------------------
                // Both-dice reroll buttons
                // Currently used by:
                // - skill_wrr_01
                // --------------------------------------------------------
                if (btn.action === "fight_reroll_both") {
                    const skillId = btn.payload?.skill_id;

                    return `
                        <button
                            onclick="fightRerollBoth('${skillId}', '${roleArg}')"
                            ${btn.enabled && skillId && isEditableRole ? "" : "disabled"}
                            style="margin-right:6px; ${activeStyle}"
                            title="${btn.label || "reroll both dice"}"
                        >
                            ${btn.label || "reroll both dice"}
                        </button>
                    `;
                }

                // --------------------------------------------------------
                // Unknown / not-yet-wired row-button action
                // --------------------------------------------------------
                return `
                    <button
                        disabled
                        style="margin-right:6px; ${activeStyle}"
                        title="Unsupported fight button action: ${btn.action || "-"}"
                    >
                        ${btn.image_path
                    ? `<img class="item-icon" src="${karakStaticAsset(btn.image_path)}" alt="${btn.label || btn.button_id || ""}">`
                    : (btn.label || btn.button_id || "action")}
                    </button>
                `;
            }).join("");
        } else if (row.button_label) {
            // ------------------------------------------------------------
            // Legacy single-button row action
            // ------------------------------------------------------------
            if (row.button_action === "fight_toss") {
                actionHtml = `
                    <button onclick="fightToss('${roleArg}')" ${row.button_enabled && isEditableRole ? "" : "disabled"}>
                        ${row.button_label}
                    </button>
                `;
            } else {
                actionHtml = `
                    <button disabled title="Unsupported row action: ${row.button_action || "-"}">
                        ${row.button_label}
                    </button>
                `;
            }
        }

        html += `
            <tr style="border-bottom:1px solid #222; background:${bg};">
                <td style="padding:6px;">${row.label || ""}</td>
                <td style="padding:6px;">
                    <div>${row.text || ""}</div>
                    ${row.note
            ? `<div class="muted" style="font-size:11px; margin-top:3px;">${row.note}</div>`
            : ""}
                </td>
                <td style="padding:6px;">${actionHtml}</td>
                <td style="padding:6px; text-align:right;">${row.value ?? 0}</td>
            </tr>
        `;
    });

    html += `</tbody></table>`;
    return html;
}


function renderFightSide(side, title, editableRole) {
    if (!side) {
        return `<div class="muted">(missing side)</div>`;
    }

    const participant = side.participant || {};
    const role = participant.role || null;
    const isEditable = editableRole && role === editableRole;
    const diceState = side.dice_state || null;

    let html = `
        <div style="border:1px solid ${isEditable ? "#55cc55" : "#333"}; padding:10px; background:${isEditable ? "#142014" : "#141414"};">
            <div style="margin-bottom:8px;">
                <b>${title}</b>
            </div>
            <div style="margin-bottom:6px;">
                <b>Name:</b> ${participant.display_name || "-"}
            </div>
            <div style="margin-bottom:6px;">
                <b>Kind:</b> ${participant.participant_kind || "-"} |
                <b>Role:</b> ${participant.role || "-"}
            </div>
    `;

    if (diceState) {
        html += `
            <div style="margin-bottom:6px;">
                <b>Dice:</b>
                ${diceState.has_been_tossed
            ? `${diceState.die_1} + ${diceState.die_2} = ${diceState.total}`
            : "(not tossed yet)"}
            </div>
        `;
    }

    html += `
            <div style="margin-bottom:6px;">
                <b>Total:</b> ${side.total ?? 0}
            </div>
            ${renderFightRows(side.rows || [], role, editableRole)}
        </div>
    `;

    return html;
}

function renderFightPrediction(prediction) {
    if (!prediction) {
        return `<div class="muted">(no prediction)</div>`;
    }

    const rawOutcome = prediction.raw_outcome || "(unknown)";
    const predictedOutcome = prediction.predicted_outcome || "(unknown)";
    const initiatorTotal = prediction.initiator_total ?? 0;
    const challengedTotal = prediction.challenged_total ?? 0;
    const modifiers = prediction.outcome_modifiers || [];

    let modifiersHtml = "";
    if (modifiers.length) {
        modifiersHtml = `
            <div style="margin-top:8px;">
                <b>Outcome modifiers:</b>
                <ul style="margin:6px 0 0 18px; padding:0;">
                    ${modifiers.map(mod => `
                        <li>
                            <b>${mod.label || mod.skill_id || "modifier"}</b>
                            ${mod.effect ? ` — ${mod.effect}` : ""}
                        </li>
                    `).join("")}
                </ul>
            </div>
        `;
    } else {
        modifiersHtml = `
            <div style="margin-top:8px;">
                <b>Outcome modifiers:</b> <span class="muted">(none)</span>
            </div>
        `;
    }

    return `
        <div style="border:1px solid #333; background:#151515; padding:10px; margin-bottom:12px;">
            <div style="margin-bottom:6px;">
                <b>Strength totals:</b>
                initiator = ${initiatorTotal},
                challenged = ${challengedTotal}
            </div>
            <div style="margin-bottom:6px;">
                <b>Raw outcome:</b> ${rawOutcome}
            </div>
            <div style="margin-bottom:6px;">
                <b>Predicted outcome:</b> <span style="color:#55cc55; font-weight:bold;">${predictedOutcome}</span>
                <b>Raw outcome:</b> <span style="color:#bbb;">${rawOutcome}</span>
            </div>
            ${modifiersHtml}
        </div>
    `;
}

function openFightModal() {
    const modal = document.getElementById("fight-modal");
    if (modal) {
        modal.classList.remove("hidden");
    }
}

function closeFightModal() {
    const modal = document.getElementById("fight-modal");
    if (modal) {
        modal.classList.add("hidden");
    }
}

function syncFightModalWithState() {
    if (latestFight) {
        openFightModal();
    } else {
        closeFightModal();
    }
}

function renderFight(data) {
    const box = document.getElementById("fight-box");
    if (!box) return;

    latestFight = data || null;

    if (!latestFight) {
        box.textContent = "(no active fight)";
        closeFightModal();
        return;
    }

    openFightModal();

    const context = data.context || {};
    const prediction = data.prediction || null;
    const outcome = data.outcome || null;

    const editableRole = data.editable_role || null;
    const committedRoles = Array.isArray(data.committed_roles)
        ? data.committed_roles
        : [];

    const isArenaPvp = context.fight_kind === "arena_pvp";
    const isResolvable = !!prediction?.is_resolvable;
    const canCommitEditableRole =
        isArenaPvp &&
        editableRole &&
        !committedRoles.includes(editableRole);

    let html = `
        <div style="margin-bottom:10px;">
            <b>Fight kind:</b> ${context.fight_kind || "-"} |
            <b>Tile:</b> (${context.tile_x ?? "?"}, ${context.tile_y ?? "?"}) |
            <b>Phase:</b> ${data.phase || "-"} |
            <b>Resolved outcome:</b> ${outcome || "(not resolved)"}
        </div>
        
                <div style="display:flex; gap:8px; align-items:center; margin-bottom:10px; flex-wrap:wrap;">
            ${
        canCommitEditableRole
            ? `<button type="button" onclick="fightCommitRole('${editableRole}')">
                            Commit ${editableRole}
                       </button>`
            : ""
    }

            <button
                type="button"
                onclick="fightResolve()"
                ${isResolvable ? "" : "disabled"}
            >
                Resolve fight
            </button>

            <button type="button" onclick="fightRefresh()">
                Refresh fight
            </button>

            ${
        editableRole
            ? `<span class="muted">Editable side: ${editableRole}</span>`
            : `<span class="muted">No editable side</span>`
    }
        </div>
        
        ${renderFightPrediction(prediction)}

        <div class="two-col">
            <div class="col">
                ${renderFightSide(data.initiator_side, "Initiator", editableRole)}
            </div>
            <div class="col">
                ${renderFightSide(data.challenged_side, "Challenged", editableRole)}
            </div>
        </div>
    `;

    box.innerHTML = html;
}

async function chooseArenaOpponent(targetPlayerId) {
    clearError();

    const r = await karakFetch(gameApi("/arena/choose_opponent"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            target_player_id: Number(targetPlayerId)
        })
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Arena opponent choice failed.");
        return;
    }

    await refreshAll();

    showMessage(
        `Arena opponent chosen: Player #${targetPlayerId}`,
        "info",
        "Arena"
    );
}

async function chooseArenaLootSkip() {
    await chooseArenaLoot({
        steal_kind: "skip"
    });
}

async function chooseArenaLootTreasure() {
    await chooseArenaLoot({
        steal_kind: "treasure_value"
    });
}

async function chooseArenaLootSlot(sourceSlotGroup, sourceSlotIndex) {
    await chooseArenaLoot({
        steal_kind: "slot_item",
        source_slot_group: sourceSlotGroup,
        source_slot_index: Number(sourceSlotIndex)
    });
}

async function chooseArenaLoot(payload) {
    clearError();

    const r = await karakFetch(gameApi("/arena/choose_loot"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(payload)
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Arena loot choice failed.");
        return;
    }

    if (handleGameOverRedirect(data)) {
        return;
    }

    await refreshAll();

    showMessage(
        "Arena loot resolved.",
        "info",
        "Arena"
    );
}

async function toggleSkillUiSelection(playerId, skillId) {
    const activePlayerId = latestPlayers?.active_player?.player_id;
    if (playerId !== activePlayerId) {
        showError("Only the active player's skill UI can be changed.");
        return;
    }

    const r = await karakFetch(gameApi("/skills/toggle"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({skill_id: skillId})
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Skill toggle failed.");
        return;
    }

    await refreshAll();
}

async function stepSkillUiValue(playerId, skillId, delta) {
    const activePlayerId = latestPlayers?.active_player?.player_id;
    if (playerId !== activePlayerId) {
        showError("Only the active player's skill value can be changed.");
        return;
    }

    const activePlayer = latestPlayers?.active_player || null;
    const skillsUi = activePlayer?.skills_ui || [];
    let currentSkill = null;

    for (const row of skillsUi) {
        for (const skill of row) {
            if (skill.skill_id === skillId) {
                currentSkill = skill;
                break;
            }
        }
        if (currentSkill) break;
    }

    const currentHp = activePlayer?.hp?.current ?? 1;
    const maxHp = activePlayer?.hp?.max ?? 5;

    const currentValue = currentSkill?.value ?? currentHp;
    const nextValue = Math.max(1, Math.min(maxHp, currentValue + delta));

    const r = await karakFetch(gameApi("/skills/set_value"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            skill_id: skillId,
            value: nextValue
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Skill value update failed.");
        return;
    }

    await refreshAll();
}

function isTeleportSkill(skillId) {
    return teleportTargetModeForSkill(skillId) !== null;
}

function teleportSkillLabel(skillId) {
    if (skillId === "skill_bea_02") {
        return "Beasthunter teleport: select one player to heal";
    }

    if (skillId === "skill_wlk_02") {
        return "Warlock swap: select one player to swap with";
    }

    if (skillId === "skill_bat_02") {
        return "Battlemage teleport: enter coordinates of entity tile";
    }

    return "Portal teleport";
}

function enterTeleportTargeting(skillId) {
    const targetMode = teleportTargetModeForSkill(skillId);

    if (!targetMode) {
        showError(`Unsupported teleport skill: ${skillId}`);
        return;
    }

    pendingTeleportSkillId = skillId;
    pendingTeleportTargetMode = targetMode;
    selectedTeleportTargetPlayerId = null;

    const label = document.getElementById("teleport-mode-label");
    const cancelBtn = document.getElementById("teleport-cancel-btn");
    const xInput = document.getElementById("teleport-x");
    const yInput = document.getElementById("teleport-y");

    if (label) {
        label.textContent = teleportSkillLabel(skillId);
    }

    if (cancelBtn) {
        cancelBtn.disabled = false;
    }

    if (xInput) {
        xInput.value = "";
        xInput.disabled = targetMode !== "coordinates";
    }

    if (yInput) {
        yInput.value = "";
        yInput.disabled = targetMode !== "coordinates";
    }

    if (targetMode === "coordinates" && xInput) {
        xInput.focus();
    }

    renderPlayers(latestPlayers);
    renderTeleportConfirmArea();
    updateActionAvailability();
    renderWaitingInstructionMessage();
}

function teleportTargetModeForSkill(skillId) {
    if (skillId === "skill_bat_02") {
        return "coordinates";
    }

    if (skillId === "skill_bea_02" || skillId === "skill_wlk_02") {
        return "player";
    }

    return null;
}

function isItemUseTargeting() {
    return !!pendingItemUse;
}

function itemUseLabel(itemUse) {
    if (!itemUse) return "Item use";

    if (itemUse.effect === "TP_HEAL") {
        if (itemUse.phase === "select_player") {
            return "Healing scroll: select target player";
        }
        if (itemUse.phase === "select_fountain") {
            return "Healing scroll: choose fountain coordinates";
        }
    }

    if (itemUse.effect === "LIFESTEAL") {
        if (itemUse.phase === "select_player") {
            return "Thorn: select target player";
        }
    }

    if (itemUse.effect === "PURGE") {
        return "Green amulet: remove curse";
    }

    return `Item use: ${itemUse.item_id || "-"}`;
}

function cancelItemUseTargeting() {
    pendingItemUse = null;

    const label = document.getElementById("teleport-mode-label");
    const cancelBtn = document.getElementById("teleport-cancel-btn");
    const xInput = document.getElementById("teleport-x");
    const yInput = document.getElementById("teleport-y");

    if (label) {
        label.textContent = "Portal teleport";
    }

    if (cancelBtn) {
        cancelBtn.disabled = true;
    }

    if (xInput) {
        xInput.value = "";
    }

    if (yInput) {
        yInput.value = "";
    }

    renderPlayers(latestPlayers);
    renderTeleportConfirmArea();
    showMessage("Item use cancelled.", "info", "Info");
    updateActionAvailability();
}

function beginItemUse(slotGroup, slotIndex, itemId, effect) {
    clearError();

    if (!itemId || !effect) {
        return;
    }

    if (effect === "TP_HEAL") {
        pendingItemUse = {
            item_id: itemId,
            effect: effect,
            slot_group: slotGroup,
            slot_index: slotIndex,
            phase: "select_player",
            target_player_id: null
        };

        const label = document.getElementById("teleport-mode-label");
        const cancelBtn = document.getElementById("teleport-cancel-btn");
        const xInput = document.getElementById("teleport-x");
        const yInput = document.getElementById("teleport-y");

        if (label) {
            label.textContent = itemUseLabel(pendingItemUse);
        }

        if (cancelBtn) {
            cancelBtn.disabled = false;
        }

        if (xInput) {
            xInput.value = "";
            xInput.disabled = true;
        }

        if (yInput) {
            yInput.value = "";
            yInput.disabled = true;
        }

        renderPlayers(latestPlayers);
        updateActionAvailability();
        renderWaitingInstructionMessage();

        return;
    }

    if (effect === "LIFESTEAL") {
        pendingItemUse = {
            item_id: itemId,
            effect: effect,
            slot_group: slotGroup,
            slot_index: slotIndex,
            phase: "select_player",
            target_player_id: null
        };

        const label = document.getElementById("teleport-mode-label");
        const cancelBtn = document.getElementById("teleport-cancel-btn");
        const xInput = document.getElementById("teleport-x");
        const yInput = document.getElementById("teleport-y");

        if (label) {
            label.textContent = itemUseLabel(pendingItemUse);
        }

        if (cancelBtn) {
            cancelBtn.disabled = false;
        }

        if (xInput) {
            xInput.value = "";
            xInput.disabled = true;
        }

        if (yInput) {
            yInput.value = "";
            yInput.disabled = true;
        }

        renderPlayers(latestPlayers);
        updateActionAvailability();
        renderWaitingInstructionMessage();

        return;
    }

    if (effect === "PURGE") {
        useInventoryItem({
            slot_group: slotGroup,
            slot_index: slotIndex,
            target_player_id: null,
            target_x: null,
            target_y: null,
            successMessage: "Green amulet used. Curse removed."
        });

        return;
    }

    if (effect === "KEY_ENTITY_DAMAGE") {
        useInventoryItem({
            slot_group: slotGroup,
            slot_index: slotIndex,
            target_player_id: null,
            target_x: null,
            target_y: null,
            successMessage: "Key used."
        });

        return;
    }

    showError(`Unsupported item effect: ${effect}`);
}

function isCoordinateTeleportSkill(skillId) {
    return teleportTargetModeForSkill(skillId) === "coordinates";
}

function isPlayerTeleportSkill(skillId) {
    return teleportTargetModeForSkill(skillId) === "player";
}

function cancelTeleportTargeting() {
    if (pendingItemUse) {
        cancelItemUseTargeting();
        return;
    }

    pendingTeleportSkillId = null;
    pendingTeleportTargetMode = null;
    selectedTeleportTargetPlayerId = null;

    const label = document.getElementById("teleport-mode-label");
    const cancelBtn = document.getElementById("teleport-cancel-btn");
    const xInput = document.getElementById("teleport-x");
    const yInput = document.getElementById("teleport-y");

    if (label) {
        label.textContent = "Portal teleport";
    }

    if (cancelBtn) {
        cancelBtn.disabled = true;
    }

    if (xInput) {
        xInput.value = "";
    }

    if (yInput) {
        yInput.value = "";
    }

    renderPlayers(latestPlayers);
    renderTeleportConfirmArea();

    showMessage("Teleport targeting cancelled.", "info", "Info");
    updateActionAvailability();
}

async function scoutPullTile(playerId) {
    clearError();

    const activePlayerId = latestPlayers?.active_player?.player_id;

    if (Number(playerId) !== Number(activePlayerId)) {
        showError("Only the active Scout can draw a pocket tile.");
        return;
    }

    const r = await karakFetch(gameApi("/skills/sco_02/pull_tile"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Scout tile draw failed.");
        return;
    }

    selectedScoutPocketTileIndex = null;

    await refreshAll();

    showMessage(
        "Scout drew one tile into the pocket.",
        "info",
        "Scout pocket"
    );
}

async function pulseSkillUiButton(playerId, skillId) {
    const activePlayerId = latestPlayers?.active_player?.player_id;

    if (playerId !== activePlayerId) {
        showError("Only the active player's skill UI can be changed.");
        return;
    }

    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;
    // --------------------------------------------------------
    // skill_sco_02:
    // Draw one tile from tile_pool into Scout pocket.
    // This is an Action.
    // --------------------------------------------------------
    if (skillId === "skill_sco_02") {
        await scoutPullTile();
        return;
    }

    // --------------------------------------------------------
    // skill_swo_02:
    // Finish post-combat item pickup without ending the turn.
    // --------------------------------------------------------
    if (skillId === "skill_swo_02") {
        const canContinue =
            !!turn &&
            turn.mode === "item_pickup" &&
            !!turn.fight_continue_after_item_pickup &&
            turn.fight_continue_skill_id === "skill_swo_02";

        if (!canContinue) {
            showError("Swordsman continuation is not available now.");
            return;
        }

        await continueAfterItemPickup();
        return;
    }

    // --------------------------------------------------------
// Skill teleports:
// Enter coordinate-targeting mode.
// The actual API call happens through confirmTeleport().
// --------------------------------------------------------
    if (isTeleportSkill(skillId)) {
        enterTeleportTargeting(skillId);
        return;
    }

    showMessage(`Skill button pressed: ${skillId}`, "info", "Info");
}

async function loadInventory() {
    if (
        latestMap?.game_over === true ||
        latestMap?.game_scope === "results" ||
        latestMap?.scope === "results" ||
        latestMap?.redirect_to
    ) {
        return;
    }
    const r = await karakFetch(gameApi("/inventory"));
    const data = await r.json();

    console.log("INVENTORY STATUS:", r.status);
    console.log("INVENTORY DATA:", data);

    if (!r.ok) {
        throw new Error(data.detail || "Failed to load inventory.");
    }

    rememberInventoryItemRefs(data);

    renderGround(data);
    renderInventory(data);
}

async function inventorySlotAction(slotGroup, slotIndex) {
    clearError();

    const r = await karakFetch(gameApi("/inventory/slot_action"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            slot_group: slotGroup,
            slot_index: slotIndex
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Inventory action failed.");
        return;
    }

    await refreshAll();
}

async function activateGroundObject() {
    clearError();

    const r = await karakFetch(gameApi("/ground/activate"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Ground activation failed.");
        return;
    }

    if (handleGameOverRedirect(data)) {
        return;
    }

    await refreshAll();

    if (data.status === "player_quit_game") {
        showMessage("Player left the dungeon.", "info", "Exit");
        return;
    }

    showMessage(data.status || "Ground object activated.", "info", "Ground");
}

function clearPendingItemUseState() {
    pendingItemUse = null;

    const label = document.getElementById("teleport-mode-label");
    const xInput = document.getElementById("teleport-x");
    const yInput = document.getElementById("teleport-y");
    const cancelBtn = document.getElementById("teleport-cancel-btn");

    if (label) {
        label.textContent = "";
    }

    if (xInput) {
        xInput.disabled = true;
        xInput.value = "";
    }

    if (yInput) {
        yInput.disabled = true;
        yInput.value = "";
    }

    if (cancelBtn) {
        cancelBtn.disabled = true;
    }
}

async function useInventoryItem({
                                    slot_group,
                                    slot_index,
                                    target_player_id = null,
                                    target_x = null,
                                    target_y = null,
                                    successMessage = "Item used."
                                }) {
    clearError();

    const r = await karakFetch(gameApi("/inventory/use_item"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            slot_group,
            slot_index,
            target_player_id,
            target_x,
            target_y
        })
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Item use failed.");
        return;
    }

    pendingItemUse = null;

    const label = document.getElementById("teleport-mode-label");
    const cancelBtn = document.getElementById("teleport-cancel-btn");
    const xInput = document.getElementById("teleport-x");
    const yInput = document.getElementById("teleport-y");

    if (label) {
        label.textContent = "Portal teleport";
    }

    if (cancelBtn) {
        cancelBtn.disabled = true;
    }

    if (xInput) {
        xInput.value = "";
    }

    if (yInput) {
        yInput.value = "";
    }

    renderTeleportConfirmArea();

    await refreshAll();

    showMessage(successMessage, "info", "Item use");
}

async function continueAfterItemPickup() {
    clearError();

    const r = await karakFetch(gameApi("/itempickup/continue"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Continue after item pickup failed.");
        return;
    }

    await refreshAll();

    showMessage(
        "Swordsman continuation used. Turn continues.",
        "info",
        "Info"
    );
}

async function endTurn() {
    // --------------------------------------------------------
    // If the FE already knows the game is over, redirect instead
    // of calling /turn/end.
    // --------------------------------------------------------
    if (
        latestMap?.game_over === true ||
        latestMap?.game_scope === "results" ||
        latestMap?.scope === "results" ||
        latestMap?.redirect_to
    ) {
        handleGameOverRedirect(latestMap);
        return;
    }

    try {
        clearError();

        const r = await karakFetch(gameApi("/turn/end"), {
            method: "POST",
        });

        const data = await r.json();

        if (!r.ok) {
            const detail = data.detail || "Failed to end turn.";

            // ----------------------------------------------------
            // Important recovery:
            // After the last player exits, backend may already have:
            // - turn_state = None
            // - game_scope = results
            //
            // In that state /turn/end correctly returns:
            // "No active turn."
            //
            // So reload /api/game/map and redirect if phase4 is active.
            // ----------------------------------------------------
            if (String(detail).includes("No active turn")) {
                await loadMap();

                if (handleGameOverRedirect(latestMap)) {
                    return;
                }
            }

            throw new Error(detail);
        }

        if (handleGameOverRedirect(data)) {
            return;
        }

        clearPendingItemUseState();

        resetMapViewportOffset();
        await refreshAll();

        if (
            latestMap?.game_over === true ||
            latestMap?.game_scope === "results" ||
            latestMap?.scope === "results" ||
            latestMap?.redirect_to
        ) {
            handleGameOverRedirect(latestMap);
            return;
        }

        showMessage("Turn ended. Next player is active.", "info", "Info");

    } catch (e) {
        console.error("endTurn failed:", e);

        const message = String(e?.message || e);

        if (message.includes("No active turn")) {
            try {
                await loadMap();

                if (handleGameOverRedirect(latestMap)) {
                    return;
                }
            } catch (mapError) {
                console.error("endTurn recovery loadMap failed:", mapError);
            }
        }

        showMessage(message, "warning", "Warning");
    }
}

function handleGameOverRedirect(data) {
    if (!data) return false;

    // --------------------------------------------------------
    // Direct game-over payload.
    // --------------------------------------------------------
    const directGameOver =
        data.game_over === true ||
        data.game_scope === "results" ||
        data.scope === "results" ||
        data.status === "game_over" ||
        !!data.redirect_to;

    if (directGameOver) {
        const target = data.redirect_to || "/phase4";
        window.location.href = karakPath(target);
        return true;
    }

    // --------------------------------------------------------
    // Nested payloads.
    //
    // Some actions return:
    // - finalize_result
    // - advance_result
    // - game_result
    //
    // PLAYER_QUIT may wrap the game-over result inside one of these.
    // --------------------------------------------------------
    const nestedCandidates = [
        data.finalize_result,
        data.advance_result,
        data.game_result,
        data.result,
    ];

    for (const nested of nestedCandidates) {
        if (nested && handleGameOverRedirect(nested)) {
            return true;
        }
    }

    return false;
}

function handleSkillChipClick(event, playerId, skillId) {
    if (event) {
        event.stopPropagation();
    }

    if (isAwaitingPoisonChoice()) {
        if (selectedPoisonTargetPlayerId == null) {
            showError("Select a poison target player first.");
            return;
        }

        if (playerId !== selectedPoisonTargetPlayerId) {
            showError("Click a skill of the selected poison target player.");
            return;
        }

        selectedPoisonTargetSkillId = skillId;
        renderPoisonConfirmArea();
        renderWaitingInstructionMessage();

        return;
    }

    console.log("skill chip clicked", {playerId, skillId});
}

async function pickupTreasure() {
    clearError();

    const r = await karakFetch(gameApi("/inventory/pickup_treasure"), {
        method: "POST"
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Treasure pickup failed.");
        return;
    }

    await refreshAll();
}

function updateActionAvailability() {
    const activePlayer = latestPlayers?.active_player;
    const tiles = latestMap?.tiles || {};
    const turn = latestMap?.turn || latestPlayers?.turn || null;

    let currentTile = null;
    if (activePlayer?.position) {
        const key = `${activePlayer.position.x},${activePlayer.position.y}`;
        currentTile = tiles[key] || null;
    }

    const fightBtn = document.getElementById("fight-start-btn");
    const finishItemPickupBtn = document.getElementById("finish-itempickup-btn");
    const endTurnBtn = document.getElementById("end-turn-btn");
    const teleportBtn = document.getElementById("teleport-btn");
    const teleportXInput = document.getElementById("teleport-x");
    const teleportYInput = document.getElementById("teleport-y");
    const teleportModeLabel = document.getElementById("teleport-mode-label");
    const teleportCancelBtn = document.getElementById("teleport-cancel-btn");

    const moveButtons = [
        document.getElementById("move-n-btn"),
        document.getElementById("move-w-btn"),
        document.getElementById("move-e-btn"),
        document.getElementById("move-s-btn"),
    ];

    const rotateButtons = [
        document.getElementById("rotate-left-btn"),
        document.getElementById("rotate-right-btn"),
    ];

    const confirmTileBtn = document.getElementById("confirm-tile-btn");

    const mode = turn?.mode || "idle";

    const isIdle = mode === "idle";
    const isPendingTile = mode === "pending_tile";
    const isAwaitingEntityChoice = mode === "awaiting_entity_choice";
    const isAwaitingEntityEncounter = mode === "awaiting_entity_encounter";
    const isAwaitingArenaTarget = mode === "awaiting_arena_target_choice";
    const isAwaitingArenaLoot = mode === "awaiting_arena_loot_choice";
    const isFight = mode === "fight";
    const isItemPickup = mode === "item_pickup";
    const isAwaitingCurse = mode === "awaiting_curse_choice";
    const isAwaitingPoison = mode === "awaiting_poison_choice";
    const isAwaitingHeal = mode === "awaiting_heal_choice";
    const isAwaitingKoReaction = isAwaitingKoReactionChoice();

    const encounter = turn?.pending_entity_encounter || null;
    const canMoveDuringEntityEncounter =
        isAwaitingEntityEncounter &&
        !!encounter?.can_skip;

    // --------------------------------------------------------
    // Special item pickup state:
    // Swordsman won a fight with a final physical 6.
    // --------------------------------------------------------
    const isSwoContinueItemPickup =
        isItemPickup &&
        !!turn?.fight_continue_after_item_pickup &&
        turn?.fight_continue_skill_id === "skill_swo_02";

    const currentEntityAllowsCombat =
        !!currentTile?.entity_id &&
        (
            currentTile.entity_can_combat === true ||
            (
                Array.isArray(currentTile.entity_injury_modes) &&
                currentTile.entity_injury_modes.includes("combat")
            )
        );

    const canStartFight =
        currentEntityAllowsCombat &&
        !!turn &&
        (isIdle || isAwaitingEntityEncounter) &&
        !isAwaitingKoReaction &&
        !isAwaitingPoison &&
        !isAwaitingEntityChoice &&
        !isAwaitingArenaTarget &&
        !isAwaitingArenaLoot;

    if (fightBtn) {
        fightBtn.disabled = !canStartFight;
    }

    // Old button: no longer part of the normal UI.
    if (finishItemPickupBtn) {
        finishItemPickupBtn.disabled = true;
        finishItemPickupBtn.style.display = "none";
    }

    if (endTurnBtn) {
        endTurnBtn.disabled =
            isPendingTile ||
            isAwaitingEntityChoice ||
            isAwaitingEntityEncounter ||
            isAwaitingArenaTarget ||
            isAwaitingArenaLoot ||
            isFight ||
            isAwaitingCurse ||
            isAwaitingPoison ||
            isAwaitingHeal ||
            isAwaitingKoReaction ||
            isSwoContinueItemPickup;
    }

    const isTeleportTargeting = !!pendingTeleportSkillId;
    const isItemTargeting = !!pendingItemUse;

    const isCoordinateTeleportTargeting =
        isTeleportTargeting &&
        pendingTeleportTargetMode === "coordinates";

    const canUsePortalTeleport =
        !!currentTile &&
        currentTile.feature === "teleport" &&
        isIdle &&
        !isTeleportTargeting &&
        !isAwaitingKoReaction &&
        !isAwaitingEntityChoice &&
        !isAwaitingEntityEncounter &&
        !isAwaitingArenaTarget &&
        !isAwaitingArenaLoot;

    const canUseCoordinateSkillTeleport =
        isCoordinateTeleportTargeting &&
        isIdle &&
        !isAwaitingKoReaction &&
        !isAwaitingEntityChoice &&
        !isAwaitingEntityEncounter &&
        !isAwaitingArenaTarget &&
        !isAwaitingArenaLoot;

    const canResolveKoReaction =
        isAwaitingKoReaction;

    const canResolveItemUseCoordinates =
        !!pendingItemUse &&
        pendingItemUse.phase === "select_fountain";

    const teleportAreaEnabled =
        canUsePortalTeleport ||
        canUseCoordinateSkillTeleport ||
        canResolveKoReaction ||
        canResolveItemUseCoordinates;

    if (teleportBtn) {
        teleportBtn.disabled = !teleportAreaEnabled;
    }

    if (teleportXInput) {
        teleportXInput.disabled = !teleportAreaEnabled;
    }

    if (teleportYInput) {
        teleportYInput.disabled = !teleportAreaEnabled;
    }

    if (teleportModeLabel) {
        if (isAwaitingKoReaction) {
            teleportModeLabel.textContent = "KO reaction: choose fountain coordinates";
        } else if (pendingItemUse) {
            teleportModeLabel.textContent = itemUseLabel(pendingItemUse);
        } else {
            teleportModeLabel.textContent = pendingTeleportSkillId
                ? teleportSkillLabel(pendingTeleportSkillId)
                : "Portal teleport";
        }
    }

    if (teleportCancelBtn) {
        teleportCancelBtn.style.display = "";
        teleportCancelBtn.disabled =
            !((pendingTeleportSkillId || pendingItemUse) && !isAwaitingKoReaction);
    }

    // --------------------------------------------------------
    // Navigation:
    // - idle: normal movement
    // - awaiting_entity_encounter: movement only if skip is allowed
    // - Arena target/loot modes block movement completely
    // --------------------------------------------------------
    moveButtons.forEach(btn => {
        if (btn) {
            btn.disabled =
                isTeleportTargeting ||
                isItemTargeting ||
                isAwaitingKoReaction ||
                isAwaitingEntityChoice ||
                isAwaitingArenaTarget ||
                isAwaitingArenaLoot ||
                !(isIdle || canMoveDuringEntityEncounter);
        }
    });

    rotateButtons.forEach(btn => {
        if (btn) {
            btn.disabled =
                isTeleportTargeting ||
                isItemTargeting ||
                isAwaitingKoReaction ||
                isAwaitingEntityChoice ||
                isAwaitingEntityEncounter ||
                isAwaitingArenaTarget ||
                isAwaitingArenaLoot ||
                !isPendingTile;
        }
    });

    if (confirmTileBtn) {
        confirmTileBtn.disabled =
            isTeleportTargeting ||
            isItemTargeting ||
            isAwaitingKoReaction ||
            isAwaitingEntityChoice ||
            isAwaitingEntityEncounter ||
            isAwaitingArenaTarget ||
            isAwaitingArenaLoot ||
            !isPendingTile;
    }
}

async function confirmTile() {
    const target = getPendingDiscoveryTarget();

    if (!target) {
        showError("No pending tile target to confirm.");
        return;
    }

    const x = target.x;
    const y = target.y;

    const r = await karakFetch(gameApi("/confirm_tile"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({x, y})
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Confirm failed.");
        return;
    }

    await refreshAll();

    const karakMessageShown = showKarakCreatedMessage(data);

    if (!karakMessageShown && data.entry?.curse_room) {
        const curse = data.entry.curse_room;
        showMessage(
            `Curse-room toss: ${curse.die}`,
            curse.triggered ? "error" : "info",
            "Curse room"
        );
    }
}

function clearPoisonSelection() {
    selectedPoisonTargetPlayerId = null;
    selectedPoisonTargetSkillId = null;
    renderPlayers(latestPlayers);
    renderPoisonConfirmArea();
    renderWaitingInstructionMessage();
}

async function confirmPoisonSelection() {
    if (selectedPoisonTargetPlayerId == null) {
        showError("No poison target player selected.");
        return;
    }

    if (!selectedPoisonTargetSkillId) {
        showError("No poison target skill selected.");
        return;
    }

    clearError();

    const r = await karakFetch(gameApi("/poison/choose_target"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            target_player_id: selectedPoisonTargetPlayerId,
            target_skill_id: selectedPoisonTargetSkillId
        })
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Poison choice failed.");
        return;
    }

    selectedPoisonTargetPlayerId = null;
    selectedPoisonTargetSkillId = null;

    await refreshAll();

    showMessage("Poison applied.", "info", "Poison");
}

function clearCurseSelection() {
    selectedCurseTargetPlayerId = null;
    renderPlayers(latestPlayers);
    renderCurseConfirmArea();
    renderWaitingInstructionMessage();
}

async function confirmCurseSelection() {
    if (selectedCurseTargetPlayerId == null) {
        showError("No curse target selected.");
        return;
    }

    clearError();

    const r = await karakFetch(gameApi("/curse/choose_target"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({target_player_id: selectedCurseTargetPlayerId})
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Curse choice failed.");
        return;
    }

    selectedCurseTargetPlayerId = null;
    await refreshAll();
}

function isAwaitingKoReactionChoice() {
    const turn =
        latestPlayers?.turn ||
        latestMap?.turn ||
        null;

    return !!turn && turn.mode === "awaiting_ko_reaction_choice";
}

async function fightStart() {
    clearError();

    const r = await karakFetch(gameApi("/fight/start"), {
        method: "POST"
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight start failed.");
        return;
    }

    if (data.mode === "chest_opened") {
        renderFight(null);
        await refreshAll();
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function fightRefresh() {
    clearError();

    const r = await karakFetch(gameApi("/fight/state"));
    const data = await r.json();

    if (!r.ok) {
        renderFight(null);
        showError(data.detail || "No active fight.");
        return;
    }

    renderFight(data);
}

async function fightToss(role = "challenged") {
    clearError();

    const r = await karakFetch(gameApi("/fight/toss"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({role})
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight toss failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();
}

async function fightRerollDie(dieIndex, skillId, role = "challenged") {
    clearError();

    const r = await karakFetch(gameApi("/fight/reroll_die"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            die_index: dieIndex,
            skill_id: skillId,
            role
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight die reroll failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();
}

async function fightRerollBoth(skillId, role = "challenged") {
    clearError();

    const r = await karakFetch(gameApi("/fight/reroll_both"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            skill_id: skillId,
            role
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight both-dice reroll failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();
}

async function fightResolve() {
    clearError();

    const r = await karakFetch(gameApi("/fight/resolve"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Fight resolve failed.");
        return;
    }

    if (handleGameOverRedirect(data)) {
        return;
    }

    renderFight(null);
    await refreshAll();

    if (data.status === "arena_pvp_resolved_awaiting_loot_choice") {
        showMessage(
            "Arena fight resolved. Choose loot or skip.",
            "waiting",
            "Arena loot"
        );
        return;
    }

    showMessage(
        data.status || "Fight resolved.",
        "info",
        "Fight"
    );
}

async function fightToggleSkill(skillId, role = "challenged") {
    clearError();

    const r = await karakFetch(gameApi("/fight/toggle_skill"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            skill_id: skillId,
            role
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight skill toggle failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();
}

async function fightToggleScroll(slotId, role = "challenged") {
    clearError();

    const r = await karakFetch(gameApi("/fight/toggle_scroll"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            slot_id: slotId,
            role
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Scroll toggle failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();
}

async function fightCommitRole(role) {
    clearError();

    const r = await karakFetch(gameApi("/fight/commit_role"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({role})
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Fight role commit failed.");
        return;
    }

    renderFight(data.fight || data);
    await refreshAll();

    showMessage(
        `${role} side committed.`,
        "info",
        "Fight"
    );
}

async function postGameAction(path, payload = null) {
    const options = {
        method: "POST",
    };

    if (payload !== null) {
        options.headers = {
            "Content-Type": "application/json",
        };
        options.body = JSON.stringify(payload);
    }

    const r = await karakFetch(gameApi(path), options);
    const data = await r.json();

    if (!r.ok) {
        throw new Error(data.detail || `Request failed: ${path}`);
    }

    if (handleGameOverRedirect(data)) {
        return {
            redirected: true,
            data,
        };
    }

    return {
        redirected: false,
        data,
    };
}


async function leaveGame() {
    try {
        await karakFetch(lobbyApi("/reset_to_phase1"), {method: "POST"});
    } catch (e) {
        console.error(e);
    }

    skillUiState = {};
    selectedCurseTargetPlayerId = null;
    latestFight = null;

    window.location.href = karakPath("/phase1");
}

function showMessage(msg, level = "info", title = null) {
    const box = document.getElementById("message-box");
    const titleEl = document.getElementById("message-title");
    const content = document.getElementById("message-content");

    if (!box || !titleEl || !content) {
        console.error("Message box elements not found.");
        return;
    }

    box.classList.remove("message-info", "message-error", "message-waiting");

    if (level === "error") {
        box.classList.add("message-error");
        titleEl.textContent = title || "Error";
    } else if (level === "waiting") {
        box.classList.add("message-waiting");
        titleEl.textContent = title || "Waiting for action";
    } else {
        box.classList.add("message-info");
        titleEl.textContent = title || "Info";
    }

    content.textContent = msg;
}

function renderWaitingInstructionMessage() {
    const waiting = getWaitingInstructionMessage();

    if (!waiting) {
        return false;
    }

    showMessage(waiting.message, "waiting", waiting.title);
    return true;
}

function refreshWaitingPromptOrReady() {
    const waitingMessageShown = renderWaitingInstructionMessage();

    if (!waitingMessageShown) {
        showMessage("(ready)", "info", "Info");
    }
}

function getWaitingInstructionMessage() {
    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;

    const mode = turn?.mode || "idle";

    // --------------------------------------------------------
    // Local frontend targeting states
    // --------------------------------------------------------
    if (pendingItemUse) {
        if (pendingItemUse.effect === "TP_HEAL") {
            if (pendingItemUse.phase === "select_player") {
                return {
                    title: "Waiting for item target",
                    message: "Healing scroll: select the player who should be teleported/healed."
                };
            }

            if (pendingItemUse.phase === "select_fountain") {
                return {
                    title: "Waiting for fountain coordinates",
                    message: "Healing scroll: enter the target fountain coordinates, then press Teleport."
                };
            }
        }

        if (pendingItemUse.effect === "LIFESTEAL") {
            return {
                title: "Waiting for item target",
                message: "Thorn: select another player as the target."
            };
        }

        return {
            title: "Waiting for item use",
            message: "Finish or cancel the current item-use targeting."
        };
    }

    if (pendingTeleportSkillId) {
        if (pendingTeleportTargetMode === "player") {
            const selected = getPlayerById(selectedTeleportTargetPlayerId);
            const selectedText = selected
                ? ` Selected: ${selected.display_name || ("Player #" + selected.player_id)}. Confirm or reset.`
                : " Select a target player, then confirm.";

            return {
                title: "Waiting for teleport target",
                message: `${teleportSkillLabel(pendingTeleportSkillId)}.${selectedText}`
            };
        }

        if (pendingTeleportTargetMode === "coordinates") {
            return {
                title: "Waiting for teleport coordinates",
                message: `${teleportSkillLabel(pendingTeleportSkillId)}. Enter target coordinates, then press Teleport.`
            };
        }

        return {
            title: "Waiting for teleport",
            message: "Finish or cancel the current teleport targeting."
        };
    }

    // --------------------------------------------------------
    // Backend-authoritative turn modes
    // --------------------------------------------------------
    if (mode === "awaiting_ko_reaction_choice") {
        return {
            title: "Waiting for Warrior teleport",
            message: "Warrior knockout reaction: choose a fountain coordinate, then press Teleport."
        };
    }

    if (mode === "awaiting_arena_target_choice") {
        const selected = getPlayerById(selectedArenaOpponentPlayerId);
        const selectedText = selected
            ? ` Selected opponent: ${selected.display_name || ("Player #" + selected.player_id)}. Confirm or reset.`
            : " Select an opponent from the player list, then confirm the Arena challenge.";

        return {
            title: "Arena activated",
            message: selectedText
        };
    }

    if (mode === "awaiting_arena_loot_choice") {
        return {
            title: "Arena loot",
            message: "Click one item or treasure in the loser’s mini-inventory, then confirm or skip."
        };
    }

    if (mode === "awaiting_entity_choice") {
        const choice = turn?.pending_entity_choice || null;
        const hasAlchemist = !!choice?.has_alc_02;
        const hasOracle = !!choice?.has_ora_02;

        if (hasOracle && hasAlchemist) {
            return {
                title: "Waiting for entity choice",
                message: "Oracle may choose a entity candidate. Alchemist may redraw for -1 HP and 1 Action; after redraw only the newest entity can be confirmed."
            };
        }

        if (hasOracle) {
            return {
                title: "Waiting for Oracle entity choice",
                message: "Choose one of the two entity candidates for this room."
            };
        }

        if (hasAlchemist) {
            return {
                title: "Waiting for Alchemist entity choice",
                message: "Confirm the current entity candidate, or redraw for -1 HP and 1 Action."
            };
        }

        return {
            title: "Waiting for entity choice",
            message: "Choose the entity candidate for this room."
        };
    }

    if (mode === "awaiting_entity_encounter") {
        const encounter = turn?.pending_entity_encounter || null;

        if (encounter?.can_skip) {
            const skillId = encounter.skip_skill_id || "movement skill";

            if (skillId === "skill_pri_02") {
                return {
                    title: "Entity encounter",
                    message: "Warrior Princess may fight, or continue moving by paying -1 HP. If no Actions remain or HP is 1, she must fight."
                };
            }

            if (skillId === "skill_thi_02") {
                return {
                    title: "Entity encounter",
                    message: "Thief may fight, or continue moving if Actions remain."
                };
            }

            return {
                title: "Entity encounter",
                message: "You may fight this entity or continue moving using your movement skill."
            };
        }

        return {
            title: "Entity encounter",
            message: "You entered a entity tile. You must start the fight."
        };
    }

    if (mode === "awaiting_curse_choice") {
        const selected = getPlayerById(selectedCurseTargetPlayerId);
        const selectedText = selected
            ? ` Selected curse target: ${selected.display_name || ("Player #" + selected.player_id)}. Confirm or reset.`
            : " Choose which player receives the curse, then confirm the curse selection.";

        return {
            title: "Waiting for curse target",
            message: selectedText
        };
    }

    if (mode === "awaiting_poison_choice") {
        const selectedPlayer = getPlayerById(selectedPoisonTargetPlayerId);

        if (!selectedPlayer) {
            return {
                title: "Waiting for poison target",
                message: "Choose a player, then click one of that player’s skill chips to poison it."
            };
        }

        if (!selectedPoisonTargetSkillId) {
            return {
                title: "Waiting for poison skill",
                message: `Selected poison target: ${selectedPlayer.display_name || ("Player #" + selectedPlayer.player_id)}. Now click one of this player's skill chips.`
            };
        }

        return {
            title: "Waiting for poison confirmation",
            message: `Selected poison target: ${selectedPlayer.display_name || ("Player #" + selectedPlayer.player_id)} / ${prettySkillLabel(selectedPoisonTargetSkillId)}. Confirm or reset.`
        };
    }

    if (mode === "awaiting_heal_choice") {
        return {
            title: "Waiting for healing choice",
            message: "Choose the target HP value for fountain healing, then confirm."
        };
    }

    if (mode === "pending_tile") {
        return {
            title: "Waiting for tile confirmation",
            message: "Rotate the discovered tile if needed, then confirm tile placement."
        };
    }

    if (mode === "fight") {
        return {
            title: "Waiting for fight resolution",
            message: "Resolve the active fight in the fight window."
        };
    }

    if (mode === "item_pickup") {
        if (
            turn?.fight_continue_after_item_pickup &&
            turn?.fight_continue_skill_id === "skill_swo_02"
        ) {
            return {
                title: "Waiting for Swordsman pickup",
                message: "Swordsman may continue after item pickup. Use the Swordsman continuation skill to proceed."
            };
        }

        return {
            title: "Waiting for item pickup",
            message: "Finish the current item pickup by choosing what to keep/drop, then end the turn."
        };
    }

    if (mode === "retreat") {
        return {
            title: "Waiting for retreat",
            message: "Resolve the retreat action before continuing."
        };
    }

    return null;
}

function showError(msg) {
    showMessage(msg, "error", "Error");
}

function clearError() {
    showMessage("(ready)", "info", "Info");
}

refreshAll();
