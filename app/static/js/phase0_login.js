// ============================================================
// Karak sign-in page backed by SHMC browser auth.
// ============================================================

const KARAK_BASE_URL = window.KARAK_BASE_URL || "";
const KARAK_AUTH_LOGIN_URL =
    window.KARAK_AUTH_LOGIN_URL || "/app/auth/api/login";

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

function showMessage(msg, level = "info", title = null) {
    const box = document.getElementById("message-box");
    const titleEl = document.getElementById("message-title");
    const content = document.getElementById("message-content");

    if (!box || !titleEl || !content) {
        return;
    }

    box.classList.remove("message-info", "message-error");
    box.classList.add(level === "error" ? "message-error" : "message-info");
    titleEl.textContent = title || (level === "error" ? "Error" : "Info");
    content.textContent = msg;
}

function getTokenPreview(token) {
    if (!token) {
        return "";
    }
    if (token.length <= 24) {
        return token;
    }
    return `${token.slice(0, 12)}...${token.slice(-8)}`;
}

function refreshTokenStatus() {
    const status = document.getElementById("token-status");
    if (!status) {
        return;
    }

    const token = karakGetJwtToken();
    if (!token) {
        status.textContent = "Not signed in. API requests will be sent without Authorization.";
        return;
    }

    status.textContent = `Signed in. Token preview: ${getTokenPreview(token)}`;
}

function getAuthErrorMessage(response, data) {
    if (data && typeof data.detail === "string") {
        return data.detail;
    }
    if (data && Array.isArray(data.detail)) {
        return data.detail.map((item) => item.msg || JSON.stringify(item)).join("\n");
    }
    return `Login failed with HTTP ${response.status}.`;
}

async function loginWithPassword() {
    const usernameInput = document.getElementById("login-username");
    const passwordInput = document.getElementById("login-password");
    const usernameOrEmail = usernameInput ? usernameInput.value.trim() : "";
    const password = passwordInput ? passwordInput.value : "";

    if (!usernameOrEmail || !password) {
        showMessage("Username/email and password are required.", "error");
        return;
    }

    showMessage("Logging in...", "info");

    let data = null;

    try {
        if (window.SHMCAuth && typeof window.SHMCAuth.login === "function") {
            data = await window.SHMCAuth.login(usernameOrEmail, password, {
                loginUrl: KARAK_AUTH_LOGIN_URL,
            });
        } else {
            const response = await window.fetch(KARAK_AUTH_LOGIN_URL, {
                method: "POST",
                headers: {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    username_or_email: usernameOrEmail,
                    password,
                }),
            });

            try {
                data = await response.json();
            } catch (_) {
                data = null;
            }

            if (!response.ok) {
                showMessage(getAuthErrorMessage(response, data), "error", "Login failed");
                return;
            }
        }
    } catch (error) {
        const response = error && error.response ? error.response : null;
        const payload = error && error.payload ? error.payload : null;
        if (response) {
            showMessage(getAuthErrorMessage(response, payload), "error", "Login failed");
            return;
        }
        showMessage(
            `Could not reach auth endpoint. ${error.message || error}`,
            "error",
            "Login failed",
        );
        return;
    }

    if (!data || !data.access_token) {
        showMessage("Auth response did not include access_token.", "error", "Login failed");
        return;
    }

    karakSetJwtToken(data.access_token);
    if (passwordInput) {
        passwordInput.value = "";
    }
    refreshTokenStatus();

    const claims = data.claims || {};
    const username = claims.username || claims.email || usernameOrEmail;
    const projects = Array.isArray(claims.projects) ? claims.projects.join(", ") : "unknown projects";
    showMessage(`Login successful for ${username}. Projects: ${projects}.`);
}

function saveToken() {
    const input = document.getElementById("token-input");
    const token = input ? input.value.trim() : "";

    if (!token) {
        showMessage("Paste a JWT before saving.", "error");
        return;
    }

    karakSetJwtToken(token);
    if (input) {
        input.value = "";
    }
    refreshTokenStatus();
    showMessage("Token saved. Future API requests will include Authorization: Bearer <JWT>.");
}

function showStoredToken() {
    const input = document.getElementById("token-input");
    if (!input) {
        return;
    }

    input.value = karakGetJwtToken();
    showMessage("Stored token copied into the input field for inspection or replacement.");
}

function clearToken() {
    karakClearJwtToken();
    const input = document.getElementById("token-input");
    if (input) {
        input.value = "";
    }
    refreshTokenStatus();
    showMessage("Token cleared. API requests will be sent without Authorization.");
}

function continueToPhase1() {
    window.location.href = karakPath("/phase1");
}

document.getElementById("save-token-btn")?.addEventListener("click", saveToken);
document.getElementById("login-btn")?.addEventListener("click", loginWithPassword);
document.getElementById("show-token-btn")?.addEventListener("click", showStoredToken);
document.getElementById("clear-token-btn")?.addEventListener("click", clearToken);
document.getElementById("continue-btn")?.addEventListener("click", continueToPhase1);

document.getElementById("auth-login-url-label").textContent = KARAK_AUTH_LOGIN_URL;
refreshTokenStatus();
