"""Per-edition branding for the CSIS daily briefs.

This is the ONLY file that differs between the Korea, China, Japan, and
Australia repositories. masthead.py is byte-identical everywhere and reads
everything region-specific from BRAND below.

Keys, and the rule for each:
  chair            Kicker above the title. "CSIS <Region> Chair".
  title            Masthead headline. "<Region> Daily Brief".
  navy             Masthead ground. Each chair keeps its own navy.
  accent           RE: label, disclaimer underline. The edition's accent.
  kicker_color     Kicker text. Muted white by default; an edition may use
                   its accent instead (Japan does).
  title_mark       Optional glyph before the title (Japan's rising-sun dot).
                   Leave "" for none.
  top_rule         Optional flag rule above the masthead. "" for none.
  re_rule          Hairline above the RE: line.
  bar_bg           Link-bar ground (light grey in every edition).
  link_color       Link-bar link color.
  disclaimer_bg    Disclaimer ground. Darkest navy in the palette.
  mono             Monospace stack for the run meta.
  contact_name     Name in the disclaimer.
  contact_email    Mailto in the disclaimer.

Only these values change. If an edition needs a structural change to the
banner, make it in masthead.py and copy that file to all four repos.
"""

TAEGUK_RED = "#CD2E3A"
TAEGUK_BLUE = "#0047A0"

BRAND = {
    "chair": "CSIS Korea Chair",
    "title": "Korea Daily Brief",
    "navy": "#072B52",
    "accent": "#E8697A",
    "kicker_color": "rgba(255,255,255,0.65)",
    "title_mark": "",
    "top_rule": (
        f'<div style="height:3px;background:{TAEGUK_RED};font-size:0;line-height:0;">&nbsp;</div>'
        f'<div style="height:3px;background:{TAEGUK_BLUE};font-size:0;line-height:0;">&nbsp;</div>'
    ),
    "re_rule": "rgba(205,46,58,0.45)",
    "bar_bg": "#F0F0F0",
    "link_color": "#2980B9",
    "disclaimer_bg": "#03142A",
    "mono": "'Courier New',Courier,monospace",
    "contact_name": "Andy Lim",
    "contact_email": "alim@csis.org",
}
