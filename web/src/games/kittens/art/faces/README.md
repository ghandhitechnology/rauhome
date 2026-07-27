# faces/ — how a card face is put together

A face is **not a component with props and not a whole SVG**. It is one function
returning SVG children that get dropped into a hole the frame has already cut:

```
CardDefs      mounted once at the table root — every filter, pattern, gradient
   │
CardFrame ────┬── stock (paper + #ek-grain) + corner halftone wash
              ├── <g clipPath="#ek-face-clip">  ← YOUR FILE RENDERS HERE
              ├── keyline (accent plate off register, then the ink plate)
              ├── corner pips at (28,28) and (212,268)
              └── title band, y 289→325
```

So: no `<svg>`, no `<defs>`, no `<title>`, no props, no `Math.random()`. Read
`../SPEC.md` before you draw and `../defs.tsx` before you reference an id.

## The canvas you actually get

| | |
|---|---|
| viewBox | `0 0 240 336` (`CARD_W` / `CARD_H`) |
| safe area | `SAFE` = x 16→224, y 16→280 |
| clipped to | `#ek-face-clip` — x 8→232, y 8→290, r9. The frame applies it; you don't have to. |
| keep clear | two 25px pip discs at (28,28) and (212,268), and everything below y 289 |

Bleeding art past the safe area into the border is fine and often good. Bleeding
under a pip is not — the pip is opaque ink and will eat whatever you put there.

## The five things every face does

1. **A background plate with `filter="url(#ek-grain)"`.** One flat rect, usually the
   card's accent at 0.15–0.25 opacity. Grain goes here and nowhere else — stacked on
   linework it just makes mud.
2. **Density behind the subject.** Radiating wedges, a halftone field, a horizon,
   repeated small marks. Bare paper reads as unfinished art, not as minimalism.
3. **An off-register plate.** Duplicate the subject's silhouette in `PALETTE.red` at
   `transform="translate(-3 2)"` *behind* the real one. (`#ek-misprint` does the same
   at a fixed −1.5/+1 if you'd rather not hand-place it.) This single move is the
   difference between "printed" and "rendered".
4. **Flat fills only.** Need a darker tone than the palette has? Lay `INK` at ~12%
   over the accent and then `url(#ek-halftone)` over that — which is how a real
   two-colour press would get there. `#ek-foil*` is reserved for `exploding_kitten`
   and `defuse`.
5. **All linework in one `<g filter="url(#ek-ink)">`** with `fill="none"`,
   `stroke={INK}`, round caps and joins. 3–4px for the silhouette, ~2px for interior
   detail. Children override `fill` where they need to.

## Worked example — `beard_cat.tsx`, layer by layer

```tsx
export default function Face(): ReactElement {
  return (
    <g aria-hidden="true">
      {/* 1. plate — the only place #ek-grain appears */}
      <rect x={8} y={8} width={224} height={282}
            fill={PALETTE.blue} opacity={0.18} filter="url(#ek-grain)" />

      {/* 2. density: sunburst + fine halftone, clipped so it can't escape */}
      <g clipPath="url(#ek-face-clip)">
        <g fill={PALETTE.blue} opacity={0.24}>
          {WEDGES.map((d, i) => <path key={i} d={d} />)}
        </g>
        <rect x={8} y={8} width={224} height={282}
              fill="url(#ek-halftone-fine)" opacity={0.11} />
      </g>

      {/* 3. off-register: red silhouette first, real one on top */}
      <path d={BEARD} fill={PALETTE.red} opacity={0.88}
            transform="translate(-3.2 2.2)" />
      <path d={BEARD} fill={PALETTE.blue} />
      <path d={BEARD} fill="url(#ek-halftone)" opacity={0.18} />

      {/* 4. one linework group, everything inside it */}
      <g filter="url(#ek-ink)" fill="none" stroke={INK}
         strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d={BEARD} strokeWidth={3.6} />
        {/* … grooves, face, moustache … */}
      </g>
    </g>
  );
}
```

Note the ordering discipline: **red plate → colour fill → halftone tone → ink
outline.** Get that order wrong and either the misprint disappears under the fill or
the halftone sits on top of the linework.

## Registering a new face

`../index.ts` already imports all thirteen by filename. A face file that doesn't
default-export a `Face` breaks the barrel, so `npm run build` from `web/` is the
real test — not `tsc` on the file alone.

## Two techniques in this folder worth stealing

- **Parametric silhouette** (`hairy_potato_cat.tsx`). A lump drawn by hand as a
  bezier chain always comes out as a circle with dents. Sum a few sine harmonics on
  the radius, sample it, run a Catmull-Rom through the samples, emit cubics. It is
  still bezier output, it is computed once at module load so it stays deterministic,
  and — the real payoff — because the outline is parametric, fur can hang off its
  normal at any angle. Same file, `furFlick`.
- **Hidden welds.** Ears, tails and feet are drawn *behind* the body fill rather
  than clipped to it. The body fill covers the join; the body's outline stroke then
  goes on last. No `<clipPath>` needed, which matters because faces cannot mint
  `<defs>`.

## Failure modes these two cards actually hit

Both are worth knowing because they are invisible in code and obvious in a render.

- **A beard filled the same colour as the coat behind it vanishes.** `beard_cat`'s
  moustache is `PALETTE.paper`, not blue, for exactly this reason.
- **Round ends read as bone.** The moustache tips are cusps — the tangent reverses
  on itself — because the first version's rounded tips made the whole thing look
  like a dog toy.
- **A cat built from smooth curves is a corporate mascot.** The potato needed
  ~90 fur flicks and 13% ink over its gold before it stopped reading as a friendly
  circle.

Render before you commit. `renderToStaticMarkup` into an HTML file and screenshot it
headless; the card must still read as itself at **60px wide**, which is roughly how
big it is in a hand.
