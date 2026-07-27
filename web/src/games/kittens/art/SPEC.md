# Card art contract

Every file in this folder obeys this. It exists so 13 cards drawn by 13 different
hands come out looking like one printed deck.

## Files

| File | Exports |
|---|---|
| `defs.tsx` | `<CardDefs/>` — one hidden `<svg>` holding every shared `<defs>` (filters, patterns, gradients). Mounted **once** at the table root. Also `PALETTE`, `INK`, and the `Face` type. |
| `frame.tsx` | `<CardFrame/>` — die-cut border, title band, corner pips, holds a face as children. `<CardBack/>` — the face-down card. |
| `faces/<id>.tsx` | `export default function Face()` returning **SVG children only** (no `<svg>` wrapper, no `<defs>`). |
| `index.ts` | `CARD_ART: Record<CardId, Face>` |

## The canvas

- Face art draws into **`viewBox="0 0 240 336"`** (2.5×3.5 poker ratio at 96dpi).
- The frame reserves the outer **12px** as bleed/border and the bottom **44px** as the
  title band. **Safe area for illustration: x 16→224, y 16→280.** Art may bleed into the
  border deliberately, but nothing load-bearing goes outside the safe area.
- No `<image>`, no external refs, no web fonts beyond the two the app already ships
  (`"DM Sans"`, `"Instrument Serif"`).

## The look

Cheap 3-colour screenprint on uncoated card stock. Bold black linework, flat fills,
one colour deliberately off-register by ~1.5px so it looks misprinted. Funny, mean,
hand-drawn — not corporate vector illustration, not gradient-mesh realism.

- Line weight: 3–4px for silhouette, 2px for interior detail. Round caps and joins.
- Fills are **flat**. The only gradients allowed are the foil ones in `defs.tsx`, and
  only on `exploding_kitten` and `defuse`.
- Every face applies `filter="url(#ek-grain)"` to its background plate and
  `filter="url(#ek-ink)"` to its linework group.
- Cats have **personality and expression**. A cat card that is just a cat shape has failed.

## Palette (from `defs.tsx` — import it, never hardcode hex)

```
PALETTE.paper   #F2E8D5   card stock
PALETTE.ink     #17130F   linework
PALETTE.red     #D6402F   the loud one
PALETTE.blue    #2C5F8A
PALETTE.green   #4E8B5A
PALETTE.gold    #E0A32E
PALETTE.pink    #E08CA0
PALETTE.violet  #6B4C93
```

Each card picks **paper + ink + at most two accents**. That restraint is what makes 13
cards read as one deck.

## Shared filter/pattern ids (defined in `defs.tsx`, referenced by faces)

`ek-grain` · `ek-ink` · `ek-halftone` · `ek-foil` · `ek-foil-dark` · `ek-misprint`

## Card ids

`exploding_kitten` `defuse` `nope` `attack` `skip` `favor` `shuffle` `see_the_future`
`tacocat` `rainbow_ralphing_cat` `cattermelon` `hairy_potato_cat` `beard_cat`

## Hard rules

- TypeScript, `.tsx`, no `any`, no props on `Face`.
- Deterministic — no `Math.random()` at render time.
- Decorative SVG gets `aria-hidden`; the card's name lives in the frame's label.
- Must compile under `npm run build` from `web/`.
