/**
 * UiModeContext — Global UI mode switch (ADR-047).
 *
 * Supported modes: "classic" | "pixel"
 * Persisted to localStorage under key "ui_mode".
 *
 * Usage:
 *   const { mode, setMode } = useUiMode();
 */
import { createContext, useContext, useState } from 'react';

const UiModeContext = createContext({ mode: 'classic', setMode: () => {} });

export function UiModeProvider({ children }) {
  const [mode, setModeState] = useState(
    () => localStorage.getItem('ui_mode') || 'classic',
  );

  const setMode = (m) => {
    setModeState(m);
    localStorage.setItem('ui_mode', m);
  };

  return (
    <UiModeContext.Provider value={{ mode, setMode }}>
      <div className={mode === 'pixel' ? 'pixel-mode h-full' : 'h-full'}>
        {children}
      </div>
    </UiModeContext.Provider>
  );
}

/** Returns { mode, setMode } */
export function useUiMode() {
  return useContext(UiModeContext);
}
