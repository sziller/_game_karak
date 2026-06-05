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

const API_BASE = karakPath("/api");

let latestResults = null;

let currentSort = {
    key: "rank_order",
    direction: "asc",
};

const ITEM_IMAGE_FILES = {
    dagger: "dagger.png",
    sword: "sword.png",
    axe: "axe.png",
    heal: "heal.png",
    thorn: "thorn.png",
    key: "key.png",
    fist: "fist.png",
    fireball: "fireball.png",
    treasure: "treasure.png",
    ruby: "ruby.png",
    p_bomb: "poison.png",
    amulet_o: "amulet_orange.png",
    amulet_g: "amulet_green.png",
    kris: "kris.png",
    hammer: "hammer.png",
};

const SKILL_LABELS = {
    skill_bea_01: "Ambush",
    skill_bea_02: "Protector",
    skill_bat_01: "Sword Master",
    skill_bat_02: "Blitz attack",
    skill_acr_01: "Throwing daggers",
    skill_acr_02: "Sprint",
    skill_bar_01: "Berserk",
    skill_bar_02: "Perseverance",
    skill_pri_01: "Dual Attack",
    skill_pri_02: "Aggressive Movement",
    skill_ran_01: "Bear attack",
    skill_ran_02: "Eavesdropping",
    skill_wrr_01: "Double Attack",
    skill_wrr_02: "Reincarnation",
    skill_wiz_01: "Magical Affinity",
    skill_wiz_02: "Astral Walking",
    skill_thi_01: "Backstab",
    skill_thi_02: "Stealth",
    skill_wlk_01: "Sacrifice",
    skill_wlk_02: "Magic Swap",
    skill_ora_01: "Farseeing",
    skill_ora_02: "Fateweaver",
    skill_alc_01: "Skin of Steel",
    skill_alc_02: "Transformation",
    skill_swo_01: "Combat Training",
    skill_swo_02: "Unstoppable",
    skill_sco_01: "Critical Hit",
    skill_sco_02: "Exploration",
};

function showMessage(message, variant = "info", title = "Info") {
    const box = document.getElementById("message-box");
    const titleEl = document.getElementById("message-title");
    const contentEl = document.getElementById("message-content");

    if (!box || !titleEl || !contentEl) {
        return;
    }

    box.classList.remove("message-info", "message-error", "message-waiting");

    if (variant === "error" || variant === "warning") {
        box.classList.add("message-error");
    } else if (variant === "waiting") {
        box.classList.add("message-waiting");
    } else {
        box.classList.add("message-info");
    }

    titleEl.textContent = title;
    contentEl.textContent = message;
}

function normalizePlayerId(playerId) {
    return String(playerId);
}

function itemImagePath(itemId) {
    if (!itemId) {
        return null;
    }

    const imgFile = ITEM_IMAGE_FILES[itemId];

    if (!imgFile) {
        return null;
    }

    return `${KARAK_STATIC_URL}/media/tile-content/${imgFile}`;
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function getPlayerNr(player) {
    const raw = player?.player_id;

    if (typeof raw === "number") {
        return raw;
    }

    const parsed = Number(String(raw ?? "").replace(/^p/i, ""));

    if (Number.isFinite(parsed)) {
        return parsed;
    }

    return 999999;
}

function getInventory(player) {
    return player?.inventory_view || player?.inventory || {};
}

function getTreasureValue(player) {
    return Number(
        player?.result_status?.credited_treasure ??
        player?.result?.credited_treasure ??
        getInventory(player)?.treasure ??
        0
    );
}

function getRawTreasureValue(player) {
    return Number(
        player?.result_status?.raw_treasure ??
        getInventory(player)?.treasure ??
        0
    );
}

function isPlayerCredited(player) {
    return !!player?.result_status?.is_credited;
}

function isPlayerUncredited(player) {
    return !!player?.result_status?.is_uncredited;
}

function getFinalStatusLabel(player) {
    return player?.result_status?.final_status_label || "-";
}

function getPlayerKillsByEntity(player) {
    const killStats = latestResults?.kill_stats || {};
    const byPlayer = killStats?.kills_by_player_id || {};
    const row = byPlayer[normalizePlayerId(player?.player_id)] || byPlayer[player?.player_id] || {};

    return row?.kills_by_entity_id || {};
}

function getTotalKills(player) {
    const kills = getPlayerKillsByEntity(player);
    return Object.values(kills).reduce((sum, value) => sum + Number(value || 0), 0);
}

function getTargetEntityIds() {
    const checks =
        latestResults?.result?.end_condition?.checks ||
        latestResults?.end_condition?.checks ||
        [];

    return checks
        .map(row => row?.entity_id_normalized)
        .filter(Boolean);
}

function getTargetEntityKills(player) {
    const targetIds = getTargetEntityIds();
    const kills = getPlayerKillsByEntity(player);

    return targetIds.reduce((sum, entityId) => {
        return sum + Number(kills?.[entityId] || 0);
    }, 0);
}

function getPvpStatsForPlayer(player) {
    const playerId = normalizePlayerId(player?.player_id);

    return (
        player?.pvp_stats ||
        latestResults?.pvp_stats?.by_player_id?.[playerId] ||
        {wins: 0, losses: 0, draws: 0, total: 0}
    );
}

function getPvpWins(player) {
    return Number(getPvpStatsForPlayer(player).wins || 0);
}

function getPvpLosses(player) {
    return Number(getPvpStatsForPlayer(player).losses || 0);
}

function getPvpDraws(player) {
    return Number(getPvpStatsForPlayer(player).draws || 0);
}

function getPvpLosses(player) {
    return Number(player?.pvp_stats?.losses ?? 0);
}

function getPvpDraws(player) {
    return Number(player?.pvp_stats?.draws ?? 0);
}

function renderPvpStats(player) {
    const wins = getPvpWins(player);
    const losses = getPvpLosses(player);
    const draws = getPvpDraws(player);

    if (!wins && !losses && !draws) {
        return `<span class="muted">-</span>`;
    }

    return `
        <div class="results-pvp-stat">
            <div><b>${wins}</b> W</div>
            <div>${losses} L</div>
            <div>${draws} D</div>
        </div>
    `;
}

function getSkillNames(player) {
    const skills = Array.isArray(player?.skills) ? player.skills : [];

    return skills.map(skillId => SKILL_LABELS[skillId] || skillId);
}

function getMiniInventorySortValue(player) {
    const inv = getInventory(player);

    const weaponCount = (inv.weapon_slots || []).filter(Boolean).length;
    const scrollCount = (inv.scroll_slots || []).filter(Boolean).length;
    const keyCount = (inv.key_slots || []).filter(Boolean).length;
    const treasure = Number(inv.treasure || 0);

    return weaponCount * 1000 + scrollCount * 100 + keyCount * 10 + treasure;
}

function getSortValue(player, key) {
    switch (key) {
        case "rank_order":
            return getPlayerNr(player);

        case "treasure":
            return getTreasureValue(player);

        case "icon":
            return player?.profession || "";

        case "name":
            return player?.display_name || "";

        case "skills":
            return getSkillNames(player).join(" ");

        case "target_kills":
            return getTargetEntityKills(player);

        case "all_kills":
            return getTotalKills(player);

        case "pvp":
            return getPvpWins(player);

        case "inventory":
            return getMiniInventorySortValue(player);

        default:
            return getPlayerNr(player);
    }
}

function compareValues(a, b, direction) {
    const dir = direction === "desc" ? -1 : 1;

    if (typeof a === "number" && typeof b === "number") {
        return (a - b) * dir;
    }

    return String(a).localeCompare(String(b)) * dir;
}

function sortPlayers(players) {
    const rows = [...players];

    rows.sort((a, b) => {
        const mainA = getSortValue(a, currentSort.key);
        const mainB = getSortValue(b, currentSort.key);

        const mainCmp = compareValues(mainA, mainB, currentSort.direction);

        if (mainCmp !== 0) {
            return mainCmp;
        }

        // Tie fallback: player nr ascending.
        return getPlayerNr(a) - getPlayerNr(b);
    });

    return rows;
}

function toggleSort(key) {
    if (currentSort.key === key) {
        currentSort.direction = currentSort.direction === "asc" ? "desc" : "asc";
    } else {
        currentSort.key = key;

        // Numeric result columns default to descending.
        if (["treasure", "target_kills", "all_kills", "pvp", "inventory"].includes(key)) {
            currentSort.direction = "desc";
        } else {
            currentSort.direction = "asc";
        }
    }

    renderResultsTable();
}

function renderSortButton(icon, key, title) {
    const active = currentSort.key === key;
    const suffix = active
        ? (currentSort.direction === "asc" ? " ▲" : " ▼")
        : "";

    return `
        <button
            class="results-sort-btn ${active ? "active-sort" : ""}"
            data-sort-key="${escapeHtml(key)}"
            title="${escapeHtml(title)}"
        >
            ${icon}${suffix}
        </button>
    `;
}

function renderPlayerIcon(player) {
    const src = player?.icon_path || player?.figurine_path || player?.image_path;

    if (!src) {
        return `<div class="results-player-icon-placeholder">?</div>`;
    }

    const normalizedSrc = karakStaticAsset(src);

    return `
        <img
            class="results-player-icon"
            src="${escapeHtml(normalizedSrc)}"
            alt="${escapeHtml(player?.display_name || "player")}"
        >
    `;
}

function renderSkillList(player) {
    const names = getSkillNames(player);

    if (!names.length) {
        return `<span class="muted">-</span>`;
    }

    return `
        <div class="results-skill-list">
            ${names.map(name => `
                <div class="results-skill-chip">${escapeHtml(name)}</div>
            `).join("")}
        </div>
    `;
}

function renderEntityKillList(player, { targetOnly = false } = {}) {
    const kills = getPlayerKillsByEntity(player);
    let entries = Object.entries(kills);

    if (targetOnly) {
        const targetIds = new Set(getTargetEntityIds());
        entries = entries.filter(([entityId]) => targetIds.has(entityId));
    }

    if (!entries.length) {
        return `<span class="muted">-</span>`;
    }

    entries.sort((a, b) => {
        const countCmp = Number(b[1] || 0) - Number(a[1] || 0);

        if (countCmp !== 0) {
            return countCmp;
        }

        return String(a[0]).localeCompare(String(b[0]));
    });

    return `
        <div class="results-entity-list">
            ${entries.map(([entityId, count]) => `
                <div class="results-entity-line">
                    <span class="results-entity-name">${escapeHtml(entityId)}</span>
                    <span class="results-entity-count">${Number(count || 0)}</span>
                </div>
            `).join("")}
        </div>
    `;
}

function renderMiniInvSlots(itemIds) {
    const ids = Array.isArray(itemIds) ? itemIds : [];

    if (!ids.length) {
        return `<span class="muted">-</span>`;
    }

    return ids.map(itemId => {
        if (!itemId) {
            return `
                <span class="results-mini-inv-slot">
                    <span class="results-mini-empty-dot">·</span>
                </span>
            `;
        }

        const src = itemImagePath(itemId);

        if (!src) {
            return `
                <span class="results-mini-inv-slot" title="${escapeHtml(itemId)}">
                    ?
                </span>
            `;
        }

        return `
            <span class="results-mini-inv-slot" title="${escapeHtml(itemId)}">
                <img
                    class="results-mini-inv-icon"
                    src="${escapeHtml(src)}"
                    alt="${escapeHtml(itemId)}"
                >
            </span>
        `;
    }).join("");
}

function renderMiniInventory(player) {
    const inv = getInventory(player);

    const weaponSlots = inv.weapon_slots || [];
    const keySlots = inv.key_slots || [];
    const scrollSlots = inv.scroll_slots || [];
    const treasure = Number(inv.treasure || 0);

    return `
        <div class="results-mini-inventory">
            <div class="results-mini-inv-row">
                <div class="results-mini-inv-label">W</div>
                <div class="results-mini-inv-slots">${renderMiniInvSlots(weaponSlots)}</div>
            </div>

            <div class="results-mini-inv-row">
                <div class="results-mini-inv-label">K</div>
                <div class="results-mini-inv-slots">${renderMiniInvSlots(keySlots)}</div>
            </div>

            <div class="results-mini-inv-row">
                <div class="results-mini-inv-label">S</div>
                <div class="results-mini-inv-slots">${renderMiniInvSlots(scrollSlots)}</div>
            </div>

            <div class="results-mini-inv-row">
                <div class="results-mini-inv-label">T</div>
                <div class="results-mini-treasure">${treasure}</div>
            </div>
        </div>
    `;
}

function renderResultsTable() {
    const root = document.getElementById("results-table-root");

    if (!root) {
        return;
    }

    const players = latestResults?.players || [];
    const sortedPlayers = sortPlayers(players);

    if (!sortedPlayers.length) {
        root.innerHTML = `<div class="muted">No players found.</div>`;
        return;
    }

    root.innerHTML = `
        <table class="results-table">
            <thead>
                <tr>
                    <th class="results-col-rank">
                        ${renderSortButton("🏆", "rank_order", "Rank / player order")}
                    </th>
                    <th class="results-col-treasure">
                        ${renderSortButton("💎", "treasure", "Treasures")}
                    </th>
                    <th class="results-col-icon">
                        ${renderSortButton("🧍", "icon", "Character")}
                    </th>
                    <th class="results-col-name">
                        ${renderSortButton("🏷️", "name", "Player name")}
                    </th>
                    <th class="results-col-skills">
                        ${renderSortButton("✨", "skills", "Skills")}
                    </th>
                    <th class="results-col-target-kills">
                        ${renderSortButton("🎯", "target_kills", "Target entities killed")}
                    </th>
                    <th class="results-col-all-kills">
                        ${renderSortButton("☠️", "all_kills", "All entities killed")}
                    </th>
                    <th class="results-col-pvp">
                        ${renderSortButton("⚔️", "pvp", "PvP wins")}
                    </th>
                    <th class="results-col-inventory">
                        ${renderSortButton("🎒", "inventory", "Mini inventory")}
                    </th>
                </tr>
            </thead>

            <tbody>
                ${sortedPlayers.map((player, index) => `
    <tr class="results-row ${isPlayerUncredited(player) ? "results-row-uncredited" : "results-row-credited"}">
                        <td class="results-rank-cell">${player?.result_rank ?? (index + 1)}</td>
                        <td class="results-number-cell">
    ${getTreasureValue(player)}
    ${isPlayerUncredited(player)
        ? `<div class="results-uncredited-note">uncredited</div>`
        : ""}
    ${getRawTreasureValue(player) !== getTreasureValue(player)
        ? `<div class="results-raw-note">carried: ${getRawTreasureValue(player)}</div>`
        : ""}
</td>
                        <td class="results-icon-cell">${renderPlayerIcon(player)}</td>
                        <td>
                            <div class="results-player-name">
    ${escapeHtml(player?.display_name || `Player ${getPlayerNr(player)}`)}
</div>
<div class="results-final-status">
    ${escapeHtml(getFinalStatusLabel(player))}
</div>
                        </td>
                        <td>${renderSkillList(player)}</td>
                        <td>${renderEntityKillList(player, {targetOnly: true})}</td>
                        <td>${renderEntityKillList(player)}</td>
                        <td class="results-pvp-cell">${renderPvpStats(player)}</td>
                        <td>${renderMiniInventory(player)}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;

    root.querySelectorAll("[data-sort-key]").forEach(button => {
        button.addEventListener("click", () => {
            toggleSort(button.dataset.sortKey);
        });
    });
}

function updateSubtitle() {
    const subtitle = document.getElementById("results-subtitle");

    if (!subtitle) {
        return;
    }

    const status = latestResults?.result?.status || "game_over";
    const mode =
        latestResults?.result?.end_condition?.mode ||
        latestResults?.end_condition?.mode ||
        "unknown";

    subtitle.textContent = `Status: ${status} | End condition: ${mode}`;
}

async function loadResults() {
    const r = await fetch(`${API_BASE}/results/state`);
    const data = await r.json();

    if (!r.ok) {
        throw new Error(data?.detail || "Failed to load results.");
    }

    latestResults = data;

    updateSubtitle();
    renderResultsTable();

    showMessage("Results loaded.", "info", "Info");
}

async function restartToBootstrap() {
    const r = await fetch(`${API_BASE}/results/restart_to_bootstrap`, {
        method: "POST",
    });

    const data = await r.json();

    if (!r.ok) {
        throw new Error(data?.detail || "Failed to restart.");
    }

    window.location.href = karakPath(data?.redirect_to || "/phase1");
}

document.addEventListener("DOMContentLoaded", async () => {
    const restartBtn = document.getElementById("restart-btn");

    if (restartBtn) {
        restartBtn.addEventListener("click", async () => {
            try {
                await restartToBootstrap();
            } catch (e) {
                console.error("restart failed:", e);
                showMessage(String(e), "warning", "Warning");
            }
        });
    }

    try {
        await loadResults();
    } catch (e) {
        console.error("loadResults failed:", e);
        showMessage(String(e), "warning", "Warning");
    }
});
