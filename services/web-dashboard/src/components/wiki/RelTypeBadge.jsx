const REL_TYPE_STYLES = {
    TRANSITIONS_TO: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    DEPENDS_ON:     'bg-amber-100 text-amber-800 border-amber-200',
    CALLS:          'bg-blue-100 text-blue-800 border-blue-200',
    MAPS_TO:        'bg-violet-100 text-violet-800 border-violet-200',
    GOVERNS:        'bg-rose-100 text-rose-800 border-rose-200',
    TRIGGERS:       'bg-orange-100 text-orange-800 border-orange-200',
    HANDLES_ERROR:  'bg-red-100 text-red-800 border-red-200',
    DEFINED_BY:     'bg-sky-100 text-sky-800 border-sky-200',
    RELATED_TO:     'bg-slate-100 text-slate-600 border-slate-200',
};

export default function RelTypeBadge({ type }) {
    const style = REL_TYPE_STYLES[type] ?? REL_TYPE_STYLES.RELATED_TO;
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style}`}>
            {type ?? 'RELATED_TO'}
        </span>
    );
}
