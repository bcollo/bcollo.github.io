#!/usr/bin/env python3
"""Rapport d'audience (Google Analytics 4), envoyé par e-mail chaque lundi.

Période couverte : LE MOIS EN COURS, du 1er à hier.
Comparaison : la même tranche de jours du mois précédent (1er au même quantième),
donnée en valeur absolue et non en pourcentage flottant.

Lancé par .github/workflows/ga-report.yml sur les serveurs GitHub.

⚠️ CE DÉPÔT EST PUBLIC — donc les logs d'exécution des Actions le sont aussi.
Ce script n'imprime JAMAIS le contenu du rapport, ni le destinataire, ni un chiffre.
Il ne dit que « rapport envoye ». Ne pas ajouter de print() de debug ici.

Zéro dépendance : l'authentification est faite en amont par google-github-actions/auth,
qui dépose un jeton OAuth de courte durée dans GA_ACCESS_TOKEN. Aucune clé n'est stockée.
"""
import calendar
import datetime
import html
import json
import math
import os
import smtplib
import struct
import sys
import urllib.error
import urllib.request
import zlib
from email.message import EmailMessage

API = "https://analyticsdata.googleapis.com/v1beta/properties/%s:runReport"
SITE = "bernardcollorafi.org"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
MOIS_COURT = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.",
              "août", "sept.", "oct.", "nov.", "déc."]
JOURS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]

INK, INK2, ACCENT, BG, PANEL, LINE = "#221e1a", "#8a8072", "#C2603F", "#F5F0E8", "#FBF8F3", "#e3d9c9"


# ------------------------------------------------------------------- périodes

def periods(today):
    """(mois en cours du 1er à hier) et (même tranche du mois précédent)."""
    hier = today - datetime.timedelta(days=1)
    debut = hier.replace(day=1)          # si on est le 1er, hier est dans le mois d'avant :
                                         # on rapporte alors le mois précédent en entier.
    # mois précédent, même nombre de jours (borné à la longueur du mois)
    pm_last = debut - datetime.timedelta(days=1)
    pm_debut = pm_last.replace(day=1)
    jours = calendar.monthrange(pm_debut.year, pm_debut.month)[1]
    pm_fin = pm_debut.replace(day=min(hier.day, jours))
    return (debut, hier), (pm_debut, pm_fin)


def jour_fr(d):
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]}"


# ---------------------------------------------------------------------- API

def env(key):
    val = os.environ.get(key, "").strip()
    if not val:
        sys.exit(f"variable d'environnement manquante : {key}")
    return val


def run_report(prop, token, body):
    req = urllib.request.Request(
        API % prop,
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"API GA4 : erreur HTTP {e.code}")  # on ne relaie pas le corps


def query(prop, token, span, metrics, dimensions=(), limit=25, order=None):
    body = {
        "dateRanges": [{"startDate": span[0].isoformat(), "endDate": span[1].isoformat()}],
        "metrics": [{"name": m} for m in metrics],
        "limit": limit,
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
    if order:
        body["orderBys"] = [{"metric": {"metricName": order}, "desc": True}]
    rows = []
    for r in run_report(prop, token, body).get("rows", []):
        rows.append((
            [d.get("value", "") for d in r.get("dimensionValues", [])],
            [num(m.get("value", "0")) for m in r.get("metricValues", [])],
        ))
    return rows


def num(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def section_of(path):
    if path in ("/", ""):
        return "Accueil"
    for prefix, name in (("/actus/", "Actus"), ("/pieces/", "Pièces"), ("/reperes/", "Repères")):
        if path.startswith(prefix):
            return name
    return "Autres"


# ------------------------------------------------------------------ affichage

def fr(n):
    return f"{n:,}".replace(",", "\u00a0")  # non-breaking: "1 234" never wraps


def resume(entetes, lignes):
    """Summary table: one row per metric, one column per period (each header names its dates)."""
    th = "".join(
        f'<th align="{"right" if i else "left"}" style="font:600 11px/1.35 Arial,sans-serif;color:{INK2};'
        f'padding:0 0 10px 10px;border-bottom:1px solid {LINE};vertical-align:bottom">{h}</th>'
        for i, h in enumerate(entetes))
    trs = []
    for label, hier, val, prev in lignes:
        ecart = val - prev
        couleur = "#2f7a52" if ecart > 0 else (ACCENT if ecart < 0 else INK2)
        signe = "+" if ecart > 0 else ("−" if ecart < 0 else "")
        cells = [label, fr(hier), f"<strong>{fr(val)}</strong>", fr(prev),
                 f'<span style="color:{couleur};font-weight:700">{signe}{fr(abs(ecart))}</span>' if prev else "—"]
        trs.append("<tr>" + "".join(
            f'<td align="{"right" if i else "left"}" style="font:400 15px/1.4 Arial,sans-serif;color:{INK};'
            f'padding:12px 0 12px 10px;border-bottom:1px solid #efe8dc;white-space:nowrap">{c}</td>'
            for i, c in enumerate(cells)) + "</tr>")
    return f"""
    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin-top:22px">
      <tr>{th}</tr>{"".join(trs)}
    </table>"""


# Gmail ignores <svg> and data: URIs, so the curve is a PNG attached by CID.
# Drawn with the stdlib only: tiny rasterizer + 3x5 digit font.
FONT = {"0": "111101101101111", "1": "010110010010111", "2": "111001111100111",
        "3": "111001111001111", "4": "101101111001001", "5": "111100111001111",
        "6": "111100111101111", "7": "111001001001001", "8": "111101111101111",
        "9": "111101111001111"}


def rgb(h):
    return bytes.fromhex(h[1:])


class Canvas:
    def __init__(self, w, h, bg):
        self.w, self.h = w, h
        self.px = bytearray(rgb(bg) * (w * h))

    def rect(self, x0, y0, x1, y1, col):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.w, int(x1)), min(self.h, int(y1))
        if x1 <= x0:
            return
        c = rgb(col)
        for y in range(y0, y1):
            i = (y * self.w + x0) * 3
            self.px[i:i + (x1 - x0) * 3] = c * (x1 - x0)

    def disc(self, x, y, r, col):
        for dy in range(-r, r + 1):
            half = int(math.sqrt(r * r - dy * dy))
            self.rect(x - half, y + dy, x + half + 1, y + dy + 1, col)

    def line(self, pts, col, r):
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            n = int(max(abs(xb - xa), abs(yb - ya))) + 1
            for k in range(n + 1):
                self.disc(xa + (xb - xa) * k / n, ya + (yb - ya) * k / n, r, col)

    def text(self, x, y, txt, col, sc=4, align="left"):
        w = len(txt) * 4 * sc - sc
        x = x - w if align == "right" else (x - w / 2 if align == "center" else x)
        for n, ch in enumerate(txt):
            for k, bit in enumerate(FONT.get(ch, "0" * 15)):
                if bit == "1":
                    cx, cy = x + n * 4 * sc + (k % 3) * sc, y + (k // 3) * sc
                    self.rect(cx, cy, cx + sc, cy + sc, col)

    def png(self):
        raw = b"".join(b"\0" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def nice_step(x):
    mag = 10 ** math.floor(math.log10(max(x, 1)))
    return max(1, next(m * mag for m in (1, 2, 5, 10) if m * mag >= x))


def courbe(cur_vals, prev_vals, n_days):
    """Visitors per day: this month (filled curve) vs last month (grey line). 2x size for retina."""
    W, H, L, R, T, B = 1200, 440, 96, 24, 24, 64
    c = Canvas(W, H, PANEL)
    step = nice_step(max(cur_vals + prev_vals + [1]) / 4)
    ymax = step * math.ceil(max(cur_vals + prev_vals + [1]) / step)

    def X(i):
        return L + (W - L - R) * i / max(n_days - 1, 1)

    def Y(v):
        return H - B - (H - T - B) * v / ymax

    for k in range(ymax // step + 1):
        y = Y(k * step)
        c.rect(L, y - 1, W - R, y + 1, LINE)
        c.text(L - 20, y - 10, str(k * step), INK2, align="right")
    for d in (1, 5, 10, 15, 20, 25, 30):
        if d <= n_days:
            c.text(X(d - 1), H - B + 22, str(d), INK2, align="center")

    pts = [(X(i), Y(v)) for i, v in enumerate(cur_vals)]
    for (xa, ya), (xb, yb) in zip(pts, pts[1:]):  # light area under the curve
        for x in range(int(xa), int(xb) + 1):
            c.rect(x, ya + (yb - ya) * (x - xa) / (xb - xa), x + 1, H - B, "#F3DDD2")
    if prev_vals:
        c.line([(X(i), Y(v)) for i, v in enumerate(prev_vals)], "#BDB2A2", 3)
    if pts:
        c.line(pts, ACCENT, 4)
        c.disc(pts[-1][0], pts[-1][1], 9, ACCENT)
    return c.png()


def annee(rows, today_month):
    """Visitors per month over 12 rolling months, as HTML bars (no image needed)."""
    vals = [(ym, v) for ym, v in rows]
    while vals and not vals[0][1]:  # skip the months before the site existed
        vals.pop(0)
    if not vals:
        return ""
    maxi = max(v for _, v in vals) or 1
    cols, labels = [], []
    for ym, v in vals:
        en_cours = ym == today_month
        h = max(round(v / maxi * 150), 2)
        cols.append(f"""<td align="center" valign="bottom" style="padding:0 3px">
          <div style="font:600 11px/1.3 Arial,sans-serif;color:{INK};margin-bottom:4px">{fr(v)}</div>
          <div style="height:{h}px;background:{"#E3B5A3" if en_cours else ACCENT};border-radius:4px 4px 0 0"></div></td>""")
        mois = MOIS_COURT[int(ym[4:]) - 1]
        labels.append(f'<td align="center" style="font:400 11px/1.3 Arial,sans-serif;color:{INK2};padding-top:6px">'
                      f'{mois}{"<br>(en cours)" if en_cours else ""}</td>')
    total = sum(v for _, v in vals)
    return f"""
    <h2 style="font:700 17px/1.3 Georgia,serif;color:{INK};margin:36px 0 4px">Visiteurs mois par mois</h2>
    <p style="font:400 13px/1.5 Arial,sans-serif;color:{INK2};margin:0 0 14px">{fr(total)} visiteurs au total sur la période.
      Le mois en cours (barre claire) n'est pas terminé.</p>
    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;table-layout:fixed">
      <tr>{"".join(cols)}</tr><tr>{"".join(labels)}</tr>
    </table>"""


def tuile(label, valeur, detail=""):
    return f"""
      <td width="50%" style="padding:14px 16px;background:{BG};border-radius:12px;vertical-align:top">
        <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:{INK2}">{html.escape(label)}</div>
        <div style="font:700 20px/1.3 Georgia,serif;color:{INK};margin-top:5px">{valeur}</div>
        <div style="font:400 12px/1.4 Arial,sans-serif;color:{INK2}">{detail}</div>
      </td>"""


def par_jour(rows, span):
    vals = {d[0]: v[0] for d, v in rows}
    out, d = [], span[0]
    while d <= span[1]:
        out.append(vals.get(d.strftime("%Y%m%d"), 0))
        d += datetime.timedelta(days=1)
    return out


def table(titre, entetes, lignes, note=""):
    if not lignes:
        return ""
    th = "".join(
        f'<th align="{"right" if i else "left"}" style="font:600 10px/1.2 Arial,sans-serif;'
        f'letter-spacing:.08em;text-transform:uppercase;color:{INK2};padding:0 0 9px;'
        f'border-bottom:1px solid {LINE}">{html.escape(h)}</th>' for i, h in enumerate(entetes))
    trs = "".join(
        "<tr>" + "".join(
            f'<td align="{"right" if i else "left"}" style="font:400 14px/1.45 Arial,sans-serif;'
            f'color:{INK};padding:10px 0;border-bottom:1px solid #efe8dc">{c}</td>'
            for i, c in enumerate(r)) + "</tr>" for r in lignes)
    n = (f'<p style="font:400 12px/1.5 Arial,sans-serif;color:{INK2};margin:8px 0 0">{html.escape(note)}</p>'
         if note else "")
    return f"""
    <h2 style="font:700 17px/1.3 Georgia,serif;color:{INK};margin:36px 0 12px">{html.escape(titre)}</h2>
    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
      <tr>{th}</tr>{trs}
    </table>{n}"""


# -------------------------------------------------------------------- rapport

def build_html(prop, token, cur, prev):
    metrics = ["totalUsers", "sessions", "screenPageViews", "newUsers", "averageSessionDuration"]
    tot_cur = query(prop, token, cur, metrics)
    tot_prev = query(prop, token, prev, metrics)
    c = tot_cur[0][1] if tot_cur else [0] * 5
    p = tot_prev[0][1] if tot_prev else [0] * 5
    prev_label = MOIS[prev[0].month - 1]
    cur_label = MOIS[cur[0].month - 1]

    jours_cur = par_jour(query(prop, token, cur, ["totalUsers"], ["date"], 62), cur)
    jours_prev = par_jour(query(prop, token, prev, ["totalUsers"], ["date"], 62), prev)
    n_mois = calendar.monthrange(cur[0].year, cur[0].month)[1]
    image = courbe(jours_cur, jours_prev, n_mois)

    y, m = cur[0].year, cur[0].month - 11
    if m < 1:
        y, m = y - 1, m + 12
    mensuel = query(prop, token, (datetime.date(y, m, 1), cur[1]), ["totalUsers"], ["yearMonth"], 24)
    mensuel = sorted((d[0], v[0]) for d, v in mensuel)
    bloc_annee = annee(mensuel, cur[0].strftime("%Y%m"))

    best = max(range(len(jours_cur)), key=lambda i: jours_cur[i]) if jours_cur else 0
    best_day = cur[0] + datetime.timedelta(days=best)
    duree = c[4]
    tot_hier = query(prop, token, (cur[1], cur[1]), metrics[:3])
    h = tot_hier[0][1] if tot_hier else [0] * 3

    pages = query(prop, token, cur, ["screenPageViews"], ["pagePath", "pageTitle"], 300, "screenPageViews")
    top = []
    for dims, vals in pages[:15]:
        path, titre = dims[0], dims[1]
        titre = titre.split(" — ")[0].split(" · ")[0].strip() or path
        top.append([
            f'<a href="https://{SITE}{html.escape(path)}" style="color:{INK};text-decoration:none">{html.escape(titre[:72])}</a>'
            f'<div style="font:400 11px/1.4 Arial,sans-serif;color:{INK2};margin-top:2px">{html.escape(path)}</div>',
            fr(vals[0]),
        ])

    sect = {}
    for dims, vals in pages:
        s = section_of(dims[0])
        sect[s] = sect.get(s, 0) + vals[0]
    total_vues = sum(sect.values()) or 1
    sect_rows = [[html.escape(k), fr(v), f"{round(v / total_vues * 100)} %"]
                 for k, v in sorted(sect.items(), key=lambda kv: -kv[1])]

    chan = [[html.escape(d[0] or "(non défini)"), fr(v[0])]
            for d, v in query(prop, token, cur, ["sessions"], ["sessionDefaultChannelGroup"], 12, "sessions")]
    src = [[html.escape(d[0] or "(direct)"), fr(v[0])]
           for d, v in query(prop, token, cur, ["sessions"], ["sessionSource"], 10, "sessions")]
    pays = [[html.escape(d[0] or "—"), fr(v[0])]
            for d, v in query(prop, token, cur, ["totalUsers"], ["country"], 8, "totalUsers")]

    titre_mois = f"{MOIS[cur[0].month - 1].capitalize()} {cur[0].year}"

    court = lambda d: f"{'1er' if d.day == 1 else d.day} {MOIS_COURT[d.month - 1]}"  # noqa: E731
    jour_hier = f"{JOURS[cur[1].weekday()]}. {court(cur[1])}"
    entetes = ["", f"Hier<br>{jour_hier}",
               f"Ce mois-ci<br>du {court(cur[0])} au {court(cur[1])}",
               f"Mois dernier<br>du {court(prev[0])} au {court(prev[1])}",
               "Écart"]
    lignes = [("Visiteurs", h[0], c[0], p[0]), ("Pages vues", h[2], c[2], p[2]), ("Sessions", h[1], c[1], p[1])]
    n_cur = (cur[1] - cur[0]).days + 1

    return f"""<!doctype html>
<html><head><meta charset="utf-8"></head><body style="margin:0;padding:0;background:{BG}">
<table width="100%" cellspacing="0" cellpadding="0" style="background:{BG}">
 <tr><td align="center" style="padding:28px 14px">
  <table width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:{PANEL};border-radius:18px;padding:32px 34px">
   <tr><td>
    <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:{ACCENT}">Rapport d'audience</div>
    <h1 style="font:700 28px/1.2 Georgia,serif;color:{INK};margin:8px 0 6px">{html.escape(titre_mois)}</h1>
    <p style="font:400 14px/1.5 Arial,sans-serif;color:{INK2};margin:0">
      Chiffres arrêtés à hier soir ({jour_hier}). « Écart » = ce mois-ci moins le mois dernier, sur les mêmes jours.
    </p>
    {resume(entetes, lignes)}

    <h2 style="font:700 17px/1.3 Georgia,serif;color:{INK};margin:36px 0 4px">Visiteurs par jour</h2>
    <p style="font:400 13px/1.5 Arial,sans-serif;color:{INK2};margin:0 0 12px">
      <span style="color:{ACCENT};font-weight:700">&#9644;</span> {cur_label}&nbsp;&nbsp;
      <span style="color:#BDB2A2;font-weight:700">&#9644;</span> {prev_label}, mêmes jours.
      En bas, le jour du mois ; à gauche, le nombre de visiteurs.</p>
    <img src="cid:courbe" width="572" alt="Courbe des visiteurs par jour" style="display:block;width:100%;max-width:572px;height:auto;border:0">

    <h2 style="font:700 17px/1.3 Georgia,serif;color:{INK};margin:36px 0 12px">Depuis le {jour_fr(cur[0])}</h2>
    <table width="100%" cellspacing="9" cellpadding="0" style="border-collapse:separate">
      <tr>{tuile("Moyenne par jour", f"{fr(round(c[0] / n_cur))} visiteurs", f"{fr(round(c[2] / n_cur))} pages vues par jour")}
          {tuile("Meilleur jour", f"{fr(jours_cur[best] if jours_cur else 0)} visiteurs", f"le {JOURS[best_day.weekday()]}. {jour_fr(best_day)}")}</tr>
      <tr>{tuile("Nouveaux visiteurs", fr(c[3]), f"{round(c[3] / c[0] * 100) if c[0] else 0} % des visiteurs venaient pour la 1re fois")}
          {tuile("Durée moyenne d'une visite", f"{duree // 60} min {duree % 60:02d} s", f"{(c[2] / c[1] if c[1] else 0):.1f}".replace(".", ",") + " pages lues par visite")}</tr>
    </table>

    {bloc_annee}
    {table("Les pages les plus lues", ["Page", "Vues"], top)}
    {table("Par section du site", ["Section", "Vues", "Part"], sect_rows)}
    {table("D'où vient le trafic", ["Canal", "Sessions"], chan)}
    {table("Sources précises", ["Source", "Sessions"], src)}
    {table("Pays", ["Pays", "Visiteurs"], pays)}

    <p style="font:400 12px/1.6 Arial,sans-serif;color:{INK2};margin:34px 0 0;padding-top:18px;border-top:1px solid {LINE}">
      Données Google Analytics 4 — {html.escape(SITE)}. Rapport généré chaque lundi par GitHub Actions.
    </p>
   </td></tr>
  </table>
 </td></tr>
</table>
</body></html>""", image


def send(sujet, corps, image, to, user, password):
    dests = [a.strip() for a in to.replace(";", ",").split(",") if a.strip()]
    if not dests:
        sys.exit("MAIL_TO ne contient aucune adresse")
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = f"Dossier Collorafi <{user}>"
    msg["To"] = ", ".join(dests)
    msg.set_content("Ce rapport nécessite un client mail capable d'afficher le HTML.")
    msg.add_alternative(corps, subtype="html")
    msg.get_payload()[1].add_related(image, "image", "png", cid="<courbe>", filename="courbe.png")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, password)
        s.send_message(msg)


def main():
    prop = env("GA_PROPERTY_ID")
    token = env("GA_ACCESS_TOKEN")
    to, user, password = env("MAIL_TO"), env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")

    cur, prev = periods(datetime.date.today())
    corps, image = build_html(prop, token, cur, prev)
    sujet = f"Audience {MOIS[cur[0].month - 1]} {cur[0].year} — du {jour_fr(cur[0])} au {jour_fr(cur[1])}"
    send(sujet, corps, image, to, user, password)
    print("rapport envoye")  # rien d'autre : les logs de ce depot sont publics


if __name__ == "__main__":
    main()
