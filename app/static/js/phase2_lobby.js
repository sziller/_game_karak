let latestLobbyState = null;
let latestLobbyProjection = null;
let latestCharacterCatalog = [];
let selectedLobbyPlayerId = null;
let lobbyPollTimer = null;
let lobbyPollInFlight = false;
let lobbyPollErrorCount = 0;
let lobbyPollStarted = false;
let startGameInFlight = false;

const LOBBY_POLL_INTERVAL_MS = 1000;
const LOBBY_POLL_MAX_BACKOFF_MS = 8000;

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

function lobbyApi(path) {
    return karakPath(karakGameScopedApiPath("lobby", path));
}

function gameApi(path) {
    const context = karakRequireGameContext();
    if (!context) {
        return "";
    }
    return karakPath(`/api/games/${encodeURIComponent(context.game_id)}${path.startsWith("/") ? path : `/${path}`}`);
}

function lobbyStateApi(sinceRevision = null) {
    if (sinceRevision === null || sinceRevision === undefined) {
        return karakPath(karakGameStateApiPath());
    }
    return karakPath(karakGameStateApiPath(`since_revision=${encodeURIComponent(sinceRevision)}`));
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
    const response = await karakFetch(url, {
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
        const message = typeof detail === "object" ? (detail.message || JSON.stringify(detail)) : detail;
        const err = new Error(message);
        err.status = response.status;
        err.currentRevision = data?.current_revision ?? data?.detail?.current_revision ?? null;
        throw err;
    }

    return data;
}

async function fetchLobbyProjection({ sinceRevision = null } = {}) {
    const response = await karakFetch(lobbyStateApi(sinceRevision));

    if (response.status === 204) {
        return null;
    }

    let data = null;
    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }

    if (!response.ok) {
        const detail = data?.detail || `HTTP ${response.status}`;
        const message = typeof detail === "object" ? (detail.message || JSON.stringify(detail)) : detail;
        const err = new Error(message);
        err.status = response.status;
        throw err;
    }

    return data;
}

function applyLobbyProjection(projection) {
    if (!projection) {
        return false;
    }
    const currentRevision = karakGetLastRevision();
    if (currentRevision !== null && projection.revision < currentRevision) {
        return false;
    }

    latestLobbyProjection = projection;
    latestLobbyState = projection.lobby || {};
    karakSetLastRevision(projection.revision);

    if (!selectedLobbyPlayerId && latestLobbyState.players?.length) {
        selectedLobbyPlayerId = latestLobbyState.players[0].player_id;
    }

    const stillExists = (latestLobbyState.players || []).some(p => p.player_id === selectedLobbyPlayerId);
    if (!stillExists) {
        selectedLobbyPlayerId = latestLobbyState.players?.[0]?.player_id || null;
    }

    if (selectedLobbyPlayerId) {
        syncClassIndexAfterLobbyChange(selectedLobbyPlayerId);
    }

    return true;
}

async function loadLobby({ sinceRevision = null, render = true } = {}) {
    const projection = await fetchLobbyProjection({ sinceRevision });
    const changed = applyLobbyProjection(projection);

    if (!projection || !changed) {
        return changed;
    }

    if (handleLobbyLifecycle(projection)) {
        return changed;
    }

    const catalogRes = await apiJson(lobbyApi("/character_catalog"));
    latestCharacterCatalog = catalogRes.classes || [];

    if (render && changed) {
        renderLobby();
    }

    return changed;
}

function handleLobbyLifecycle(projection) {
    const lifecycle = projection?.lifecycle;
    if (lifecycle === "in_game") {
        stopLobbyPolling();
        window.location.href = karakPath("/phase3");
        return true;
    }
    if (lifecycle === "results") {
        stopLobbyPolling();
        window.location.href = karakPath("/phase4");
        return true;
    }
    if (lifecycle === "closed") {
        stopLobbyPolling();
        karakClearGameContext();
        showMessage("warning", "Game closed", "This game is no longer available.");
        window.setTimeout(() => {
            window.location.href = karakPath("/phase1");
        }, 1200);
        return true;
    }
    if (lifecycle === "faulted") {
        stopLobbyPolling();
        showMessage("error", "Game faulted", "This game cannot continue.");
        return true;
    }
    return false;
}

async function reloadAuthoritativeLobby(message = null) {
    const changed = await loadLobby({ render: true });
    if (message) {
        showMessage("warning", "Lobby refreshed", message);
    }
    return changed;
}

async function mutateLobby(url, options = {}) {
    try {
        const result = await apiJson(url, options);
        if (Number.isInteger(result?.revision)) {
            karakSetLastRevision(result.revision);
        }
        await loadLobby({ render: true });
        return result;
    } catch (err) {
        if (err.status === 409) {
            await reloadAuthoritativeLobby("Your lobby view was stale. Review the refreshed state and try again.");
        }
        throw err;
    }
}

async function finalGameMutation(url, options = {}) {
    try {
        return await apiJson(url, options);
    } catch (err) {
        if (err.status === 409) {
            await reloadAuthoritativeLobby("Your lobby view was stale. Review the refreshed state and try again.");
        }
        throw err;
    }
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
    renderParticipationBar();
    renderParticipants();
    renderPlayers();
    renderClassCard();
    renderConfigEditor();
    updateStartButton();
    updateLobbyControls();
}

function isMultiplayerLobby() {
    return latestLobbyProjection?.participation_mode === "multiplayer";
}

function currentPermissions() {
    return latestLobbyProjection?.permissions || {};
}

function buildJoinUrl() {
    const roomCode = latestLobbyProjection?.room_code;
    if (!roomCode) {
        return "";
    }
    const basePath = window.KARAK_BASE_URL || "";
    const prefix = basePath.replace(/\/+$/, "");
    const advertisedOrigin = String(window.KARAK_ADVERTISED_ORIGIN || "").replace(/\/+$/, "");
    const origin = advertisedOrigin || window.location.origin;
    return `${origin}${prefix}/phase1?join=${encodeURIComponent(roomCode)}`;
}

async function copyJoinUrl() {
    const joinUrl = buildJoinUrl();
    if (!joinUrl) {
        return;
    }
    try {
        await navigator.clipboard.writeText(joinUrl);
        showMessage("info", "Join URL copied", joinUrl);
    } catch (_) {
        const field = document.getElementById("join-url-output");
        if (field) {
            field.focus();
            field.select();
        }
        showMessage("warning", "Copy manually", "Select and copy the join URL.");
    }
}

async function leaveLobby() {
    try {
        const confirmed = window.confirm("Leave this lobby?");
        if (!confirmed) return;
        const res = await finalGameMutation(gameApi("/leave"), {method: "POST"});
        stopLobbyPolling();
        karakClearGameContext();
        showMessage("info", "Left lobby", res?.game_id || "");
        window.location.href = karakPath("/phase1");
    } catch (err) {
        showMessage("error", "Leave failed", err.message);
    }
}

async function closeLobby() {
    try {
        const confirmed = window.confirm("Close this game for every participant?");
        if (!confirmed) return;
        const res = await finalGameMutation(gameApi("/close"), {method: "POST"});
        stopLobbyPolling();
        karakClearGameContext();
        showMessage("info", "Game closed", res?.game_id || "");
        window.location.href = karakPath("/phase1");
    } catch (err) {
        showMessage("error", "Close failed", err.message);
    }
}

function renderParticipationBar() {
    const box = document.getElementById("lobby-participation-bar");
    if (!box || !latestLobbyProjection) return;

    const permissions = currentPermissions();
    const self = latestLobbyProjection.self || {};
    const joinUrl = buildJoinUrl();

    box.innerHTML = "";

    const details = document.createElement("div");
    details.className = "lobby-participation-details";

    const selfLabel = `${self.display_name || "Participant"}${self.is_host ? " (host)" : ""}`;
    details.innerHTML = `
        <span>Mode: ${escapeHtml(latestLobbyProjection.participation_mode)}</span>
        <span>Lifecycle: ${escapeHtml(latestLobbyProjection.lifecycle)}</span>
        <span>You: ${escapeHtml(selfLabel)}</span>
        <span>Revision: ${escapeHtml(latestLobbyProjection.revision)}</span>
    `;
    box.appendChild(details);

    if (isMultiplayerLobby() && latestLobbyProjection.room_code) {
        const joinRow = document.createElement("div");
        joinRow.className = "lobby-join-row";
        joinRow.innerHTML = `
            <span>Room: <b>${escapeHtml(latestLobbyProjection.room_code)}</b></span>
            <input id="join-url-output" readonly value="${escapeHtml(joinUrl)}">
            <button id="copy-join-url-btn" type="button">Copy</button>
        `;
        box.appendChild(joinRow);
        document.getElementById("copy-join-url-btn")?.addEventListener("click", copyJoinUrl);
    }

    const actions = document.createElement("div");
    actions.className = "lobby-participation-actions";
    if (permissions.can_leave) {
        const leaveBtn = document.createElement("button");
        leaveBtn.id = "leave-lobby-btn";
        leaveBtn.type = "button";
        leaveBtn.textContent = "Leave";
        leaveBtn.addEventListener("click", leaveLobby);
        actions.appendChild(leaveBtn);
    }
    if (permissions.can_close) {
        const closeBtn = document.createElement("button");
        closeBtn.id = "close-lobby-btn";
        closeBtn.type = "button";
        closeBtn.textContent = "Close Game";
        closeBtn.addEventListener("click", closeLobby);
        actions.appendChild(closeBtn);
    }
    if (actions.children.length) {
        box.appendChild(actions);
    }
}

function participantById(participantId) {
    return (latestLobbyProjection?.participants || []).find(p => p.participant_id === participantId) || null;
}

function participantOwnedSeatLabels(participant) {
    const playerById = new Map((latestLobbyState?.players || []).map(p => [p.player_id, p]));
    const owned = participant?.owned_player_ids || [];
    if (!owned.length) {
        return "unassigned";
    }
    return owned.map(playerId => playerById.get(playerId)?.display_name || playerId).join(", ");
}

function renderParticipants() {
    const box = document.getElementById("participant-list");
    if (!box || !latestLobbyProjection) return;

    box.innerHTML = "";
    const title = document.createElement("div");
    title.className = "participant-list-title";
    title.textContent = "Participants";
    box.appendChild(title);

    for (const participant of latestLobbyProjection.participants || []) {
        const row = document.createElement("div");
        row.className = "participant-row";
        const markers = [];
        if (participant.is_host) markers.push("host");
        if (participant.participant_id === latestLobbyProjection.self?.participant_id) markers.push("you");
        row.innerHTML = `
            <div class="participant-name">${escapeHtml(participant.display_name)} ${markers.length ? `<span>${escapeHtml(markers.join(", "))}</span>` : ""}</div>
            <div class="participant-seats">${escapeHtml(participantOwnedSeatLabels(participant))}</div>
        `;
        box.appendChild(row);
    }
}

function renderSessionLabel() {
    const el = document.getElementById("lobby-session-label");
    if (!el || !latestLobbyState) return;

    const mode = latestLobbyProjection?.participation_mode || latestLobbyState.mode || "hotseat";
    const revision = latestLobbyProjection?.revision ?? karakGetLastRevision();
    el.textContent = `Session: ${latestLobbyProjection?.game_id || latestLobbyState.session_id} | Mode: ${mode} | Revision: ${revision}`;
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

        const owner = document.createElement("div");
        owner.className = "lobby-player-owner";
        owner.textContent = player.owner_display_name ? `Owner: ${player.owner_display_name}` : "Unassigned";

        const removeBtn = document.createElement("button");
        removeBtn.className = "lobby-remove-btn";
        removeBtn.textContent = "Remove";
        removeBtn.disabled = !latestLobbyProjection?.permissions?.can_remove_player;
        removeBtn.onclick = async (ev) => {
            ev.preventDefault();
            ev.stopPropagation();

            const removedPlayerId = player.player_id;
            const removedPlayerName = player.display_name;

            try {
                await mutateLobby(lobbyApi(`/remove_player/${encodeURIComponent(removedPlayerId)}`), {
                    method: "POST",
                });

                // Remove stale carousel state for deleted player.
                delete selectedClassIndexByPlayerId[removedPlayerId];

                showMessage("info", "Player removed", removedPlayerName);
            } catch (err) {
                showMessage("error", "Remove failed", err.message);
            }
        };

        row.appendChild(colorDot);
        row.appendChild(name);
        row.appendChild(profession);
        const seatControls = createSeatControls(player);

        row.appendChild(owner);
        row.appendChild(removeBtn);
        if (seatControls) {
            row.appendChild(seatControls);
        }

        box.appendChild(row);
    }
}

function createSeatControls(player) {
    if (!isMultiplayerLobby()) {
        return null;
    }

    const controls = document.createElement("div");
    controls.className = "seat-controls";
    controls.addEventListener("click", ev => {
        ev.stopPropagation();
    });

    const canAssign = Boolean(currentPermissions().can_assign_seat);
    const canUnassign = Boolean(currentPermissions().can_unassign_seat);

    if (!canAssign && !canUnassign) {
        controls.textContent = player.owner_display_name || "Unassigned";
        return controls;
    }

    const select = document.createElement("select");
    select.className = "seat-owner-select";
    select.disabled = Boolean(player.owner_participant_id) || !canAssign;

    const empty = document.createElement("option");
    empty.value = "";
    empty.textContent = "Assign to...";
    select.appendChild(empty);

    for (const participant of latestLobbyProjection?.participants || []) {
        const option = document.createElement("option");
        option.value = participant.participant_id;
        option.textContent = participant.display_name + (participant.is_host ? " (host)" : "");
        select.appendChild(option);
    }

    const assignBtn = document.createElement("button");
    assignBtn.type = "button";
    assignBtn.textContent = "Assign";
    assignBtn.disabled = Boolean(player.owner_participant_id) || !canAssign;
    assignBtn.onclick = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const participantId = select.value;
        if (!participantId) {
            showMessage("warning", "No participant selected", "Choose a participant before assigning.");
            return;
        }
        try {
            await mutateLobby(lobbyApi(`/seats/${encodeURIComponent(player.player_id)}/assign`), {
                method: "POST",
                body: JSON.stringify({participant_id: participantId}),
            });
            const target = participantById(participantId);
            showMessage("info", "Seat assigned", `${player.display_name} -> ${target?.display_name || participantId}`);
        } catch (err) {
            showMessage("error", "Seat assignment failed", err.message);
        }
    };

    const unassignBtn = document.createElement("button");
    unassignBtn.type = "button";
    unassignBtn.textContent = "Unassign";
    unassignBtn.disabled = !player.owner_participant_id || !canUnassign;
    unassignBtn.onclick = async (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        try {
            await mutateLobby(lobbyApi(`/seats/${encodeURIComponent(player.player_id)}/unassign`), {
                method: "POST",
            });
            showMessage("info", "Seat unassigned", player.display_name);
        } catch (err) {
            showMessage("error", "Seat unassignment failed", err.message);
        }
    };

    controls.appendChild(select);
    controls.appendChild(assignBtn);
    controls.appendChild(unassignBtn);
    return controls;
}

function renderClassCard() {
    const box = document.getElementById("lobby-class-card");
    if (!box) return;

    const player = getSelectedPlayer();

    if (!player) {
        box.innerHTML = `<div class="muted">Add or select a player first.</div>`;
        return;
    }

    if (!currentPermissions().can_assign_profession) {
        box.classList.add("readonly");
    } else {
        box.classList.remove("readonly");
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
        assignBtn.disabled = player.profession === selectedProfession || !latestLobbyProjection?.permissions?.can_assign_profession;

        assignBtn.onclick = async () => {
            try {
                await mutateLobby(lobbyApi("/assign_profession"), {
                    method: "POST",
                    body: JSON.stringify({
                        player_id: player.player_id,
                        profession: selectedProfession,
                    }),
                });

                // Keep the selector coherent after filtering changes.
                syncClassIndexAfterLobbyChange(player.player_id);

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
        input.disabled = !latestLobbyProjection?.permissions?.can_configure;
        return input;
    }

    if (typeof value === "number") {
        input = document.createElement("input");
        input.type = "number";
        input.value = String(value);
        input.className = "config-input";
        input.dataset.configPath = pathStr;
        input.dataset.configType = Number.isInteger(value) ? "integer" : "float";
        input.disabled = !latestLobbyProjection?.permissions?.can_configure;
        return input;
    }

    if (typeof value === "string") {
        input = document.createElement("input");
        input.type = "text";
        input.value = value;
        input.className = "config-input";
        input.dataset.configPath = pathStr;
        input.dataset.configType = "string";
        input.disabled = !latestLobbyProjection?.permissions?.can_configure;
        return input;
    }

    // Arrays and mixed structures stay editable as JSON.
    input = document.createElement("textarea");
    input.value = JSON.stringify(value, null, 2);
    input.className = "config-input config-json-textarea";
    input.dataset.configPath = pathStr;
    input.dataset.configType = "json";
    input.disabled = !latestLobbyProjection?.permissions?.can_configure;
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
    if (!currentPermissions().can_add_player) {
        showMessage("error", "Not allowed", "Only the host can add player seats.");
        return;
    }
    const input = document.getElementById("player-name-input");
    const name = input?.value?.trim();

    if (!name) {
        showMessage("warning", "Missing player name", "Enter a display name first.");
        return;
    }

    try {
        await mutateLobby(lobbyApi("/add_hotseat_player"), {
            method: "POST",
            body: JSON.stringify({
                display_name: name,
            }),
        });

        const newPlayer = latestLobbyState.players?.at(-1) || null;

        if (newPlayer) {
            selectedLobbyPlayerId = newPlayer.player_id;
            selectedClassIndexByPlayerId[newPlayer.player_id] = 0;
            syncClassIndexAfterLobbyChange(newPlayer.player_id);
        }

        input.value = "";

        showMessage("info", "Player added", name);
    } catch (err) {
        showMessage("error", "Add player failed", err.message);
    }
}

function updateStartButton() {
    const btn = document.getElementById("start-game-btn");
    if (!btn) return;

    const readiness = latestLobbyProjection?.start_readiness || null;
    const readinessMessages = (readiness?.blocking_reasons || [])
        .map(reason => reason?.message || String(reason || ""))
        .filter(Boolean);
    const canStart = Boolean(latestLobbyProjection?.permissions?.can_start_game);

    btn.disabled = !canStart || startGameInFlight;
    btn.textContent = startGameInFlight ? "Starting..." : "Start game";
    btn.title = readinessMessages.join("\n");

    let readinessBox = document.getElementById("start-readiness-box");
    if (!readinessBox && btn.parentElement) {
        readinessBox = document.createElement("div");
        readinessBox.id = "start-readiness-box";
        readinessBox.className = "lobby-start-readiness";
        btn.parentElement.appendChild(readinessBox);
    }
    if (readinessBox) {
        readinessBox.innerHTML = "";
        if (isMultiplayerLobby() && readinessMessages.length) {
            for (const message of readinessMessages) {
                const line = document.createElement("div");
                line.textContent = message;
                readinessBox.appendChild(line);
            }
        }
    }
}

function updateLobbyControls() {
    const permissions = currentPermissions();
    const addInput = document.getElementById("player-name-input");
    const addButton = document.getElementById("add-player-btn");
    if (addInput) {
        addInput.disabled = !permissions.can_add_player;
    }
    if (addButton) {
        addButton.disabled = !permissions.can_add_player;
    }
}

async function startGameFromLobby() {
    if (startGameInFlight) {
        return;
    }
    startGameInFlight = true;
    updateStartButton();
    try {
        const runtimeConfig = collectRuntimeConfigFromEditor();

        await mutateLobby(lobbyApi("/start_game"), {
            method: "POST",
            body: JSON.stringify({
                runtime_config: runtimeConfig,
            }),
        });
        showMessage("info", "Game started", "Loading gameplay...");
    } catch (err) {
        showMessage("error", "Start game failed", err.message);
    } finally {
        startGameInFlight = false;
        updateStartButton();
    }
}

async function resetToPhase1() {
    try {
        const res = await mutateLobby(lobbyApi("/reset_to_phase1"), {
            method: "POST",
        });

        if (res.redirect_to) {
            karakClearGameContext();
            window.location.href = karakPath(res.redirect_to);
            return;
        }

        showMessage("info", "Reset", "Returned to Phase 1.");
    } catch (err) {
        showMessage("error", "Reset failed", err.message);
    }
}

function scheduleLobbyPoll(delayMs = LOBBY_POLL_INTERVAL_MS) {
    if (!karakGetGameContext()) {
        return;
    }
    if (lobbyPollTimer !== null) {
        window.clearTimeout(lobbyPollTimer);
    }
    lobbyPollTimer = window.setTimeout(runLobbyPoll, delayMs);
}

async function runLobbyPoll() {
    lobbyPollTimer = null;
    if (lobbyPollInFlight || !karakGetGameContext()) {
        scheduleLobbyPoll();
        return;
    }

    const revision = karakGetLastRevision();
    if (revision === null) {
        scheduleLobbyPoll();
        return;
    }

    lobbyPollInFlight = true;
    try {
        const changed = await loadLobby({ sinceRevision: revision, render: true });
        lobbyPollErrorCount = 0;
        scheduleLobbyPoll();
        return changed;
    } catch (err) {
        if (err.status === 401 || err.status === 403 || err.status === 404) {
            stopLobbyPolling();
            karakClearGameContext();
            showMessage("warning", "Lobby unavailable", "The game was closed or your participant session is no longer valid.");
            window.setTimeout(() => {
                window.location.href = karakPath("/phase1");
            }, 1200);
            return false;
        }
        lobbyPollErrorCount += 1;
        const backoff = Math.min(
            LOBBY_POLL_MAX_BACKOFF_MS,
            LOBBY_POLL_INTERVAL_MS * Math.max(1, lobbyPollErrorCount)
        );
        scheduleLobbyPoll(backoff);
        return false;
    } finally {
        lobbyPollInFlight = false;
    }
}

function startLobbyPolling() {
    if (lobbyPollStarted) {
        return;
    }
    lobbyPollStarted = true;
    scheduleLobbyPoll();
}

function stopLobbyPolling() {
    lobbyPollStarted = false;
    lobbyPollInFlight = false;
    if (lobbyPollTimer !== null) {
        window.clearTimeout(lobbyPollTimer);
        lobbyPollTimer = null;
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
    if (!karakRequireShmcLogin()) {
        return;
    }
    if (!karakRequireGameContext()) {
        return;
    }

    document.getElementById("add-player-btn")?.addEventListener("click", addPlayerFromInput);

    document.getElementById("player-name-input")?.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
            addPlayerFromInput();
        }
    });

    document.getElementById("start-game-btn")?.addEventListener("click", startGameFromLobby);
    document.getElementById("back-to-phase1-btn")?.addEventListener("click", resetToPhase1);
    window.addEventListener("beforeunload", stopLobbyPolling);

    try {
        await loadLobby();
        startLobbyPolling();
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
