# Piece art contract

Every file in this folder obeys this. It exists so six pieces drawn separately come
out looking like one set that was turned on one lathe, out of one tree, by one person.

The kittens deck has the same kind of document at `games/kittens/art/SPEC.md`. This
one is stricter, for a reason: thirteen cards can each be their own joke, but a chess
set that does not agree with itself about light, scale and material stops reading as
a set of objects and starts reading as six clip-art files sharing a board.

## Files

| File | Exports |
|---|---|
| `defs.tsx` | `<PieceDefs/>` — one hidden `<svg>` holding every gradient, pattern and filter, plus the stylesheet that drives both finishes. Mounted **once** at the board root. Also the geometry constants and the turning helpers below. |
| `pieces/<id>.tsx` | `export default function Piece()` returning **SVG children only** — no `<svg>` wrapper, no `<defs>`, no ids, no colours. |
| `index.ts` | `ChessPiece`, `PIECE_ART`, `PIECE_HEIGHT`, `PIECE_BASE`, `PIECE_ANCHOR`, `PieceType`, `Finish`. |

## The canvas

- `viewBox="0 0 120 200"`, side elevation.
- The turning axis is **`CX` = 60**. Everything is symmetric about it except the
  knight, which is carved rather than turned and is the deliberate exception.
- The contact line is **`FLOOR` = 196**, and it means the *lowest pixel of the
  footprint* — the near lip of the base disc, not its centre. A base of half-width
  `w` puts its axis at `footY(w)`. Bases differ by eight units across the set, and
  measuring from the centre instead has every piece floating by a different amount.
  The four units below `FLOOR` are for the felt and the contact shadow.
- **`SQUASH` = 0.18.** Every ellipse in the set — base, collar, rim, crenel, felt —
  is squashed by that constant. It is not a taste decision: `clawd/chessTableLayer.ts`
  draws a square 3.45 stage units across and 0.58 deep, so the board is seen at
  roughly six to one. One ellipse at a different squash is a piece photographed with
  a different lens, and it stops standing on the square.
- Pieces are authored **base-down**. The board owns scale and stacking; the art has no
  opinion about how big a square is.

## The look

A carved wooden Staunton set under a warm lamp, seen from a seated player's height.
Not flat icons. Not cartoon characters. Not gradient-mesh realism either — this is
lathe-turned hardwood with tool marks still on it. If a piece would still read
correctly with all of its interior detail deleted, it is not finished.

**Everything turned is turned.** Bodies are built with `revolve()` from a profile of
`Station` points, not drawn as freehand outlines. `revolve` mirrors the profile
exactly, and that exactness is the point: a lathe cannot make an asymmetric turning,
so the character has to come from the profile. A hand-wobbled silhouette does not
read as craft, it reads as a mistake.

## The light

The room's desk lamp is at stage x≈119 and the game table is at x=72, so **the lamp
is up and to the right of every piece on the board.** Get this backwards and
thirty-two pieces are lit from a window on the wrong wall.

- `cw-turn` darkens the left flank, and puts a terminator back on the *right-hand
  rim* — that second darkening is what makes a shape read as round rather than as a
  flat shape with a gradient on it.
- `cw-lacquer` puts its specular at 0.72 of the bounding box. Narrow. Widen it past
  about a fifth of the width and the piece looks wet rather than shellacked.
- Lit facets face right and up; shaded facets face left and down. Never both sides.
- Shadow and highlight are **warm**: `SHADOW` is mixed out of the room's browns and
  `SPECULAR` is `ROOM.dust`. Neutral black over pale maple gives grey, and grey is
  what makes drawn wood read as painted metal.

The knight faces **left**, in both finishes. A mirrored knight needs its whole
lighting pass rebuilt — the lit flank becomes the shaded one — and two knight files
is how a set stops being a set.

## The two finishes

`ChessPiece` sets `data-chess-finish="maple" | "walnut"` on the `<svg>`. The stylesheet
in `defs.tsx` hangs custom properties off that attribute, and **no file under
`pieces/` names a colour or knows which side it is on.** One set of drawings, two woods.

Tones are mixed out of `clawd/palette` (`ROOM`, `CLAWD`, `mixHex`) rather than picked,
so the set stays in the room when the room is retoned. The mixes are pinned by one
constraint: the board's light squares are `mix(woodLit, paper, 0.45)` and its dark
squares are `ROOM.walnut`, so maple must sit clearly **above** the light squares and
walnut clearly **below** the dark ones. A set the same value as the board it stands
on is a set nobody can play on.

## Class names and def ids (from `defs.tsx` — never hardcode a fill)

A piece names a **role**, never a colour:

```
cw-body    the finished surface        cw-grain   the wood grain field
cw-lit     lacquer, and faces          cw-figure  pale streaks in the grain
           turned at the lamp          cw-raw     wood exposed by a chip
cw-shade   the flank turned away       cw-felt    baize
cw-deep    undercuts and hollows       cw-line    incised lines and contour
```

`cw-k-*` is the same role as a **stroke**: `cw-k-lit`, `cw-k-line`, `cw-k-grain`,
`cw-k-deep`, `cw-k-shade`, `cw-k-raw`, `cw-k-figure`.

Def ids: `cw-grain-maple` · `cw-grain-walnut` · `cw-turn` · `cw-lacquer` · `cw-sky` ·
`cw-floor` · `cw-contact` · `cw-nap` · `cw-wear`.

## Turning helpers

| Helper | For |
|---|---|
| `revolve(profile, squash?)` | A solid of revolution from a list of `Station`s. The workhorse. A profile may stop short of the axis, in which case it is capped flat, ready for crenellations or a coronet on top. |
| `foot(w)` | The six stations every piece stands on, scaled to its base. **Use it** — six hand-drawn feet is six different sets. |
| `drum(rx, top, bot)` | A turned band. Top edge bulges up, bottom edge bulges down, because that is what an opaque cylinder does seen slightly from above. |
| `rimY(u, rx, y, near)` / `rimRun(...)` | The y of a rim at horizontal offset `u`. Anything standing on a circular rim — merlons, coronet points, crown teeth — stands on a *curve*. Level feet is the fastest way to flatten a round object, and it is what every flat chess icon does. |
| `Wood`, `Disc`, `Collar`, `Turned`, `Ground` | Composed parts that already carry grain, light and shadow. |

Prefer these over raw paths. A piece that draws its own ellipse will not match, and the
mismatch is visible at the size these render.

## Every piece carries

1. A base from `foot()`, with a **felt disc** and a contact shadow under it
   (`<Ground/>`). The felt shows as a two-unit green crescent under the near rim —
   which is exactly how much baize you can see from a chair, and why it is drawn as a
   whole disc offset down rather than as a visible pad.
2. **Turned collar rings**, at least one, drawn with `<Collar/>` so they get the line
   of shadow they throw onto the shaft below. Without that arc a ring is a painted
   stripe. A collar's top face is drawn as the *near lune* only, never as a whole
   ellipse: the far half is behind whatever rises out of the collar.
3. **Visible grain**: the shared pattern, *plus* two or three arcs the piece draws by
   hand around its own swells. The pattern runs dead straight and cannot know the
   shaft is round. The pattern is fourteen fine lines, none wider than 0.8 — density
   is what says wood; a handful of wide dark lines says scratches in a lacquer.
4. A **lacquer highlight** down the lit side (`<Wood/>` applies it).
5. **At least one chipped or worn edge**, in `cw-raw` with a hairline of `cw-k-line`
   under it — every broken arris keeps a shadow on its underside. Put it where that
   piece is actually handled: the rook by its battlements, the knight by its ears, the
   pawn by being dragged rather than lifted.
6. A **self-shadow** on the unlit side, and a cast shadow wherever one part overhangs
   another.

## Turnings are graded; carvings are faceted

The one rule that keeps the knight and the king's cross from looking moulded:

- Anything off the lathe gets `<Wood/>` and the gradients. Smooth.
- Anything off a chisel gets **flat polygons with hard arrises between them**, and
  every arris is drawn twice — the lit edge, and the shadow immediately under it.

## Proportions — the set reads by silhouette

```
k 182   q 168   b 150   n 148   r 128   p 108      (PIECE_HEIGHT)
k  29   q  27   n  24   r  24   b  23   p  21      (PIECE_BASE, half-width)
```

Do not normalise these. The king must tower over the rook or the position is
unreadable at a glance, which is the one thing a chess set has to do. The bishop and
the knight are within two units on purpose: they are told apart by silhouette, never
by size.

## Per-piece requirements

- **Pawn** — the simplest turning, and the one repeated eight times a side. It has to
  survive repetition without looking stamped. The stem *hollows* rather than tapers.
- **Knight** — **carved, not turned.** The exception to every symmetry rule here. A
  sculpted head with a chiselled mane, a defined muzzle and jaw, an eye, and visible
  chisel facets. Built as two objects — a turned stem and a head socketed into a
  capless collar — with the head scaled about its ear tips so head-to-body proportion
  can be tuned without re-authoring forty interior paths. The head is about six tenths
  of the piece; at seven it reads as a sculpture with a chess base glued underneath.
  Its face is on the shaded flank and stays legible on bounce light off the board.
  This is the piece that decides whether the set looks hand-made.
- **Bishop** — the brim is a vertical face, not a bulge, and the mitre carries its own
  `revolve` so it can be lit as the separate solid it is. The slot has three parts: a
  dark interior, a lit lower lip, and a hard shadow on the upper wall.
- **Rook** — crenellations are cut on the squashed rim, so the centre merlon stands
  three units lower on screen than the ones at the edges. Through each crenel you see
  the wall's cut top, the dark bore, and a far merlon standing higher because it is
  further away.
- **Queen** — nine coronet points on a circle, individually drawn: five near ones
  drawn *in front of* the finial and four far ones *behind* it, at different heights
  because they are at different depths.
- **King** — the cross is drawn geometry: an upright 6.6 wide, a bar 21.6 across,
  every outer corner chamfered, and eleven separate facets. It is the piece of the
  board the eye goes to first and stays on longest.

## Hard rules

- TypeScript, `.tsx`, no `any`, no non-null `!`, `type` over `interface`.
- **A piece file declares no ids.** Eight pawns render at once, so eight
  `<clipPath id="pawn">` would be eight duplicate ids. Interior detail is authored to
  fit its own silhouette by hand. (`clip-path: path()` avoids the id and was tried; it
  does not render in every engine this ships to.)
- **Deterministic** — no `Math.random()` at render time. Wear and grain are authored,
  or computed once at module load, or the pieces shimmer between frames.
- **One filtered element per piece**, and it is the contour (`cw-wear`). Thirty-two
  pieces are on screen at once and displacement maps are not free. The displacement
  is 0.42 against a 0.9 stroke, and it has to stay small against the *smallest* radius
  on the board — at 0.7 a five-unit finial grew a notch out of one shoulder.
- No `<image>`, no external refs, no web fonts.
- Decorative SVG is `aria-hidden`; the position is carried as text by the board, not
  by thirty-two SVGs announcing themselves.
- No colour literals in `pieces/`. Finish is the stylesheet's job.
- Must compile under `npm run build` from `web/`.
