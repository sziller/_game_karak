const gameApi = (p) => "/api" + (p.startsWith("/") ? p : "/" + p);
const lobbyApi = (p) => "/api/lobby" + (p.startsWith("/") ? p : "/" + p);

let latestPlayers = null;
let latestMap = null;
let latestFight = null;
let selectedCurseTargetPlayerId = null;
let selectedPoisonTargetPlayerId = null;
let selectedPoisonTargetSkillId = null;
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
        return "/static/media/tiles/entrance.png";
    }

    return `/static/media/tiles/${imgBase}-${variant}.png`;
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
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;

    const rect = mapDiv.getBoundingClientRect();
    const screenCX = rect.width / 2;
    const screenCY = rect.height / 2;

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
        if (tile.archetype_id === "entrance") {
            baseImg.src = "/static/media/tiles/entrance.png";
        } else {
            const variant = getTileVariant(tile, x, y);
            baseImg.src = `/static/media/tiles/${tile.img_base}-${variant}.png`;
        }

        baseImg.className = "tile-base-img";
        baseImg.style.transform = `rotate(${tile.rotation_q * 90}deg)`;
        tileBox.appendChild(baseImg);

        if (tile.monster_id) {
            const img = document.createElement("img");
            img.src = `/static/media/tile-content/${tile.monster_id}.png`;
            img.alt = tile.monster_id;
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

        const marker = document.createElement("div");
        marker.style.position = "absolute";
        marker.style.left = `${px - 14}px`;
        marker.style.top = `${py - 14}px`;
        marker.style.width = `28px`;
        marker.style.height = `28px`;
        marker.style.borderRadius = "50%";
        marker.style.display = "flex";
        marker.style.alignItems = "center";
        marker.style.justifyContent = "center";
        marker.style.fontSize = "14px";
        marker.style.fontWeight = "bold";
        marker.style.color = "#000";
        marker.style.boxSizing = "border-box";
        marker.style.pointerEvents = "none";
        marker.style.background = getPlayerTokenColor(p.player_id, idx);
        marker.style.border = isActive ? "3px solid #ffffff" : "2px solid #333";
        marker.style.zIndex = isActive ? "50" : "20";
        marker.textContent = String(p.player_id ?? "?");

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

function renderMiniInventoryColumnRow(label, slotsOrValue, isTreasure = false) {
    if (isTreasure) {
        return `
            <div class="mini-inv-row mini-inv-row-treasure">
                <span class="mini-inv-label">${label}</span>
                <span class="mini-inv-treasure-value">${slotsOrValue ?? 0}</span>
            </div>
        `;
    }

    const slots = Array.isArray(slotsOrValue) ? slotsOrValue : [];

    return `
        <div class="mini-inv-row">
            <span class="mini-inv-label">${label}</span>
            <span class="mini-inv-slots">
                ${slots.map(slot => renderMiniInventorySlot(slot)).join("")}
            </span>
        </div>
    `;
}

function renderMiniInventorySlot(slot) {
    const itemId = miniItemIdFromSlot(slot);

    if (!itemId) {
        return `
            <span class="mini-inv-slot mini-inv-slot-empty">
                <span class="mini-inv-empty-dot">·</span>
            </span>
        `;
    }

    const item = resolveItemForMiniInventory(itemId);

    if (!item) {
        return `
            <span class="mini-inv-slot mini-inv-slot-missing" title="${itemId}">
                ?
            </span>
        `;
    }

    return `
        <span class="mini-inv-slot" title="${itemId}">
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
            ${renderMiniInventoryColumnRow("W", miniInv.weapons)}
            ${renderMiniInventoryColumnRow("K", miniInv.keys)}
            ${renderMiniInventoryColumnRow("S", miniInv.scrolls)}
            ${renderMiniInventoryColumnRow("T", miniInv.treasure, true)}
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

function renderPlayers(data) {
    const box = document.getElementById("players-box");
    if (!box) return;

    box.innerHTML = "";

    const players = data?.players || [];
    const activeIdx = data?.active_player_idx ?? 0;

    const awaitingCurse = isAwaitingCurseChoice();
    const awaitingPoison = isAwaitingPoisonChoice();

    if (!players.length) {
        box.textContent = "(no runtime players)";
        return;
    }

    players.forEach((p, idx) => {
        const isActive = idx === activeIdx;

        const isCursed = !!(p.status?.is_cursed || p.is_cursed || p.cursed);
        const isEvil = !!(p.status?.is_evil || p.is_evil);

        const row = document.createElement("div");
        row.className = "player-row" + (isActive ? " active" : "");

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

        const isTeleportPlayerTargeting =
            !!pendingTeleportSkillId &&
            pendingTeleportTargetMode === "player";

        const isItemPlayerTargeting =
            !!pendingItemUse &&
            pendingItemUse.phase === "select_player";

        const canSelectForCurse = awaitingCurse;
        const canSelectForPoison = awaitingPoison;
        const canSelectForTeleport = isTeleportPlayerTargeting;
        const canSelectForItemUse = isItemPlayerTargeting;

        row.style.cursor = (
            canSelectForCurse ||
            canSelectForPoison ||
            canSelectForTeleport ||
            canSelectForItemUse
        )
            ? "pointer"
            : "default";

        // --------------------------------------------------------
        // Player row click behavior
        // --------------------------------------------------------
        row.onclick = () => {
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
            img.src = p.icon_path;
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
async function selectActivePlayer(playerId) {
    const r = await fetch(gameApi("/players/select"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({player_id: playerId})
    });

    const data = await r.json();
    if (!r.ok) {
        throw new Error(data.detail || "Failed to select active player.");
    }

    await refreshAll();
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

    const r = await fetch(gameApi("/move"), {
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

    if (mapData.player) {
        lines.push(`Compat player position: (${mapData.player.x}, ${mapData.player.y})`);
    }

    lines.push(`Tiles left: ${mapData.tiles_left}`);
    lines.push(`Monsters left: ${mapData.monsters_left}`);
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

function monsterImagePath(monsterId) {
    if (!monsterId) {
        return null;
    }

    return `/static/media/tile-content/${monsterId}.png`;
}

async function loadPlayers() {
    const r = await fetch(gameApi("/players"));
    const data = await r.json();
    if (!r.ok) {
        throw new Error(data.detail || "Failed to load runtime players.");
    }

    latestPlayers = data;
    renderPlayers(data);
}

async function loadMap() {
    const r = await fetch(gameApi("/map"));
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

function getPendingMonsterChoice() {
    const turn =
        latestMap?.turn ||
        latestPlayers?.turn ||
        null;

    return turn?.pending_monster_choice || null;
}

async function confirmMonsterCandidate(candidateIndex) {
    clearError();

    const r = await fetch(gameApi("/monster/confirm_candidate"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({candidate_index: candidateIndex})
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Monster confirmation failed.");
        return;
    }

    await refreshAll();
}

async function redrawMonsterCandidate() {
    clearError();

    const r = await fetch(gameApi("/monster/redraw_candidate"), {
        method: "POST"
    });

    const data = await r.json();

    if (!r.ok) {
        showError(data.detail || "Monster redraw failed.");
        return;
    }

    await refreshAll();
}


function renderEncounterPanel() {
    const box = document.getElementById("monster-choice-box");

    if (!box) {
        console.error("monster-choice-box not found");
        return;
    }

    const activePlayer = latestPlayers?.active_player || null;
    const currentTile = getActivePlayerCurrentTile();
    const pendingChoice = getPendingMonsterChoice();

    const tableauPath =
        activePlayer?.tableau_path ||
        activePlayer?.image_path ||
        activePlayer?.icon_path ||
        null;

    // --------------------------------------------------------
    // Pending Oracle / Alchemist monster choice
    // --------------------------------------------------------
    if (pendingChoice) {
        const candidates = Array.isArray(pendingChoice.candidates)
            ? pendingChoice.candidates
            : [];

        const confirmable = new Set(
            (pendingChoice.confirmable_indices || []).map(Number)
        );

        const canRedraw = !!pendingChoice.has_alc_02;

        box.classList.remove("panel-placeholder");
        box.classList.add("encounter-box", "encounter-monster-choice-box");

        box.innerHTML = `
            <div class="encounter-active-player">
                ${
            tableauPath
                ? `<img class="encounter-tableau-img" src="${tableauPath}" alt="active player">`
                : `<div class="encounter-tableau-placeholder">no tableau</div>`
        }
            </div>

            <div class="encounter-monster-choice">
                <div class="monster-choice-candidates">
                    ${
            candidates.length
                ? candidates.map((m, i) => {
                    const isConfirmable = confirmable.has(i);
                    const monsterId = m.monster_id || "?";
                    const imgPath = m.image_path || monsterImagePath(monsterId);

                    return `
                                    <button
                                        type="button"
                                        class="monster-choice-card ${isConfirmable ? "confirmable" : "not-confirmable"}"
                                        ${isConfirmable ? "" : "disabled"}
                                        onclick="confirmMonsterCandidate(${i})"
                                        title="${monsterId}"
                                    >
                                        <img src="${imgPath}" alt="${monsterId}">
                                        <span>${monsterId}</span>
                                    </button>
                                `;
                }).join("")
                : `<div class="encounter-target-empty">no candidates</div>`
        }
                </div>

                <div class="monster-choice-actions">
                    <button
                        type="button"
                        onclick="redrawMonsterCandidate()"
                        ${canRedraw ? "" : "disabled"}
                        title="Alchemist redraw: costs 1 Action and 1 HP"
                    >redraw</button>
                </div>
            </div>
        `;

        return;
    }

    // --------------------------------------------------------
    // Default encounter display: active player + current monster
    // --------------------------------------------------------
    const monsterId = currentTile?.monster_id || null;
    const monsterPath = monsterImagePath(monsterId);

    console.log("ENCOUNTER DEBUG", {
        activePlayer,
        tableauPath,
        currentTile,
        monsterId,
        monsterPath
    });

    box.classList.remove("panel-placeholder", "encounter-monster-choice-box");
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
        monsterId
            ? `<img class="encounter-monster-img" src="${monsterPath}" alt="${monsterId}">`
            : `<div class="encounter-target-empty">no monster</div>`
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
        await loadPlayers();
        await loadMap();
        await loadInventory();

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

        const turn = latestMap?.turn || latestPlayers?.turn || null;

        if (turn?.mode === "fight") {
            try {
                const r = await fetch(gameApi("/fight/state"));
                const data = await r.json();

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
    } catch (e) {
        console.error("refreshAll failed:", e);
        showError(String(e));
    }

    updateActionAvailability();
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

    const r = await fetch(gameApi("/healing/choose_target"), {
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
        const r = await fetch(gameApi("/ko_reaction/choose_fountain"), {
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

    const r = await fetch(gameApi(endpoint), {
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

    const r = await fetch(gameApi(endpoint), {
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

    const r = await fetch(gameApi("/rotate_tile"), {
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

    return item.image_path;
}

function renderGround(data) {
    const box = document.getElementById("ground-box");
    if (!box) return;

    const groundItem = data?.ground_item || null;
    const groundItemId = data?.ground_item_id || groundItem?.item_id || null;
    const groundItemDesc = groundItem?.desc || "";

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

    const actionLabel = slotActionLabel(slot);
    const actionDisabled = slotActionDisabled(slot);

    const canUse = !!slot?.can_use_slot_item;
    const useEffect = slot?.use_effect || null;

    const useDisabled = !canUse || !itemId || !useEffect;

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
                title="${actionDisabled ? "" : actionLabel}"
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

function renderFightRows(rows) {
    if (!rows || !rows.length) {
        return `<div class="muted">(no rows)</div>`;
    }

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
                            onclick="fightToggleScroll('${slotId}')"
                            ${btn.enabled ? "" : "disabled"}
                            style="margin-right:6px; ${activeStyle}"
                            title="${btn.label || slotId || ""}"
                        >
                            ${btn.image_path
                        ? `<img class="item-icon" src="${btn.image_path}" alt="${btn.label || slotId || ""}">`
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
                            onclick="fightToggleSkill('${skillId}')"
                            ${btn.enabled && skillId ? "" : "disabled"}
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
                            onclick="fightRerollDie(${dieIndex}, '${skillId}')"
                            ${btn.enabled && dieIndex && skillId ? "" : "disabled"}
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
                            onclick="fightRerollBoth('${skillId}')"
                            ${btn.enabled && skillId ? "" : "disabled"}
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
                    ? `<img class="item-icon" src="${btn.image_path}" alt="${btn.label || btn.button_id || ""}">`
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
                    <button onclick="fightToss()" ${row.button_enabled ? "" : "disabled"}>
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


function renderFightSide(side, title) {
    if (!side) {
        return `<div class="muted">(missing side)</div>`;
    }

    const participant = side.participant || {};
    const diceState = side.dice_state || null;

    let html = `
        <div style="border:1px solid #333; padding:10px; background:#141414;">
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
            ${renderFightRows(side.rows || [])}
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

    let html = `
        <div style="margin-bottom:10px;">
            <b>Fight kind:</b> ${context.fight_kind || "-"} |
            <b>Tile:</b> (${context.tile_x ?? "?"}, ${context.tile_y ?? "?"}) |
            <b>Phase:</b> ${data.phase || "-"} |
            <b>Resolved outcome:</b> ${outcome || "(not resolved)"}
        </div>

        ${renderFightPrediction(prediction)}

        <div class="two-col">
            <div class="col">
                ${renderFightSide(data.initiator_side, "Initiator")}
            </div>
            <div class="col">
                ${renderFightSide(data.challenged_side, "Challenged")}
            </div>
        </div>
    `;

    box.innerHTML = html;
}

async function toggleSkillUiSelection(playerId, skillId) {
    const activePlayerId = latestPlayers?.active_player?.player_id;
    if (playerId !== activePlayerId) {
        showError("Only the active player's skill UI can be changed.");
        return;
    }

    const r = await fetch(gameApi("/skills/toggle"), {
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

    const r = await fetch(gameApi("/skills/set_value"), {
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
        return "Battlemage teleport: enter coordinates of monster tile";
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

    const r = await fetch(gameApi("/skills/sco_02/pull_tile"), {
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
    const r = await fetch(gameApi("/inventory"));
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

    const r = await fetch(gameApi("/inventory/slot_action"), {
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

async function useInventoryItem({
                                    slot_group,
                                    slot_index,
                                    target_player_id = null,
                                    target_x = null,
                                    target_y = null,
                                    successMessage = "Item used."
                                }) {
    clearError();

    const r = await fetch(gameApi("/inventory/use_item"), {
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

    const r = await fetch(gameApi("/itempickup/continue"), {
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
    try {
        const r = await fetch(gameApi("/turn/end"), {
            method: "POST",
        });
        const data = await r.json();

        if (!r.ok) {
            throw new Error(data.detail || "Failed to end turn.");
        }

        await refreshAll();
        showMessage("Turn ended. Next player is active.", "info", "Info");
    } catch (e) {
        console.error("endTurn failed:", e);
        showMessage(String(e), "warning", "Warning");
    }
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

    const r = await fetch(gameApi("/inventory/pickup_treasure"), {
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
    const isAwaitingMonsterChoice = mode === "awaiting_monster_choice";
    const isAwaitingMonsterEncounter = mode === "awaiting_monster_encounter";
    const isFight = mode === "fight";
    const isItemPickup = mode === "item_pickup";
    const isAwaitingCurse = mode === "awaiting_curse_choice";
    const isAwaitingPoison = mode === "awaiting_poison_choice";
    const isAwaitingHeal = mode === "awaiting_heal_choice";
    const isAwaitingKoReaction = isAwaitingKoReactionChoice();

    const encounter = turn?.pending_monster_encounter || null;
    const canMoveDuringMonsterEncounter =
        isAwaitingMonsterEncounter &&
        !!encounter?.can_skip;

    // --------------------------------------------------------
    // Special item pickup state:
    // Swordsman won a fight with a final physical 6.
    // --------------------------------------------------------
    const isSwoContinueItemPickup =
        isItemPickup &&
        !!turn?.fight_continue_after_item_pickup &&
        turn?.fight_continue_skill_id === "skill_swo_02";

    const canStartFight =
        !!currentTile?.monster_id &&
        !!turn &&
        (isIdle || isAwaitingMonsterEncounter) &&
        !isAwaitingKoReaction &&
        !isAwaitingPoison &&
        !isAwaitingMonsterChoice;

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
            isAwaitingMonsterChoice ||
            isAwaitingMonsterEncounter ||
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
        !isAwaitingMonsterChoice &&
        !isAwaitingMonsterEncounter;

    const canUseCoordinateSkillTeleport =
        isCoordinateTeleportTargeting &&
        isIdle &&
        !isAwaitingKoReaction &&
        !isAwaitingMonsterChoice &&
        !isAwaitingMonsterEncounter;

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
    // - awaiting_monster_encounter: movement only if skip is allowed
    // --------------------------------------------------------
    moveButtons.forEach(btn => {
        if (btn) {
            btn.disabled =
                isTeleportTargeting ||
                isItemTargeting ||
                isAwaitingKoReaction ||
                isAwaitingMonsterChoice ||
                !(isIdle || canMoveDuringMonsterEncounter);
        }
    });

    rotateButtons.forEach(btn => {
        if (btn) {
            btn.disabled =
                isTeleportTargeting ||
                isItemTargeting ||
                isAwaitingKoReaction ||
                isAwaitingMonsterChoice ||
                isAwaitingMonsterEncounter ||
                !isPendingTile;
        }
    });

    if (confirmTileBtn) {
        confirmTileBtn.disabled =
            isTeleportTargeting ||
            isItemTargeting ||
            isAwaitingKoReaction ||
            isAwaitingMonsterChoice ||
            isAwaitingMonsterEncounter ||
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

    const r = await fetch(gameApi("/confirm_tile"), {
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

    const r = await fetch(gameApi("/poison/choose_target"), {
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
}

async function confirmCurseSelection() {
    if (selectedCurseTargetPlayerId == null) {
        showError("No curse target selected.");
        return;
    }

    clearError();

    const r = await fetch(gameApi("/curse/choose_target"), {
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

    const r = await fetch(gameApi("/fight/start"), {
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

    const r = await fetch(gameApi("/fight/state"));
    const data = await r.json();

    if (!r.ok) {
        renderFight(null);
        showError(data.detail || "No active fight.");
        return;
    }

    renderFight(data);
}

async function fightToss() {
    clearError();

    const r = await fetch(gameApi("/fight/toss"), {
        method: "POST"
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight toss failed.");
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function fightRerollDie(dieIndex, skillId) {
    clearError();

    const r = await fetch(gameApi("/fight/reroll_die"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            die_index: dieIndex,
            skill_id: skillId
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight die reroll failed.");
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function fightRerollBoth(skillId) {
    clearError();

    const r = await fetch(gameApi("/fight/reroll_both"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            skill_id: skillId
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight both-dice reroll failed.");
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function fightResolve() {
    clearError();

    const r = await fetch(gameApi("/fight/resolve"), {
        method: "POST"
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight resolve failed.");
        return;
    }

    renderFight(null);
    await refreshAll();
}

async function fightToggleSkill(skillId) {
    clearError();

    const r = await fetch(gameApi("/fight/toggle_skill"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            skill_id: skillId
        })
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Fight skill toggle failed.");
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function fightToggleScroll(slotId) {
    clearError();

    const r = await fetch(gameApi("/fight/toggle_scroll"), {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({slot_id: slotId})
    });

    const data = await r.json();
    if (!r.ok) {
        showError(data.detail || "Scroll toggle failed.");
        return;
    }

    renderFight(data);
    await refreshAll();
}

async function finishItemPickup() {
    try {
        const r = await fetch(gameApi("/itempickup/finish"), {
            method: "POST",
        });
        const data = await r.json();

        if (!r.ok) {
            throw new Error(data.detail || "Failed to finish item pickup.");
        }

        renderFight(null);
        await refreshAll();
        showMessage("Item pickup finished. Turn ended.", "info", "Info");
    } catch (e) {
        console.error("finishItemPickup failed:", e);
        showMessage(String(e), "warning", "Warning");
    }
}

async function leaveGame() {
    try {
        await fetch(lobbyApi("/reset_to_phase1"), {method: "POST"});
    } catch (e) {
        console.error(e);
    }

    skillUiState = {};
    selectedCurseTargetPlayerId = null;
    latestFight = null;

    window.location.href = "/phase1";
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
            return {
                title: "Waiting for teleport target",
                message: `${teleportSkillLabel(pendingTeleportSkillId)}. Select a target player, then confirm.`
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

    if (mode === "awaiting_monster_choice") {
        const choice = turn?.pending_monster_choice || null;
        const hasAlchemist = !!choice?.has_alc_02;
        const hasOracle = !!choice?.has_ora_02;

        if (hasOracle && hasAlchemist) {
            return {
                title: "Waiting for monster choice",
                message: "Oracle may choose a monster candidate. Alchemist may redraw for -1 HP and 1 Action; after redraw only the newest monster can be confirmed."
            };
        }

        if (hasOracle) {
            return {
                title: "Waiting for Oracle monster choice",
                message: "Choose one of the two monster candidates for this room."
            };
        }

        if (hasAlchemist) {
            return {
                title: "Waiting for Alchemist monster choice",
                message: "Confirm the current monster candidate, or redraw for -1 HP and 1 Action."
            };
        }

        return {
            title: "Waiting for monster choice",
            message: "Choose the monster candidate for this room."
        };
    }

    if (mode === "awaiting_monster_encounter") {
        const encounter = turn?.pending_monster_encounter || null;

        if (encounter?.can_skip) {
            const skillId = encounter.skip_skill_id || "movement skill";

            if (skillId === "skill_pri_02") {
                return {
                    title: "Monster encounter",
                    message: "Warrior Princess may fight, or continue moving by paying -1 HP. If no Actions remain or HP is 1, she must fight."
                };
            }

            if (skillId === "skill_thi_02") {
                return {
                    title: "Monster encounter",
                    message: "Thief may fight, or continue moving if Actions remain."
                };
            }

            return {
                title: "Monster encounter",
                message: "You may fight this monster or continue moving using your movement skill."
            };
        }

        return {
            title: "Monster encounter",
            message: "You entered a monster tile. You must start the fight."
        };
    }

    if (mode === "awaiting_curse_choice") {
        return {
            title: "Waiting for curse target",
            message: "Choose which player receives the curse, then confirm the curse selection."
        };
    }

    if (mode === "awaiting_poison_choice") {
        return {
            title: "Waiting for poison target",
            message: "Choose a player, then click one of that player’s skill chips to poison it."
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
