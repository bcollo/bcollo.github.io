#!/usr/bin/env python3
"""Publication différée des articles Actus (lancé par GitHub Actions, cron quotidien).

Lit queue/manifest.json (branche `queue`, déposée dans l'arbre par le workflow) et
publie les articles dont la date `publish_at` est atteinte :
  - copie queue/pages/<slug>/index.html vers actus/<slug>/index.html
  - inscrit l'article en tête de tools/actus_registry.json
  - régénère actus/index.html, le bloc Actus de la home, et sitemap.xml

Idempotent : un article déjà présent dans le registre est ignoré.
Sort en code 0 sans rien modifier s'il n'y a rien à publier.
"""
import datetime
import html
import json
import os
import re
import shutil
import sys

SITE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://bernardcollorafi.org"
OUT = os.path.join(SITE, "actus")
REGISTRY = os.path.join(SITE, "tools", "actus_registry.json")
QUEUE = os.path.join(SITE, "queue")

GA = """<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-EMT2H8EP2G"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());

  gtag('config', 'G-EMT2H8EP2G');
</script>"""

STYLE = """<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,600;12..96,700;12..96,800&family=Public+Sans:ital,wght@0,300;0,400;0,500;0,600;0,700;1,400;1,500&display=swap" rel="stylesheet">

<script src="https://cdn.tailwindcss.com"></script>
<script>
tailwind.config = {
  theme: { extend: {
    colors: {
      cream:'rgb(var(--bg-rgb)/<alpha-value>)', cream2:'rgb(var(--bg2-rgb)/<alpha-value>)',
      ink:'rgb(var(--ink-rgb)/<alpha-value>)', ink2:'rgb(var(--ink2-rgb)/<alpha-value>)',
      ox:'rgb(var(--accent-rgb)/<alpha-value>)', oxdeep:'var(--accent-deep)',
      gold:'rgb(var(--gold-rgb)/<alpha-value>)',
    },
    fontFamily: { display:['"Bricolage Grotesque"','system-ui','sans-serif'], body:['"Public Sans"','system-ui','sans-serif'], ui:['"Public Sans"','system-ui','sans-serif'] },
  } }
}
</script>

<style>
  :root{
    --bg-rgb:245 240 232; --bg2-rgb:234 226 214;
    --ink-rgb:34 30 26; --ink2-rgb:138 128 114;
    --accent-rgb:194 96 63; --accent-deep:#a54e30; --gold-rgb:214 180 140;
    --panel:#ffffff; --card-hover:#ffffff;
    --shadow:rgba(60,44,28,.32);
    --line: rgb(var(--ink-rgb) / .10); --line2: rgb(var(--ink-rgb) / .05);
  }
  html{ scroll-behavior:smooth; }
  body{ background-color:rgb(var(--bg-rgb));
    background-image:
      radial-gradient(1100px 640px at 88% -10%, rgb(var(--accent-rgb) / .06), transparent 60%),
      radial-gradient(900px 700px at -8% 8%, rgb(var(--gold-rgb) / .07), transparent 55%); }
  ::selection{ background:rgb(var(--accent-rgb)); color:rgb(var(--bg-rgb)); }
  .eyebrow{ font-family:"Public Sans",sans-serif; font-weight:700; text-transform:uppercase; letter-spacing:.2em; }
  .hair{ background:var(--line); }
  .ulink{ position:relative; }
  .ulink::after{ content:""; position:absolute; left:0; bottom:-2px; height:1px; width:100%; background:currentColor; transform:scaleX(0); transform-origin:left; transition:transform .35s cubic-bezier(.2,.7,.2,1); }
  .ulink:hover::after{ transform:scaleX(1); }
  .card{ transition:transform .3s cubic-bezier(.2,.7,.2,1), box-shadow .3s, background-color .3s; }
  .card:hover{ transform:translateY(-4px); box-shadow:0 22px 40px -26px var(--shadow); background:var(--card-hover); }
  .softshadow{ box-shadow:0 30px 60px -40px var(--shadow); }
  .crumb a{ color:rgb(var(--ink2-rgb)); } .crumb a:hover{ color:rgb(var(--accent-rgb)); }

  /* corps d'article */
  .wrap{ max-width:820px; }
  .prose-art{ font-size:17.5px; line-height:1.75; color:rgb(var(--ink-rgb)/.9); }
  .prose-art h2{ font-family:"Bricolage Grotesque",sans-serif; font-weight:700; font-size:1.72rem; line-height:1.2; color:rgb(var(--ink-rgb)); margin:2.6rem 0 .9rem; letter-spacing:-.01em; }
  .prose-art h3{ font-family:"Bricolage Grotesque",sans-serif; font-weight:700; font-size:1.22rem; color:rgb(var(--accent-rgb)); margin:1.8rem 0 .5rem; }
  .prose-art p{ margin:1rem 0; }
  .prose-art ul{ margin:1rem 0 1.2rem 1.2rem; list-style:disc; }
  .prose-art ol{ margin:1rem 0 1.2rem 1.3rem; list-style:decimal; }
  .prose-art li{ margin:.4rem 0; }
  .prose-art strong{ font-weight:600; }
  .prose-art blockquote{ margin:1.6rem 0; padding:1.15rem 1.35rem; background:var(--panel); border:1px solid var(--line); border-left:3px solid rgb(var(--accent-rgb)); border-radius:14px; font-size:16.5px; line-height:1.65; color:rgb(var(--ink-rgb)/.85); }
  .prose-art blockquote cite{ display:block; margin-top:.6rem; font-style:normal; font-size:12.5px; color:rgb(var(--ink2-rgb)); }
  .prose-art table{ width:100%; border-collapse:collapse; margin:1.4rem 0; font-size:15px; }
  .prose-art th{ text-align:left; background:rgb(var(--bg2-rgb)); font-family:"Public Sans",sans-serif; font-weight:700; text-transform:uppercase; letter-spacing:.1em; font-size:.66rem; padding:.55rem .75rem; }
  .prose-art td{ padding:.55rem .75rem; border-top:1px solid var(--line2); vertical-align:top; }
  /* lien interne (dossier) — dofollow */
  .prose-art a.ilink{ color:rgb(var(--accent-rgb)); text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:2.5px; text-decoration-color:rgb(var(--accent-rgb)/.35); transition:.2s; }
  .prose-art a.ilink:hover{ color:var(--accent-deep); text-decoration-color:rgb(var(--accent-rgb)); }
  /* lien externe (source) — nofollow */
  .prose-art a.xlink{ color:rgb(var(--ink-rgb)); text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:2.5px; text-decoration-color:rgb(var(--ink2-rgb)/.5); transition:.2s; }
  .prose-art a.xlink:hover{ color:rgb(var(--accent-rgb)); text-decoration-color:rgb(var(--accent-rgb)); }
  .prose-art a.xlink::after{ content:"\\2197"; font-size:.72em; margin-left:.15em; color:rgb(var(--ink2-rgb)); vertical-align:.15em; }

  .neutral-note{ background:rgb(var(--bg2-rgb)/.6); border:1px solid var(--line2); border-radius:14px; padding:.9rem 1.1rem; font-size:13.5px; line-height:1.6; color:rgb(var(--ink2-rgb)); }
  .src-list{ counter-reset:s; }
  .src-list li{ margin:.55rem 0; font-size:14.5px; line-height:1.55; color:rgb(var(--ink2-rgb)); }
  .src-list li a{ color:rgb(var(--ink-rgb)/.85); text-decoration:underline; text-decoration-color:rgb(var(--ink2-rgb)/.4); text-underline-offset:2.5px; }
  .src-list li a:hover{ color:rgb(var(--accent-rgb)); text-decoration-color:rgb(var(--accent-rgb)); }
  .tag{ display:inline-block; border-radius:99px; padding:.2rem .6rem; font-size:9.5px; }
</style>"""


def header(prefix):
    return f"""<header class="sticky top-0 z-40 bg-cream/85 backdrop-blur-md">
  <div class="max-w-[1100px] mx-auto px-5 sm:px-8 h-16 flex items-center justify-between border-b" style="border-color:var(--line)">
    <a href="{prefix}" class="font-display text-2xl font-semibold tracking-tight leading-none">Collo <span class="font-medium text-ink2">contre</span> <span class="text-ox">McDo</span></a>
    <nav class="flex items-center gap-6 eyebrow text-[10.5px] text-ink2">
      <a href="{prefix}#recit" class="hidden sm:inline hover:text-ox transition">Le récit</a>
      <a href="{prefix}#pieces" class="hover:text-ox transition">Les pièces</a>
      <a href="{prefix}actus/" class="text-ox hover:text-oxdeep transition">Actus</a>
    </nav>
  </div>
</header>"""


def footer(prefix):
    return f"""<footer class="mt-10 border-t" style="border-color:var(--line)">
  <div class="max-w-[1100px] mx-auto px-5 sm:px-8 py-10 text-[13px] text-ink2">
    <div class="font-display text-xl font-semibold text-ink">Collo <span class="font-medium text-ink2">contre</span> <span class="text-ox">McDo</span></div>
    <p class="mt-2 max-w-md">Dossier documentaire du procès Bernard Collorafi contre McDonald's France (Antibes, 1987–2002). Toutes les pièces en accès libre.</p>
    <p class="mt-3"><a href="{prefix}actus/" class="text-ox hover:text-oxdeep transition">Les actus du dossier</a></p>
    <p class="mt-3 text-gold eyebrow text-[9px]">Cour d'appel de Paris · RG 1998/14119</p>
    <p class="mt-2 text-[13px]"><a href="mailto:bernardcollo@gmail.com" class="text-ox hover:text-oxdeep transition">Contact&nbsp;: bernardcollo@gmail.com</a></p>
  </div>
</footer>"""


def esc(s):
    return html.escape(s, quote=True)


def index_page(articles):
    cards = []
    for i, a in enumerate(articles):
        big = i == 0
        if big:
            cards.append(
                f"""<a href="{a['slug']}/" class="card group block rounded-[22px] bg-panel border p-6 sm:p-8 softshadow sm:col-span-2" style="border-color:var(--line2)">
  <span class="eyebrow text-[10px] text-ox">{esc(a['cat'])} · {esc(a['date_fr'])}</span>
  <span class="block font-display text-[clamp(1.5rem,3.2vw,2.15rem)] font-extrabold leading-[1.08] tracking-[-.02em] mt-3 text-ink group-hover:text-ox transition">{esc(a['title'])}</span>
  <span class="block text-[16.5px] leading-relaxed text-ink2 mt-3 max-w-2xl">{esc(a['dek'])}</span>
  <span class="inline-flex items-center gap-1.5 mt-5 eyebrow text-[10px] text-ox">Lire l'article <span class="group-hover:translate-x-1 transition inline-block">›</span></span>
</a>"""
            )
        else:
            cards.append(
                f"""<a href="{a['slug']}/" class="card group block rounded-[18px] bg-panel border p-5" style="border-color:var(--line2)">
  <span class="eyebrow text-[9.5px] text-ox">{esc(a['cat'])}</span>
  <span class="block font-display text-[19px] font-bold leading-[1.15] tracking-[-.01em] mt-2 text-ink group-hover:text-ox transition">{esc(a['title'])}</span>
  <span class="block text-[14px] leading-snug text-ink2 mt-2">{esc(a['dek'])}</span>
  <span class="block eyebrow text-[9px] text-ink2/70 mt-4">{esc(a['date_fr'])}</span>
</a>"""
            )
    grid = "\n".join(cards)

    import json

    ld = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Blog",
            "name": "Actus — Le Dossier Collorafi",
            "url": BASE + "/actus/",
            "inLanguage": "fr-FR",
            "description": "Articles de contexte sur McDonald's, la franchise, les procès et les jurisprudences.",
            "blogPost": [
                {
                    "@type": "BlogPosting",
                    "headline": a["title"],
                    "url": f"{BASE}/actus/{a['slug']}/",
                    "datePublished": a["date_iso"],
                    "description": a["dek"],
                }
                for a in articles
            ],
        },
        ensure_ascii=False,
    )

    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
{GA}
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Actus — McDonald's, la franchise, les procès · Dossier Collorafi</title>
<meta name="description" content="Articles de contexte : le droit de la franchise, les grands procès de McDonald's dans le monde, les jurisprudences, les pratiques du réseau. Faits et sources, sans parti pris.">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="icon" type="image/png" sizes="32x32" href="../favicon-32.png">
<link rel="icon" href="../favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="../apple-touch-icon.png">
<link rel="canonical" href="{BASE}/actus/">
<meta property="og:type" content="website">
<meta property="og:title" content="Actus — McDonald's, la franchise, les procès">
<meta property="og:description" content="Articles de contexte : le droit de la franchise, les grands procès de McDonald's dans le monde, les jurisprudences, les pratiques du réseau.">
<meta property="og:url" content="{BASE}/actus/">
<meta property="og:site_name" content="Le Dossier Collorafi">
<meta property="og:image" content="{BASE}/assets/og-cover.png">
<meta property="og:locale" content="fr_FR">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{BASE}/assets/og-cover.png">
<script type="application/ld+json">{ld}</script>
<meta name="theme-color" content="#C2603F">
{STYLE}
</head>
<body class="font-body text-ink antialiased overflow-x-hidden">
{header("../")}

<main class="max-w-[1100px] mx-auto px-5 sm:px-8 py-10 sm:py-14">
  <nav class="crumb eyebrow text-[10px] mb-7 flex flex-wrap gap-2 items-center" aria-label="Fil d'Ariane">
    <a href="../">Accueil</a><span class="text-ink2/50">›</span>
    <span class="text-ink2/60">Actus</span>
  </nav>

  <div class="max-w-3xl">
    <p class="eyebrow text-[10px] text-ox mb-3">Actus</p>
    <h1 class="font-display text-[clamp(2.2rem,5.5vw,3.6rem)] font-extrabold leading-[1.02] tracking-[-.025em]">McDonald's, la franchise,<br>les procès</h1>
    <p class="mt-5 text-[19px] leading-[1.55] text-ink2">Le dossier Collorafi n'est pas un cas isolé&nbsp;: il s'inscrit dans une histoire — celle du contrat de franchise, des litiges qui l'ont façonné, et des affaires qui ont marqué McDonald's dans le monde. Ces articles rapportent les faits et citent leurs sources. Ils ne prennent pas parti.</p>
  </div>

  <div class="mt-12 grid sm:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
{grid}
  </div>

  <p class="mt-14 text-[13.5px] text-ink2 max-w-2xl">Ces articles sont des documents de contexte, distincts des <a href="../#pieces" class="text-ox hover:text-oxdeep transition underline underline-offset-2">87 pièces du procès</a>, qui sont, elles, les originaux versés au dossier.</p>
</main>

{footer("../")}
</body>
</html>
"""


def actus_section(articles):
    feat = articles[0]
    rest = articles[1:4]
    small = "\n".join(
        f'''          <a href="actus/{a["slug"]}/" class="card group block rounded-[16px] bg-panel border p-4" style="border-color:var(--line2)">
            <span class="eyebrow text-[9px] text-ox">{esc(a["cat"])}</span>
            <span class="block font-display text-[16.5px] font-bold leading-[1.16] tracking-[-.01em] mt-1.5 text-ink group-hover:text-ox transition">{esc(a["title"])}</span>
            <span class="block text-[13px] leading-snug text-ink2 mt-1.5" style="display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden">{esc(a["dek"])}</span>
          </a>'''
        for a in rest
    )
    return f'''<!-- ============ ACTUS ============ -->
<section id="actus" class="mt-24 sm:mt-32">
  <div class="max-w-[1320px] mx-auto px-5 sm:px-8">
    <div class="h-px hair"></div>
    <div class="pt-12 flex flex-wrap items-end justify-between gap-4">
      <div>
        <p class="eyebrow text-[10px] text-ox">Actus</p>
        <h2 class="mt-2 font-display text-[clamp(1.9rem,4vw,2.8rem)] font-extrabold leading-[1.05] tracking-[-.02em]">McDonald's, la franchise, les procès</h2>
        <p class="mt-3 max-w-2xl text-[16.5px] leading-relaxed text-ink2">Des articles de contexte pour situer ce dossier&nbsp;: le droit de la franchise, les grandes affaires judiciaires du groupe dans le monde, les jurisprudences.</p>
      </div>
      <a href="actus/" class="eyebrow text-[10px] text-ox hover:text-oxdeep transition shrink-0">Toutes les actus ›</a>
    </div>

    <div class="mt-8 grid lg:grid-cols-[1.35fr_1fr] gap-4 items-start">
      <a href="actus/{feat["slug"]}/" class="card group block rounded-[22px] bg-panel border p-6 sm:p-8 softshadow" style="border-color:var(--line2)">
        <span class="eyebrow text-[10px] text-ox">{esc(feat["cat"])} · {esc(feat["date_fr"])}</span>
        <span class="block font-display text-[clamp(1.45rem,2.6vw,2rem)] font-extrabold leading-[1.1] tracking-[-.02em] mt-3 text-ink group-hover:text-ox transition">{esc(feat["title"])}</span>
        <span class="block text-[16px] leading-relaxed text-ink2 mt-3">{esc(feat["dek"])}</span>
        <span class="inline-flex items-center gap-1.5 mt-5 eyebrow text-[10px] text-ox">Lire l'article <span class="group-hover:translate-x-1 transition inline-block">›</span></span>
      </a>
      <div class="grid gap-3">
{small}
      </div>
    </div>
  </div>
</section>
<!-- ============ /ACTUS ============ -->'''




def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def rebuild_index(articles):
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_page(articles))


def rebuild_home(articles):
    p = os.path.join(SITE, "index.html")
    with open(p, encoding="utf-8") as f:
        s = f.read()
    new = re.sub(
        r"<!-- ============ ACTUS ============ -->.*?<!-- ============ /ACTUS ============ -->",
        lambda _m: actus_section(articles),
        s,
        flags=re.S,
    )
    if new == s:
        return False
    with open(p, "w", encoding="utf-8") as f:
        f.write(new)
    return True


def rebuild_sitemap(articles, today):
    p = os.path.join(SITE, "sitemap.xml")
    with open(p, encoding="utf-8") as f:
        sm = f.read()
    sm = re.sub(r"\s*<url><loc>https://bernardcollorafi\.org/actus/[^<]*</loc>.*?</url>", "", sm)
    rows = [f'  <url><loc>{BASE}/actus/</loc><lastmod>{today}</lastmod><priority>0.9</priority></url>']
    for a in articles:
        rows.append(
            f'  <url><loc>{BASE}/actus/{a["slug"]}/</loc><lastmod>{a["date_iso"]}</lastmod><priority>0.8</priority></url>'
        )
    sm = sm.replace("</urlset>", "\n".join(rows) + "\n</urlset>")
    with open(p, "w", encoding="utf-8") as f:
        f.write(sm)


def main():
    today = datetime.date.today().isoformat()
    articles = load(REGISTRY)
    known = {a["slug"] for a in articles}

    manifest_path = os.path.join(QUEUE, "manifest.json")
    due = []
    if os.path.exists(manifest_path):
        for entry in load(manifest_path):
            if entry["slug"] in known:
                continue
            if entry["publish_at"] <= today:
                due.append(entry)

    if not due:
        print("rien a publier (date du jour: %s)" % today)
        return 0

    due.sort(key=lambda e: e["publish_at"])
    for entry in due:
        slug = entry["slug"]
        src = os.path.join(QUEUE, "pages", slug, "index.html")
        if not os.path.exists(src):
            print("ERREUR: page absente pour %s" % slug, file=sys.stderr)
            return 1
        dst = os.path.join(OUT, slug)
        os.makedirs(dst, exist_ok=True)
        shutil.copyfile(src, os.path.join(dst, "index.html"))
        meta = {k: entry[k] for k in ("slug", "cat", "date_fr", "date_iso", "title", "dek")}
        articles.insert(0, meta)  # le plus recent en tete (article a la une)
        print("publie: %s (%s)" % (slug, entry["publish_at"]))

    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
        f.write("\n")

    rebuild_index(articles)
    rebuild_home(articles)
    rebuild_sitemap(articles, today)
    print("regenere: actus/index.html, index.html (bloc Actus), sitemap.xml")
    return 0


if __name__ == "__main__":
    sys.exit(main())
