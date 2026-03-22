"""Generate tests_output/gallery.html — visual comparison of all test outputs."""

from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "tests_output"

GROUPS = [
    ("Edge CDP", "edge_cdp_"),
    ("Firefox BiDi", "firefox_bidi_"),
    ("Chrome CDP (existing)", "cdp_"),
    ("Issue 177 / Chrome", "issue177_"),
]


def build_gallery():
    images = sorted(OUTPUT_DIR.glob("*.png")) + sorted(OUTPUT_DIR.glob("*.jpg"))
    if not images:
        print("No images found in tests_output/")
        return

    def group_for(name):
        for label, prefix in GROUPS:
            if name.startswith(prefix):
                return label
        return "Other"

    grouped: dict[str, list[Path]] = {}
    for img in images:
        g = group_for(img.name)
        grouped.setdefault(g, []).append(img)

    sections = []
    for label, _ in GROUPS + [("Other", "")]:
        if label not in grouped:
            continue
        cards = []
        for img in grouped[label]:
            rel = img.name
            cards.append(f"""
        <figure>
          <img src="{rel}" loading="lazy" alt="{rel}">
          <figcaption>{rel}</figcaption>
        </figure>""")
        sections.append(f"""
  <section>
    <h2>{label}</h2>
    <div class="grid">{"".join(cards)}
    </div>
  </section>""")

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>html2image — backend gallery</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px 32px; background: #f5f5f5; color: #111; }}
    h1 {{ margin: 0 0 32px; }}
    h2 {{ margin: 32px 0 12px; font-size: 1.1rem; text-transform: uppercase; letter-spacing: .05em; color: #555; }}
    .grid {{ display: flex; flex-wrap: wrap; gap: 16px; }}
    figure {{ margin: 0; background: #fff; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }}
    figure img {{ display: block; max-width: 480px; max-height: 360px; width: auto; height: auto; }}
    figcaption {{ padding: 6px 10px; font-size: .78rem; color: #555; border-top: 1px solid #eee; }}
  </style>
</head>
<body>
  <h1>html2image — backend gallery</h1>
  {"".join(sections)}
</body>
</html>"""

    out = OUTPUT_DIR / "gallery.html"
    out.write_text(html, encoding="utf-8")
    print(f"Gallery written to {out}")


if __name__ == "__main__":
    build_gallery()
