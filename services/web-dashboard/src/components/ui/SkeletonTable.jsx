import { Skeleton } from './skeleton.jsx';

export function SkeletonRow({ cols = 4 }) {
  const widths = ['w-2/5', 'w-1/4', 'w-1/5', 'w-1/6', 'w-1/3'];
  return (
    <div className="flex items-center gap-4 px-4 py-3.5 border-b border-zinc-100">
      {Array.from({ length: cols }).map((_, i) => (
        <Skeleton
          key={i}
          className={`h-3.5 bg-zinc-100 flex-shrink-0 ${widths[i % widths.length]}`}
        />
      ))}
    </div>
  );
}

export function SkeletonTable({ rows = 5, cols = 4 }) {
  return (
    <div className="bg-white rounded-xl border border-zinc-200 overflow-hidden">
      {/* header row */}
      <div className="flex gap-4 px-4 py-3 border-b border-zinc-200 bg-zinc-50">
        {Array.from({ length: cols }).map((_, i) => (
          <Skeleton key={i} className={`h-3 bg-zinc-200 ${i === 0 ? 'w-2/5' : 'w-1/5'}`} />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} cols={cols} />
      ))}
    </div>
  );
}
