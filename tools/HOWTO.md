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

## Real screenshots instead of drawn mockups

Put `brainstorming.png`, `icon-ir.png`, `linkspace.png` (≈1280×920, top of the page)
into `tools/screens/` and rebuild — they get embedded into the project cards.
Keep each under ~300 KB (export as JPG/WebP) or the SVGs get heavy.
