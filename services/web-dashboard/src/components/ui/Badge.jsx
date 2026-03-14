const VARIANTS = {
  primary: 'bg-indigo-100 text-indigo-700 border-indigo-200',
  success: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  warning: 'bg-amber-100 text-amber-700 border-amber-200',
  error:   'bg-rose-100 text-rose-700 border-rose-200',
  info:    'bg-blue-100 text-blue-700 border-blue-200',
  slate:   'bg-slate-100 text-slate-600 border-slate-200',
};

const DOT_COLORS = {
  primary: 'bg-indigo-500',
  success: 'bg-emerald-500',
  warning: 'bg-amber-500',
  error:   'bg-rose-500',
  info:    'bg-blue-500',
  slate:   'bg-slate-400',
};

export default function Badge({ children, variant = 'slate', dot = false }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
        VARIANTS[variant] ?? VARIANTS.slate
      }`}
    >
      {dot && (
        <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${DOT_COLORS[variant] ?? DOT_COLORS.slate}`} />
      )}
      {children}
    </span>
  );
}
