import { createContext, useContext, useState, useEffect } from 'react';

/**
 * GlobalLoadingContext — tracks in-flight mutation requests (POST/PUT/DELETE/PATCH).
 *
 * Intercepts window.fetch at mount time. Only mutations are tracked;
 * GET requests and /health polling are excluded to avoid false positives.
 */

const LoadingContext = createContext({ loading: false });

export function useLoading() {
    return useContext(LoadingContext);
}

const MUTATION_METHODS = new Set(['POST', 'PUT', 'DELETE', 'PATCH']);

export function LoadingProvider({ children }) {
    const [count, setCount] = useState(0);

    useEffect(() => {
        const originalFetch = window.fetch;

        window.fetch = function (input, init = {}) {
            const method = (init.method || 'GET').toUpperCase();
            const url = typeof input === 'string' ? input : (input?.url ?? '');
            const isMutation = MUTATION_METHODS.has(method);
            const isHealth   = url.includes('/health');

            if (!isMutation || isHealth) {
                return originalFetch.apply(this, arguments);
            }

            setCount(c => c + 1);

            return originalFetch.apply(this, arguments).finally(() => {
                setCount(c => Math.max(0, c - 1));
            });
        };

        return () => {
            window.fetch = originalFetch;
        };
    }, []);

    return (
        <LoadingContext.Provider value={{ loading: count > 0 }}>
            {children}
        </LoadingContext.Provider>
    );
}
