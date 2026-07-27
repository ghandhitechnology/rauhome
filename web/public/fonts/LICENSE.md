# Bundled fonts

Both families are licensed under the SIL Open Font License 1.1, which permits
bundling and redistribution with the software that uses them.

| Family           | Source                                                | Files |
|------------------|-------------------------------------------------------|-------|
| DM Sans          | https://fonts.google.com/specimen/DM+Sans             | `dm-sans-*.woff2` |
| Instrument Serif | https://fonts.google.com/specimen/Instrument+Serif    | `instrument-serif-*.woff2` |

The `.woff2` files are the exact subsets Google Fonts serves for `latin` and
`latin-ext` (DM Sans v17, Instrument Serif v5), fetched once and vendored here.

## Why these are vendored rather than linked

Rau runs on localhost and is expected to work with no internet connection. When
the fonts came from `fonts.googleapis.com`:

- offline, the display serif never arrived and the wordmark rendered in Georgia;
- online, `display=swap` guaranteed a visible reflow of every heading on boot;
- every page load told a third party the app had been opened.

To refresh them, re-request the CSS Google serves to a modern browser UA and
download the `latin` / `latin-ext` `src` URLs it names.
