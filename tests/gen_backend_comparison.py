"""Generate a side-by-side visual comparison of all backends.

Runs the same scenarios on every available backend, writes images to
tests_output/comparison/, then builds tests_output/comparison.html.

Usage:
    uv run tests/gen_backend_comparison.py
"""

from html2image import Html2Image
from pathlib import Path
import json

OUTPUT_DIR = Path(__file__).parent.parent / "tests_output" / "comparison"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

BACKENDS = [
    "chrome-cdp",
    "chrome-headless",
    "edge",
    "edge-cdp",
    "firefox-bidi",
    "firefox-headless",
]

RICH_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html, body { width: 100%; height: 100%; }
    body {
      display: flex;
      align-items: center;
      justify-content: center;
      background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
      font-family: Georgia, "Times New Roman", serif;
    }
    .card {
      width: 680px;
      padding: 40px 48px;
      border-radius: 20px;
      background: rgba(255,255,255,0.07);
      border: 1px solid rgba(255,255,255,0.15);
      box-shadow: 0 24px 60px rgba(0,0,0,0.4);
      color: #fff;
    }
    .badge {
      display: inline-block;
      padding: 4px 14px;
      border-radius: 100px;
      background: #e94560;
      font-size: 13px;
      letter-spacing: .06em;
      text-transform: uppercase;
      margin-bottom: 18px;
    }
    h1 { font-size: 38px; line-height: 1.2; margin-bottom: 14px; }
    p  { font-size: 17px; line-height: 1.6; color: rgba(255,255,255,0.75); margin-bottom: 24px; }
    .row { display: flex; gap: 12px; }
    .chip {
      flex: 1;
      padding: 14px 18px;
      border-radius: 12px;
      background: rgba(255,255,255,0.1);
      text-align: center;
      font-size: 13px;
      color: rgba(255,255,255,0.8);
    }
    .chip strong { display: block; font-size: 22px; color: #fff; margin-bottom: 2px; }
  </style>
</head>
<body>
  <div class="card">
    <span class="badge">html2image</span>
    <h1>Backend comparison</h1>
    <p>Same HTML, rendered by every available backend.
       Font rendering, gradient accuracy, and layout consistency
       are all visible here.</p>
    <div class="row">
      <div class="chip"><strong>PNG</strong>lossless</div>
      <div class="chip"><strong>800×450</strong>viewport</div>
      <div class="chip"><strong>CSS3</strong>gradients</div>
    </div>
  </div>
</body>
</html>"""

SCENARIOS = [
    {
        "name": "rich_html",
        "label": "Rich HTML string",
        "description": "Custom HTML with gradient, card layout, CSS3 — good for font & color comparison.",
        "kwargs": {"html_str": RICH_HTML, "size": (800, 450)},
        "ext": "png",
    },
    {
        "name": "html_file",
        "label": "HTML file (blue_page.html)",
        "description": "Simple blue page from the examples directory.",
        "kwargs": {"html_file": "./examples/blue_page.html", "css_file": "./examples/blue_background.css", "size": (800, 450)},
        "ext": "png",
    },
    {
        "name": "url_example",
        "label": "URL — example.com",
        "description": "Live URL fetch — tests network + rendering consistency.",
        "kwargs": {"url": "https://www.example.com", "size": (800, 450)},
        "ext": "png",
    },
    {
        "name": "svg_alpha",
        "label": "SVG with transparent background",
        "description": "star.svg — top-left pixel should be transparent (alpha=0). BiDi backends may show opaque white.",
        "kwargs": {"other_file": "./examples/star.svg", "size": (400, 400)},
        "ext": "png",
    },
    {
        "name": "jpeg_output",
        "label": "JPEG output",
        "description": "Same rich HTML saved as JPEG. Firefox CLI may produce PNG regardless of extension.",
        "kwargs": {"html_str": RICH_HTML, "size": (800, 450)},
        "ext": "jpg",
    },
]


def run_scenario(browser_name, scenario):
    """Run one scenario with one backend. Returns image path or None on skip/error."""
    filename = f"{scenario['name']}__{browser_name.replace('-', '_')}.{scenario['ext']}"
    output_path = OUTPUT_DIR / filename

    try:
        hti = Html2Image(
            browser=browser_name,
            output_path=str(OUTPUT_DIR),
            disable_logging=True,
        )
    except FileNotFoundError:
        return None, "browser not found"

    kwargs = dict(scenario["kwargs"])
    kwargs["save_as"] = filename

    try:
        hti.screenshot(**kwargs)
        if output_path.exists() and output_path.stat().st_size > 0:
            return str(output_path), "ok"
        return None, "no output produced"
    except Exception as exc:
        return None, str(exc)


def build_comparison_html(results):
    """Build an HTML table: rows = scenarios, columns = backends."""

    # Table header
    header_cells = "<th>Scenario</th>" + "".join(
        f"<th>{b}</th>" for b in BACKENDS
    )

    rows = []
    for scenario in SCENARIOS:
        cells = [f'<td class="scenario-label"><strong>{scenario["label"]}</strong><br><span>{scenario["description"]}</span></td>']
        for backend in BACKENDS:
            path, status = results[scenario["name"]][backend]
            if path:
                rel = Path(path).name
                cells.append(f'<td class="img-cell"><img src="comparison/{rel}" alt="{rel}" loading="lazy"><div class="status ok">✓</div></td>')
            else:
                cells.append(f'<td class="img-cell empty"><div class="status skip">{status}</div></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>html2image — backend comparison</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px 32px; background: #f0f0f0; color: #111; font-size: 14px; }}
    h1 {{ margin: 0 0 8px; }}
    p.subtitle {{ color: #555; margin: 0 0 24px; }}
    table {{ border-collapse: collapse; width: 100%; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,.1); }}
    th {{ background: #222; color: #fff; padding: 10px 14px; text-align: center; font-size: 13px; white-space: nowrap; }}
    th:first-child {{ text-align: left; }}
    td {{ border: 1px solid #e0e0e0; vertical-align: top; padding: 0; }}
    td.scenario-label {{ padding: 12px 16px; min-width: 180px; max-width: 220px; background: #fafafa; vertical-align: middle; }}
    td.scenario-label strong {{ display: block; margin-bottom: 4px; }}
    td.scenario-label span {{ color: #666; font-size: 12px; line-height: 1.4; }}
    td.img-cell {{ text-align: center; padding: 8px; min-width: 120px; position: relative; }}
    td.img-cell img {{ max-width: 280px; max-height: 200px; width: auto; height: auto; display: block; margin: 0 auto; border: 1px solid #ddd; background: repeating-conic-gradient(#ccc 0% 25%, #fff 0% 50%) 0 0 / 16px 16px; }}
    td.img-cell.empty {{ background: #fafafa; }}
    .status {{ font-size: 11px; margin-top: 4px; text-align: center; }}
    .status.ok {{ color: #2a7a2a; }}
    .status.skip {{ color: #999; padding: 16px; }}
    tr:hover td {{ background: #f5f8ff; }}
    tr:hover td.scenario-label {{ background: #edf1ff; }}
  </style>
</head>
<body>
  <h1>html2image — backend comparison</h1>
  <p class="subtitle">Same scenarios, every available backend. Checkered background reveals transparent pixels.</p>
  <table>
    <thead><tr>{header_cells}</tr></thead>
    <tbody>{"".join(rows)}</tbody>
  </table>
</body>
</html>"""

    out = OUTPUT_DIR.parent / "comparison.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nGallery written: {out}")
    return out


def main():
    results = {s["name"]: {} for s in SCENARIOS}

    for scenario in SCENARIOS:
        print(f"\n-- {scenario['label']} --")
        for backend in BACKENDS:
            path, status = run_scenario(backend, scenario)
            results[scenario["name"]][backend] = (path, status)
            icon = "OK" if path else "KO"
            print(f"  {icon}  {backend:<22} {status}")

    out = build_comparison_html(results)
    print(f"\nOpen in browser: {out}")

    summary = {s["name"]: {b: r[1] for b, r in results[s["name"]].items()} for s in SCENARIOS}
    (OUTPUT_DIR.parent / "comparison_results.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
