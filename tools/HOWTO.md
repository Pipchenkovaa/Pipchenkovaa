# How this README works

GitHub strips CSS from README files, so every block is an SVG in `assets/`,
generated from `tools/content.json` by `tools/build.py`. Text is converted to
outlines (Inter font, `tools/fonts`, SIL OFL 1.1), so it renders identically everywhere.

## Change text, links, stack, projects

1. Edit `tools/content.json`.
2. Either commit it — the GitHub Action rebuilds `assets/` and `README.md` for you —
   or build locally:

   ```bash
   pip install -r tools/requirements.txt
   python tools/build.py
   ```

Do not edit `README.md` by hand — it is overwritten on every build.

## Things to fill in

- `contacts` → LinkedIn `url` is empty, so the button is not rendered. Paste a URL to show it.
- `projects` → Icon IR and LinkSpace have no `url`; their cards link to the repositories tab.

## Project screenshots

`tools/screens/<project-key>.jpg` (or .png/.webp) is embedded into the project card.
Only the top of the page is visible (about 820×540 px is enough).
Keep each file under ~100 KB or the SVGs get heavy. Delete the file to get the drawn mockup back.

## Accent colour

`"accent"` at the top of `content.json` is the only colour setting. Glows, the name gradient,
the flower, the CTA button (and the text colour on it) are all derived from it.
The green "open to work" dot and the tech-stack brand colours are independent.

## Tech stack colours

Each stack item is `[name, monogram, brand hex]`. Pure black brands (`#000000`) are shown as white.
