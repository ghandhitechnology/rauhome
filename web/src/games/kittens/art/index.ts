/* ─────────────────────────────────────────────────────────────
   Exploding Kittens — art barrel

   The only import the table needs. Mount <CardDefs/> once at the root,
   then render CARD_ART[id] inside a <CardFrame/>.
   ───────────────────────────────────────────────────────────── */

import type { Face } from "./defs";

import ExplodingKitten from "./faces/exploding_kitten";
import Defuse from "./faces/defuse";
import Nope from "./faces/nope";
import Attack from "./faces/attack";
import Skip from "./faces/skip";
import Favor from "./faces/favor";
import Shuffle from "./faces/shuffle";
import SeeTheFuture from "./faces/see_the_future";
import Tacocat from "./faces/tacocat";
import RainbowRalphingCat from "./faces/rainbow_ralphing_cat";
import Cattermelon from "./faces/cattermelon";
import HairyPotatoCat from "./faces/hairy_potato_cat";
import BeardCat from "./faces/beard_cat";

export type CardId =
  | "exploding_kitten"
  | "defuse"
  | "nope"
  | "attack"
  | "skip"
  | "favor"
  | "shuffle"
  | "see_the_future"
  | "tacocat"
  | "rainbow_ralphing_cat"
  | "cattermelon"
  | "hairy_potato_cat"
  | "beard_cat";

export const CARD_IDS: readonly CardId[] = [
  "exploding_kitten",
  "defuse",
  "nope",
  "attack",
  "skip",
  "favor",
  "shuffle",
  "see_the_future",
  "tacocat",
  "rainbow_ralphing_cat",
  "cattermelon",
  "hairy_potato_cat",
  "beard_cat",
] as const;

export const CARD_ART: Record<CardId, Face> = {
  exploding_kitten: ExplodingKitten,
  defuse: Defuse,
  nope: Nope,
  attack: Attack,
  skip: Skip,
  favor: Favor,
  shuffle: Shuffle,
  see_the_future: SeeTheFuture,
  tacocat: Tacocat,
  rainbow_ralphing_cat: RainbowRalphingCat,
  cattermelon: Cattermelon,
  hairy_potato_cat: HairyPotatoCat,
  beard_cat: BeardCat,
};

export { PALETTE, INK, CardDefs, CARD_W, CARD_H, SAFE } from "./defs";
export type { Face, PaletteKey } from "./defs";
export { CardFrame, CardBack } from "./frame";
export type { CardKind, CardFrameProps } from "./frame";
