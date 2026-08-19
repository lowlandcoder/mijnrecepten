#!/usr/bin/env python3
"""Recepten ophalen van een webadres voor MijnRecepten.

Deze module haalt een receptpagina op en zet die om naar de velden die
MijnRecepten gebruikt: titel, ingrediënten, bereiding, bron, foto en een
voorstel voor labels.

Werkwijze:
  1. Het adres wordt gecontroleerd. Alleen http en https zijn toegestaan en
     het adres mag niet in het eigen netwerk liggen.
  2. De pagina wordt opgehaald met een tijdslimiet en een maximale grootte.
  3. De inhoud wordt gelezen met recipe-scrapers. Kent die de site niet, dan
     volgt een terugval op de schema.org-gegevens in de pagina zelf.
  4. De foto van het gerecht wordt los opgehaald en opgeslagen.

De module maakt zelf geen recepten aan; dat doet app.py.
"""

import ipaddress
import json
import os
import re
import socket
import uuid
from html import unescape
from urllib.parse import urljoin, urlparse

import requests

BROWSERNAAM = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0 Safari/537.36 MijnRecepten/1.0"
)
TIJDSLIMIET = 20          # seconden per verzoek
MAX_PAGINA = 4_000_000    # bytes html
MAX_FOTO = 8_000_000      # bytes beeld
MAX_SPRONGEN = 5          # aantal doorverwijzingen dat wordt gevolgd

FOTO_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


class SchraapFout(Exception):
    """Iets ging mis bij het ophalen; de tekst is bedoeld voor de gebruiker."""


# --- Adrescontrole ---------------------------------------------------------
def _is_openbaar_adres(ip_tekst):
    try:
        ip = ipaddress.ip_address(ip_tekst)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def controleer_adres(url):
    """Weigert adressen die niet op het open internet staan.

    Zo kan de beheerpagina niet worden gebruikt om apparaten in het eigen
    netwerk te bevragen.
    """
    deel = urlparse(url)
    if deel.scheme not in ("http", "https"):
        raise SchraapFout("Alleen adressen die met http of https beginnen.")
    if not deel.hostname:
        raise SchraapFout("Dit adres heeft geen geldige naam.")
    try:
        gegevens = socket.getaddrinfo(deel.hostname, None)
    except socket.gaierror:
        raise SchraapFout("De naam in het adres is niet te vinden.")
    adressen = {rij[4][0] for rij in gegevens}
    if not adressen or not all(_is_openbaar_adres(a) for a in adressen):
        raise SchraapFout("Dit adres ligt in het eigen netwerk en wordt niet opgehaald.")
    return url


# --- Ophalen ---------------------------------------------------------------
def _haal_op(url, soorten, maximum):
    """Haalt een adres op en volgt doorverwijzingen met controle per stap."""
    kop = {"User-Agent": BROWSERNAAM, "Accept-Language": "nl,en;q=0.8"}
    huidig = url
    for _ in range(MAX_SPRONGEN):
        controleer_adres(huidig)
        try:
            antwoord = requests.get(
                huidig, headers=kop, timeout=TIJDSLIMIET,
                allow_redirects=False, stream=True,
            )
        except requests.RequestException as fout:
            raise SchraapFout(f"De pagina is niet op te halen: {fout}")
        if antwoord.is_redirect or antwoord.is_permanent_redirect:
            volgende = antwoord.headers.get("Location", "")
            antwoord.close()
            if not volgende:
                raise SchraapFout("De pagina verwijst door zonder adres.")
            huidig = urljoin(huidig, volgende)
            continue
        if antwoord.status_code != 200:
            antwoord.close()
            raise SchraapFout(f"De pagina gaf foutcode {antwoord.status_code}.")
        type_ = antwoord.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if soorten and type_ not in soorten:
            antwoord.close()
            raise SchraapFout(f"Onverwacht soort bestand: {type_ or 'onbekend'}.")
        inhoud = b""
        for blok in antwoord.iter_content(65536):
            inhoud += blok
            if len(inhoud) > maximum:
                antwoord.close()
                raise SchraapFout("Het bestand is te groot.")
        codering = antwoord.encoding
        antwoord.close()
        return inhoud, type_, huidig, codering
    raise SchraapFout("Te veel doorverwijzingen.")


def haal_pagina(url):
    """Geeft de html van de pagina en het uiteindelijke adres terug."""
    soorten = {"text/html", "application/xhtml+xml", "text/plain"}
    ruw, _, definitief, codering = _haal_op(url, soorten, MAX_PAGINA)
    tekst = ruw.decode(codering or "utf-8", errors="replace")
    return tekst, definitief


# --- Lezen van de pagina ---------------------------------------------------
def _veilig(functie, standaard=None):
    try:
        waarde = functie()
    except Exception:
        return standaard
    return waarde if waarde not in (None, "", [], {}) else standaard


def _met_recipe_scrapers(html, url):
    """Leest de pagina met recipe-scrapers. Geeft None bij een mislukking."""
    try:
        from recipe_scrapers import scrape_html
    except ImportError:
        return None

    lezer = None
    for opties in ({"supported_only": False}, {"wild_mode": True}, {}):
        try:
            lezer = scrape_html(html, org_url=url, **opties)
            break
        except TypeError:
            continue
        except Exception:
            continue
    if lezer is None:
        return None

    titel = _veilig(lezer.title, "")
    ingredienten = _veilig(lezer.ingredients, []) or []
    bereiding = _veilig(lezer.instructions, "") or ""
    if not (titel and (ingredienten or bereiding)):
        return None
    return {
        "titel": titel.strip(),
        "ingredienten": [str(x).strip() for x in ingredienten if str(x).strip()],
        "bereiding": bereiding.strip(),
        "foto_url": _veilig(lezer.image, "") or "",
        "porties": str(_veilig(lezer.yields, "") or ""),
        "bereidingstijd": str(_veilig(lezer.total_time, "") or ""),
    }


def _json_blokken(html):
    """Alle blokken met schema.org-gegevens uit de pagina."""
    blokken = []
    patroon = re.compile(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    for stuk in patroon.findall(html):
        try:
            blokken.append(json.loads(unescape(stuk.strip())))
        except (ValueError, TypeError):
            continue
    return blokken


def _zoek_recept(knoop):
    """Zoekt in de schema.org-gegevens naar het onderdeel van het soort Recipe."""
    if isinstance(knoop, list):
        for deel in knoop:
            gevonden = _zoek_recept(deel)
            if gevonden:
                return gevonden
        return None
    if not isinstance(knoop, dict):
        return None
    soort = knoop.get("@type")
    soorten = soort if isinstance(soort, list) else [soort]
    if any(str(s).lower() == "recipe" for s in soorten if s):
        return knoop
    for sleutel in ("@graph", "mainEntity", "itemListElement"):
        if sleutel in knoop:
            gevonden = _zoek_recept(knoop[sleutel])
            if gevonden:
                return gevonden
    return None


def _tekst_van(waarde):
    """Maakt van een schema.org-veld leesbare tekst."""
    if waarde is None:
        return ""
    if isinstance(waarde, str):
        return re.sub(r"<[^>]+>", " ", unescape(waarde)).strip()
    if isinstance(waarde, dict):
        for sleutel in ("text", "name", "url", "@id"):
            if waarde.get(sleutel):
                return _tekst_van(waarde[sleutel])
        return ""
    if isinstance(waarde, list):
        regels = [_tekst_van(x) for x in waarde]
        return "\n".join(r for r in regels if r)
    return str(waarde)


def _met_schema_org(html, url):
    """Terugval: leest de schema.org-gegevens rechtstreeks uit de pagina."""
    for blok in _json_blokken(html):
        recept = _zoek_recept(blok)
        if not recept:
            continue
        titel = _tekst_van(recept.get("name"))
        ingredienten = recept.get("recipeIngredient") or recept.get("ingredients") or []
        if isinstance(ingredienten, str):
            ingredienten = [ingredienten]
        ingredienten = [_tekst_van(x) for x in ingredienten]
        bereiding = _tekst_van(recept.get("recipeInstructions"))
        if not (titel and (ingredienten or bereiding)):
            continue
        foto = recept.get("image")
        if isinstance(foto, dict):
            foto = foto.get("url") or foto.get("contentUrl") or ""
        if isinstance(foto, list) and foto:
            eerste = foto[0]
            foto = eerste.get("url", "") if isinstance(eerste, dict) else str(eerste)
        return {
            "titel": titel,
            "ingredienten": [x for x in ingredienten if x],
            "bereiding": bereiding,
            "foto_url": urljoin(url, foto) if foto else "",
            "porties": _tekst_van(recept.get("recipeYield")),
            "bereidingstijd": _tekst_van(recept.get("totalTime")),
        }
    return None


# --- Labels voorstellen ----------------------------------------------------
MATEN = {
    "g", "gr", "gram", "kg", "kilo", "mg", "ml", "cl", "dl", "l", "liter",
    "el", "tl", "eetlepel", "eetlepels", "theelepel", "theelepels", "kopje",
    "kopjes", "snufje", "snuf", "mespunt", "scheutje", "scheut", "teen",
    "tenen", "stuk", "stuks", "stukje", "stukjes", "blik", "blikje", "pak",
    "pakje", "zakje", "bosje", "bos", "handvol", "plak", "plakjes", "takje",
    "takjes", "bol", "bollen", "cm", "tbsp", "tsp", "cup", "cups", "oz", "lb",
    "pond", "ons", "flesje", "pot", "potje", "krop", "reep", "blaadjes",
}
WOORDEN_WEG = {
    "verse", "vers", "grote", "kleine", "middelgrote", "fijn", "fijne",
    "fijngesneden", "fijngehakte", "grof", "grove", "gesneden", "gehakte",
    "geraspte", "gemalen", "gedroogde", "gepelde", "geschilde", "gewassen",
    "grofgesneden", "gekookte", "rauwe", "halve", "hele", "een", "wat",
    "eventueel", "optioneel", "naar", "smaak", "circa", "ca", "ongeveer",
    "van", "de", "het", "en", "of", "in", "met", "voor", "per", "extra",
    "goede", "beetje", "à", "a", "ml", "gram", "stuks", "stuk", "zonder",
    "biologische", "verpakking", "ongeveer", "plus", "erbij", "geserveerd",
}
MAX_LABELS = 12


def voorstel_labels(ingredienten):
    """Maakt uit de ingrediëntregels een voorstel voor labels.

    Hoeveelheden, maten en toevoegingen zoals "fijngesneden" gaan eruit. Wat
    overblijft is meestal het ingrediënt zelf. Het voorstel is bedoeld om na
    te lopen, niet om blind over te nemen.
    """
    labels, gezien = [], set()
    for regel in ingredienten or []:
        tekst = str(regel).lower()
        tekst = tekst.split("(")[0]          # opmerking tussen haakjes weg
        tekst = tekst.split(",")[0]          # toevoeging na de komma weg
        tekst = re.sub(r"\[.*?\]", " ", tekst)
        tekst = re.sub(r"[0-9]+([.,/][0-9]+)?", " ", tekst)   # hoeveelheden
        tekst = re.sub(r"[½¼¾⅓⅔⅛]", " ", tekst)
        tekst = re.sub(r"[^a-zà-ÿ\s-]", " ", tekst)
        delen = [w for w in tekst.split() if w and w not in MATEN and w not in WOORDEN_WEG]
        if not delen:
            continue
        naam = " ".join(delen[:3]).strip(" -")
        if len(naam) < 3 or len(naam) > 30:
            continue
        if naam not in gezien:
            gezien.add(naam)
            labels.append(naam)
        if len(labels) >= MAX_LABELS:
            break
    return labels


# --- Foto ------------------------------------------------------------------
def download_foto(foto_url, foto_dir):
    """Haalt de foto van het gerecht op en slaat die op. Geeft de naam terug."""
    if not foto_url:
        return None
    try:
        ruw, type_, _, _ = _haal_op(foto_url, set(FOTO_TYPES), MAX_FOTO)
    except SchraapFout:
        return None
    naam = f"{uuid.uuid4().hex}{FOTO_TYPES.get(type_, '.jpg')}"
    try:
        with open(os.path.join(foto_dir, naam), "wb") as bestand:
            bestand.write(ruw)
    except OSError:
        return None
    return naam


# --- Hoofdfunctie ----------------------------------------------------------
def schraap(url, foto_dir=None):
    """Haalt een recept op van een webadres.

    Geeft een dict terug met titel, ingredienten (tekst met één regel per
    ingrediënt), bereiding, labels, bron en eventueel de opgeslagen foto.
    Bij een fout volgt een SchraapFout met een leesbare melding.
    """
    url = (url or "").strip()
    if not url:
        raise SchraapFout("Geen adres opgegeven.")
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "https://" + url
    controleer_adres(url)

    html, definitief = haal_pagina(url)
    gegevens = _met_recipe_scrapers(html, definitief) or _met_schema_org(html, definitief)
    if not gegevens:
        raise SchraapFout(
            "Op deze pagina is geen recept herkend. Vul het recept met de hand in, "
            "of probeer een andere pagina van dezelfde site."
        )

    ingredienten = gegevens["ingredienten"]
    bereiding = gegevens["bereiding"]
    extra = []
    if gegevens.get("porties"):
        extra.append(f"Porties: {gegevens['porties']}")
    if gegevens.get("bereidingstijd"):
        extra.append(f"Bereidingstijd: {gegevens['bereidingstijd']} minuten")
    if extra:
        bereiding = bereiding + "\n\n" + "\n".join(extra)

    foto = None
    if foto_dir and gegevens.get("foto_url"):
        foto = download_foto(urljoin(definitief, gegevens["foto_url"]), foto_dir)

    return {
        "titel": gegevens["titel"],
        "ingredienten": "\n".join(ingredienten),
        "bereiding": bereiding.strip(),
        "labels": voorstel_labels(ingredienten),
        "bron": definitief,
        "foto": foto,
    }
