from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image


PRODUCT_NAMES = {
    "amelie-matte": "The Amélie (Matte)",
    "simone": "The Simone",
    "amelie": "The Amélie",
    "mabel-mini-tote": "The Mabel Mini Tote",
    "audrey": "The Audrey",
    "arc": "The Arc",
    "lattice": "The Lattice",
    "sera": "The Sera",
}

# Explicit creative-owner corrections. Keep both the original Canva label and
# the approved display label in catalog-manifest.json for auditability.
LABEL_CORRECTIONS = {
    ("mabel-mini-tote", "Cappucino"): "Cappuccino",
}
PREVIEW_VERSION = "v2"

ROLE_WORDS = {
    "dimension": "dimension",
    "human": "lifestyle",
    "display": "display",
    "large vs small": "comparison",
}


def slugify(value: str) -> str:
    value = value.lower().replace("é", "e")
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "item"


def classify(label: str) -> str:
    lowered = label.lower()
    for token, role in ROLE_WORDS.items():
        if token in lowered:
            return role
    return "colour"


def source_image(page: dict[str, Any]) -> Path:
    if classify(page["label"]) == "dimension":
        return Path(page["composite_path"])
    large = [row for row in page.get("images", []) if int(row.get("natural_height") or 0) > 200]
    if not large:
        raise RuntimeError(f"No product image on {page['label']}")
    return Path(large[0]["path"])


def save_webp(source: Path, destination: Path, max_size: int, quality: int) -> tuple[int, int, int, str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        image = original.convert("RGBA") if "A" in original.getbands() else original.convert("RGB")
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
        image.save(destination, "WEBP", quality=quality, method=6, exact=True)
        width, height = image.size
    payload = destination.read_bytes()
    return width, height, len(payload), hashlib.sha256(payload).hexdigest()


def unique_measurements(text: str) -> list[str]:
    values = re.findall(r"\d+(?:\.\d+)?\s*cm", text, flags=re.I)
    result: list[str] = []
    for value in values:
        normalized = re.sub(r"\s+", "", value.lower())
        if normalized not in result:
            result.append(normalized)
    return result


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def image_tag(
    asset: dict[str, Any],
    alt: str,
    *,
    eager: bool = False,
    css_class: str = "",
    sizes: str = "(max-width: 620px) calc(100vw - 36px), 50vw",
) -> str:
    loading = "eager" if eager else "lazy"
    priority = ' fetchpriority="high"' if eager else ""
    class_attr = f' class="{css_class}"' if css_class else ""
    return (
        f'<img{class_attr} src="{esc(asset["thumb"])}" '
        f'srcset="{esc(asset["thumb"])} 480w, {esc(asset["full"])} 1200w" '
        f'sizes="{esc(sizes)}" width="{asset["full_width"]}" '
        f'height="{asset["full_height"]}" alt="{esc(alt)}" loading="{loading}" '
        f'decoding="async"{priority}>'
    )


def document_head(title: str, description: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <meta name="description" content="{esc(description)}">
  <meta name="robots" content="noindex,nofollow">
  <meta name="theme-color" content="#F5F1EA">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,500;1,400&family=DM+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="assets/css/catalog.css">
</head>"""


def nav() -> str:
    return f"""<a class="skip-link" href="#main">Skip to content</a>
<nav class="site-nav" aria-label="Primary">
  <div class="nav-inner">
    <a class="brand" href="index.html">Softline Theory</a>
    <div class="nav-links">
      <a href="index.html#collection">Collection</a>
      <a href="index.html#lookbook">Lookbook</a>
      <span class="preview-pill">Private preview {PREVIEW_VERSION}</span>
    </div>
  </div>
</nav>"""


def footer() -> str:
    return f"""<footer class="site-footer">
  <div class="footer-inner">
    <div>
      <div class="footer-brand">Softline Theory</div>
      <p class="footer-copy">Catalogue preview {PREVIEW_VERSION} built from owner-supplied Canva assets.</p>
    </div>
    <div class="footer-right">Not published · September 2026</div>
  </div>
</footer>"""


def card(product: dict[str, Any], *, related: bool = False) -> str:
    main = product["colour_pages"][0]
    label = "related-card" if related else "product-card"
    grid_sizes = "(max-width: 620px) calc(100vw - 36px), (max-width: 1060px) 50vw, 25vw"
    if related:
        return f"""<a class="{label}" href="product-{product['slug']}.html">
  {image_tag(main, product['name'], sizes=grid_sizes)}
  <h3>{esc(product['name'])}</h3>
</a>"""
    colours = ", ".join(page["label"] for page in product["colour_pages"])
    size_copy = " · two supplied sizes" if len(product["dimension_pages"]) > 1 else ""
    return f"""<article class="{label}">
  <a href="product-{product['slug']}.html" aria-label="View {esc(product['name'])}">
    <div class="product-card-image">{image_tag(main, product['name'], sizes=grid_sizes)}</div>
    <div class="product-card-meta">
      <h3>{esc(product['name'])}</h3>
      <p class="product-card-summary">{len(product['colour_pages'])} supplied colourways{size_copy}</p>
      <p class="variant-list">{esc(colours)}</p>
      <span class="card-link">View catalogue</span>
    </div>
  </a>
</article>"""


def build_home(products: list[dict[str, Any]], destination: Path) -> None:
    hero = products[0]["colour_pages"][0]
    lifestyle = next((p for p in products[0]["pages"] if p["role"] == "lifestyle"), products[0]["pages"][0])
    total_colours = sum(len(product["colour_pages"]) for product in products)
    cards = "\n".join(card(product) for product in products)
    lookbook_items: list[str] = []
    for product in products:
        chosen = next(
            (page for page in product["pages"] if page["role"] in {"lifestyle", "display", "comparison"}),
            product["colour_pages"][0],
        )
        lookbook_items.append(
            f'<a class="lookbook-item" href="product-{product["slug"]}.html">'
            + image_tag(
                chosen,
                f'{product["name"]} — {chosen["label"]}',
                sizes="(max-width: 620px) 50vw, (max-width: 1060px) 50vw, 25vw",
            )
            + "</a>"
        )
    body = f"""{document_head('Softline Theory — Eight-bag catalogue preview', 'Private preview of eight Softline Theory bag catalogues.')}
<body>
{nav()}
<main id="main">
  <section class="hero">
    <div class="hero-inner">
      <div>
        <p class="eyebrow">Eight-bag catalogue preview</p>
        <h1>Softness,<br><em>structured.</em></h1>
        <p class="hero-copy">Eight everyday silhouettes, presented with their supplied colours, lifestyle views and dimensions.</p>
        <div class="button-row">
          <a class="btn btn-primary" href="#collection">View all eight bags</a>
          <a class="btn btn-secondary" href="#lookbook">Open lookbook</a>
        </div>
      </div>
      <div class="hero-image">{image_tag(hero, f'{products[0]["name"]} in {hero["label"]}', eager=True)}</div>
    </div>
  </section>

  <section class="section collection" id="collection">
    <div class="section-inner">
      <div class="section-heading">
        <div><p class="eyebrow">The collection</p><h2>Eight considered shapes</h2></div>
        <p>Every product page keeps the catalogue names, colour labels and dimension diagrams exactly as supplied.</p>
      </div>
      <div class="collection-grid">{cards}</div>
    </div>
  </section>

  <section class="editorial">
    <div class="editorial-media">{image_tag(lifestyle, f'{products[0]["name"]} lifestyle view')}</div>
    <div class="editorial-copy">
      <p class="eyebrow" style="color:rgba(255,255,255,.65)">Scale and styling</p>
      <h2>See the bag in context</h2>
      <p>Lifestyle, comparison and display views sit inside each product catalogue, so size and silhouette are easier to judge before launch.</p>
    </div>
  </section>

  <section class="catalog-statement">
    <h2>Eight bags. {total_colours} supplied colourways.</h2>
    <p>No guessed materials, prices or performance claims. This preview is limited to what the approved catalogue assets actually show.</p>
  </section>

  <section class="section" id="lookbook">
    <div class="section-inner">
      <div class="section-heading">
        <div><p class="eyebrow">The lookbook</p><h2>One view from every bag</h2></div>
        <p>Tap any image to open the complete product catalogue, including every supplied colour and dimension diagram.</p>
      </div>
      <div class="lookbook-grid">{''.join(lookbook_items)}</div>
    </div>
  </section>

  <section class="section preview-note" id="waitlist">
    <div class="section-inner">
      <p class="eyebrow">Review boundary</p>
      <h2>Preview first. Publish only after approval.</h2>
      <p>This version does not collect payments or customer details. It exists for catalogue, image-quality and mobile-speed review.</p>
    </div>
  </section>
</main>
{footer()}
</body>
</html>"""
    (destination / "index.html").write_text(body, encoding="utf-8")


def build_product_page(product: dict[str, Any], products: list[dict[str, Any]], destination: Path) -> None:
    main = product["colour_pages"][0]
    thumbs: list[str] = []
    for index, page in enumerate(product["pages"]):
        active = " active" if index == 0 else ""
        thumbs.append(
            f'<button class="thumb{active}" type="button" data-gallery-thumb '
            f'data-full="{esc(page["full"])}" data-label="{esc(page["label"])}" '
            f'data-alt="{esc(product["name"] + " — " + page["label"])}" '
            f'aria-label="Show {esc(page["label"])}" aria-pressed="{"true" if index == 0 else "false"}">'
            f'<img src="{esc(page["thumb"])}" width="{page["thumb_width"]}" height="{page["thumb_height"]}" '
            f'alt="" loading="lazy" decoding="async"></button>'
        )
    colour_chips = "".join(f'<span class="colour-chip">{esc(page["label"])}</span>' for page in product["colour_pages"])
    dimension_rows: list[str] = []
    for page in product["dimension_pages"]:
        values = " × ".join(value.replace("cm", "") for value in page["measurements"])
        copy = f"{values} cm" if values else "See supplied diagram"
        dimension_rows.append(
            f'<div class="dimension-row"><span>{esc(page["label"])}</span><span>{esc(copy)}</span></div>'
        )
    related_products = [item for item in products if item["slug"] != product["slug"]][:3]
    related_cards = "".join(card(item, related=True) for item in related_products)
    body = f"""{document_head(product['name'] + ' — Softline Theory', f'Private catalogue preview for {product["name"]}.')}
<body>
{nav()}
<main id="main">
  <div class="breadcrumb"><a href="index.html">Home</a> / <a href="index.html#collection">Collection</a> / {esc(product['name'])}</div>
  <section class="product-layout">
    <div class="product-gallery">
      <div class="main-image">
        <img src="{esc(main['full'])}" width="{main['full_width']}" height="{main['full_height']}" alt="{esc(product['name'] + ' in ' + main['label'])}" data-main-image decoding="async" fetchpriority="high">
      </div>
      <div class="thumbnail-strip" aria-label="Product views">{''.join(thumbs)}</div>
    </div>
    <div class="product-info">
      <p class="product-kicker">Catalogue preview</p>
      <h1 class="product-title">{esc(product['name'])}</h1>
      <p class="product-status">Coming soon · <span data-active-image-label>{esc(main['label'])}</span></p>
      <div class="divider"></div>
      <p class="detail-heading">Supplied colours</p>
      <div class="colour-names">{colour_chips}</div>
      <div class="divider"></div>
      <p class="detail-heading">Supplied dimensions</p>
      <div class="dimension-list">{''.join(dimension_rows) or '<p class="catalog-copy">No dimension page was supplied.</p>'}</div>
      <p class="catalog-copy">Use the dimension thumbnails for line orientation. Values are shown in source order; width, height and depth have not been guessed.</p>
      <div class="divider"></div>
      <p class="detail-heading">Catalogue contents</p>
      <p class="catalog-copy">{len(product['colour_pages'])} colour pages · {len(product['support_pages'])} lifestyle, display or comparison pages · {len(product['dimension_pages'])} dimension page{'s' if len(product['dimension_pages']) != 1 else ''}.</p>
      <p class="source-note">This preview uses only the images and labels supplied in the approved Canva design. Material, price, weight, capacity and availability have not been published because they were not included in the source catalogue.</p>
    </div>
  </section>

  <section class="section related">
    <div class="section-inner">
      <div class="section-heading">
        <div><p class="eyebrow">Continue browsing</p><h2>More from the collection</h2></div>
      </div>
      <div class="related-grid">{related_cards}</div>
    </div>
  </section>
</main>
{footer()}
<script src="assets/js/catalog.js" defer></script>
</body>
</html>"""
    (destination / f"product-{product['slug']}.html").write_text(body, encoding="utf-8")


def build(source_manifest: Path, destination: Path) -> None:
    manifest = json.loads(source_manifest.read_text(encoding="utf-8"))
    if len(manifest) != 8:
        raise RuntimeError(f"Expected 8 designs, received {len(manifest)}")
    if any(row.get("error") for row in manifest):
        raise RuntimeError("Extraction manifest contains errors")
    if sum(int(row["total_pages"]) for row in manifest) != 74:
        raise RuntimeError("Expected 74 extracted pages")

    output_root = destination / "assets" / "img" / "catalog"
    if output_root.exists():
        shutil.rmtree(output_root)
    products: list[dict[str, Any]] = []
    compact_sources: list[dict[str, Any]] = []

    for design in manifest:
        slug = design["slug"]
        pages: list[dict[str, Any]] = []
        for page in design["pages"]:
            source_label = page["label"]
            display_label = LABEL_CORRECTIONS.get((slug, source_label), source_label)
            role = classify(display_label)
            source = source_image(page)
            page_slug = f"{int(page['page_number']):02d}-{slugify(display_label)}"
            relative_root = Path("assets") / "img" / "catalog" / slug
            full_rel = (relative_root / f"{page_slug}-1200.webp").as_posix()
            thumb_rel = (relative_root / f"{page_slug}-480.webp").as_posix()
            full_path = destination / full_rel
            thumb_path = destination / thumb_rel
            fw, fh, full_bytes, full_sha = save_webp(source, full_path, 1200, 90 if role == "dimension" else 88)
            tw, th, thumb_bytes, thumb_sha = save_webp(source, thumb_path, 480, 84)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            pages.append({
                "page_number": int(page["page_number"]),
                "source_label": source_label,
                "label": display_label,
                "role": role,
                "measurements": unique_measurements(page.get("text", "")),
                "full": full_rel,
                "thumb": thumb_rel,
                "full_width": fw,
                "full_height": fh,
                "thumb_width": tw,
                "thumb_height": th,
                "full_bytes": full_bytes,
                "thumb_bytes": thumb_bytes,
                "source_sha256": source_sha,
                "full_sha256": full_sha,
                "thumb_sha256": thumb_sha,
            })
        product = {
            "slug": slug,
            "name": PRODUCT_NAMES[slug],
            "source": design["source"],
            "title": design["title"],
            "total_pages": design["total_pages"],
            "pages": pages,
            "colour_pages": [page for page in pages if page["role"] == "colour"],
            "dimension_pages": [page for page in pages if page["role"] == "dimension"],
            "support_pages": [page for page in pages if page["role"] in {"lifestyle", "display", "comparison"}],
        }
        if not product["colour_pages"]:
            raise RuntimeError(f"No colour pages for {slug}")
        products.append(product)
        compact_sources.append(product)

    build_home(products, destination)
    for product in products:
        build_product_page(product, products, destination)

    manifest_path = destination / "catalog-manifest.json"
    manifest_path.write_text(json.dumps(compact_sources, ensure_ascii=False, indent=2), encoding="utf-8")
    total_files = sum(len(product["pages"]) * 2 for product in products)
    total_bytes = sum(
        page["full_bytes"] + page["thumb_bytes"]
        for product in products
        for page in product["pages"]
    )
    print(json.dumps({
        "products": len(products),
        "pages": sum(product["total_pages"] for product in products),
        "colourways": sum(len(product["colour_pages"]) for product in products),
        "generated_images": total_files,
        "generated_image_bytes": total_bytes,
        "html_pages": len(products) + 1,
        "manifest": str(manifest_path),
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source_manifest", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    build(args.source_manifest.resolve(), args.destination.resolve())
