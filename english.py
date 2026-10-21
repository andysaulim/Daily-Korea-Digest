"""Keep Korean script, and em dashes, out of what the reader sees.

The brief is written in English for American readers. Korean reached the page
three ways: outlet names taken from Korean-language feeds (뉴시스, 동아일보),
Korean headlines pasted into source fields, and Korean labels the schema asked
for (ministry_korean). The one place Korean belongs is a direct quote, and
only when its English translation sits beside it.

`apply` rewrites the digest in place before render and audio: outlet names to
their English names, Korean headlines dropped from source fields, Korean-only
label fields removed. Body text is not rewritten: anything Korean left there
that is not a translated quote is returned as a warning, so the model's text
stays what it wrote against its sources. Nothing here raises.
"""
from __future__ import annotations

import re

HANGUL = re.compile(r"[ㄱ-ㆎ가-힣]")

# Korean-language outlets by the English names they use themselves.
OUTLETS = {
    "연합뉴스": "Yonhap", "연합뉴스TV": "Yonhap News TV", "뉴시스": "Newsis", "뉴스1": "News1",
    "조선일보": "Chosun Ilbo", "중앙일보": "JoongAng Ilbo", "동아일보": "Dong-A Ilbo",
    "한겨레": "Hankyoreh", "경향신문": "Kyunghyang Shinmun", "한국일보": "Hankook Ilbo",
    "서울신문": "Seoul Shinmun", "국민일보": "Kookmin Ilbo", "문화일보": "Munhwa Ilbo",
    "세계일보": "Segye Ilbo", "매일경제": "Maeil Business", "한국경제": "Korea Economic Daily",
    "서울경제": "Seoul Economic Daily", "머니투데이": "Money Today", "아시아경제": "Asia Economy",
    "이데일리": "Edaily", "헤럴드경제": "Herald Economy", "파이낸셜뉴스": "Financial News",
    "프레시안": "Pressian", "오마이뉴스": "OhmyNews", "노컷뉴스": "Nocut News",
    "KBS뉴스": "KBS", "MBC뉴스": "MBC", "SBS뉴스": "SBS", "채널A": "Channel A",
    "대통령실": "Presidential Office", "청와대": "Presidential Office", "외교부": "MOFA",
    "국방부": "MND", "통일부": "Unification Ministry", "합동참모본부": "Joint Chiefs",
    "합참": "Joint Chiefs", "기획재정부": "Finance Ministry", "산업통상자원부": "MOTIE",
    "방위사업청": "DAPA", "국회": "National Assembly", "한국은행": "Bank of Korea",
    "통계청": "Statistics Korea", "관세청": "Korea Customs", "정책브리핑": "korea.kr",
    "갤럽": "Gallup Korea", "한국갤럽": "Gallup Korea", "노동신문": "Rodong Sinmun",
    "조선중앙통신": "KCNA", "조선중앙TV": "KCTV", "우리민족끼리": "Uriminzokkiri",
}
_BY_LENGTH = sorted(OUTLETS, key=len, reverse=True)

# Fields that name a source or carry a label rather than prose.
_LABEL_KEYS = {"source", "source_label", "src_line", "outlet", "publisher", "label",
               "name", "secondary_label", "via"}
# Fields that exist only to hold Korean; the English field beside them is kept.
_KOREAN_ONLY = {"ministry_korean", "party_kr", "title_kr", "headline_kr", "name_kr"}
# A quoted Korean headline inside a source field: 뉴시스 — '대중·대미 …'
_QUOTED = re.compile(r"""\s*[—–:-]?\s*['"‘“「『][^'"’”」』]*[ㄱ-ㆎ가-힣][^'"’”」』]*['"’”」』]""")


def outlet(name: str) -> str:
    """One label in English: known outlets mapped, other Korean words dropped."""
    s = str(name or "")
    if not HANGUL.search(s):
        return s
    s = _QUOTED.sub("", s)
    for ko in _BY_LENGTH:
        s = s.replace(ko, OUTLETS[ko])
    if HANGUL.search(s):
        # A Korean headline or description with no quotes around it: keep
        # whatever English came before it ("Newsis — 대중…" → "Newsis").
        s = re.split(r"\s+[—–]\s+|\s*:\s+", s)[0] if HANGUL.search(s.split(" — ")[-1]) else s
        s = HANGUL.sub("", s)
    return re.sub(r"\s{2,}", " ", s).strip(" ·—–-;,/")


_DASH = re.compile(r"\s*[\u2014\u2015]\s*|\s+[\u2013]\s+|\s+--\s+")


def dashes(text: str) -> str:
    """Em dashes (and spaced en dashes) between words become commas.

    A bare dash standing for a missing value is left alone, as are en dashes
    in ranges (1,900\u20132,200, Jan\u2013Sep), which have no spaces around them.
    """
    s = str(text or "")
    if not re.search(r"[A-Za-z0-9].*[\u2014\u2015\u2013-].*[A-Za-z0-9]", s):
        return s
    s = _DASH.sub(", ", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r",\s*([.;:!?)])", r"\1", s)
    return re.sub(r"^\s*,\s*|\s*,\s*$", "", s)


_GLOSS = re.compile(r"\s*\(([^()]*[\u3131-\u318E\uAC00-\uD7A3][^()]*)\)")


def glosses(text: str) -> str:
    """Drop Korean glosses in brackets: '(중대범죄수사청 / SCIA)' -> '(SCIA)', '(소추)' -> ''."""
    def one(m):
        rest = HANGUL.sub("", m.group(1))
        rest = re.sub(r"^[\s/,;:·-]+|[\s/,;:·-]+$", "", re.sub(r"[\u3131-\u318E\uAC00-\uD7A3\s]*[/,;]\s*(?=[/,;]|$)", "", rest))
        return f" ({rest})" if re.search(r"[A-Za-z0-9]", rest) else ""
    return _GLOSS.sub(one, str(text or ""))


def _translated_quote(text: str, start: int) -> bool:
    """Korean at `start` sits inside quotes followed (or preceded) by English in brackets/quotes."""
    window = text[max(0, start - 160): start + 220]
    return bool(re.search(r"[\"'‘“][^\"'’”]*[ㄱ-ㆎ가-힣][^\"'’”]*[\"'’”]\s*\(\s*[\"'‘“]?[A-Za-z]",
                          window)
                or re.search(r"[\"'‘“][A-Za-z][^\"'’”]{8,}[\"'’”]\s*\(\s*[ㄱ-ㆎ가-힣]", window))


_QUOTE_SECTIONS = ("official_x_posts", "social_statements")


def _drop_untranslated_quotes(digest: dict, warnings: list) -> None:
    """A quote left in Korean with no English beside it cannot be shown; the item goes."""
    for key in _QUOTE_SECTIONS:
        items = digest.get(key)
        if not isinstance(items, list):
            continue
        kept = []
        for it in items:
            q = str((it or {}).get("quote_text") or "") if isinstance(it, dict) else ""
            m = HANGUL.search(q)
            if m and not _translated_quote(q, m.start()):
                warnings.append(f"dropped untranslated quote in {key}: {q[:40]!r}")
                continue
            kept.append(it)
        digest[key] = kept


def apply(digest: dict) -> list[str]:
    """Rewrite labels to English in place; return warnings for Korean left in prose."""
    warnings: list[str] = []

    def walk(v, path: str):
        if isinstance(v, dict):
            for k in list(v):
                x = v[k]
                if k in _KOREAN_ONLY:
                    del v[k]
                elif str(k).startswith("_") or k in ("url", "secondary_url", "source_url"):
                    continue
                elif k in _LABEL_KEYS and isinstance(x, str):
                    v[k] = dashes(outlet(x))
                else:
                    walk(x, f"{path}.{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                if isinstance(x, str) and path.endswith(("sources", "source_names", "outlets")):
                    v[i] = outlet(x)
                else:
                    walk(x, f"{path}[{i}]")
        elif isinstance(v, str) and HANGUL.search(v):
            pass  # prose is checked below, after the outlet names are mapped

    try:
        _drop_untranslated_quotes(digest, warnings)
        walk(digest, "")
        # Outlet names inside prose ("a 경향신문 editorial") are names, not
        # quotes; map them. Anything Korean left is reported, not rewritten.
        def prose(v, path: str, parent=None, key=None):
            if isinstance(v, dict):
                for k, x in v.items():
                    if not str(k).startswith("_") and k not in ("url", "secondary_url", "source_url"):
                        prose(x, f"{path}.{k}", v, k)
            elif isinstance(v, list):
                for i, x in enumerate(v):
                    prose(x, f"{path}[{i}]", v, i)
            elif isinstance(v, str) and parent is not None and re.search(r"[\u2014\u2015]|\s[\u2013]\s|\s--\s", v):
                parent[key] = v = dashes(v)
            if isinstance(v, str) and HANGUL.search(v) and parent is not None:
                s = glosses(v)
                for ko in _BY_LENGTH:
                    s = s.replace(ko, OUTLETS[ko])
                parent[key] = s
                m = HANGUL.search(s)
                if m and not _translated_quote(s, m.start()):
                    warnings.append(f"Korean text in {path.lstrip('.')}: {s[max(0, m.start() - 20): m.start() + 40]!r}")
        prose(digest, "")
    except Exception as e:                                      # noqa: BLE001
        warnings.append(f"English pass skipped: {e}")
    return warnings
