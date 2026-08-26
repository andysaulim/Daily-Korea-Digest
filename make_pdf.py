"""
Render a Korea Daily Brief to PDF.

Two inputs supported:
  python make_pdf.py latest.html                 # an already-rendered email HTML
  python make_pdf.py digest_2026-07-24.json      # a digest JSON (rendered first)
  python make_pdf.py latest.html brief.pdf       # explicit output path

The email HTML is a 680px table layout built for inbox width; for print we keep
the design intact but let the wrapper breathe to the page width and force
background graphics on, so the navy panels and Taegukgi accents survive. Uses
the pre-installed Chromium via Playwright.
"""
import json
import sys
from pathlib import Path

# Print tweak injected before <body> close: relax the fixed email width so the
# brief fills the page instead of sitting as a narrow centered column, and make
# sure backgrounds print. Kept minimal — the email design is otherwise unchanged.
_PRINT_CSS = """
<style>
  @media print {
    html, body { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; background:#fff !important; }
    .wrapper { box-shadow: none !important; }
    a { text-decoration: none; }
    /* Let EVERYTHING flow across page breaks. Avoiding breaks on cards/rows
       pushes anything that doesn't fit to the next page, leaving big empty
       gaps — worse than a card occasionally splitting. */
    * { page-break-inside: auto !important; }
  }
  @page { size: Letter; margin: 9mm 10mm; }
</style>
"""


def html_from_input(path: Path) -> str:
    if path.suffix.lower() == ".json":
        digest = json.loads(path.read_text(encoding="utf-8"))
        from render import render
        html = render(digest)
    else:
        html = path.read_text(encoding="utf-8")
    # Inject print CSS just before </head> (or prepend if no head)
    if "</head>" in html:
        html = html.replace("</head>", _PRINT_CSS + "</head>", 1)
    else:
        html = _PRINT_CSS + html
    return html


def html_to_pdf(html: str, out_path: Path):
    from playwright.sync_api import sync_playwright
    chromium_path = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    with sync_playwright() as p:
        launch = {"args": ["--no-sandbox", "--disable-gpu"]}
        if Path(chromium_path).exists():
            launch["executable_path"] = chromium_path
        browser = p.chromium.launch(**launch)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(
            path=str(out_path),
            format="Letter",
            print_background=True,
            margin={"top": "9mm", "bottom": "9mm", "left": "10mm", "right": "10mm"},
        )
        browser.close()


def main():
    if len(sys.argv) < 2:
        print("usage: python make_pdf.py <latest.html | digest.json> [out.pdf]")
        return 1
    src = Path(sys.argv[1])
    if not src.exists():
        print(f"input not found: {src}")
        return 1
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    html = html_from_input(src)
    html_to_pdf(html, out)
    kb = out.stat().st_size / 1024
    print(f"✅  PDF written: {out} ({kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
