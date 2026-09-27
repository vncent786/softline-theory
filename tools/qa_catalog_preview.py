from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8018/"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa"
OUT.mkdir(exist_ok=True)
MANIFEST = json.loads((ROOT / "catalog-manifest.json").read_text(encoding="utf-8"))


def inspect_page(page, url: str, expected_images: int | None = None) -> dict:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []

    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))
    page.on("requestfailed", lambda req: failed_requests.append(f"{req.method} {req.url}: {req.failure}"))
    page.on("response", lambda res: bad_responses.append(f"{res.status} {res.url}") if res.status >= 400 else None)

    response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_function("document.fonts ? document.fonts.status === 'loaded' : true", timeout=15_000)
    page.wait_for_timeout(250)
    assert response and response.status == 200, (url, response.status if response else None)

    # Trigger every native-lazy image directly. Jump-scrolling can move an image
    # out of Chromium's lazy-load window before the request is scheduled.
    images = page.locator("img")
    for index in range(images.count()):
        images.nth(index).scroll_into_view_if_needed(timeout=5_000)
        page.wait_for_timeout(60)
    page.evaluate("window.scrollTo(0, 0)")
    page.wait_for_timeout(250)

    broken = images.evaluate_all("els => els.filter(img => !img.complete || img.naturalWidth === 0).map(img => img.currentSrc || img.src)")
    assert not broken, (url, broken)
    if expected_images is not None:
        assert images.count() == expected_images, (url, images.count(), expected_images)

    geometry = page.evaluate("""() => ({
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      height: document.documentElement.scrollHeight
    })""")
    assert geometry["scrollWidth"] <= geometry["innerWidth"] + 1, (url, geometry)
    assert geometry["bodyScrollWidth"] <= geometry["innerWidth"] + 1, (url, geometry)

    resources = page.evaluate("""() => performance.getEntriesByType('resource').map(r => ({
      name: r.name,
      initiatorType: r.initiatorType,
      transferSize: r.transferSize,
      encodedBodySize: r.encodedBodySize,
      duration: r.duration
    }))""")
    local_resources = [row for row in resources if row["name"].startswith(BASE)]
    result = {
        "url": url,
        "title": page.title(),
        "images": images.count(),
        "geometry": geometry,
        "console_errors": console_errors,
        "page_errors": page_errors,
        "failed_requests": failed_requests,
        "bad_responses": bad_responses,
        "local_resource_count": len(local_resources),
        "local_encoded_bytes": int(sum(row["encodedBodySize"] for row in local_resources)),
        "largest_local_resources": sorted(local_resources, key=lambda row: row["encodedBodySize"], reverse=True)[:5],
    }
    assert not console_errors, result
    assert not page_errors, result
    assert not failed_requests, result
    assert not bad_responses, result
    return result


def main() -> None:
    results: dict[str, object] = {"viewports": {}, "products": []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for label, viewport in {
            "desktop": {"width": 1440, "height": 1100},
            "mobile": {"width": 390, "height": 844},
        }.items():
            context = browser.new_context(viewport=viewport, device_scale_factor=1)
            page = context.new_page()
            home = inspect_page(page, BASE)
            assert page.locator(".product-card").count() == 8
            assert page.locator(".lookbook-item").count() == 8
            assert page.locator("text=Eight bags. 45 supplied colourways.").count() == 1
            page.screenshot(path=str(OUT / f"home-{label}.png"), full_page=True)

            product_url = urljoin(BASE, "product-amelie-matte.html")
            product = inspect_page(page, product_url)
            assert page.locator("[data-gallery-thumb]").count() == 10
            assert page.locator(".colour-chip").count() == 6
            before = page.locator("[data-main-image]").get_attribute("src")
            page.locator("[data-gallery-thumb]").last.click()
            page.wait_for_function("document.querySelector('[data-active-image-label]').textContent.includes('Dimension - large')")
            after = page.locator("[data-main-image]").get_attribute("src")
            assert before != after
            assert "10-dimension-large" in after
            page.screenshot(path=str(OUT / f"amelie-matte-{label}.png"), full_page=True)

            results["viewports"][label] = {"home": home, "amelie_matte": product}
            context.close()

        context = browser.new_context(viewport={"width": 1280, "height": 900})
        for item in MANIFEST:
            page = context.new_page()
            url = urljoin(BASE, f"product-{item['slug']}.html")
            result = inspect_page(page, url)
            assert page.locator("[data-gallery-thumb]").count() == item["total_pages"]
            assert page.locator(".colour-chip").count() == len(item["colour_pages"])
            assert page.locator(".dimension-row").count() == len(item["dimension_pages"])
            results["products"].append({
                "slug": item["slug"],
                "page_count": item["total_pages"],
                "colour_count": len(item["colour_pages"]),
                "dimension_count": len(item["dimension_pages"]),
                "result": result,
            })
            page.close()
        context.close()
        browser.close()

    output = OUT / "qa-results.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    print(json.dumps({
        "viewports": list(results["viewports"]),
        "products_checked": len(results["products"]),
        "screenshots": 4,
        "errors": 0,
        "home_desktop_local_encoded_bytes": results["viewports"]["desktop"]["home"]["local_encoded_bytes"],
        "home_mobile_local_encoded_bytes": results["viewports"]["mobile"]["home"]["local_encoded_bytes"],
    }, indent=2))


if __name__ == "__main__":
    main()
