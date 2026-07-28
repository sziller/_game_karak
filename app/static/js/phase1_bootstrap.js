// ============================================================
// Phase 1 Bootstrap logic
// ============================================================

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

const bootstrapApi = (p) => karakPath("/api/bootstrap" + (p.startsWith("/") ? p : "/" + p));
const gamesApi = (p = "") => karakPath("/api/games" + (p ? (p.startsWith("/") ? p : "/" + p) : ""));


// ============================================================
// Message helpers
// ============================================================

function showMessage(msg, level = "info", title = null) {
    const box = document.getElementById("message-box");
    const titleEl = document.getElementById("message-title");
    const content = document.getElementById("message-content");

    if (!box || !titleEl || !content) {
        console.error("Message box elements not found.");
        return;
    }

    box.classList.remove("message-info", "message-error");

    if (level === "error") {
        box.classList.add("message-error");
        titleEl.textContent = title || "Error";
    } else {
        box.classList.add("message-info");
        titleEl.textContent = title || "Info";
    }

    content.textContent = msg;
}

function showError(msg) {
    showMessage(msg, "error", "Error");
}

function clearError() {
    showMessage("(ready)", "info", "Info");
}

function setButtonBusy(button, busy) {
    if (!button) return;
    button.disabled = Boolean(busy);
}

async function parseApiResponse(response) {
    let data = null;
    try {
        data = await response.json();
    } catch (_) {
        data = null;
    }
    if (!response.ok) {
        const detail = data?.detail || `HTTP ${response.status}`;
        const message = typeof detail === "object" ? (detail.message || JSON.stringify(detail)) : detail;
        throw new Error(message);
    }
    return data;
}

function storeCreatedGameContext(data) {
    karakSetGameContext(data.game_id, data.participant_token);
    if (Number.isInteger(data?.revision)) {
        karakSetLastRevision(data.revision);
    }
}


// ============================================================
// Bootstrap state handling
// ============================================================

function setStatus(data) {
    // Diagnostics UI was intentionally removed from bootstrap HTML.
    // Keep non-secret state visible in the browser console for debugging.
    const safeData = data && typeof data === "object" ? {...data} : data;
    if (safeData && typeof safeData === "object" && "participant_token" in safeData) {
        safeData.participant_token = "[redacted]";
    }
    console.log("Bootstrap state:", safeData);
}

async function refreshState() {
    clearError();

    try {
        const r = await karakFetch(bootstrapApi("/state"));
        const data = await r.json();

        setStatus(data);

        if (!r.ok) {
            showError(data.detail || "Failed to refresh bootstrap state.");
        }
    } catch (e) {
        console.error(e);
        showError("Failed to refresh bootstrap state.");
    }
}


// ============================================================
// Bootstrap actions
// ============================================================

async function startHotseat() {
    clearError();

    try {
        karakClearGameContext();
        const r = await karakFetch(bootstrapApi("/hotseat"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ player_name: "Local Admin" })
        });

        const data = await r.json();
        setStatus(data);

        if (!r.ok) {
            showError(data.detail || "Failed to start hot-seat session.");
            return;
        }

        karakSetGameContext(data.game_id, data.participant_token);
        if (Number.isInteger(data?.revision)) {
            karakSetLastRevision(data.revision);
        }
        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        showError("Failed to start hot-seat session.");
    }
}

async function startHost() {
    clearError();

    const button = document.getElementById("host-submit-btn");
    const display_name = document.getElementById("host-name").value.trim() || "Host";

    try {
        karakClearGameContext();
        setButtonBusy(button, true);
        const r = await karakFetch(gamesApi(), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                participation_mode: "multiplayer",
                display_name,
            })
        });

        const data = await parseApiResponse(r);
        setStatus(data);

        storeCreatedGameContext(data);
        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        karakClearGameContext();
        showError(e.message || "Failed to create multiplayer lobby.");
    } finally {
        setButtonBusy(button, false);
    }
}

async function joinHost() {
    clearError();

    const button = document.getElementById("join-submit-btn");
    const display_name = document.getElementById("join-name").value.trim() || "Guest";
    const room_code = document.getElementById("join-room").value.trim();

    if (!room_code) {
        showError("Room code is required.");
        return;
    }

    try {
        setButtonBusy(button, true);
        const r = await karakFetch(gamesApi("/join"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ display_name, room_code })
        });

        const data = await parseApiResponse(r);
        setStatus(data);

        storeCreatedGameContext(data);
        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        showError(e.message || "Failed to join multiplayer lobby.");
    } finally {
        setButtonBusy(button, false);
    }
}

function applyJoinQuery() {
    const params = new URLSearchParams(window.location.search);
    const roomCode = params.get("join");
    if (!roomCode) {
        return;
    }
    const joinRoom = document.getElementById("join-room");
    const joinName = document.getElementById("join-name");
    if (joinRoom) {
        joinRoom.value = roomCode.trim().toUpperCase();
    }
    if (joinName) {
        joinName.focus();
    }
}


// ============================================================
// Initial load
// ============================================================

if (karakRequireShmcLogin()) {
    applyJoinQuery();
    refreshState();
}
