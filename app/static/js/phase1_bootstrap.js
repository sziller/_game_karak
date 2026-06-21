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


// ============================================================
// Bootstrap state handling
// ============================================================

function setStatus(data) {
    // Diagnostics UI was intentionally removed from bootstrap HTML.
    // Keep the state visible in the browser console for debugging.
    console.log("Bootstrap state:", data);
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

        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        showError("Failed to start hot-seat session.");
    }
}

async function startHost() {
    clearError();

    const player_name = document.getElementById("host-name").value.trim() || "Host";
    const bind_url = document.getElementById("host-url").value.trim() || null;

    try {
        const r = await karakFetch(bootstrapApi("/host"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ player_name, bind_url })
        });

        const data = await r.json();
        setStatus(data);

        if (!r.ok) {
            showError(data.detail || "Failed to start host session.");
            return;
        }

        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        showError("Failed to start host session.");
    }
}

async function joinHost() {
    clearError();

    const player_name = document.getElementById("join-name").value.trim() || "Guest";
    const server_url = document.getElementById("join-url").value.trim();
    const room_code = document.getElementById("join-room").value.trim() || null;

    if (!server_url) {
        showError("Server URL is required.");
        return;
    }

    try {
        const r = await karakFetch(bootstrapApi("/join"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ player_name, server_url, room_code })
        });

        const data = await r.json();
        setStatus(data);

        if (!r.ok) {
            showError(data.detail || "Failed to join session.");
            return;
        }

        window.location.href = karakPath("/phase2");
    } catch (e) {
        console.error(e);
        showError("Failed to join session.");
    }
}


// ============================================================
// Initial load
// ============================================================

if (karakRequireShmcLogin()) {
    refreshState();
}
