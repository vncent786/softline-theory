from __future__ import annotations

import json
import statistics
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8018/"
ROOT = Path(__file__).resolve().parents[1]

INIT = """
window.__catalogPerf = {lcp: 0, cls: 0};
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) window.__catalogPerf.lcp = Math.max(window.__catalogPerf.lcp, entry.startTime);
}).observe({type: 'largest-contentful-paint', buffered: true});
new PerformanceObserver((list) => {
  for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.__catalogPerf.cls += entry.value;
}).observe({type: 'layout-shift', buffered: true});
"""


def run() -> None:
    rows = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        for viewport_name, viewport in {
            "desktop": {"width": 1440, "height": 1100},
            "mobile": {"width": 390, "height": 844},
        }.items():
            for attempt in range(3):
                context = browser.new_context(viewport=viewport, device_scale_factor=1)
                page = context.new_page()
                page.add_init_script(INIT)
                response = page.goto(BASE, wait_until="load", timeout=30_000)
                page.wait_for_timeout(1500)
                assert response and response.status == 200
                data = page.evaluate("""() => {
                  const nav = performance.getEntriesByType('navigation')[0];
                  const resources = performance.getEntriesByType('resource');
                  const local = resources.filter(r => r.name.startsWith(location.origin));
                  const images = Array.from(document.images);
                  return {
                    navEncodedBytes: nav.encodedBodySize,
                    localResourceEncodedBytes: local.reduce((s, r) => s + r.encodedBodySize, 0),
                    localResourceCount: local.length,
                    loadedImageCount: images.filter(i => i.complete && i.naturalWidth > 0).length,
                    totalImageCount: images.length,
                    domContentLoadedMs: nav.domContentLoadedEventEnd,
                    loadMs: nav.loadEventEnd,
                    fcpMs: (performance.getEntriesByName('first-contentful-paint')[0] || {}).startTime || 0,
                    lcpMs: window.__catalogPerf.lcp,
                    cls: window.__catalogPerf.cls
                  };
                }""")
                data.update({"viewport": viewport_name, "attempt": attempt + 1})
                rows.append(data)
                context.close()
        browser.close()

    summary = {}
    for viewport_name in ("desktop", "mobile"):
        selected = [row for row in rows if row["viewport"] == viewport_name]
        summary[viewport_name] = {
            key: round(statistics.median(row[key] for row in selected), 3)
            for key in (
                "navEncodedBytes", "localResourceEncodedBytes", "localResourceCount",
                "loadedImageCount", "totalImageCount", "domContentLoadedMs", "loadMs",
                "fcpMs", "lcpMs", "cls"
            )
        }
    result = {"runs": rows, "median": summary}
    output = ROOT / "qa" / "performance.json"
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(output)


if __name__ == "__main__":
    run()
