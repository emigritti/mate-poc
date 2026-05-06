import { Skeleton } from './skeleton.jsx';

export function SkeletonCard() {
  return (
    <div className="bg-white rounded-xl border border-zinc-200 p-5 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <Skeleton className="h-4 w-2/3 bg-zinc-100" />
        <Skeleton className="h-5 w-16 rounded-full bg-zinc-100" />
      </div>
      <Skeleton className="h-3 w-1/2 bg-zinc-100" />
      <div className="flex gap-2 pt-1">
        <Skeleton className="h-5 w-14 rounded-full bg-zinc-100" />
        <Skeleton className="h-5 w-18 rounded-full bg-zinc-100" />
      </div>
      <div className="flex items-center justify-between pt-2 border-t border-zinc-100">
        <Skeleton className="h-3 w-24 bg-zinc-100" />
        <Skeleton className="h-7 w-20 rounded-lg bg-zinc-100" />
      </div>
    </div>
  );
}

export function SkeletonCardGrid({ count = 6 }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {Array.from({ length: count }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
    </div>
  );
}
