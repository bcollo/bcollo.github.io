#!/usr/bin/env python3
"""Rapport d'audience hebdomadaire (Google Analytics 4), envoyé par e-mail.

Lancé par .github/workflows/ga-report.yml sur les serveurs GitHub (cron du lundi).

⚠️ CE DÉPÔT EST PUBLIC — donc les logs d'exécution des Actions le sont aussi.
Ce script n'imprime JAMAIS le contenu du rapport, ni le destinataire, ni un chiffre.
Il ne dit que « rapport envoyé ». Ne pas ajouter de print() de debug ici.

Zéro dépendance : l'authentification est faite en amont par google-github-actions/auth,
qui dépose un jeton OAuth de courte durée dans GA_ACCESS_TOKEN. Aucune clé n'est stockée
nulle part.

Variables attendues :
  GA_PROPERTY_ID       identifiant NUMÉRIQUE de la propriété GA4 (pas le « G-… »)
  GA_ACCESS_TOKEN      jeton OAuth fourni par l'action d'authentification
  MAIL_TO              destinataire du rapport
  GMAIL_USER           compte Gmail expéditeur
  GMAIL_APP_PASSWORD   mot de passe d'application Gmail (16 caractères)
"""
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

CUR = ("7daysAgo", "yesterday")
PREV = ("14daysAgo", "8daysAgo")


def env(key):
    val = os.environ.get(key, "").strip()
    if not val:
        sys.exit(f"variable d'environnement manquante : {key}")
    return val


def run_report(prop, token, body):
    req = urllib.request.Request(
        API % prop,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # on ne relaie PAS le corps de la réponse : il peut contenir des données
        sys.exit(f"API GA4 : erreur HTTP {e.code}")


def query(prop, token, period, metrics, dimensions=(), limit=25, order_desc=None):
    body = {
        "dateRanges": [{"startDate": period[0], "endDate": period[1]}],
        "metrics": [{"name": m} for m in metrics],
        "limit": limit,
    }
    if dimensions:
        body["dimensions"] = [{"name": d} for d in dimensions]
    if order_desc:
        body["orderBys"] = [{"metric": {"metricName": order_desc}, "desc": True}]
    data = run_report(prop, token, body)
    rows = []
    for r in data.get("rows", []):
        dims = [d.get("value", "") for d in r.get("dimensionValues", [])]
        vals = [num(m.get("value", "0")) for m in r.get("metricValues", [])]
        rows.append((dims, vals))
    return rows


def num(s):
    try:
        return int(float(s))
    except (TypeError, ValueError):
        return 0


def totals(prop, token, period):
    rows = query(prop, token, period, ["totalUsers", "sessions", "screenPageViews"])
    return rows[0][1] if rows else [0, 0, 0]


def section_of(path):
    if path in ("/", ""):
        return "Accueil"
    if path.startswith("/actus/"):
        return "Actus"
    if path.startswith("/pieces/"):
        return "Pièces"
    if path.startswith("/reperes/"):
        return "Repères"
    return "Autres"


# ---------------------------------------------------------------- mise en forme

def fr(n):
    return f"{n:,}".replace(",", " ")


def delta(cur, prev):
    if not prev:
        return ("—", "#8a8072")
    pct = round((cur - prev) / prev * 100)
    if pct > 0:
        return (f"+{pct} %", "#2f7a52")
    if pct < 0:
        return (f"{pct} %".replace("-", "−"), "#a54e30")
    return ("stable", "#8a8072")


def kpi(label, cur, prev):
    txt, color = delta(cur, prev)
    return f"""
      <td style="padding:14px 16px;background:#EAE2D6;border-radius:12px;vertical-align:top">
        <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.09em;text-transform:uppercase;color:#8a8072">{html.escape(label)}</div>
        <div style="font:700 26px/1.25 Georgia,serif;color:#221e1a;margin-top:4px">{fr(cur)}</div>
        <div style="font:400 12px/1.3 Arial,sans-serif;color:{color};margin-top:2px">{txt} <span style="color:#8a8072">vs 7 j. préc.</span></div>
      </td>"""


def table(title, headers, rows, note=""):
    if not rows:
        return ""
    th = "".join(
        f'<th align="{"right" if i else "left"}" style="font:600 10px/1.2 Arial,sans-serif;'
        f'letter-spacing:.08em;text-transform:uppercase;color:#8a8072;padding:0 0 8px;'
        f'border-bottom:1px solid #ddd3c4">{html.escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    trs = []
    for r in rows:
        tds = "".join(
            f'<td align="{"right" if i else "left"}" style="font:400 14px/1.45 Arial,sans-serif;'
            f'color:#221e1a;padding:9px 0;border-bottom:1px solid #efe8dc">{c}</td>'
            for i, c in enumerate(r)
        )
        trs.append(f"<tr>{tds}</tr>")
    n = f'<p style="font:400 12px/1.5 Arial,sans-serif;color:#8a8072;margin:6px 0 0">{html.escape(note)}</p>' if note else ""
    return f"""
    <h2 style="font:700 17px/1.3 Georgia,serif;color:#221e1a;margin:34px 0 10px">{html.escape(title)}</h2>
    <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse">
      <tr>{th}</tr>
      {''.join(trs)}
    </table>{n}"""


def build_html(prop, token, d1, d2):
    cur = totals(prop, token, CUR)
    prev = totals(prop, token, PREV)

    # pages
    pages_cur = query(prop, token, CUR, ["screenPageViews"], ["pagePath"], 300, "screenPageViews")
    pages_prev = dict(
        (d[0], v[0])
        for d, v in query(prop, token, PREV, ["screenPageViews"], ["pagePath"], 300, "screenPageViews")
    )
    titles = {d[0]: d[1] for d, _ in query(prop, token, CUR, ["screenPageViews"], ["pagePath", "pageTitle"], 300, "screenPageViews")}

    top_rows = []
    for dims, vals in pages_cur[:15]:
        path = dims[0]
        t = titles.get(path, path).split(" — ")[0].split(" · ")[0]
        txt, color = delta(vals[0], pages_prev.get(path, 0))
        top_rows.append([
            f'<a href="https://{SITE}{html.escape(path)}" style="color:#221e1a;text-decoration:none">{html.escape(t[:70])}</a>'
            f'<div style="font:400 11px/1.4 Arial,sans-serif;color:#8a8072">{html.escape(path)}</div>',
            fr(vals[0]),
            f'<span style="color:{color}">{txt}</span>',
        ])

    # sections
    sect = {}
    for dims, vals in pages_cur:
        sect[section_of(dims[0])] = sect.get(section_of(dims[0]), 0) + vals[0]
    sect_prev = {}
    for path, v in pages_prev.items():
        sect_prev[section_of(path)] = sect_prev.get(section_of(path), 0) + v
    tot = sum(sect.values()) or 1
    sect_rows = []
    for name, v in sorted(sect.items(), key=lambda kv: -kv[1]):
        txt, color = delta(v, sect_prev.get(name, 0))
        sect_rows.append([html.escape(name), fr(v), f"{round(v / tot * 100)} %", f'<span style="color:{color}">{txt}</span>'])

    # provenance
    chan = query(prop, token, CUR, ["sessions"], ["sessionDefaultChannelGroup"], 12, "sessions")
    chan_rows = [[html.escape(d[0] or "(non défini)"), fr(v[0])] for d, v in chan]

    src = query(prop, token, CUR, ["sessions"], ["sessionSource"], 10, "sessions")
    src_rows = [[html.escape(d[0] or "(direct)"), fr(v[0])] for d, v in src]

    ctry = query(prop, token, CUR, ["totalUsers"], ["country"], 8, "totalUsers")
    ctry_rows = [[html.escape(d[0] or "—"), fr(v[0])] for d, v in ctry]

    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#F5F0E8">
<table width="100%" cellspacing="0" cellpadding="0" style="background:#F5F0E8">
 <tr><td align="center" style="padding:28px 14px">
  <table width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:#FBF8F3;border-radius:18px;padding:30px 32px">
   <tr><td>
    <div style="font:600 10px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;color:#C2603F">Rapport d'audience</div>
    <h1 style="font:700 27px/1.2 Georgia,serif;color:#221e1a;margin:8px 0 4px">bernardcollorafi.org</h1>
    <p style="font:400 14px/1.5 Arial,sans-serif;color:#8a8072;margin:0">Du {d1} au {d2} — comparé aux sept jours précédents.</p>

    <table width="100%" cellspacing="8" cellpadding="0" style="margin:22px 0 0;border-collapse:separate">
      <tr>{kpi("Visiteurs", cur[0], prev[0])}{kpi("Sessions", cur[1], prev[1])}{kpi("Pages vues", cur[2], prev[2])}</tr>
    </table>

    {table("Les pages les plus lues", ["Page", "Vues", "Évol."], top_rows)}
    {table("Par section du site", ["Section", "Vues", "Part", "Évol."], sect_rows)}
    {table("D'où vient le trafic", ["Canal", "Sessions"], chan_rows)}
    {table("Sources précises", ["Source", "Sessions"], src_rows)}
    {table("Pays", ["Pays", "Visiteurs"], ctry_rows)}

    <p style="font:400 12px/1.6 Arial,sans-serif;color:#8a8072;margin:32px 0 0;padding-top:16px;border-top:1px solid #ddd3c4">
      Données Google Analytics 4. Rapport généré automatiquement chaque lundi par GitHub Actions.
    </p>
   </td></tr>
  </table>
 </td></tr>
</table>
</body></html>"""


def send(subject, body_html, to, user, password):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Dossier Collorafi <{user}>"
    msg["To"] = to
    msg.set_content(
        "Ce rapport nécessite un client mail capable d'afficher le HTML."
    )
    msg.add_alternative(body_html, subtype="html")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(user, password)
        s.send_message(msg)


def main():
    prop = env("GA_PROPERTY_ID")
    token = env("GA_ACCESS_TOKEN")
    to = env("MAIL_TO")
    user = env("GMAIL_USER")
    password = env("GMAIL_APP_PASSWORD")

    today = datetime.date.today()
    d2 = today - datetime.timedelta(days=1)
    d1 = today - datetime.timedelta(days=7)
    fmt = "%d/%m/%Y"

    body = build_html(prop, token, d1.strftime(fmt), d2.strftime(fmt))
    send(f"Audience du site — semaine du {d1.strftime('%d/%m')}", body, to, user, password)
    print("rapport envoye")  # rien d'autre : les logs de ce depot sont publics


if __name__ == "__main__":
    main()
