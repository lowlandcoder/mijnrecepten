#!/usr/bin/env python3
"""Recepten van de blogspot-blog importeren in MijnRecepten.

Dit script leest de Atom-feed van https://peterkuijer.blogspot.com/ uit, haalt
per bericht de titel, de tekst en de eerste foto op, en voegt ze toe als
recept in de categorie "Favoriet". Het praat rechtstreeks met de backend op
localhost (die zelf geen inlog kent; de afscherming zit in nginx). Draai dit
dus op de lab023-server, of via een SSH-tunnel naar poort 8300.

Gebruik:
    python3 importeer_blog.py --api http://127.0.0.1:8300 [--max 500] [--proef]

--proef toont alleen wat er zou worden geïmporteerd, zonder iets op te slaan.

Let op: de indeling van blogberichten verschilt. Dit script zet de volledige
berichttekst in het veld "bereiding". Verfijn de veldindeling (ingrediënten
apart) zo nodig nadat de eerste import is bekeken.
"""

import argparse
import html
import io
import mimetypes
import re
import sys
import urllib.request
import uuid
import xml.etree.ElementTree as ET

FEED = "https://peterkuijer.blogspot.com/feeds/posts/default"
ATOM = "{http://www.w3.org/2005/Atom}"


def haal_feed(max_results):
    url = f"{FEED}?max-results={max_results}&alt=atom"
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read()


def strip_html(tekst):
    tekst = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", tekst)
    tekst = re.sub(r"(?i)<br\s*/?>", "\n", tekst)
    tekst = re.sub(r"(?i)</p>", "\n\n", tekst)
    tekst = re.sub(r"<[^>]+>", "", tekst)
    return html.unescape(tekst).strip()


def eerste_afbeelding(html_tekst):
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_tekst, re.I)
    return m.group(1) if m else None


def download(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        data = r.read()
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip()
    ext = mimetypes.guess_extension(ctype) or ".jpg"
    if ext == ".jpe":
        ext = ".jpg"
    return data, ctype or "image/jpeg", f"blog_{uuid.uuid4().hex}{ext}"


def bouw_multipart(velden, foto):
    """Bouwt een multipart/form-data body zonder externe pakketten."""
    grens = "----mijnrecepten" + uuid.uuid4().hex
    delen = []
    for naam, waarde in velden.items():
        delen.append(f"--{grens}\r\n".encode())
        delen.append(f'Content-Disposition: form-data; name="{naam}"\r\n\r\n'.encode())
        delen.append(f"{waarde}\r\n".encode())
    if foto:
        data, ctype, naam = foto
        delen.append(f"--{grens}\r\n".encode())
        delen.append(
            f'Content-Disposition: form-data; name="foto"; filename="{naam}"\r\n'.encode()
        )
        delen.append(f"Content-Type: {ctype}\r\n\r\n".encode())
        delen.append(data)
        delen.append(b"\r\n")
    delen.append(f"--{grens}--\r\n".encode())
    body = b"".join(delen)
    return body, f"multipart/form-data; boundary={grens}"


def voeg_toe(api, velden, foto):
    body, ctype = bouw_multipart(velden, foto)
    req = urllib.request.Request(
        api.rstrip("/") + "/api/beheer/recept",
        data=body,
        headers={"Content-Type": ctype},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://127.0.0.1:8300", help="basis-URL van de backend")
    p.add_argument("--max", type=int, default=500, help="maximaal aantal berichten")
    p.add_argument("--proef", action="store_true", help="alleen tonen, niets opslaan")
    args = p.parse_args()

    wortel = ET.fromstring(haal_feed(args.max))
    berichten = wortel.findall(f"{ATOM}entry")
    print(f"{len(berichten)} berichten gevonden in de feed.")

    aantal = 0
    for entry in berichten:
        titel = (entry.findtext(f"{ATOM}title") or "").strip()
        inhoud_html = entry.findtext(f"{ATOM}content") or entry.findtext(f"{ATOM}summary") or ""
        link = ""
        for l in entry.findall(f"{ATOM}link"):
            if l.get("rel") == "alternate":
                link = l.get("href", "")
        tekst = strip_html(inhoud_html)
        foto_url = eerste_afbeelding(inhoud_html)

        print(f"- {titel}  ({'foto' if foto_url else 'geen foto'})")
        if args.proef:
            continue

        foto = None
        if foto_url:
            try:
                foto = download(foto_url)
            except Exception as fout:
                print(f"    foto overslaan: {fout}")

        velden = {
            "titel": titel or "Zonder titel",
            "categorie": "favoriet",
            "bereiding": tekst,
            "bron": link,
        }
        try:
            voeg_toe(args.api, velden, foto)
            aantal += 1
        except Exception as fout:
            print(f"    toevoegen mislukt: {fout}", file=sys.stderr)

    print(f"Klaar. {aantal} recepten toegevoegd.")


if __name__ == "__main__":
    main()
