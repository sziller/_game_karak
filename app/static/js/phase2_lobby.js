let latestLobbyState = null;
let latestCharacterCatalog = [];
let selectedLobbyPlayerId = null;

// Arrow-step class selector state.
let selectedClassIndexByPlayerId = {};

const KARAK_BASE_URL = window.KARAK_BASE_URL || "";

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

    const staticBase = window.KARAK_STATIC_URL || `${KARAK_BASE_URL}/static`;
    const normalized = String(path).replace(/^\/+/, "");

    if (normalized.startsWith("static/")) {
        return `${staticBase}/${normalized.slice("static/".length)}`;
    }
    if (normalized.startsWith("media/")) {
        return `${staticBase}/${normalized}`;
    }

    return karakPath(path);
}

function showMessage(kind, title, content) {
    const box = document.getElementById("message-box");
    const titleEl = document.getElementById("message-title");
    const contentEl = document.getElementById("message-content");

    if (!box || !titleEl || !contentEl) return;

    box.classList.remove("message-info", "message-warning", "message-error");
    box.classList.add(`message-${kind}`);

    titleEl.textContent = title;
    contentEl.textContent = content || "";
}

async function apiJson(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        ...options,
    });

    let data = null;

    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }

    if (!response.ok) {
        const detail = data?.detail || `HTTP ${response.status}`;
        throw new Error(detail);
    }

    return data;
}

async function loadLobby() {
    const [stateRes, catalogRes] = await Promise.all([
        apiJson(karakPath("/api/lobby/state")),
        apiJson(karakPath("/api/lobby/character_catalog")),
    ]);

    latestLobbyState = stateRes.lobby_state;
    latestCharacterCatalog = catalogRes.classes || [];

    if (!selectedLobbyPlayerId && latestLobbyState.players?.length) {
        selectedLobbyPlayerId = latestLobbyState.players[0].player_id;
    }

    renderLobby();
}

function getSelectedPlayer() {
    return (latestLobbyState?.players || []).find(p => p.player_id === selectedLobbyPlayerId) || null;
}

function getTakenProfessions() {
    const taken = new Set();

    for (const p of latestLobbyState?.players || []) {
        if (p.profession) {
            taken.add(p.profession);
        }
    }

    return taken;
}

function renderLobby() {
    if (!assertUniqueLobbyPlayerIds()) {
        return;
    }

    renderSessionLabel();
    renderPlayers();
    renderClassCard();
    renderConfigEditor();
    updateStartButton();
}

function renderSessionLabel() {
    const el = document.getElementById("lobby-session-label");
    if (!el || !latestLobbyState) return;

    el.textContent = `Session: ${latestLobbyState.session_id} | Admin: ${latestLobbyState.admin_name}`;
}

function renderPlayers() {
    const box = document.getElementById("lobby-player-list");
    if (!box) return;

    const players = [...(latestLobbyState?.players || [])].reverse();

    box.innerHTML = "";

    for (const player of players) {
        const row = document.createElement("div");
        row.className = "lobby-player-row";

        if (player.player_id === selectedLobbyPlayerId) {
            row.classList.add("selected");
        }

        if (!player.profession) {
            row.classList.add("missing-profession");
        }

        row.onclick = () => {
            selectedLobbyPlayerId = player.player_id;
            syncClassIndexAfterLobbyChange(player.player_id);
            renderLobby();
        };

        const colorDot = document.createElement("div");
        colorDot.className = "lobby-color-dot";
        colorDot.style.backgroundColor = player.color || "#555";

        const name = document.createElement("div");
        name.className = "lobby-player-name";
        name.textContent = player.display_name || player.player_id;

        const profession = document.createElement("div");
        profession.className = "lobby-player-profession";
        profession.textContent = player.profession || "no profession";

        const removeBtn = document.createElement("button");
        removeBtn.className = "lobby-remove-btn";
        removeBtn.textContent = "Remove";
        removeBtn.onclick = async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();

            const removedPlayerId = player.player_id;
            const removedPlayerName = player.display_name;

            try {
                const res = await apiJson(karakPath(`/api/lobby/remove_player/${encodeURIComponent(removedPlayerId)}`), {
                    method: "POST",
                });

                latestLobbyState = res.lobby_state;

                // Remove stale carousel state for deleted player.
                delete selectedClassIndexByPlayerId[removedPlayerId];

                // If the currently selected player was removed, choose a valid remaining player.
                const stillExists = (latestLobbyState.players || []).some(
                    p => p.player_id === selectedLobbyPlayerId
                );

                if (!stillExists) {
                    selectedLobbyPlayerId = latestLobbyState.players?.at(-1)?.player_id || null;
                }

                if (selectedLobbyPlayerId) {
                    syncClassIndexAfterLobbyChange(selectedLobbyPlayerId);
                }

                renderLobby();
                showMessage("info", "Player removed", removedPlayerName);
            } catch (err) {
                showMessage("error", "Remove failed", err.message);
            }
        };

        row.appendChild(colorDot);
        row.appendChild(name);
        row.appendChild(profession);
        row.appendChild(removeBtn);

        box.appendChild(row);
    }
}

function renderClassCard() {
    const box = document.getElementById("lobby-class-card");
    if (!box) return;

    const player = getSelectedPlayer();

    if (!player) {
        box.innerHTML = `<div class="muted">Add or select a player first.</div>`;
        return;
    }

    const availableClasses = getAvailableClassesForPlayer(player);

    if (!availableClasses.length) {
        box.innerHTML = `
            <div class="muted">
                No available professions left for this player.
            </div>
        `;
        return;
    }

    let currentIndex = selectedClassIndexByPlayerId[player.player_id];

    if (typeof currentIndex !== "number") {
        const ownProfessionIndex = availableClasses.findIndex(
            cls => cls.profession === player.profession
        );

        currentIndex = ownProfessionIndex >= 0 ? ownProfessionIndex : 0;
        selectedClassIndexByPlayerId[player.player_id] = currentIndex;
    }

    if (currentIndex < 0) currentIndex = 0;
    if (currentIndex >= availableClasses.length) currentIndex = availableClasses.length - 1;

    selectedClassIndexByPlayerId[player.player_id] = currentIndex;

    const selectedClass = availableClasses[currentIndex];
    if (!selectedClass) {
    selectedClassIndexByPlayerId[player.player_id] = 0;
    renderClassCard();
    return;
}
    const selectedProfession = selectedClass.profession;

    const imgPath = karakStaticAsset(
        selectedClass?.image_path ||
        selectedClass?.portrait_path ||
        selectedClass?.tableau_path ||
        ""
    );

    const displayName =
        selectedClass?.character_name ||
        selectedClass?.name ||
        selectedClass?.profession ||
        "Unknown";

    const skillNames = getClassSkillDisplay(selectedClass);

    box.innerHTML = `
        <div class="class-carousel-header">
            <button id="class-prev-btn" class="class-arrow-btn">&lt;</button>

            <div class="class-title-box">
                <div class="class-title">${escapeHtml(displayName)}</div>
                <div class="class-subtitle">${escapeHtml(selectedProfession)}</div>
            </div>

            <button id="class-next-btn" class="class-arrow-btn">&gt;</button>
        </div>

        <div class="class-image-box">
            ${
        imgPath
            ? `<img class="class-image-img" src="${escapeHtml(imgPath)}" alt="">`
            : `<span class="muted">No class image</span>`
    }
        </div>

        <div class="class-info">
            <b>${escapeHtml(player.display_name)}</b><br>
            Current: ${escapeHtml(player.profession || "none")}<br>
            Candidate: ${escapeHtml(selectedProfession)}<br>
            Color: ${escapeHtml(player.color || "none")}<br>
            ${skillNames ? `Skills: ${escapeHtml(skillNames)}` : ""}
        </div>

        <button id="assign-profession-btn" class="class-assign-btn">
            Assign profession
        </button>
    `;

    const prevBtn = document.getElementById("class-prev-btn");
    const nextBtn = document.getElementById("class-next-btn");
    const assignBtn = document.getElementById("assign-profession-btn");

    if (prevBtn) {
        prevBtn.disabled = availableClasses.length <= 1;
        prevBtn.onclick = () => {
            stepSelectedClass(player.player_id, availableClasses.length, -1);
        };
    }

    if (nextBtn) {
        nextBtn.disabled = availableClasses.length <= 1;
        nextBtn.onclick = () => {
            stepSelectedClass(player.player_id, availableClasses.length, 1);
        };
    }

    if (assignBtn) {
        assignBtn.disabled = player.profession === selectedProfession;

        assignBtn.onclick = async () => {
            try {
                const res = await apiJson(karakPath("/api/lobby/assign_profession"), {
                    method: "POST",
                    body: JSON.stringify({
                        player_id: player.player_id,
                        profession: selectedProfession,
                    }),
                });

                latestLobbyState = res.lobby_state;

                // Keep the selector coherent after filtering changes.
                syncClassIndexAfterLobbyChange(player.player_id);

                renderLobby();
                showMessage("info", "Profession assigned", `${player.display_name} -> ${selectedProfession}`);
            } catch (err) {
                showMessage("error", "Profession assignment failed", err.message);
            }
        };
    }
}

function getAvailableClassesForPlayer(player) {
    const taken = getTakenProfessions();

    return latestCharacterCatalog.filter(cls => {
        const profession = cls.profession;
        if (!profession) return false;

        // The player's own profession must stay visible,
        // otherwise the carousel would lose its current assignment.
        if (profession === player.profession) return true;

        // Professions assigned to other players disappear.
        return !taken.has(profession);
    });
}

function stepSelectedClass(playerId, total, delta) {
    if (!total) return;

    const current = selectedClassIndexByPlayerId[playerId] || 0;
    const next = (current + delta + total) % total;

    selectedClassIndexByPlayerId[playerId] = next;
    renderClassCard();
}

function syncClassIndexAfterLobbyChange(playerId) {
    const player = (latestLobbyState?.players || []).find(p => p.player_id === playerId);

    if (!player) {
        delete selectedClassIndexByPlayerId[playerId];
        return;
    }

    const availableClasses = getAvailableClassesForPlayer(player);

    if (!availableClasses.length) {
        selectedClassIndexByPlayerId[playerId] = 0;
        return;
    }

    // Prefer showing the player's already assigned profession.
    if (player.profession) {
        const ownProfessionIndex = availableClasses.findIndex(
            cls => cls.profession === player.profession
        );

        if (ownProfessionIndex >= 0) {
            selectedClassIndexByPlayerId[playerId] = ownProfessionIndex;
            return;
        }
    }

    // Otherwise clamp current index into the valid range.
    let currentIndex = selectedClassIndexByPlayerId[playerId];

    if (typeof currentIndex !== "number") {
        currentIndex = 0;
    }

    if (currentIndex < 0) {
        currentIndex = 0;
    }

    if (currentIndex >= availableClasses.length) {
        currentIndex = availableClasses.length - 1;
    }

    selectedClassIndexByPlayerId[playerId] = currentIndex;
}

function getClassSkillDisplay(cls) {
    if (!cls) return "";

    const rawSkills =
        cls.skills ||
        cls.skill_ids ||
        cls.skill_names ||
        [];

    if (!Array.isArray(rawSkills)) return "";

    return rawSkills.join(", ");
}

function renderConfigEditor() {
    const box = document.getElementById("config-editor");
    if (!box) return;

    const config = latestLobbyState?.runtime_config || {};
    box.innerHTML = "";

    for (const [topKey, value] of Object.entries(config)) {
        const group = document.createElement("div");
        group.className = "config-group";

        const title = document.createElement("div");
        title.className = "config-group-title";
        title.textContent = topKey;

        const body = document.createElement("div");
        body.className = "config-group-body";

        renderConfigNode(body, [topKey], value);

        group.appendChild(title);
        group.appendChild(body);
        box.appendChild(group);
    }
}

function renderConfigNode(parent, path, value) {
    if (isPlainObject(value)) {
        for (const [key, childValue] of Object.entries(value)) {
            const childPath = [...path, key];

            if (isPlainObject(childValue)) {
                const subgroup = document.createElement("div");
                subgroup.className = "config-group";

                const title = document.createElement("div");
                title.className = "config-group-title";
                title.textContent = childPath.join(".");

                const body = document.createElement("div");
                body.className = "config-group-body";

                renderConfigNode(body, childPath, childValue);

                subgroup.appendChild(title);
                subgroup.appendChild(body);
                parent.appendChild(subgroup);
            } else {
                parent.appendChild(createConfigRow(childPath, childValue));
            }
        }
    } else {
        parent.appendChild(createConfigRow(path, value));
    }
}

function createConfigRow(path, value) {
    const row = document.createElement("div");
    row.className = "config-row";

    const label = document.createElement("label");
    label.className = "config-label";
    label.textContent = path.slice(1).join(".");

    const input = createConfigInput(path, value);

    row.appendChild(label);
    row.appendChild(input);

    return row;
}

function createConfigInput(path, value) {
    const pathStr = path.join(".");

    let input;

    if (typeof value === "boolean") {
        input = document.createElement("input");
        input.type = "checkbox";
        input.checked = value;
        input.className = "config-input";
        input.dataset.configPath = pathStr;
        input.dataset.configType = "boolean";
        return input;
    }

    if (typeof value === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.value = String(value);
        input.className = "config-input";
        input.dataset.configPath = pathStr;
        input.dataset.configType = Number.isInteger(value) ? "integer" : "float";
        return input;
    }

    if (typeof value === "string") {
        input = document.createElement("input");
        input.type = "text";
        input.value = value;
        input.className = "config-input";
        input.dataset.configPath = pathStr;
        input.dataset.configType = "string";
        return input;
    }

    // Arrays and mixed structures stay editable as JSON.
    input = document.createElement("textarea");
    input.value = JSON.stringify(value, null, 2);
    input.className = "config-input config-json-textarea";
    input.dataset.configPath = pathStr;
    input.dataset.configType = "json";
    return input;
}

function collectRuntimeConfigFromEditor() {
    const original = structuredClone(latestLobbyState?.runtime_config || {});
    const fields = document.querySelectorAll("[data-config-path]");

    for (const field of fields) {
        const path = field.dataset.configPath.split(".");
        const type = field.dataset.configType;

        let value;

        if (type === "boolean") {
            value = field.checked;
        } else if (type === "integer") {
            value = parseInt(field.value, 10);
            if (Number.isNaN(value)) {
                throw new Error(`Invalid integer at ${path.join(".")}`);
            }
        } else if (type === "float") {
            value = parseFloat(field.value);
            if (Number.isNaN(value)) {
                throw new Error(`Invalid float at ${path.join(".")}`);
            }
        } else if (type === "json") {
            try {
                value = JSON.parse(field.value);
            } catch (err) {
                throw new Error(`Invalid JSON at ${path.join(".")}: ${err.message}`);
            }
        } else {
            value = field.value;
        }

        setNestedValue(original, path, value);
    }

    return original;
}

function setNestedValue(obj, path, value) {
    let cur = obj;

    for (let i = 0; i < path.length - 1; i++) {
        const key = path[i];

        if (!cur[key] || typeof cur[key] !== "object") {
            cur[key] = {};
        }

        cur = cur[key];
    }

    cur[path[path.length - 1]] = value;
}

function isPlainObject(value) {
    return (
        value !== null &&
        typeof value === "object" &&
        !Array.isArray(value)
    );
}

async function addPlayerFromInput() {
    const input = document.getElementById("player-name-input");
    const name = input?.value?.trim();

    if (!name) {
        showMessage("warning", "Missing player name", "Enter a display name first.");
        return;
    }

    try {
        const res = await apiJson(karakPath("/api/lobby/add_hotseat_player"), {
            method: "POST",
            body: JSON.stringify({
                display_name: name,
            }),
        });

        latestLobbyState = res.lobby_state;

        const newPlayer = latestLobbyState.players?.at(-1) || null;

        if (newPlayer) {
            selectedLobbyPlayerId = newPlayer.player_id;
            selectedClassIndexByPlayerId[newPlayer.player_id] = 0;
            syncClassIndexAfterLobbyChange(newPlayer.player_id);
        }

        input.value = "";

        renderLobby();
        showMessage("info", "Player added", name);
    } catch (err) {
        showMessage("error", "Add player failed", err.message);
    }
}

function updateStartButton() {
    const btn = document.getElementById("start-game-btn");
    if (!btn) return;

    const players = latestLobbyState?.players || [];
    const canStart = players.length >= 1 && players.every(p => Boolean(p.profession));

    btn.disabled = !canStart;
}

async function startGameFromLobby() {
    try {
        const runtimeConfig = collectRuntimeConfigFromEditor();

        const res = await apiJson(karakPath("/api/lobby/start_game"), {
            method: "POST",
            body: JSON.stringify({
                runtime_config: runtimeConfig,
            }),
        });

        if (res.redirect_to) {
            window.location.href = karakPath(res.redirect_to);
            return;
        }

        showMessage("info", "Game started", JSON.stringify(res, null, 2));
    } catch (err) {
        showMessage("error", "Start game failed", err.message);
    }
}

async function resetToPhase1() {
    try {
        const res = await apiJson(karakPath("/api/lobby/reset_to_phase1"), {
            method: "POST",
        });

        if (res.redirect_to) {
            window.location.href = karakPath(res.redirect_to);
            return;
        }

        showMessage("info", "Reset", "Returned to Phase 1.");
    } catch (err) {
        showMessage("error", "Reset failed", err.message);
    }
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

document.addEventListener("DOMContentLoaded", async () => {
    document.getElementById("add-player-btn")?.addEventListener("click", addPlayerFromInput);

    document.getElementById("player-name-input")?.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
            addPlayerFromInput();
        }
    });

    document.getElementById("start-game-btn")?.addEventListener("click", startGameFromLobby);
    document.getElementById("back-to-phase1-btn")?.addEventListener("click", resetToPhase1);

    try {
        await loadLobby();
        showMessage("info", "Lobby ready", "Add players, assign professions, edit rules, then start.");
    } catch (err) {
        showMessage("error", "Lobby load failed", err.message);
    }
});

function assertUniqueLobbyPlayerIds() {
    const players = latestLobbyState?.players || [];
    const ids = players.map(p => p.player_id);
    const duplicates = ids.filter((id, index) => ids.indexOf(id) !== index);

    if (duplicates.length) {
        console.error("Duplicate lobby player IDs detected:", duplicates, players);
        showMessage(
            "error",
            "Lobby identity error",
            `Duplicate player IDs detected: ${[...new Set(duplicates)].join(", ")}`
        );
        return false;
    }

    return true;
}
