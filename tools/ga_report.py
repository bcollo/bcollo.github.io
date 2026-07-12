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
import os
import smtplib
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage

API = "https://analyticsdata.googleapis.com/v1beta/properties/%s:runReport"
SITE = "bernardcollorafi.org"

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
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
    return f"{n:,}".replace(",", " ")


def kpi(label, val, prev, prev_label):
    if prev:
        ecart = val - prev
        signe = "+" if ecart > 0 else ("−" if ecart < 0 else "")
        couleur = "#2f7a52" if ecart > 0 else (ACCENT if ecart < 0 else INK2)
        comp = (f'<span style="color:{couleur};font-weight:600">{signe}{fr(abs(ecart))}</span>'
                f'<span style="color:{INK2}">&nbsp;vs {fr(prev)} en {prev_label}</span>')
    else:
        comp = f'<span style="color:{INK2}">aucune donnée en {prev_label}</span>'
    return f"""
      <td width="33%" style="padding:16px 18px;background:{BG};border-radius:14px;vertical-align:top">
        <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:{INK2}">{html.escape(label)}</div>
        <div style="font:700 30px/1.2 Georgia,serif;color:{INK};margin:6px 0 5px">{fr(val)}</div>
        <div style="font:400 12px/1.4 Arial,sans-serif">{comp}</div>
      </td>"""


def bars(rows, span):
    """Barres jour par jour : lisible dans tous les clients mail (tableau + fond coloré)."""
    if not rows:
        return ""
    par_jour = {d[0]: v[0] for d, v in rows}
    jours, maxi = [], max(par_jour.values()) or 1
    d = span[0]
    while d <= span[1]:
        jours.append((d, par_jour.get(d.strftime("%Y%m%d"), 0)))
        d += datetime.timedelta(days=1)

    lignes = []
    for d, v in jours:
        pct = max(round(v / maxi * 100), 1) if v else 0
        barre = (f'<div style="height:11px;width:{pct}%;background:{ACCENT};border-radius:3px"></div>'
                 if v else f'<div style="height:11px;width:2px;background:{LINE};border-radius:3px"></div>')
        lignes.append(f"""
        <tr>
          <td width="58" style="font:400 11px/1.4 Arial,sans-serif;color:{"#b9ad9b" if d.weekday() >= 5 else INK2};padding:3px 10px 3px 0;white-space:nowrap">{JOURS[d.weekday()]}. {d.day}</td>
          <td style="padding:3px 10px 3px 0">{barre}</td>
          <td width="46" align="right" style="font:600 12px/1.4 Arial,sans-serif;color:{INK};padding:3px 0">{fr(v)}</td>
        </tr>""")
    return f"""
    <h2 style="font:700 17px/1.3 Georgia,serif;color:{INK};margin:36px 0 12px">Pages vues, jour par jour</h2>
    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">{''.join(lignes)}</table>"""


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
    tot_cur = query(prop, token, cur, ["totalUsers", "sessions", "screenPageViews"])
    tot_prev = query(prop, token, prev, ["totalUsers", "sessions", "screenPageViews"])
    c = tot_cur[0][1] if tot_cur else [0, 0, 0]
    p = tot_prev[0][1] if tot_prev else [0, 0, 0]
    prev_label = MOIS[prev[0].month - 1]

    daily = query(prop, token, cur, ["screenPageViews"], ["date"], 62)

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

    # ne jamais annoncer « à durée égale » quand le mois précédent est trop court (ex. février)
    n_cur = (cur[1] - cur[0]).days + 1
    n_prev = (prev[1] - prev[0]).days + 1
    if n_cur == n_prev:
        mention = f'Comparaison avec la même tranche de <strong style="color:{INK}">{prev_label}</strong> : du {jour_fr(prev[0])} au {jour_fr(prev[1])}.'
    else:
        mention = (f'Comparaison avec <strong style="color:{INK}">{prev_label}</strong>, du {jour_fr(prev[0])} '
                   f'au {jour_fr(prev[1])} — {n_prev} jours seulement, le mois étant plus court.')

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:{BG}">
<table width="100%" cellspacing="0" cellpadding="0" style="background:{BG}">
 <tr><td align="center" style="padding:28px 14px">
  <table width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:{PANEL};border-radius:18px;padding:32px 34px">
   <tr><td>
    <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:{ACCENT}">Rapport d'audience</div>
    <h1 style="font:700 28px/1.2 Georgia,serif;color:{INK};margin:8px 0 6px">{html.escape(titre_mois)}</h1>
    <p style="font:400 14px/1.5 Arial,sans-serif;color:{INK2};margin:0">
      Du {jour_fr(cur[0])} au {jour_fr(cur[1])}, soit {n_cur} jours. {mention}
    </p>

    <table width="100%" cellspacing="9" cellpadding="0" style="margin:24px 0 0;border-collapse:separate">
      <tr>{kpi("Visiteurs", c[0], p[0], prev_label)}{kpi("Sessions", c[1], p[1], prev_label)}{kpi("Pages vues", c[2], p[2], prev_label)}</tr>
    </table>

    {bars(daily, cur)}
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
</body></html>"""


def send(sujet, corps, to, user, password):
    msg = EmailMessage()
    msg["Subject"] = sujet
    msg["From"] = f"Dossier Collorafi <{user}>"
    msg["To"] = to
    msg.set_content("Ce rapport nécessite un client mail capable d'afficher le HTML.")
    msg.add_alternative(corps, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, password)
        s.send_message(msg)


def main():
    prop = env("GA_PROPERTY_ID")
    token = env("GA_ACCESS_TOKEN")
    to, user, password = env("MAIL_TO"), env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")

    cur, prev = periods(datetime.date.today())
    corps = build_html(prop, token, cur, prev)
    sujet = f"Audience {MOIS[cur[0].month - 1]} {cur[0].year} — du {jour_fr(cur[0])} au {jour_fr(cur[1])}"
    send(sujet, corps, to, user, password)
    print("rapport envoye")  # rien d'autre : les logs de ce depot sont publics


if __name__ == "__main__":
    main()
