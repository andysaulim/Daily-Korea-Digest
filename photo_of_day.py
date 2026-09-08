"""Pick and host one image for today's Korea brief.

Two problems have to be solved before a photo belongs in an email brief, and
both shape this module.

**Blocking.** Most mail clients suppress remote images by default, so a photo
that carries information the reader cannot get elsewhere is a photo half the
readership never sees. Everything here therefore travels with a caption and a
credit that stand on their own; the image is an enhancement, never the payload.

**Rights.** A wire photograph is licensed, and re-hosting one is not ours to
do. Candidates are ranked by how defensible their use is:

  1. Beyond Parallel and CSIS imagery — CSIS's own work.
  2. 38 North and other specialist satellite analysis — routinely credited and
     reproduced in policy writing.
  3. Official handouts (KCNA, the Presidential Office, ministries) — issued for
     publication, still credited.
  4. Everything else — not used. Wire photographs from Reuters, AP, AFP and
     Yonhap are deliberately excluded rather than hot-linked or copied.

That ranking is a judgement about what is defensible for an internally
distributed brief, not legal advice. If the brief ever goes external, this list
should be reviewed by someone who can make that call.

The image is copied into `public/` so the email references an asset the Korea
Chair controls, rather than hot-linking a publisher who may move, expire or
block it.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

# Ordered best-first. Matched against the article's source label and URL.
_PREFERRED = [
    (("beyondparallel", "beyond parallel", "csis.org"), "CSIS Beyond Parallel"),
    (("38north", "38 north"), "38 North"),
    (("aei.org", "accessdprk"), "AEI / AccessDPRK"),
    (("kcna", "rodong"), "KCNA"),
    (("president.go.kr", "korea.kr", "mofa.go.kr", "mnd.go.kr",
      "unikorea.go.kr"), "ROK government"),
]
# Never re-host from these, whatever the story.
_EXCLUDED = ("reuters.com", "apnews.com", "afp.com", "gettyimages",
             "bloomberg.com", "wsj.com", "nytimes.com", "ft.com",
             "washingtonpost.com", "yna.co.kr", "yonhap")

_IMG_EXT_RE = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
MAX_BYTES = 900_000
TIMEOUT = 8.0


def _candidate_image(article: dict) -> str:
    """Image URL an RSS entry advertised, if any."""
    for key in ("image_url", "media_content", "media_thumbnail", "enclosure_url"):
        value = article.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
        if isinstance(value, list) and value:
            first = value[0]
            url = first.get("url") if isinstance(first, dict) else first
            if isinstance(url, str) and url.startswith("http"):
                return url
    return ""


def _rank(article: dict) -> tuple[int, str] | None:
    """(preference index, credit) for a usable article, else None."""
    blob = f"{article.get('source', '')} {article.get('url', '')}".lower()
    if any(bad in blob for bad in _EXCLUDED):
        return None
    for i, (needles, credit) in enumerate(_PREFERRED):
        if any(n in blob for n in needles):
            return i, credit
    return None


def pick(articles) -> dict | None:
    """Choose today's image. Returns a dict or None when nothing qualifies.

    Returning None is the common case and an acceptable one — a brief with no
    defensible image simply has no photo that day.
    """
    best = None
    for article in articles or []:
        url = _candidate_image(article)
        if not url or not _IMG_EXT_RE.search(url):
            continue
        ranked = _rank(article)
        if not ranked:
            continue
        index, credit = ranked
        if best is None or index < best["rank"]:
            best = {
                "rank": index,
                "image_url": url,
                "credit": credit,
                "caption": (article.get("headline") or article.get("title") or "").strip(),
                "source_url": article.get("url", ""),
                "source": article.get("source", ""),
            }
    return best


def fetch_to_public(photo: dict, public_dir: Path, date_slug: str) -> dict:
    """Copy the image next to the archive so the email does not hot-link.

    On any failure the photo dict comes back without a local path and the
    caller renders the caption alone.
    """
    if not photo or not photo.get("image_url"):
        return photo or {}
    try:
        import requests
        resp = requests.get(photo["image_url"], timeout=TIMEOUT, stream=True,
                            headers={"User-Agent": "CSIS-Korea-Digest/1.0"})
        if resp.status_code != 200:
            return photo
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            return photo
        blob = resp.content
        if not blob or len(blob) > MAX_BYTES:
            return photo
        ext = ".jpg"
        path_ext = Path(urlparse(photo["image_url"]).path).suffix.lower()
        if path_ext in (".png", ".webp", ".jpeg", ".jpg"):
            ext = ".jpg" if path_ext == ".jpeg" else path_ext
        public_dir.mkdir(parents=True, exist_ok=True)
        name = f"photo_{date_slug}{ext}"
        (public_dir / name).write_bytes(blob)
        photo = dict(photo)
        photo["local_file"] = name
        photo["bytes"] = len(blob)
    except Exception:
        return photo
    return photo
