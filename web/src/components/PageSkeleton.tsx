import { Skeleton, SkeletonPanel } from './Skeleton'
import { normalizePath } from '../routes'
import { tr } from '../i18n'
import './PageSkeleton.css'

/**
 * Route-shaped loading states.
 *
 * These replace what used to be the full-screen boot splash ("Rau / waking
 * up") whenever a lazy chunk was still in flight. That splash is honest for a
 * cold start and misleading for a 60ms module fetch: it throws away the topbar
 * and nav the user is already looking at, then throws them back.
 *
 * Each shape mirrors the real route's container and panel count so the swap to
 * live content does not move anything. When a route's layout changes, its
 * shape here has to change with it — that is the cost of not jumping.
 */

function DashboardSkeleton() {
  return (
    <div className="dash grid-2 page-skeleton">
      <SkeletonPanel bodyH="9rem" />
      <SkeletonPanel bodyH="9rem" />
    </div>
  )
}

function TwoPanelSkeleton({ bodyH }: { bodyH: string }) {
  return (
    <div className="grid-2 page-skeleton">
      <SkeletonPanel bodyH={bodyH} />
      <SkeletonPanel bodyH={bodyH} />
    </div>
  )
}

function OperationsSkeleton() {
  return (
    <div className="operations page-skeleton">
      <div className="ops-head">
        <div>
          <Skeleton className="skeleton-line" w="10rem" h="2rem" />
          <Skeleton className="skeleton-line" w="18rem" h="0.9rem" mt="0.7rem" />
        </div>
      </div>
      {/* Mirrors the real page: one full-width job-plans panel, then the
          two-column schedule/approvals grid beneath it. */}
      <SkeletonPanel headW="8rem" bodyH="7rem" className="ops-wide" />
      <div className="ops-grid">
        <SkeletonPanel bodyH="18rem" />
        <SkeletonPanel bodyH="18rem" />
      </div>
    </div>
  )
}

/**
 * Just the message bubbles. Talk renders its hero and composer immediately —
 * both are usable before any history arrives — so only the thread needs to
 * stand in for something. Exported for `Conversation` to use directly while
 * its first `api.log()` is in flight, which stops the page claiming "Say
 * something" to a user who has a month of history.
 */
export function ThreadSkeleton() {
  return (
    // Alternating sides so the shape reads as a conversation, not a list.
    <div className="convo-skeleton-thread page-skeleton" role="status" aria-live="polite">
      <span className="sr-only">{tr('skeleton.loadingThread')}</span>
      <Skeleton className="convo-skeleton-bubble left" h="3.2rem" w="62%" />
      <Skeleton className="convo-skeleton-bubble right" h="2.4rem" w="45%" />
      <Skeleton className="convo-skeleton-bubble left" h="4.6rem" w="74%" />
    </div>
  )
}

function ConversationSkeleton() {
  return (
    <div className="convo-skeleton page-skeleton">
      <div className="convo-skeleton-hero">
        <Skeleton className="skeleton-line" w="9rem" h="3.4rem" />
        <Skeleton className="skeleton-line" w="14rem" h="0.9rem" mt="0.9rem" />
      </div>
      <div className="convo-skeleton-thread">
        <Skeleton className="convo-skeleton-bubble left" h="3.2rem" w="62%" />
        <Skeleton className="convo-skeleton-bubble right" h="2.4rem" w="45%" />
        <Skeleton className="convo-skeleton-bubble left" h="4.6rem" w="74%" />
      </div>
      <Skeleton className="convo-skeleton-compose" h="3.1rem" />
    </div>
  )
}

function SetupSkeleton() {
  return (
    <div className="page-skeleton setup-skeleton">
      <SkeletonPanel headW="45%" bodyH="18rem" />
    </div>
  )
}

/**
 * `/face` and `/pet` own the whole viewport and render a canvas rather than
 * panels. A shimmering placeholder there would be a bright flash before a very
 * dark scene, so they get the room's own background and nothing else.
 */
function CanvasSkeleton() {
  return <div className="canvas-skeleton" />
}

export default function PageSkeleton({ pathname }: { pathname: string }) {
  const path = normalizePath(pathname)
  let shape
  switch (path) {
    case '/':
      shape = <ConversationSkeleton />
      break
    case '/dashboard':
      shape = <DashboardSkeleton />
      break
    case '/operations':
      shape = <OperationsSkeleton />
      break
    case '/identity':
      shape = <TwoPanelSkeleton bodyH="16rem" />
      break
    case '/settings':
      shape = <TwoPanelSkeleton bodyH="12rem" />
      break
    case '/setup':
      shape = <SetupSkeleton />
      break
    case '/face':
    case '/pet':
      shape = <CanvasSkeleton />
      break
    default:
      shape = <TwoPanelSkeleton bodyH="12rem" />
  }

  return (
    <div role="status" aria-live="polite" aria-busy="true">
      <span className="sr-only">{tr('skeleton.loading')}</span>
      {shape}
    </div>
  )
}
