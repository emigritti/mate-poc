const ENTITY_TYPE_STYLES = {
    system:        'bg-blue-100 text-blue-800 border-blue-200',
    api_entity:    'bg-violet-100 text-violet-800 border-violet-200',
    business_term: 'bg-amber-100 text-amber-800 border-amber-200',
    state:         'bg-emerald-100 text-emerald-800 border-emerald-200',
    rule:          'bg-rose-100 text-rose-800 border-rose-200',
    field:         'bg-sky-100 text-sky-800 border-sky-200',
    process:       'bg-indigo-100 text-indigo-800 border-indigo-200',
    generic:       'bg-slate-100 text-slate-600 border-slate-200',
};

export default function EntityTypeBadge({ type }) {
    const style = ENTITY_TYPE_STYLES[type] ?? ENTITY_TYPE_STYLES.generic;
    return (
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border ${style}`}>
            {type ?? 'generic'}
        </span>
    );
}
