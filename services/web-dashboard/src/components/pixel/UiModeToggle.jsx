/**
 * UiModeToggle — Toggle between Classic and Pixel UI modes (ADR-047).
 * Rendered in TopBar (classic mode) and PixelSidebar (pixel mode).
 */
import { Tv, Monitor } from 'lucide-react';
import { useUiMode } from '../../context/UiModeContext';

export default function UiModeToggle() {
  const { mode, setMode } = useUiMode();

  if (mode === 'pixel') {
    return (
      <button
        onClick={() => setMode('classic')}
        title="Switch to Classic mode"
        className="pixel-button w-full justify-center"
        style={{ fontSize: '6px' }}
      >
        <Monitor size={11} />
        &gt; CLASSIC
      </button>
    );
  }

  return (
    <button
      onClick={() => setMode('pixel')}
      title="Switch to Commodore 64 mode"
      className="flex items-center justify-center gap-1.5 w-full px-3 py-1.5 rounded-lg text-xs font-semibold
                 border border-zinc-700 text-zinc-500 hover:border-sky-500
                 hover:text-sky-400 transition-colors"
    >
      <Tv size={13} />
      C-64 Mode
    </button>
  );
}
