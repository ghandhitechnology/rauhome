/**
 * Loading placeholders.
 *
 * These reuse the `.skeleton` / `.skeleton-line` shimmer already defined in
 * `index.css` — the point of this file is not a new visual, it is that the
 * *shapes* stop being written as one-off inline styles at each call site. A
 * skeleton whose dimensions do not match the content it stands in for causes
 * exactly the layout jump it was added to prevent, so the shapes live next to
 * each other here where they can be kept honest.
 */

type SkeletonProps = {
  /** Any CSS width. Defaults to filling the container. */
  w?: string
  /** Any CSS height. */
  h?: string
  /** Space above, so callers do not need a wrapper just for rhythm. */
  mt?: string
  className?: string
}

export function Skeleton({ w, h, mt, className }: SkeletonProps) {
  return (
    <div
      className={className ? `skeleton ${className}` : 'skeleton'}
      style={{ width: w, height: h, marginTop: mt }}
      aria-hidden="true"
    />
  )
}

/**
 * A run of text lines with a short last line, the way a real paragraph ends.
 * Uniform-width bars read as a table, not prose.
 */
export function SkeletonText({ lines = 3, mt }: { lines?: number; mt?: string }) {
  return (
    <div style={{ marginTop: mt }} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div
          key={i}
          className="skeleton skeleton-line"
          style={{ width: i === lines - 1 ? '55%' : '100%' }}
        />
      ))}
    </div>
  )
}

/**
 * A panel-shaped block: heading bar, then a body of the given height. This is
 * the unit almost every route is built from.
 */
export function SkeletonPanel({
  headW = '35%',
  bodyH = '12rem',
  className,
}: {
  headW?: string
  bodyH?: string
  className?: string
}) {
  return (
    <section className={className ? `panel ${className}` : 'panel'}>
      <Skeleton className="skeleton-line" w={headW} h="1.6rem" />
      <Skeleton h={bodyH} mt="1.2rem" />
    </section>
  )
}
