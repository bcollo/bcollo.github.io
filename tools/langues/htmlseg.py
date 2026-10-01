"""Découpage d'une page HTML en unités traduisibles, sans altérer le reste du fichier.

Principe : on tokenise le HTML (tags / texte / commentaires / contenus bruts), on
reconstruit l'arbre des éléments, et on retient comme « unité » tout élément qui porte
du texte direct (au moins une lettre) et dont aucun ancêtre n'est déjà une unité.
Le contenu d'une unité est remis au traducteur avec ses balises remplacées par des
marqueurs numérotés (<x1>…</x1>, <x2/>), puis réinjecté balise pour balise.
Tout ce qui n'est pas une unité est recopié octet pour octet.
"""
import hashlib
import html
import re

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
RAW = {"script", "style", "textarea", "title"}
SKIP = {"script", "style", "svg", "iframe", "noscript", "template"}

TAG_RE = re.compile(
    r"""<!--.*?-->|<![^>]*>|</?([a-zA-Z][a-zA-Z0-9:-]*)"""
    r"""(?:\s+[^\s=/>"']+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>]+))?)*\s*/?>""",
    re.S,
)
LETTER = re.compile(r"[^\W\d_]")
ATTR_RE = re.compile(r"""([^\s=/>"']+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'>]+))?""")
PH_RE = re.compile(r"</?x\d+/?>")


class Tok:
    __slots__ = ("kind", "text", "name", "selfclose")

    def __init__(self, kind, text, name=None, selfclose=False):
        self.kind, self.text, self.name, self.selfclose = kind, text, name, selfclose


def tokenize(s):
    toks, i, low = [], 0, s.lower()
    while i < len(s):
        m = TAG_RE.search(s, i)
        if not m:
            toks.append(Tok("text", s[i:]))
            break
        if m.start() > i:
            toks.append(Tok("text", s[i:m.start()]))
        t = m.group(0)
        if t.startswith("<!--"):
            toks.append(Tok("comment", t))
        elif t.startswith("<!"):
            toks.append(Tok("decl", t))
        elif t.startswith("</"):
            toks.append(Tok("end", t, m.group(1).lower()))
        else:
            name = m.group(1).lower()
            sc = t.endswith("/>")
            toks.append(Tok("start", t, name, sc))
            if name in RAW and not sc:
                j = low.find("</" + name, m.end())
                if j == -1:
                    raise ValueError("balise %s non fermée" % name)
                toks.append(Tok("raw", s[m.end():j]))
                i = j
                continue
        i = m.end()
    assert "".join(t.text for t in toks) == s
    return toks


class Node:
    __slots__ = ("name", "start", "end", "parent", "children")

    def __init__(self, name, start, parent):
        self.name, self.start, self.end, self.parent, self.children = name, start, None, parent, []


def build_tree(toks):
    """Renvoie la racine ; chaque Node connaît l'index de son tag ouvrant/fermant."""
    root = Node("#root", -1, None)
    stack = [root]
    problems = []
    for i, t in enumerate(toks):
        if t.kind == "start":
            n = Node(t.name, i, stack[-1])
            stack[-1].children.append(n)
            if t.name in VOID or t.selfclose:
                n.end = i
            else:
                stack.append(n)
        elif t.kind == "end":
            if t.name in VOID:
                continue
            k = len(stack) - 1
            while k > 0 and stack[k].name != t.name:
                k -= 1
            if k == 0:
                problems.append("fermante orpheline </%s> au token %d" % (t.name, i))
                continue
            if k != len(stack) - 1:
                problems.append("fermeture implicite de %s au token %d"
                                % ([x.name for x in stack[k + 1:]], i))
            for x in stack[k + 1:]:
                x.end = i  # fermeture implicite : on borne à la fermante englobante
            stack[k].end = i
            del stack[k:]
    root.end = len(toks)
    return root, problems


def attrs(tag):
    """Liste ordonnée (nom, valeur brute avec guillemets ou None, span) des attributs d'un tag ouvrant."""
    m = re.match(r"<[a-zA-Z][a-zA-Z0-9:-]*", tag)
    out = []
    for a in ATTR_RE.finditer(tag, m.end()):
        if a.group(1) in ("/", ">"):
            continue
        out.append((a.group(1).lower(), a.group(2), a.span(2) if a.group(2) else None))
    return out


def attr_value(tag, name):
    for n, v, _ in attrs(tag):
        if n == name and v is not None:
            return html.unescape(v[1:-1] if v[0] in "\"'" else v)
    return None


def set_attr(tag, name, value):
    """Remplace la valeur d'un attribut existant (valeur déjà prête, non échappée)."""
    for n, v, span in attrs(tag):
        if n == name and span:
            return tag[:span[0]] + '"' + html.escape(value, quote=True) + '"' + tag[span[1]:]
    raise KeyError(name)


def sid(kind, src):
    return hashlib.sha1((kind + "\x00" + src).encode()).hexdigest()[:12]


def norm_ws(s):
    s = s.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", s)


def has_letter(s):
    return bool(LETTER.search(s))


class Unit:
    """Une unité traduisible : le contenu entre toks[a] (exclu) et toks[b] (exclu)."""
    __slots__ = ("node", "a", "b", "src", "tags", "lead", "trail", "pre")


def direct_text(node, toks):
    """Texte direct d'un élément (hors sous-éléments)."""
    out = []
    i = node.start + 1
    kids = iter(node.children)
    nxt = next(kids, None)
    while i < node.end:
        if nxt is not None and i == nxt.start:
            i = nxt.end + 1
            nxt = next(kids, None)
            continue
        if toks[i].kind in ("text", "raw"):
            out.append(toks[i].text)
        i += 1
    return "".join(out)


def find_units(root, toks):
    units = []

    def walk(n, in_head):
        for c in n.children:
            if c.name in SKIP or c.end == c.start:
                continue
            head = in_head or c.name == "head"
            if head and c.name != "title":
                walk(c, head)
                continue
            if has_letter(html.unescape(direct_text(c, toks))):
                units.append(c)
            else:
                walk(c, head)

    walk(root, False)
    return units


def placeholderize(node, toks):
    """Contenu d'un élément -> (texte à traduire, table marqueur->tag d'origine, pre)."""
    tags = {}
    out = []
    stack = []
    n = 0
    i = node.start + 1
    pre = "ocr" in (attr_value(toks[node.start].text, "class") or "").split()
    # sous-éléments à ignorer en bloc (svg, script…) : index de début -> fin
    skip_spans = {}

    def mark(nn):
        for c in nn.children:
            if c.name in SKIP:
                skip_spans[c.start] = c.end
            else:
                mark(c)

    mark(node)
    while i < node.end:
        t = toks[i]
        if i in skip_spans:
            n += 1
            j = skip_spans[i]
            tags["<x%d/>" % n] = "".join(x.text for x in toks[i:j + 1])
            out.append("<x%d/>" % n)
            i = j + 1
            continue
        if t.kind in ("text", "raw"):
            out.append(html.unescape(t.text))
        elif t.kind == "start":
            n += 1
            if t.name in VOID or t.selfclose:
                tags["<x%d/>" % n] = t.text
                out.append("<x%d/>" % n)
            else:
                stack.append((t.name, n))
                tags["<x%d>" % n] = t.text
                out.append("<x%d>" % n)
        elif t.kind == "end":
            if t.name in VOID:
                n += 1
                tags["<x%d/>" % n] = t.text
                out.append("<x%d/>" % n)
            else:
                k = len(stack) - 1
                while k >= 0 and stack[k][0] != t.name:
                    k -= 1
                if k < 0:
                    raise ValueError("fermante inattendue dans une unité: " + t.text)
                num = stack[k][1]
                del stack[k:]
                tags["</x%d>" % num] = t.text
                out.append("</x%d>" % num)
        elif t.kind in ("comment", "decl"):
            n += 1
            tags["<x%d/>" % n] = t.text
            out.append("<x%d/>" % n)
        i += 1
    raw = "".join(out)
    if pre:
        body = raw.strip("\n")
        lead = raw[:len(raw) - len(raw.lstrip("\n"))]
        trail = raw[len(raw.rstrip("\n")):]
        return body, tags, lead, trail, True
    s = norm_ws(raw)
    lead = raw[:len(raw) - len(raw.lstrip())]
    trail = raw[len(raw.rstrip()):]
    return s.strip(), tags, lead, trail, False


def units_of(s):
    toks = tokenize(s)
    root, problems = build_tree(toks)
    res = []
    for node in find_units(root, toks):
        u = Unit()
        u.node = node
        u.a, u.b = node.start, node.end
        u.src, u.tags, lead, trail, u.pre = placeholderize(node, toks)
        # espaces de tête/queue d'origine, ré-émis tels quels (échappés)
        u.lead = "\n" if (u.pre and lead) else (" " if lead and not u.pre else "")
        u.trail = "\n" if (u.pre and trail) else (" " if trail and not u.pre else "")
        res.append(u)
    return toks, root, res, problems


def placeholders(s):
    return sorted(PH_RE.findall(s))


def render(translation, tags, rewrite_tag=lambda t: t):
    """Réinjecte les tags d'origine (éventuellement réécrits) dans une traduction à marqueurs."""
    out = []
    pos = 0
    for m in PH_RE.finditer(translation):
        out.append(html.escape(translation[pos:m.start()], quote=False))
        out.append(rewrite_tag(tags[m.group(0)]))
        pos = m.end()
    out.append(html.escape(translation[pos:], quote=False))
    return "".join(out)


def chunk_pre(text, limit=1400):
    """Découpe un texte préformaté en morceaux de lignes entières (~limit caractères),
    en coupant de préférence sur une ligne vide."""
    lines = text.split("\n")
    chunks, cur, size = [], [], 0
    for ln in lines:
        cur.append(ln)
        size += len(ln) + 1
        if size >= limit and (ln.strip() == "" or size >= limit * 1.6):
            chunks.append("\n".join(cur))
            cur, size = [], 0
    if cur:
        chunks.append("\n".join(cur))
    return chunks
