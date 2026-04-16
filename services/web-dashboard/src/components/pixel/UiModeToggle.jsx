/**
 * UiModeToggle — Toggle between Classic and Pixel UI modes (ADR-047).
 * Rendered in TopBar (classic mode) and PixelSidebar (pixel mode).
 */
import { Gamepad2, Monitor } from 'lucide-react';
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
        Classic Mode
      </button>
    );
  }

  return (
    <button
      onClick={() => setMode('pixel')}
      title="Switch to 8-bit Pixel mode"
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold
                 border border-slate-200 text-slate-600 hover:border-indigo-400
                 hover:text-indigo-600 transition-colors"
    >
      <Gamepad2 size={13} />
      Pixel
    </button>
  );
}
