"""Build the standing US–Korea trade reference page.

The pledge tracker, the bilateral investment ledger and the standing policy
watch all move at monthly cadence at best. Carried in every issue they made
Trade & Investment the longest section in the brief by double, and buried the
tariff status — the one part that actually changes day to day.

They live here instead: one page, rebuilt on every run so it is never stale,
linked from the daily brief. Nothing is lost; it stops competing for attention
with the news.

The page reuses the blocks `render.py` already built, so there is one
implementation of each and no chance of the two drifting apart.

Its own frame has to be kept in step by hand, and was not: the brief moved to
a blue nameplate and this page kept the navy one it replaced, so a reader
following the link arrived somewhere that looked like a different product.
Match any masthead change here as well.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

NAVY = "#1B2A4A"
BAND = "#0052B4"
SERIF = "Georgia,'Times New Roman',serif"
SANS = "Arial,Helvetica,sans-serif"


def build(standing_html: str, *, date_str: str = "", web_base: str = "") -> str:
    """Return the full standing page. Empty input still produces a valid page
    saying so, rather than a broken link from the daily brief."""
    generated = datetime.now(ZoneInfo("America/New_York")).strftime("%B %-d, %Y at %-I:%M %p ET")
    body = standing_html or (
        f'<p style="font-family:{SERIF};font-size:15px;color:#6B7280;">'
        f'No standing trade reference was available in the most recent run.</p>')
    back = ""
    if web_base:
        back = (f'<a href="{web_base}latest.html" style="color:{BAND};'
                f'text-decoration:none;">&#8592; Back to today\'s brief</a>')
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>US–Korea Trade Reference · CSIS Korea Chair</title>
<style>
  /* The page set no font, so every node without its own declaration fell to
     the browser default serif: 73 of them rendered in Times New Roman, and
     the page carried five faces where the brief carries three. Inherit the
     house sans; the explicit Georgia and monospace declarations still win. */
  body {{ margin:0; background:#EEF1F4; font-family:{SANS}; }}
  .wrap {{ max-width:760px; margin:0 auto; background:#fff; }}
  @media (max-width:640px) {{ .pad {{ padding-left:20px !important; padding-right:20px !important; }} }}
</style></head>
<body>
<div class="wrap">
  <div class="pad" style="background:{BAND};color:#fff;padding:16px 32px 16px;">
    <div style="font-family:{SANS};font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:rgba(255,255,255,0.78);margin-bottom:7px;">CSIS Korea Chair</div>
    <h1 style="margin:0 0 4px;font-family:{SERIF};font-size:26px;font-weight:700;">US&ndash;Korea Trade Reference</h1>
    <div style="font-family:{SERIF};font-size:15px;color:rgba(255,255,255,0.85);">Standing status &middot; rebuilt daily</div>
  </div>
  <div class="pad" style="padding:18px 32px 12px;font-family:{SERIF};font-size:13px;line-height:1.65;color:#4A5260;border-bottom:1px solid #E4E7EB;">
    The investment ledger, pledge tracker and standing policy measures below change
    monthly at most. They are published here rather than in the daily brief so the
    brief can carry what changed today. This page is regenerated on every run.
    {f'<br>Last rebuilt {generated}.' if generated else ''}
  </div>
  <div class="pad" style="padding:20px 32px 28px;">
    {body}
  </div>
  <div class="pad" style="padding:16px 32px 22px;border-top:1px solid #E4E7EB;font-family:{SANS};font-size:11.5px;color:#9AA3AE;">
    {back}
    <div style="font-family:{SERIF};font-size:12px;margin-top:10px;line-height:1.6;">
      This page is automatically generated, so it may contain errors. Please check all
      information and sources before citing. To report errors or other issues, please
      contact Andy Lim at <a href="mailto:alim@csis.org" style="color:{BAND};">alim@csis.org</a>.
    </div>
  </div>
</div>
</body></html>"""


def write(standing_html: str, public_dir: Path, *, web_base: str = "") -> Path | None:
    """Write trade.html next to the archive. Never raises."""
    try:
        public_dir.mkdir(parents=True, exist_ok=True)
        path = public_dir / "trade.html"
        path.write_text(build(standing_html, web_base=web_base), encoding="utf-8")
        return path
    except OSError:
        return None
