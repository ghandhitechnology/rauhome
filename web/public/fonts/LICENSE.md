# Bundled fonts

All four families are licensed under the SIL Open Font License 1.1, which
permits bundling and redistribution with the software that uses them.

| Family           | Source                                                | Files |
|------------------|-------------------------------------------------------|-------|
| DM Sans          | https://fonts.google.com/specimen/DM+Sans             | `dm-sans-*.woff2` |
| Instrument Serif | https://fonts.google.com/specimen/Instrument+Serif    | `instrument-serif-*.woff2` |
| Pretendard       | https://github.com/orioncactus/pretendard             | `pretendard-variable-hangul.woff2` |
| Nanum Myeongjo   | https://fonts.google.com/specimen/Nanum+Myeongjo      | `nanum-myeongjo-hangul.woff2` |

The Latin `.woff2` files are the exact subsets Google Fonts serves for `latin`
and `latin-ext` (DM Sans v17, Instrument Serif v5), fetched once and vendored
here.

## The Korean pair

Pretendard carries Hangul body text next to DM Sans, and Nanum Myeongjo carries
Hangul headings next to Instrument Serif. They were chosen on metrics rather
than taste alone — Pretendard's x-height and cap height (0.530 / 0.707 em) land
within a percent of DM Sans (0.526 / 0.700), and Nanum Myeongjo's cap height
(0.737) sits beside Instrument Serif's (0.720) with the same high stroke
contrast and beaked terminals. Mixed Korean-English lines therefore need no
`size-adjust`; the two scripts already sit on the same optical size.

Both are subset to the Hangul blocks only (syllables, jamo, halfwidth and
CJK punctuation) and their `@font-face` rules carry a matching `unicode-range`,
so an English-only session never downloads either file, and a Korean session
never pulls Latin glyphs it would not use. Regenerate with:

```
python -m fontTools.subset PretendardVariable.woff2 --flavor=woff2 \
  --output-file=pretendard-variable-hangul.woff2 \
  --unicodes="U+AC00-D7A3,U+1100-11FF,U+3130-318F,U+A960-A97F,U+D7B0-D7FF,U+3000-303F,U+FF01-FF60" \
  --layout-features='*' --name-IDs='*'
```

Full modern Hangul (all 11,172 syllables) is kept on purpose: a subset of the
common 2,350 drops a syllable mid-sentence into the system font, and that swap
is visible.

## Why these are vendored rather than linked

Rau runs on localhost and is expected to work with no internet connection. When
the fonts came from `fonts.googleapis.com`:

- offline, the display serif never arrived and the wordmark rendered in Georgia;
- online, `display=swap` guaranteed a visible reflow of every heading on boot;
- every page load told a third party the app had been opened.

To refresh them, re-request the CSS Google serves to a modern browser UA and
download the `latin` / `latin-ext` `src` URLs it names.
