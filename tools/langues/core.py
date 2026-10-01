"""Versions traduites du site (en, es, de, it) dérivées des pages FR.

Utilisé par :
  - le chantier de traduction (hors dépôt), qui construit toutes les pages traduites ;
  - tools/publish_actus.py, qui traduit à la volée les pages qu'il régénère
    (index Actus, bloc Actus de l'accueil, cartes des fiches Repères) à partir de
    tools/langues/runtime.json (correspondance des slugs + mémoire de traduction utile).

Principe : on découpe le HTML FR en unités (htmlseg.py), on remplace chaque unité par sa
traduction (repérée par l'empreinte du texte source), on réécrit les liens internes vers la
version traduite de la page cible ; tout le reste du HTML est recopié tel quel.
"""
import html
import json
import os
import posixpath
import re
from urllib.parse import urlsplit

from . import htmlseg as H

BASE = "https://bernardcollorafi.org"
RUNTIME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime.json")

# Langues actives. it est en pause à la demande du user (2026-10-01 ; traductions
# partielles dans le chantier hors dépôt) : l'ajouter ici puis relancer build.py.
LANGS = ["fr", "en", "es", "de"]
TARGETS = ["en", "es", "de"]
LANG_NAME = {"fr": "Français", "en": "English", "es": "Español", "de": "Deutsch", "it": "Italiano"}
LOCALE = {"fr": "fr_FR", "en": "en_GB", "es": "es_ES", "de": "de_DE", "it": "it_IT"}
LD_LANG = {"fr": "fr-FR", "en": "en-GB", "es": "es-ES", "de": "de-DE", "it": "it-IT"}
SECTIONS = {
    "fr": {"actus": "actus", "reperes": "reperes", "pieces": "pieces", "fiches": "fiches"},
    "en": {"actus": "news", "reperes": "glossary", "pieces": "documents", "fiches": "summaries"},
    "es": {"actus": "actualidad", "reperes": "glosario", "pieces": "documentos", "fiches": "fichas"},
    "de": {"actus": "aktuelles", "reperes": "glossar", "pieces": "dokumente", "fiches": "uebersichten"},
    "it": {"actus": "attualita", "reperes": "glossario", "pieces": "documenti", "fiches": "schede"},
}
SWITCH_LABEL = {"fr": "Langue", "en": "Language", "es": "Idioma", "de": "Sprache", "it": "Lingua"}

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
        "octobre", "novembre", "décembre"]
MONTHS = {
    "fr": MOIS,
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"],
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
           "octubre", "noviembre", "diciembre"],
    "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
           "Oktober", "November", "Dezember"],
    "it": ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"],
}

META_KEYS = {("name", "description"), ("property", "og:title"), ("property", "og:description"),
             ("property", "og:image:alt"), ("property", "og:site_name"),
             ("name", "twitter:title"), ("name", "twitter:description")}
BODY_ATTRS = ("title", "alt", "aria-label", "placeholder")
URL_ATTRS = ("href", "src", "data-src", "action")
LD_KEYS = {"name", "description", "headline", "articleSection", "about", "alternateName"}
LD_URL_KEYS = {"url", "item", "@id", "mainEntityOfPage"}

HREF_OPEN, HREF_CLOSE = "<!-- i18n:alternates -->", "<!-- /i18n:alternates -->"
SW_OPEN, SW_CLOSE = "<!-- i18n:switch -->", "<!-- /i18n:switch -->"
NUM_DATE_RE = re.compile(r"^(\s*)(\d{2})/(\d{2})/(\d{4})(\s*)$")
LONG_DATE_RE = re.compile(r"(\d{1,2})(?:er)? (%s) (\d{4})" % "|".join(MOIS))


def fmt_date(lang, iso):
    """2026-09-25 -> « 25 septembre 2026 » dans la langue voulue."""
    y, m, d = (int(x) for x in iso.split("-"))
    name = MONTHS[lang][m - 1]
    if lang == "en":
        return "%d %s %d" % (d, name, y)
    if lang == "es":
        return "%d de %s de %d" % (d, name, y)
    if lang == "de":
        return "%d. %s %d" % (d, name, y)
    return "%d %s %d" % (d, name, y)


def long_date_fr_to(lang, s):
    """Traduit les dates longues FR (« 25 septembre 2026 ») contenues dans une chaîne."""
    def rep(m):
        return fmt_date(lang, "%s-%02d-%02d" % (m.group(3), MOIS.index(m.group(2)) + 1, int(m.group(1))))
    return LONG_DATE_RE.sub(rep, s)


class Runtime:
    """Correspondances nécessaires à la traduction d'une page.

    slugs : {lang: {"actus/<slug fr>": "<slug traduit>", "reperes/…", "pieces/…"}}
    stub  : anciens slugs de pièces -> slug courant
    fiche : nom du PDF de fiche FR -> slug de pièce
    tm    : {lang: {id de segment: traduction}}
    """

    def __init__(self, slugs, stub, fiche, tm):
        self.slugs, self.stub, self.fiche, self.tm = slugs, stub, fiche, tm
        self.warnings = []

    @classmethod
    def load(cls, path=RUNTIME):
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return cls(d["slugs"], d["stub"], d["fiche"], d["tm"])

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def map_path(self, path, lang):
        """Chemin FR absolu -> chemin dans la langue cible (inchangé pour une ressource partagée)."""
        if lang == "fr":
            return path
        if path in ("/", "/index.html"):
            return "/%s/" % lang
        parts = path.strip("/").split("/")
        sec = SECTIONS[lang]
        if parts[0] in ("actus", "reperes", "pieces"):
            if len(parts) == 1 or (len(parts) == 2 and parts[1] == "index.html"):
                if parts[0] == "pieces":
                    return "/%s/#pieces" % lang
                return "/%s/%s/" % (lang, sec[parts[0]])
            slug = parts[1]
            if parts[0] == "pieces" and slug in self.stub:
                slug = self.stub[slug]
            t = self.slugs[lang].get(parts[0] + "/" + slug)
            if t is None:
                self.warn("lien vers une page sans traduction: %s" % path)
                return path
            return "/%s/%s/%s/" % (lang, sec[parts[0]], t)
        if parts[0] == "fiches" and len(parts) == 2 and parts[1] in self.fiche:
            t = self.slugs[lang]["pieces/" + self.fiche[parts[1]]]
            return "/%s/%s/%s.pdf" % (lang, sec["fiches"], t)
        return path

    def page_path(self, fr_path, lang):
        return self.map_path(fr_path, lang) if fr_path != "/404.html" else fr_path


def rewrite_url(rt, url, page_dir_fr, page_dir_new, lang):
    if not url or url.startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
        return url
    absolute = url.startswith(BASE)
    if url.startswith(("http://", "https://", "//")) and not absolute:
        return url
    sp = urlsplit(url[len(BASE):] if absolute else url)
    path = sp.path
    if not absolute:
        path = posixpath.normpath(posixpath.join(page_dir_fr, path or "./"))
        if sp.path.endswith("/") or sp.path in ("", ".", "./"):
            path = path.rstrip("/") + "/"
        if path.startswith("//"):
            path = path[1:]
    new = rt.map_path(path or "/", lang)
    frag = ("#" + sp.fragment) if sp.fragment else ""
    if "#" in new:  # ex. /en/#pieces
        new, frag2 = new.split("#", 1)
        frag = frag or "#" + frag2
    q = ("?" + sp.query) if sp.query else ""
    if absolute:
        return BASE + new + q + frag
    rel = posixpath.relpath(new, page_dir_new)
    if rel == ".":
        rel = "./"
    elif new.endswith("/"):
        rel = rel.rstrip("/") + "/"
    return rel + q + frag


class PageBuilder:
    """Traduit une page (ou un fragment) FR située à fr_path vers lang."""

    def __init__(self, rt, fr_path, lang):
        self.rt, self.lang = rt, lang
        self.tm = rt.tm.get(lang, {})
        self.dir_fr = fr_path if fr_path.endswith("/") else posixpath.dirname(fr_path) + "/"
        newp = rt.page_path(fr_path, lang)
        self.dir_new = newp if newp.endswith("/") else posixpath.dirname(newp) + "/"
        self.missing = 0
        self.used = set()

    def tr(self, kind, src):
        if self.lang == "fr":
            return src
        i = H.sid(kind, src)
        t = self.tm.get(i)
        if t is not None:
            self.used.add(i)
            return t
        # chaîne composée « Catégorie · 25 septembre 2026 » : catégorie traduite + date formatée
        m = re.match(r"^(.*?) · (\d{1,2}(?:er)? (?:%s) \d{4})$" % "|".join(MOIS), src)
        if m and kind == "html":
            left = self.tr(kind, m.group(1)) if H.has_letter(m.group(1)) else m.group(1)
            if left is not None:
                return left + " · " + long_date_fr_to(self.lang, m.group(2))
            return None
        if kind == "html" and LONG_DATE_RE.fullmatch(src):
            return long_date_fr_to(self.lang, src)
        self.missing += 1
        self.rt.warn("traduction manquante (%s, %s): %s" % (self.lang, kind, src[:70].replace("\n", " ")))
        return None

    def url(self, u):
        return rewrite_url(self.rt, u, self.dir_fr, self.dir_new, self.lang)

    def tag(self, t, in_body):
        """Réécrit un tag ouvrant : URLs, attributs traduisibles, lang, og:locale."""
        tok = H.tokenize(t)[0] if isinstance(t, str) else t
        if tok.kind != "start":
            return tok.text
        text, name = tok.text, tok.name
        if name == "html" and H.attr_value(text, "lang"):
            text = H.set_attr(text, "lang", self.lang)
        for a in URL_ATTRS:
            v = H.attr_value(text, a)
            if v is not None:
                nv = self.url(v)
                if nv != v:
                    text = H.set_attr(text, a, nv)
        if name == "meta":
            prop, nm = H.attr_value(text, "property"), H.attr_value(text, "name")
            c = H.attr_value(text, "content")
            if c is not None:
                if prop == "og:locale":
                    text = H.set_attr(text, "content", LOCALE[self.lang])
                elif c.startswith(BASE):
                    nc = self.url(c)
                    if nc != c:
                        text = H.set_attr(text, "content", nc)
                elif (("property", prop) in META_KEYS or ("name", nm) in META_KEYS) and H.has_letter(c):
                    t2 = self.tr("attr", H.norm_ws(c).strip())
                    if t2 is not None:
                        text = H.set_attr(text, "content", t2)
        if in_body:
            for a in BODY_ATTRS:
                v = H.attr_value(text, a)
                if v and H.has_letter(v):
                    t2 = self.tr("attr", H.norm_ws(v).strip())
                    if t2 is not None:
                        text = H.set_attr(text, a, t2)
        return text

    def date_text(self, s):
        m = NUM_DATE_RE.match(s)
        if not m or self.lang not in ("en", "de"):
            return s
        d, mo, y = m.group(2), m.group(3), m.group(4)
        if self.lang == "en":
            return "%s%d %s %s%s" % (m.group(1), int(d), MONTHS["en"][int(mo) - 1][:3], y, m.group(5))
        return "%s%s.%s.%s%s" % (m.group(1), d, mo, y, m.group(5))

    def ld(self, raw):
        try:
            obj = json.loads(raw)
        except ValueError:
            return raw

        def walk(o, key=None):
            if isinstance(o, dict):
                return {k: walk(v, k) for k, v in o.items()}
            if isinstance(o, list):
                return [walk(v, key) for v in o]
            if isinstance(o, str):
                if key == "inLanguage":
                    return LD_LANG[self.lang]
                if key in LD_URL_KEYS and o.startswith(BASE):
                    return self.url(o)
                if key in LD_KEYS and H.has_letter(o):
                    t = self.tr("attr", H.norm_ws(o).strip())
                    return t if t is not None else o
            return o

        return json.dumps(walk(obj), ensure_ascii=False)

    def unit(self, u):
        def rew(frag):
            # un marqueur peut couvrir un sous-arbre entier (svg…) : on réécrit chaque tag ouvrant
            return "".join(self.tag(x, True) if x.kind == "start" else x.text for x in H.tokenize(frag))

        if u.pre:
            parts = []
            for ch in H.chunk_pre(u.src):
                t = self.tr("pre", ch) if H.has_letter(ch) else ch
                parts.append(t if t is not None else ch)
            return u.lead + html.escape("\n".join(parts), quote=False) + u.trail
        t = self.tr("html", u.src)
        if t is None:
            t = u.src
        if H.placeholders(t) != H.placeholders(u.src):
            self.rt.warn("marqueurs incohérents (%s): %s" % (self.lang, u.src[:60]))
            t = u.src
        return u.lead + H.render(t, u.tags, rew) + u.trail

    def build(self, src):
        if self.lang == "fr":
            return src
        toks, root, units, problems = H.units_of(src)
        unit_at = {u.a: u for u in units}
        out, i, in_body, ld_next = [], 0, False, False
        # un fragment (sans <head>) est considéré comme du corps de page
        if "<head" not in src[:2000].lower():
            in_body = True
        while i < len(toks):
            t = toks[i]
            if i in unit_at:
                u = unit_at[i]
                out.append(self.tag(t, in_body or t.name != "title"))
                out.append(self.unit(u))
                out.append(toks[u.b].text)
                i = u.b + 1
                continue
            if t.kind == "start":
                if t.name == "body":
                    in_body = True
                ld_next = t.name == "script" and H.attr_value(t.text, "type") == "application/ld+json"
                out.append(self.tag(t, in_body))
            elif t.kind == "raw" and ld_next:
                out.append(self.ld(t.text))
            elif t.kind == "text":
                out.append(self.date_text(t.text))
            else:
                out.append(t.text)
            i += 1
        return "".join(out)


# ---------------------------------------------------------------- hreflang + sélecteur

def alternates_block(rt, fr_path):
    rows = [HREF_OPEN]
    for lang in LANGS:
        rows.append('<link rel="alternate" hreflang="%s" href="%s%s">' % (lang, BASE, rt.page_path(fr_path, lang)))
    rows.append('<link rel="alternate" hreflang="x-default" href="%s%s">' % (BASE, fr_path))
    rows.append("<style>.i18n-lang summary{list-style:none}"
                ".i18n-lang summary::-webkit-details-marker{display:none}"
                ".i18n-lang[open] summary{color:rgb(var(--accent-rgb))}</style>")
    rows.append(HREF_CLOSE)
    return "\n".join(rows)


def switcher(rt, fr_path, lang):
    here = rt.page_path(fr_path, lang)
    here_dir = here if here.endswith("/") else posixpath.dirname(here) + "/"
    links = []
    for l2 in LANGS:
        target = rt.page_path(fr_path, l2)
        rel = posixpath.relpath(target, here_dir)
        rel = "./" if rel == "." else (rel.rstrip("/") + "/" if target.endswith("/") else rel)
        cur = ' aria-current="true"' if l2 == lang else ""
        cls = "text-ox" if l2 == lang else "text-ink hover:text-ox"
        links.append(
            '<a href="%s" hreflang="%s" lang="%s"%s class="flex items-center justify-between gap-4 px-4 py-1.5 %s transition">'
            '<span>%s</span><span class="text-[10px] font-semibold text-ink2">%s</span></a>'
            % (rel, l2, l2, cur, cls, LANG_NAME[l2], l2.upper()))
    return (
        SW_OPEN + '<details class="i18n-lang relative">'
        '<summary class="cursor-pointer select-none inline-flex items-center gap-1 hover:text-ox transition" '
        'aria-label="%s : %s"><svg class="sm:hidden" width="16" height="16" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 '
        '15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg><span class="hidden sm:inline">%s</span>'
        '<svg class="hidden sm:block" width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'
        '</summary><div class="absolute right-0 top-full mt-3 z-50 rounded-xl border py-1.5 min-w-[170px] normal-case '
        'font-body text-[13.5px] font-medium" style="letter-spacing:0;background:var(--panel);border-color:var(--line);'
        'box-shadow:0 22px 40px -26px var(--shadow)">%s</div></details>'
        % (SWITCH_LABEL[lang], LANG_NAME[lang], lang.upper(), "".join(links)) + SW_CLOSE)


def decorate(rt, fr_path, lang, s):
    """Ajoute (ou remplace) le bloc hreflang dans <head> et le sélecteur de langue dans le header."""
    blk = alternates_block(rt, fr_path)
    if HREF_OPEN in s:
        s = re.sub(re.escape(HREF_OPEN) + ".*?" + re.escape(HREF_CLOSE), lambda _m: blk, s, flags=re.S)
    else:
        s = s.replace("</head>", blk + "\n</head>", 1)
    # en-tête : écart réduit sous 640 px pour loger le sélecteur
    s = re.sub(r'(<header\b.*?<nav class="flex items-center) gap-6 ', r'\1 gap-4 sm:gap-6 ', s, count=1, flags=re.S)
    if lang != "fr":
        # libellés traduits plus longs : le lien « pièces » de l'en-tête passe sous 640 px
        s = re.sub(r'(<header\b.*?<a href="[^"]*#pieces" class=")(hover:text-ox transition")',
                   r'\1hidden sm:inline \2', s, count=1, flags=re.S)
    sw = switcher(rt, fr_path, lang)
    if SW_OPEN in s:
        return re.sub(re.escape(SW_OPEN) + ".*?" + re.escape(SW_CLOSE), lambda _m: sw, s, flags=re.S)
    m = re.search(r"(?s)<header\b.*?</nav>", s)
    if not m:
        rt.warn("pas de <nav> dans le header: %s" % fr_path)
        return s
    j = m.end() - len("</nav>")
    return s[:j] + "  " + sw + "\n    " + s[j:]


def undecorate(s):
    """Retire hreflang + sélecteur (pour retraduire une page FR déjà décorée)."""
    s = re.sub(r"\n?" + re.escape(HREF_OPEN) + ".*?" + re.escape(HREF_CLOSE), "", s, flags=re.S)
    return re.sub(r"  " + re.escape(SW_OPEN) + ".*?" + re.escape(SW_CLOSE) + r"\n    ", "", s, flags=re.S)


def translate_page(rt, fr_path, lang, fr_html):
    """Page FR complète -> page traduite et décorée (hreflang + sélecteur)."""
    src = undecorate(fr_html)
    return decorate(rt, fr_path, lang, PageBuilder(rt, fr_path, lang).build(src))


def translate_fragment(rt, fr_path, lang, fr_fragment):
    """Fragment HTML d'une page FR (ex. bloc Actus de l'accueil) -> fragment traduit."""
    return PageBuilder(rt, fr_path, lang).build(fr_fragment)


# ---------------------------------------------------------------- sitemap

URL_ROW = re.compile(r"\s*<url><loc>([^<]*)</loc>(.*?)</url>", re.S)


def sitemap_i18n(rt, sm):
    """Retire les URL traduites du sitemap puis les régénère à partir des URL FR."""
    lang_prefix = tuple("%s/%s/" % (BASE, l) for l in TARGETS)
    rows = [(m.group(1), m.group(2)) for m in URL_ROW.finditer(sm)]
    fr_rows = [(loc, rest) for loc, rest in rows if not loc.startswith(lang_prefix)]
    out = []
    for lang in TARGETS:
        for loc, rest in fr_rows:
            path = loc[len(BASE):] or "/"
            new = rt.map_path(path, lang)
            if new == path or "#" in new:
                continue
            out.append("  <url><loc>%s%s</loc>%s</url>" % (BASE, new, rest))
    head = sm[:sm.index("<url>")] if "<url>" in sm else sm.replace("</urlset>", "")
    body = "\n".join("  <url><loc>%s</loc>%s</url>" % r for r in fr_rows)
    return head.rstrip() + "\n" + body + "\n" + "\n".join(out) + "\n</urlset>\n"
