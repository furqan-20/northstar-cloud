# NorthStar asset notes

- `static/images/workspace-hero.png`: original AI-generated editorial workspace image, created with the built-in image-generation tool for this website. It illustrates a fictional collection; it is not a photograph of actual inventory.
- The 20 product SVG images are original code-generated catalogue illustrations. Their editable source is `build_assets.py` and their colours/names come from `catalog.py`. Rebuild with `python3 build_assets.py` if desired. The delivered SVG files are ready to use; rebuilding is not required.
- `static/images/brand.svg` and UI icons are original simple SVG artwork.
- `static/fonts/Editorial-Regular.otf` is Nimbus Roman Regular; `Sans-Regular.otf` and `Sans-Bold.otf` are Nimbus Sans Regular/Bold from URW Base 35. Original font family names inside the fonts are unchanged. The stylesheet uses local aliases. The accompanying distribution copyright/licence is reproduced in `FONT-LICENSE.txt`.
- All imagery and fonts are bundled. The browser does not load stock-photo URLs or CDN font files.

## Editorial image prompt

Use case: product-mockup. Create an editorial ecommerce lifestyle photograph for the website NorthStar, a design-focused workspace and everyday goods shop. Asset: large landscape homepage hero, approximately 3:2. Scene: a quietly beautiful sunlit modern home workspace, honey oak desk spanning the lower frame, warm white textured wall, chrome and dark forest green mushroom lamp on right, taupe desk mat, closed sand linen notebook and black pen near center, white ceramic cup, one slender olive branch in pale stone vase at left edge, rattan chair partially visible. No computer screens. Strong late afternoon sunlight from upper left casting sculptural leaf shadows on the wall. Warm sand, olive green, cream and brown, refined luxury product photography with realistic materials and subtle film grain. Composition contains whole room vignette tightly framed with objects in bottom half and wall above, can be cropped in website responsive hero. No people, no text, no logos, no typography or watermark.

The built-in image tool was used, not the optional CLI fallback. The final asset is included at the path above.
