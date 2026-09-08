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
  body {{ margin:0; background:#EEF1F4; }}
  .wrap {{ max-width:760px; margin:0 auto; background:#fff; }}
  @media (max-width:640px) {{ .pad {{ padding-left:20px !important; padding-right:20px !important; }} }}
</style></head>
<body>
<div class="wrap">
  <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{BAND};">
    <tr><td class="pad" style="padding:7px 32px 8px;font-family:{SANS};font-size:11px;font-weight:700;letter-spacing:2.5px;text-transform:uppercase;color:#fff;">CSIS Korea Chair</td></tr>
  </table>
  <div class="pad" style="background:{NAVY};color:#fff;padding:20px 32px 18px;">
    <h1 style="margin:0 0 4px;font-family:{SERIF};font-size:26px;font-weight:700;">US–Korea Trade Reference</h1>
    <div style="font-family:{SERIF};font-size:15px;color:rgba(255,255,255,0.85);">Standing status &middot; rebuilt daily</div>
  </div>
  <div class="pad" style="padding:18px 32px 8px;font-family:{SANS};font-size:12px;line-height:1.6;color:#6B7280;border-bottom:1px solid #E4E7EB;">
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
    <div style="margin-top:10px;line-height:1.55;">
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
