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


# The running header and footer are drawn outside the page's own document,
# so they see none of its stylesheet or web fonts: each names its own face
# and size. Chromium sets the template in the page margin at 1:1, unscaled,
# with `side` the horizontal inset that lines it up with the text column.
_RUN_FONT = "font-family:'Liberation Sans',Arial,sans-serif;font-size:8px;color:#5F6670;"


def _run_line(left: str, right: str, side: str, rule: str) -> str:
    return (f'<div style="box-sizing:border-box;width:100%;padding:0 {side};">'
            f'<div style="{_RUN_FONT}{rule}display:flex;justify-content:space-between;align-items:baseline;">'
            f'<span>{left}</span><span>{right}</span></div></div>')


def footer_template(text: str, side: str = "12mm") -> str:
    """Chromium's running footer: `text` on the left, "Page N of M" on the right, small and grey."""
    from html import escape
    return _run_line(escape(text), 'Page <span class="pageNumber"></span> of <span class="totalPages"></span>',
                     side, "padding-top:2mm;")


def header_template(left: str, right: str, side: str = "12mm") -> str:
    """Chromium's running header: `left` and `right` at either end of a hairline."""
    from html import escape
    return ('<div style="width:100%;padding-top:3.5mm;">'
            + _run_line(escape(left), escape(right), side, "padding-bottom:2px;border-bottom:0.5px solid #B8BEC7;")
            + '</div>')


def _first_page_from(plain: bytes, headed: bytes, out_path: Path) -> bool:
    """Write `headed` with its first page taken from `plain`; False when no PDF library is installed.

    Chromium draws a running header on every page or none. The two prints
    share margins and pagination, so page 1 of the one without a header
    drops in for page 1 of the one with it.
    """
    import io
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        try:
            import pymupdf as fitz                              # noqa: F401
        except ImportError:
            try:
                import fitz                                     # noqa: F401
            except ImportError:
                return False
        doc, first = fitz.open(stream=headed, filetype="pdf"), fitz.open(stream=plain, filetype="pdf")
        if len(doc) != len(first):
            return False
        doc.delete_page(0)
        doc.insert_pdf(first, from_page=0, to_page=0, start_at=0)
        doc.save(str(out_path))
        return True
    a, b = PdfReader(io.BytesIO(plain)), PdfReader(io.BytesIO(headed))
    if len(a.pages) != len(b.pages):
        return False
    w = PdfWriter()
    w.add_page(a.pages[0])
    for pg in b.pages[1:]:
        w.add_page(pg)
    with open(out_path, "wb") as f:
        w.write(f)
    return True


def html_to_pdf(html: str, out_path: Path, *, footer: str = "", margin: dict | None = None,
                wait_for_fonts: bool = False, scale: float = 1.0,
                header: tuple[str, str] | None = None, header_on_first: bool = False):
    """Print `html` to a Letter PDF with backgrounds.

    With no keyword arguments this is the list's PDF as it always was.
    `footer` is a running footer's text (footer_template adds the page
    numbers); `margin` replaces the default margins; `wait_for_fonts` waits
    for the page's web fonts, at most 15 seconds, before printing, so a
    font that is still loading does not print in its fallback. `scale`
    prints smaller (0.9 sets 14px type at about ten points).

    `header` is a running header's (left, right) text. It is left off page
    1, where the masthead says the same, unless `header_on_first`: the page
    is printed twice and page 1 taken from the print without it
    (_first_page_from). With no PDF library to do that, page 1 keeps the
    header above the masthead.
    """
    from playwright.sync_api import sync_playwright
    chromium_path = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
    with sync_playwright() as p:
        launch = {"args": ["--no-sandbox", "--disable-gpu"]}
        if Path(chromium_path).exists():
            launch["executable_path"] = chromium_path
        browser = p.chromium.launch(**launch)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        if wait_for_fonts:
            try:
                page.evaluate("() => Promise.race([document.fonts.ready.then(() => true),"
                              " new Promise(r => setTimeout(() => r(false), 15000))])")
            except Exception:                                   # noqa: BLE001
                pass
        margin = margin or {"top": "9mm", "bottom": "9mm", "left": "10mm", "right": "10mm"}
        opts = {"path": str(out_path), "format": "Letter", "print_background": True, "margin": margin}
        if scale != 1.0:
            opts["scale"] = scale
        side = margin.get("left", "12mm")
        if footer or header:
            opts.update(display_header_footer=True, header_template="<span></span>",
                        footer_template=footer_template(footer, side) if footer else "<span></span>")
        if header:
            plain = None if header_on_first else page.pdf(**{k: v for k, v in opts.items() if k != "path"})
            opts["header_template"] = header_template(header[0], header[1], side)
            headed = page.pdf(**{k: v for k, v in opts.items() if k != "path"})
            if plain is None or not _first_page_from(plain, headed, out_path):
                Path(out_path).write_bytes(headed)
        else:
            page.pdf(**opts)
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
