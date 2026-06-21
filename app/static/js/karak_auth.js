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
            return normalizeJwtToken(window.KARAK_LOCAL_DEV_JWT);
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

    function karakFetch(input, init) {
        const shmcAuth = getSHMCAuth();
        if (shmcAuth && typeof shmcAuth.fetch === "function") {
            return shmcAuth.fetch(input, init);
        }

        const token = getStoredKarakJwt();

        if (!token) {
            return window.fetch(input, init);
        }

        const nextInit = {
            ...(init || {}),
        };
        const headers = new Headers(nextInit.headers || {});

        if (!headers.has("Authorization")) {
            headers.set("Authorization", `Bearer ${token}`);
        }

        nextInit.headers = headers;
        return window.fetch(input, nextInit);
    }

    window.KarakAuth = {
        tokenStorageKey: TOKEN_STORAGE_KEY,
        getToken: getStoredKarakJwt,
        setToken: setStoredKarakJwt,
        clearToken: clearStoredKarakJwt,
        hasToken: hasStoredKarakJwt,
        fetch: karakFetch,
    };

    window.karakGetJwtToken = getStoredKarakJwt;
    window.karakSetJwtToken = setStoredKarakJwt;
    window.karakClearJwtToken = clearStoredKarakJwt;
    window.karakHasJwtToken = hasStoredKarakJwt;
    window.karakFetch = karakFetch;
}());
