/* ─────────────────────────────────────────────────────────────
   Exploding Kittens — deck gallery (dev only)

   Not routed, not shipped in any screen. Render it from a scratch entry
   point when you want to look at the whole deck at once:

     import Gallery from "./games/kittens/art/Gallery"
     createRoot(el).render(<Gallery />)

   It mounts <CardDefs/> exactly once at its own root — every filter,
   pattern and gradient the faces reference lives in there, so nothing
   below it needs (or may have) its own <defs>.

   Everything is inline-styled on purpose: the gallery must not depend on
   Kittens.css or any app stylesheet, so what you are judging is the card
   art and nothing else.
   ───────────────────────────────────────────────────────────── */

import type { CSSProperties, ReactElement } from "react";

import { CARD_ART, CARD_IDS, type CardId } from "./index";
import { CardBack, CardFrame } from "./frame";
import { CardDefs, PALETTE } from "./defs";
import { cardMeta } from "../meta";

/* The backdrop is deliberately near-black and neutral: warm paper on a warm
   ground hides exactly the figure/ground failures this page exists to catch. */
const BACKDROP = "#121215";
const RULE = "#2A2A30";
const LABEL = "#9A9AA4";

const page: CSSProperties = {
  minHeight: "100%",
  boxSizing: "border-box",
  padding: "clamp(16px, 4vw, 40px)",
  background: BACKDROP,
  color: PALETTE.paper,
  fontFamily: '"DM Sans", system-ui, sans-serif',
};

const grid: CSSProperties = {
  display: "grid",
  /* auto-fit + minmax is the whole responsive story: one column on a phone,
     as many as fit on a monitor, no breakpoints. */
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: "clamp(14px, 2.5vw, 28px)",
  maxWidth: 1320,
  margin: "0 auto",
};

const cell: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "stretch",
  gap: 8,
};

const cardBox: CSSProperties = {
  aspectRatio: "240 / 336",
  /* Cards carry their own die-cut edge; the shadow just lifts them off the
     backdrop so the bleed is readable. */
  filter: "drop-shadow(0 6px 18px rgba(0,0,0,0.55))",
};

const caption: CSSProperties = {
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: LABEL,
  textAlign: "center",
};

function Cell({ label, children }: { label: string; children: ReactElement }) {
  return (
    <figure style={{ ...cell, margin: 0 }}>
      <div style={cardBox}>{children}</div>
      <figcaption style={caption}>{label}</figcaption>
    </figure>
  );
}

function GalleryCard({ id }: { id: CardId }): ReactElement {
  const meta = cardMeta(id);
  const Face = CARD_ART[id];
  return (
    <Cell label={meta.title}>
      <CardFrame title={meta.title} accent={meta.accent} kind={meta.kind}>
        <Face />
      </CardFrame>
    </Cell>
  );
}

export function Gallery(): ReactElement {
  return (
    <div style={page}>
      {/* Mounted once, here, for every card on the page. */}
      <CardDefs />

      <header style={{ maxWidth: 1320, margin: "0 auto 24px" }}>
        <h1
          style={{
            margin: 0,
            fontFamily: '"Instrument Serif", Georgia, serif',
            fontWeight: 400,
            fontSize: "clamp(24px, 4vw, 38px)",
            color: PALETTE.paper,
          }}
        >
          Exploding Kittens — deck proof
        </h1>
        <p style={{ margin: "6px 0 0", fontSize: 13, color: LABEL }}>
          {CARD_IDS.length} faces plus the card back. Shrink the window until a
          card is about 60px wide — anything that stops reading there is broken.
        </p>
        <hr style={{ border: 0, borderTop: `1px solid ${RULE}`, marginTop: 18 }} />
      </header>

      <div style={grid}>
        {CARD_IDS.map((id) => (
          <GalleryCard key={id} id={id} />
        ))}
        <Cell label="Card back">
          <CardBack />
        </Cell>
      </div>
    </div>
  );
}

export default Gallery;
