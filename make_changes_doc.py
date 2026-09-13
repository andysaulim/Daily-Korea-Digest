"""Generate CSIS_Digest_Presentation.docx — unified China + Korea + replication guide."""
from docx import Document
from docx.shared import Pt, RGBColor, Inches, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# Monochrome. Same structure as the China/Korea presentation deck, printed
# in black and white: NAVY becomes near-black, GOLD becomes mid-grey, and
# the table fills become greys that hold up on a mono laser printer.
NAVY  = RGBColor(0x11, 0x11, 0x11)   # headings, table header fill
GOLD  = RGBColor(0x66, 0x66, 0x66)   # cover eyebrow
GRAY  = RGBColor(0x44, 0x44, 0x44)   # body
RED   = RGBColor(0x00, 0x00, 0x00)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
MID   = RGBColor(0x80, 0x80, 0x80)   # meta


def set_cell_bg(cell, hex_color):
    tc = cell._tc
    tcPr = tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), hex_color)
    tcPr.append(shd)


def para(doc, text, bold=False, italic=False, size=11, color=None,
         align=None, space_before=0, space_after=6):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    if align:
        p.alignment = align
    run = p.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.size = Pt(size)
    if color:
        run.font.color.rgb = color
    return p


def heading(doc, text, level=1):
    sizes = {1: 17, 2: 13, 3: 11}
    p = para(doc, text, bold=True, size=sizes.get(level, 11), color=NAVY,
             space_before=16 if level == 1 else 10, space_after=4)
    if level == 1:
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bot = OxmlElement('w:bottom')
        bot.set(qn('w:val'), 'single'); bot.set(qn('w:sz'), '6')
        bot.set(qn('w:space'), '1'); bot.set(qn('w:color'), '111111')
        pBdr.append(bot); pPr.append(pBdr)
    return p


def bullet(doc, text, bold_prefix=None, level=0):
    p = doc.add_paragraph(style='List Bullet')
    p.paragraph_format.space_before = Pt(1)
    p.paragraph_format.space_after = Pt(3)
    p.paragraph_format.left_indent = Inches(0.25 + level * 0.2)
    if bold_prefix:
        r1 = p.add_run(bold_prefix + "  ")
        r1.bold = True; r1.font.size = Pt(10.5); r1.font.color.rgb = NAVY
    r2 = p.add_run(text)
    r2.font.size = Pt(10.5); r2.font.color.rgb = GRAY


def callout(doc, label, text, color=NAVY):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(10)
    p.paragraph_format.left_indent = Inches(0.2)
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    left = OxmlElement('w:left')
    left.set(qn('w:val'), 'single'); left.set(qn('w:sz'), '12')
    left.set(qn('w:space'), '6')
    left.set(qn('w:color'), '%02X%02X%02X' % (color[0], color[1], color[2]))
    pBdr.append(left); pPr.append(pBdr)
    r1 = p.add_run(label + "  ")
    r1.bold = True; r1.font.size = Pt(10); r1.font.color.rgb = color
    r2 = p.add_run(text)
    r2.font.size = Pt(10.5); r2.font.color.rgb = GRAY


def table(doc, headers, rows, col_widths=None):
    t = doc.add_table(rows=1 + len(rows), cols=len(headers))
    t.style = 'Table Grid'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for i, h in enumerate(headers):
        cell = t.rows[0].cells[i]
        set_cell_bg(cell, '111111')
        p = cell.paragraphs[0]
        run = p.add_run(h); run.bold = True
        run.font.size = Pt(9); run.font.color.rgb = WHITE
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(2)
    for ri, row in enumerate(rows):
        tr = t.rows[ri + 1]
        for ci, val in enumerate(row):
            cell = tr.cells[ci]
            if ri % 2 == 1:
                set_cell_bg(cell, 'F2F2F2')
            p = cell.paragraphs[0]
            bold = isinstance(val, tuple)
            text_val = val[0] if bold else val
            run = p.add_run(text_val)
            run.bold = bold and val[1]
            run.font.size = Pt(9.5)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(2)
    if col_widths:
        for i, w in enumerate(col_widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


# ── BUILD ────────────────────────────────────────────────────────────────────
# A point-in-time changelog, written to be read rather than looked up. The
# companion JAPAN_DIGEST_PRESENTATION.docx is the reference: it lists every
# feed and every section. This one answers a different question — what changed
# and why it mattered — for a reader who does not work on the code.

doc = Document()
for section in doc.sections:
    section.top_margin = Cm(2.0); section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.5); section.right_margin = Cm(2.5)

style = doc.styles['Normal']
style.font.name = 'Calibri'
style.font.size = Pt(10.5)

# ── COVER ────────────────────────────────────────────────────────────────────
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(30)
r = p.add_run("CSIS DAILY BRIEFS")
r.font.size = Pt(10); r.font.color.rgb = GOLD; r.bold = True

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("What Changed")
r.font.size = Pt(30); r.font.color.rgb = NAVY; r.bold = True

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(4)
r = p.add_run("Korea  ·  Japan  ·  China  ·  Australia")
r.font.size = Pt(15); r.font.color.rgb = GRAY

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(26)
r = p.add_run("Two weeks of work on four daily briefs, in six parts")
r.font.size = Pt(11); r.font.color.rgb = MID; r.italic = True

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Prepared by Andy Lim  ·  September 2026")
r.font.size = Pt(10); r.font.color.rgb = MID

doc.add_page_break()

# ── SUMMARY ──────────────────────────────────────────────────────────────────
heading(doc, "The short version")
para(doc,
     "Four briefs — Korea, Japan, China, Australia — went from four separate "
     "products that happened to share an author to one publication with four "
     "editions. Most of the work fell into six areas. Each is a page.",
     size=11, color=GRAY, space_after=10)

table(doc,
    ["", "What was wrong", "Where it stands"],
    [
        (("1. Delivery", True), "Briefs sent twice, sent at midnight, or did not send at all",
         "One send a day, at the intended hour"),
        (("2. One look", True), "Four briefs that did not look related",
         "One masthead, one subject line, one archive, one set of sections"),
        (("3. Dark mode", True), "Text the same colour as its background for some readers",
         "Every colour has a dark counterpart, checked automatically"),
        (("4. Accuracy", True), "Claims a reader could not check",
         "An item that cannot be traced to a source is dropped, not printed"),
        (("5. The archive", True), "Every run erased the list of past issues",
         "The history is read before it is written, and cannot be overwritten blind"),
        (("6. Cost", True), "No record of what any of it cost",
         "Every run records its own cost; a weekly sheet covers all five"),
    ],
    col_widths=[1.3, 2.6, 2.4]
)

callout(doc, "The through-line:",
        "Most of these were not features anyone asked for. They were faults found by "
        "reading what actually shipped, or reported by a reader. The pattern worth "
        "noting is that almost none of them announced themselves — a brief that sends "
        "twice, or loses its archive, or renders white-on-white, reports success.")

# ── 1 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "1.  Delivery")
para(doc,
     "A daily brief has one job before any other: arrive once, in the morning. All "
     "four failed that at least once in the past two weeks, each for a different "
     "reason.",
     size=11, color=GRAY, space_after=8)

table(doc,
    ["What happened", "Why", "Fixed by"],
    [
        ("Japan mailed the list four times in one morning",
         "A commit message mentioning the phrase that triggers a live send was read as the trigger",
         "Only the subject line of a commit is read, not the body"),
        ("Japan went out at 00:44",
         "Nothing checked the hour before mailing",
         "A floor: nothing reaches the list before the delivery hour"),
        ("Australia stopped sending entirely for a morning",
         "That floor was set above the only trigger that fires on time",
         "The floor moved below it"),
        ("Australia sent twice yesterday",
         "The check for \"already sent today\" ran before the code was downloaded, so it could never find the record",
         "The download runs first; the record is saved on its own, immediately"),
        ("Korea did not send at 7 AM",
         "A design check measured one caption as too small and cancelled the whole brief",
         "Design checks report; only code failures can stop a send"),
    ],
    col_widths=[2.1, 2.3, 1.9]
)

callout(doc, "The rule that came out of it:",
        "A check may cancel the brief only if it tests the code. Anything that measures "
        "the day's content — contrast, layout, length — reports and lets the brief go. "
        "A brief that does not arrive is a worse outcome than a brief with a small "
        "caption.")

para(doc,
     "All four now deliver at 7:00 AM ET, with fallback runs behind the primary trigger "
     "and a guard that makes each fallback a no-op once the brief has gone out. "
     "Australia is at 6:00 AM until its external scheduler is repointed; raising its "
     "floor before moving that schedule is what broke it once already.",
     size=10.5, color=GRAY, space_after=6, space_before=6)

# ── 2 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "2.  One look across the four")
para(doc,
     "The four briefs were built one after another, so each carried the habits of the "
     "week it was written. Opened side by side they did not read as the same "
     "publication. That is now fixed at the level of the shared code, not by editing "
     "four files to match.",
     size=11, color=GRAY, space_after=8)

table(doc,
    ["Element", "Before", "Now"],
    [
        ("Subject line", "Four different shapes, some with the summary appended",
         "Name first, then the date: \"Japan Daily Brief | Thursday, September 10, 2026\""),
        ("Masthead", "Different colours, alignments and type sizes",
         "One band, each edition's own colour, same structure"),
        ("Section headings", "Coloured type over a hairline rule",
         "A black bar with an accent ring — a hard stop between sections"),
        ("Archive page", "Korea had a searchable archive; the others had a landing page",
         "One archive page, built from one module, searchable in all four"),
        ("Overnight items", "Headline and summary run together in a paragraph",
         "Headline on one line, summary on the next"),
        ("Market moves", "Direction shown by an arrow only",
         "Green up, red down, in every edition"),
        ("Footer", "Two and three lines, worded differently",
         "One line, same wording"),
        ("Frame width", "Varied by edition",
         "680 pixels everywhere, capped the same way on a tablet"),
    ],
    col_widths=[1.3, 2.5, 2.5]
)

para(doc,
     "The Korea \"Week in Review\" was the last holdout. It predated the redesign and "
     "kept the older look — a gold accent the daily uses nowhere, a green-black panel "
     "where the daily's is navy, no dark mode. Rather than restate the palette, it now "
     "imports it from the daily renderer, so the two cannot drift apart again.",
     size=10.5, color=GRAY, space_after=6, space_before=6)

# ── 3 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "3.  Dark mode")
para(doc,
     "A reader whose mail client is set to dark mode sees a different brief. Colours "
     "chosen against white do not survive the switch, and nothing complains — absent "
     "styling is not an error, so a section can render as near-black text on a "
     "near-black ground and every check still passes.",
     size=11, color=GRAY, space_after=8)

callout(doc, "What now catches it:",
        "A check that reads every colour out of the finished brief and fails if any of "
        "them has no dark counterpart. It runs on every build, so a colour added today "
        "cannot reach a reader tomorrow without one.")

table(doc,
    ["Found", "Reading", "Status"],
    [
        ("China's market arrows rendered white in dark mode",
         "Invisible on a white ground",
         "Fixed"),
        ("Korea's polling sparkline was unreadable in one mode or the other",
         "Below the legibility threshold either way",
         "Replaced with a plain trend line"),
        ("The buttons in the footer went dark on dark",
         "1.23 to 1, against a 4.5 to 1 standard",
         "Fixed"),
        ("A caption in Korea's polling section",
         "2.55 to 1 at 9 pixels",
         "Fixed — and it was this that cancelled a send"),
        ("Australia's third accent colour had no dark rule at all",
         "2.1 to 1",
         "Fixed"),
    ],
    col_widths=[2.6, 1.9, 1.7]
)

para(doc,
     "The briefs also now declare which colour schemes they support, so a mail client "
     "stops guessing and inverting things itself.",
     size=10.5, color=GRAY, space_after=6, space_before=6)

# ── 4 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "4.  Accuracy")
para(doc,
     "The governing rule in all four briefs is that every claim traces to an article "
     "collected that morning. Two things were quietly undermining it.",
     size=11, color=GRAY, space_after=8)

para(doc, "A story with no link", bold=True, size=12, color=NAVY, space_after=3)
para(doc,
     "A reader spotted a Japan item attributed to the Washington Post with no "
     "hyperlink. The link checker had done its job — it could not match the address to "
     "anything collected that morning — but it removed the link and kept the story. "
     "That published the problem instead of catching it: the attribution stayed, and "
     "now nothing behind it could be checked. An item that cannot be traced is now "
     "dropped, after one attempt to recover the right link from the same publisher.",
     size=10.5, color=GRAY, space_after=8)

para(doc, "Formatting marks printed as text", bold=True, size=12, color=NAVY, space_after=3)
para(doc,
     "The model marks names for emphasis. In several places those marks were being "
     "printed literally, so readers saw raw markup in the middle of a sentence. Every "
     "field that carries prose now runs through the same conversion, and a check "
     "asserts it by reading the renderer itself rather than a test fixture — the "
     "earlier test passed while the fault was live.",
     size=10.5, color=GRAY, space_after=8)

table(doc,
    ["Also fixed", "What it was"],
    [
        ("Japan: a minister's surname with no first name",
         "The brief had no roster to complete it from; the BOJ Policy Board was added"),
        ("Japan: two-month-old polling numbers",
         "Poll dates are now checked before use, and an old poll is dropped rather than printed"),
        ("Australia: \"annual, venue alternates 2026\" in the calendar",
         "A description of how often an event recurs was being stamped as a date"),
        ("Korea: a thin Upcoming section",
         "The model now looks for dated events in the day's own reporting first"),
        ("Korea: length",
         "The band moved to 2,500-2,750 words, since quality mattered more than the cap"),
    ],
    col_widths=[2.5, 3.7]
)

# ── 5 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "5.  The archive")
para(doc,
     "Every issue is published to a web archive with a PDF beside it, and an index "
     "lists them. The index was being destroyed on every run, in all four briefs, for "
     "months.",
     size=11, color=GRAY, space_after=8)

para(doc,
     "The mechanism is worth understanding because it is the kind of fault that hides. "
     "The published folder is not kept in the code repository, and each run starts on a "
     "clean machine. So code that opened the index, found nothing, started an empty "
     "list, added today and saved it did exactly what it was written to do — and "
     "replaced a list of every past issue with a list of one. The deploy keeps files it "
     "is not publishing and overwrites the ones it is, so today's issue was always "
     "fine. Only the list was lost, and nothing reports a lost list.",
     size=10.5, color=GRAY, space_after=8)

callout(doc, "The rule now:",
        "Read the published copy first, and if that read fails, write nothing. Skipping "
        "the index costs one day of listing. Writing one built without the history "
        "costs every day before it.")

para(doc,
     "That held until Australia's web hosting turned out to be switched off. A request "
     "for a file that does not exist and a request to a site that is not running both "
     "answer the same way, so the guard read \"this file does not exist yet\" and wrote "
     "the one-day list anyway. It now asks for a file that must exist before believing "
     "either answer, and Australia's archive carries a checked-in floor of all fifteen "
     "published issues, so the history restores itself.",
     size=10.5, color=GRAY, space_after=8)

table(doc,
    ["Brief", "Archive index", "Note"],
    [
        ("Korea", "170 issues", "Intact throughout"),
        ("Japan", "Intact", ""),
        ("China", "Intact", ""),
        ("Australia", "Restored to 15", "Web hosting was off; now on"),
    ],
    col_widths=[1.3, 2.0, 2.9]
)

# ── 6 ────────────────────────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "6.  Cost")
para(doc,
     "Until last week nothing recorded what any of this cost. The model charges by the "
     "amount of text in and out, which varies daily with how much news there is, so an "
     "estimate made once is wrong by the following week.",
     size=11, color=GRAY, space_after=8)

para(doc,
     "Each run now writes its own token counts to a file that is committed, not left on "
     "the machine — job logs expire and would take the spend history with them. A "
     "weekly sheet collects every edition, including the Middle East brief, and needs "
     "no credentials to do it.",
     size=10.5, color=GRAY, space_after=8)

para(doc,
     "The figures below are measured, not estimated, and they are further apart than "
     "expected. Cost tracks how much news there is to read and how much the brief "
     "writes about it, so the wider editions cost several times the narrower ones.",
     size=10.5, color=GRAY, space_after=6)

table(doc,
    ["Edition", "Per issue", "Runs measured", "Implied monthly"],
    [
        ("Australia", "$1.55", "12", "About $34"),
        ("China", "$0.90", "14", "About $20"),
        ("Middle East", "$0.66", "4", "About $14"),
        ("Japan", "$0.40", "1", "About $9"),
        ("Korea", ("not recording", True), "0", ("unknown", True)),
        (("Four measured editions", True), "", "", ("About $77 a month", True)),
    ],
    col_widths=[1.4, 1.1, 1.4, 2.3]
)

callout(doc, "Two caveats, both real:",
        "The samples are short — Japan's figure rests on a single run — so treat the "
        "monthly column as an extrapolation that will become a measurement in a month. "
        "And Korea is not recording at all: the code is in place and the file has never "
        "reached the repository, which is being chased. Everything else here — the "
        "hosting, the scheduling, the email, the archive — is free.")

# ── WHAT IS STILL OPEN ───────────────────────────────────────────────────────
doc.add_page_break()
heading(doc, "Still open")
para(doc,
     "Honest list, in the order I would take them.",
     size=11, color=GRAY, space_after=8)

table(doc,
    ["", "What", "Why it matters"],
    [
        (("1", True), "Japan's sources depend on a search engine",
         "86 of 116 feeds have no publisher feed behind them, including almost all think-tank and academic sources. One change upstream takes most of two tiers at once, silently."),
        (("2", True), "Two Japanese dailies have been silent for two months",
         "Mainichi and Jiji have not appeared since July. A source that stops delivering does not announce it."),
        (("3", True), "The Middle East brief's once-a-day guard rides a 40 MB file",
         "It works, but the record of \"already sent\" is carried by a large binary push with no retry. The other four now use a small marker instead."),
        (("4", True), "Australia's schedule",
         "It delivers at 6 AM, not 7, until its external scheduler is repointed. The order matters: move the schedule first, then the floor."),
        (("5", True), "Japan and China have no weekly",
         "Korea and Australia do. Building one is a synthesis job, not a formatting job."),
    ],
    col_widths=[0.4, 2.2, 3.6]
)

# ── CLOSE ────────────────────────────────────────────────────────────────────
doc.add_page_break()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(50)
r = p.add_run("CSIS Daily Briefs")
r.font.size = Pt(12); r.font.color.rgb = NAVY; r.bold = True

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_after = Pt(20)
r = p.add_run("Korea  ·  Japan  ·  China  ·  Australia  ·  Middle East")
r.font.size = Pt(11); r.font.color.rgb = GRAY

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Prepared by Andy Lim  ·  September 2026")
r.font.size = Pt(10); r.font.color.rgb = MID

doc.save("CSIS_Briefs_What_Changed.docx")
print("Saved CSIS_Briefs_What_Changed.docx")
