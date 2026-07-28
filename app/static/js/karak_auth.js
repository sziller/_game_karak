// ============================================================
// Karak frontend auth/request helpers
// ============================================================
// Feature code should call karakFetch(...). In SHMC, this adapter delegates to
// the central browser auth object. Outside SHMC, it keeps a local-dev fallback.

(function () {
    "use strict";

    const TOKEN_STORAGE_KEY = "karak.jwt";

    function getSHMCAuth() {
        return window.SHMCAuth || null;
    }

    function isCentralHostedMode() {
        return String(window.KARAK_DEPLOYMENT_MODE || "").trim() === "central_hosted";
    }

    function centralAuthBootstrapMissing() {
        return isCentralHostedMode() && !getSHMCAuth();
    }

    function normalizeJwtToken(token) {
        const value = String(token || "").trim();
        if (!value) {
            return "";
        }
        return value.replace(/^Bearer\s+/i, "").trim();
    }

    function removeLocalFallbackToken() {
        try {
            window.localStorage.removeItem(TOKEN_STORAGE_KEY);
        } catch (_) {
            // Storage may be disabled.
        }
    }

    function getStoredKarakJwt() {
        const shmcAuth = getSHMCAuth();
        if (shmcAuth && typeof shmcAuth.getAccessToken === "function") {
            return normalizeJwtToken(shmcAuth.getAccessToken());
        }
        if (shmcAuth && typeof shmcAuth.getToken === "function") {
            return normalizeJwtToken(shmcAuth.getToken());
        }

        if (typeof window.KARAK_JWT === "string" && window.KARAK_JWT.trim()) {
            return normalizeJwtToken(window.KARAK_JWT);
        }

        if (typeof window.KARAK_LOCAL_DEV_JWT === "string" && window.KARAK_LOCAL_DEV_JWT.trim()) {
            if (isCentralHostedMode()) {
                return "";
            }
            return normalizeJwtToken(window.KARAK_LOCAL_DEV_JWT);
        }

        if (isCentralHostedMode()) {
            return "";
        }

        try {
            return normalizeJwtToken(window.localStorage.getItem(TOKEN_STORAGE_KEY));
        } catch (_) {
            return "";
        }
    }

    function setStoredKarakJwt(token) {
        const normalized = normalizeJwtToken(token);
        const shmcAuth = getSHMCAuth();

        if (shmcAuth && typeof shmcAuth.setAccessToken === "function") {
            shmcAuth.setAccessToken(normalized);
            removeLocalFallbackToken();
            window.KARAK_JWT = normalized;
            return;
        }
        if (shmcAuth && typeof shmcAuth.setToken === "function") {
            shmcAuth.setToken(normalized);
            removeLocalFallbackToken();
            window.KARAK_JWT = normalized;
            return;
        }

        try {
            if (normalized) {
                window.localStorage.setItem(TOKEN_STORAGE_KEY, normalized);
            } else {
                window.localStorage.removeItem(TOKEN_STORAGE_KEY);
            }
        } catch (_) {
            // Storage may be disabled. Keep the API safe for local/manual testing.
        }

        window.KARAK_JWT = normalized;
    }

    function clearStoredKarakJwt() {
        const shmcAuth = getSHMCAuth();
        if (shmcAuth && typeof shmcAuth.clearAccessToken === "function") {
            shmcAuth.clearAccessToken();
            removeLocalFallbackToken();
            window.KARAK_JWT = "";
            window.KARAK_LOCAL_DEV_JWT = "";
            return;
        }
        if (shmcAuth && typeof shmcAuth.clearToken === "function") {
            shmcAuth.clearToken();
            removeLocalFallbackToken();
            window.KARAK_JWT = "";
            window.KARAK_LOCAL_DEV_JWT = "";
            return;
        }

        window.KARAK_LOCAL_DEV_JWT = "";
        setStoredKarakJwt("");
    }

    function hasStoredKarakJwt() {
        return Boolean(getStoredKarakJwt());
    }

    function withParticipantTokenHeader(init) {
        const nextInit = {
            ...(init || {}),
        };
        const headers = new Headers(nextInit.headers || {});
        const gameContext = window.KarakGameContext?.get?.() || null;
        const participantToken = gameContext?.participant_token || "";
        const participantHeader = window.KarakGameContext?.participantTokenHeader || "X-Karak-Participant-Token";
        if (participantToken && !headers.has(participantHeader)) {
            headers.set(participantHeader, participantToken);
        }
        nextInit.headers = headers;
        return nextInit;
    }

    function requestMethod(init) {
        return String(init?.method || "GET").toUpperCase();
    }

    function isGameScopedLobbyMutation(input, init) {
        const method = requestMethod(init);
        if (method === "GET" || method === "HEAD" || method === "OPTIONS") {
            return false;
        }
        const url = typeof input === "string" ? input : String(input?.url || "");
        return (
            /\/api\/games\/[^/]+\/lobby\//.test(url) ||
            /\/api\/games\/[^/]+\/(?:leave|close)$/.test(url)
        );
    }

    function isGameScopedGameplayMutation(input, init) {
        const method = requestMethod(init);
        if (method === "GET" || method === "HEAD" || method === "OPTIONS") {
            return false;
        }
        const url = typeof input === "string" ? input : String(input?.url || "");
        return /\/api\/games\/[^/]+\/game\//.test(url);
    }

    function commandKey(input, init) {
        const url = typeof input === "string" ? input : String(input?.url || "");
        return `${requestMethod(init)} ${url} ${String(init?.body || "")}`;
    }

    const inFlightGameplayMutations = new Set();

    function withExpectedRevisionHeader(input, init) {
        const nextInit = {
            ...(init || {}),
        };
        if (!isGameScopedLobbyMutation(input, nextInit) && !isGameScopedGameplayMutation(input, nextInit)) {
            return nextInit;
        }

        const revision = window.KarakGameContext?.getLastRevision?.();
        if (revision === null || revision === undefined) {
            throw new Error("Missing authoritative Karak revision.");
        }

        const headers = new Headers(nextInit.headers || {});
        const revisionHeader = window.KarakGameContext?.expectedRevisionHeader || "X-Karak-Expected-Revision";
        if (!headers.has(revisionHeader)) {
            headers.set(revisionHeader, String(revision));
        }
        nextInit.headers = headers;
        return nextInit;
    }

    async function notifyGameplayMutationFailure(input, init, response) {
        if (!isGameScopedGameplayMutation(input, init)) {
            return;
        }
        if (response.status !== 409 && response.status !== 403) {
            return;
        }
        if (typeof window.karakHandleGameplayMutationFailure !== "function") {
            return;
        }
        try {
            await window.karakHandleGameplayMutationFailure(response.clone());
        } catch (_) {
            // Command callers still receive the original response.
        }
    }

    async function updateRevisionFromResponse(response) {
        const method = String(response?.url || "");
        if (!method || !window.KarakGameContext?.setLastRevision) {
            return response;
        }
        if (!response?.ok || response.status === 204) {
            return response;
        }
        try {
            const clone = response.clone();
            const data = await clone.json();
            if (Number.isInteger(data?.revision) && data.revision >= 0) {
                window.KarakGameContext.setLastRevision(data.revision);
            }
        } catch (_) {
            // Not every successful response is JSON or contains a revision.
        }
        return response;
    }

    function buildShmcLoginUrl() {
        const currentPath = `${window.location.pathname}${window.location.search}`;
        const next = currentPath || `${window.KARAK_BASE_URL || ""}/` || "/";
        return `/auth/login.html?next=${encodeURIComponent(next)}`;
    }

    function requireShmcLogin() {
        if (centralAuthBootstrapMissing()) {
            window.KARAK_AUTH_BOOTSTRAP_ERROR = "Central Karak authentication bootstrap is unavailable.";
            return false;
        }

        const shmcAuth = getSHMCAuth();

        if (shmcAuth && typeof shmcAuth.isAuthenticated === "function") {
            if (shmcAuth.isAuthenticated()) {
                return true;
            }
            window.location.href = buildShmcLoginUrl();
            return false;
        }

        if (hasStoredKarakJwt()) {
            return true;
        }

        window.location.href = buildShmcLoginUrl();
        return false;
    }

    async function karakFetch(input, init) {
        const nextInit = withExpectedRevisionHeader(input, withParticipantTokenHeader(init));
        const gameplayMutation = isGameScopedGameplayMutation(input, nextInit);
        const gameplayMutationKey = gameplayMutation ? commandKey(input, nextInit) : "";
        if (gameplayMutation && inFlightGameplayMutations.has(gameplayMutationKey)) {
            throw new Error("Karak command is already in flight.");
        }
        if (gameplayMutation) {
            inFlightGameplayMutations.add(gameplayMutationKey);
        }
        const shmcAuth = getSHMCAuth();
        try {
            if (shmcAuth && typeof shmcAuth.fetch === "function") {
                const response = await shmcAuth.fetch(input, nextInit);
                await notifyGameplayMutationFailure(input, nextInit, response);
                return updateRevisionFromResponse(response);
            }

            const token = getStoredKarakJwt();

            const headers = new Headers(nextInit.headers || {});

            if (token && !headers.has("Authorization")) {
                headers.set("Authorization", `Bearer ${token}`);
            }

            nextInit.headers = headers;
            const response = await window.fetch(input, nextInit);
            await notifyGameplayMutationFailure(input, nextInit, response);
            return updateRevisionFromResponse(response);
        } finally {
            if (gameplayMutation) {
                inFlightGameplayMutations.delete(gameplayMutationKey);
            }
        }
    }

    window.KarakAuth = {
        tokenStorageKey: TOKEN_STORAGE_KEY,
        getToken: getStoredKarakJwt,
        setToken: setStoredKarakJwt,
        clearToken: clearStoredKarakJwt,
        hasToken: hasStoredKarakJwt,
        requireLogin: requireShmcLogin,
        buildLoginUrl: buildShmcLoginUrl,
        fetch: karakFetch,
        isGameScopedGameplayMutation,
    };

    window.karakGetJwtToken = getStoredKarakJwt;
    window.karakSetJwtToken = setStoredKarakJwt;
    window.karakClearJwtToken = clearStoredKarakJwt;
    window.karakHasJwtToken = hasStoredKarakJwt;
    window.karakRequireShmcLogin = requireShmcLogin;
    window.karakBuildShmcLoginUrl = buildShmcLoginUrl;
    window.karakFetch = karakFetch;
}());
