import { FileSearch, Inbox, AlertTriangle } from 'lucide-react';

const VARIANT_CONFIG = {
  default: {
    Icon: Inbox,
    iconClass: 'text-zinc-300',
    bgClass: 'bg-zinc-50',
  },
  'no-results': {
    Icon: FileSearch,
    iconClass: 'text-zinc-300',
    bgClass: 'bg-zinc-50',
  },
  error: {
    Icon: AlertTriangle,
    iconClass: 'text-rose-400',
    bgClass: 'bg-rose-50',
  },
};

export default function EmptyState({
  variant = 'default',
  icon: IconOverride,
  title,
  description,
  action,
  className = '',
}) {
  const cfg = VARIANT_CONFIG[variant] ?? VARIANT_CONFIG.default;
  const Icon = IconOverride ?? cfg.Icon;

  return (
    <div className={`flex flex-col items-center justify-center py-16 px-6 text-center ${className}`}>
      <div className={`w-14 h-14 rounded-full ${cfg.bgClass} flex items-center justify-center mb-4`}>
        <Icon size={24} className={cfg.iconClass} />
      </div>
      {title && (
        <p className="text-sm font-semibold text-zinc-700 mb-1" style={{ fontFamily: 'Outfit, sans-serif' }}>
          {title}
        </p>
      )}
      {description && (
        <p className="text-xs text-zinc-400 max-w-xs leading-relaxed">{description}</p>
      )}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
