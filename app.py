#!/usr/bin/env python3
"""Backend voor MijnRecepten (mijnrecepten.lab023.nl).

Deze backend doet drie dingen:
  1. Recepten, labels en foto's opslaan in een SQLite-database.
  2. Een publieke pagina en lees-API aanbieden (zonder inlog): recepten
     bekijken en filteren op categorie en op labels (ingrediënten).
  3. Een beheer-API aanbieden voor toevoegen, wijzigen en verwijderen. Die
     routes lopen onder /beheer en /api/beheer en worden door nginx
     afgeschermd met de centrale aanmelding (oauth2-proxy, map mijnlogin).

Bij "Uitproberen" kan een foto of printscreen worden toegevoegd. De tekst op
die foto wordt met Tesseract (Nederlands) herkend en opgeslagen, zodat het
recept doorzoekbaar en filterbaar wordt.

Een recept kan ook via een webadres binnenkomen. De route
/api/beheer/importeer-url haalt de pagina op met de module schraper.py en
geeft de gevonden velden terug. Die worden op de beheerpagina getoond ter
controle en pas na akkoord opgeslagen.

Instellingen komen uit omgevingsvariabelen (in te vullen in docker-compose):
  DATA_DIR   map voor database en foto's        (standaard /app/data)
  POORT      poort waarop de pagina draait       (standaard 8000)
  OCR_TAAL   taal voor Tesseract                 (standaard nld)
"""

import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

from flask import Flask, jsonify, request, send_from_directory, abort
from waitress import serve

try:
    import pytesseract
    from PIL import Image
    OCR_BESCHIKBAAR = True
except Exception:  # pytesseract of Pillow niet aanwezig
    OCR_BESCHIKBAAR = False

try:
    import schraper
    IMPORT_BESCHIKBAAR = True
except Exception:  # schraper of requests niet aanwezig
    schraper = None
    IMPORT_BESCHIKBAAR = False

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
FOTO_DIR = os.path.join(DATA_DIR, "fotos")
DB_PATH = os.path.join(DATA_DIR, "recepten.db")
POORT = int(os.environ.get("POORT", "8000"))
OCR_TAAL = os.environ.get("OCR_TAAL", "nld")

TOEGESTANE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
CATEGORIEEN = {"favoriet", "uitproberen", "afgeserveerd"}

db_lock = threading.Lock()


# --- Database --------------------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    os.makedirs(FOTO_DIR, exist_ok=True)
    with db_lock:
        conn = get_db()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS recepten (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titel TEXT NOT NULL,
                categorie TEXT NOT NULL DEFAULT 'uitproberen',
                foto TEXT,
                ingredienten TEXT,
                bereiding TEXT,
                bron TEXT,
                ocr_tekst TEXT,
                aangemaakt TEXT NOT NULL,
                bijgewerkt TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                naam TEXT NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS recept_labels (
                recept_id INTEGER NOT NULL REFERENCES recepten(id) ON DELETE CASCADE,
                label_id  INTEGER NOT NULL REFERENCES labels(id)   ON DELETE CASCADE,
                PRIMARY KEY (recept_id, label_id)
            );

            CREATE INDEX IF NOT EXISTS idx_recept_categorie ON recepten(categorie);
            """
        )
        conn.commit()
        conn.close()


# --- Hulp ------------------------------------------------------------------
def nu():
    return datetime.now(timezone.utc).isoformat()


def normaliseer_label(naam):
    return re.sub(r"\s+", " ", (naam or "").strip().lower())


def label_id_van(conn, naam):
    """Zoekt of maakt een label en geeft het id terug."""
    naam = normaliseer_label(naam)
    if not naam:
        return None
    rij = conn.execute("SELECT id FROM labels WHERE naam = ?", (naam,)).fetchone()
    if rij:
        return rij["id"]
    cur = conn.execute("INSERT INTO labels (naam) VALUES (?)", (naam,))
    return cur.lastrowid


def zet_labels(conn, recept_id, labels):
    conn.execute("DELETE FROM recept_labels WHERE recept_id = ?", (recept_id,))
    for naam in labels or []:
        lid = label_id_van(conn, naam)
        if lid:
            conn.execute(
                "INSERT OR IGNORE INTO recept_labels (recept_id, label_id) VALUES (?, ?)",
                (recept_id, lid),
            )


def labels_van(conn, recept_id):
    rijen = conn.execute(
        """SELECT l.naam FROM labels l
           JOIN recept_labels rl ON rl.label_id = l.id
           WHERE rl.recept_id = ? ORDER BY l.naam""",
        (recept_id,),
    ).fetchall()
    return [r["naam"] for r in rijen]


def recept_naar_dict(conn, rij):
    d = dict(rij)
    d["labels"] = labels_van(conn, rij["id"])
    d["foto_url"] = f"/foto/{rij['foto']}" if rij["foto"] else None
    return d


def bewaar_foto(bestand):
    """Slaat een geüpload beeldbestand op en geeft de bestandsnaam terug."""
    if not bestand or not bestand.filename:
        return None
    if bestand.mimetype not in TOEGESTANE_TYPES:
        abort(400, "Alleen jpg, png, webp of gif is toegestaan.")
    ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }[bestand.mimetype]
    naam = f"{uuid.uuid4().hex}{ext}"
    bestand.save(os.path.join(FOTO_DIR, naam))
    return naam


def bestaande_foto(naam):
    """Controleert een fotonaam die al eerder is opgeslagen.

    Wordt gebruikt bij het ophalen via een webadres en bij de tekstherkenning:
    de foto staat dan al in de fotomap en hoeft niet nog eens te worden
    verstuurd. Geeft None als de naam niet deugt of het bestand ontbreekt.
    """
    naam = (naam or "").strip()
    if not naam or not re.fullmatch(r"[A-Za-z0-9]+\.(jpg|png|webp|gif)", naam):
        return None
    if not os.path.isfile(os.path.join(FOTO_DIR, naam)):
        return None
    return naam


def ocr_van_foto(bestandsnaam):
    """Herkent tekst op een opgeslagen foto met Tesseract."""
    if not OCR_BESCHIKBAAR or not bestandsnaam:
        return ""
    try:
        pad = os.path.join(FOTO_DIR, bestandsnaam)
        return pytesseract.image_to_string(Image.open(pad), lang=OCR_TAAL).strip()
    except Exception as fout:
        print("OCR mislukt:", fout, flush=True)
        return ""


# --- Webpagina en publieke API ---------------------------------------------
app = Flask(__name__, static_folder="static", static_url_path="")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/beheer")
@app.route("/beheer/")
def beheer():
    # nginx schermt deze route af met de centrale aanmelding.
    return send_from_directory("static", "beheer.html")


@app.route("/beheer/toevoegen")
def beheer_toevoegen_pagina():
    # Aparte pagina voor toevoegen en wijzigen (ook afgeschermd via /beheer).
    return send_from_directory("static", "beheer-toevoegen.html")


@app.route("/foto/<naam>")
def foto(naam):
    if "/" in naam or "\\" in naam or ".." in naam:
        abort(404)
    return send_from_directory(FOTO_DIR, naam)


@app.route("/api/labels")
def api_labels():
    """Alle labels met het aantal recepten, voor het filter."""
    with db_lock:
        conn = get_db()
        rijen = conn.execute(
            """SELECT l.naam, COUNT(rl.recept_id) AS aantal
               FROM labels l LEFT JOIN recept_labels rl ON rl.label_id = l.id
               GROUP BY l.id HAVING aantal > 0 ORDER BY l.naam"""
        ).fetchall()
        conn.close()
    return jsonify([dict(r) for r in rijen])


@app.route("/api/recepten")
def api_recepten():
    """Recepten ophalen, met filter op categorie, labels en zoekwoord.

    Parameters:
      categorie  'favoriet', 'uitproberen' of 'afgeserveerd' (optioneel)
      labels     komma-gescheiden lijst; recept moet ze ALLE hebben
      zoek       zoekwoord in titel, ingrediënten, bereiding en ocr-tekst
    """
    categorie = request.args.get("categorie", "").strip().lower()
    labels = [normaliseer_label(x) for x in request.args.get("labels", "").split(",") if x.strip()]
    zoek = request.args.get("zoek", "").strip()

    voorwaarden, params = [], []
    if categorie in CATEGORIEEN:
        voorwaarden.append("r.categorie = ?")
        params.append(categorie)
    if zoek:
        voorwaarden.append(
            "(r.titel LIKE ? OR r.ingredienten LIKE ? OR r.bereiding LIKE ? OR r.ocr_tekst LIKE ?)"
        )
        params.extend([f"%{zoek}%"] * 4)
    if labels:
        # Recept moet alle gekozen labels hebben (AND): tel de treffers.
        plaats = ",".join("?" for _ in labels)
        voorwaarden.append(
            f"""r.id IN (
                SELECT rl.recept_id FROM recept_labels rl
                JOIN labels l ON l.id = rl.label_id
                WHERE l.naam IN ({plaats})
                GROUP BY rl.recept_id HAVING COUNT(DISTINCT l.naam) = ?
            )"""
        )
        params.extend(labels)
        params.append(len(labels))

    where = ("WHERE " + " AND ".join(voorwaarden)) if voorwaarden else ""
    query = f"SELECT * FROM recepten r {where} ORDER BY r.bijgewerkt DESC"
    with db_lock:
        conn = get_db()
        rijen = conn.execute(query, params).fetchall()
        uitvoer = [recept_naar_dict(conn, r) for r in rijen]
        conn.close()
    return jsonify(uitvoer)


@app.route("/api/recepten/<int:recept_id>")
def api_recept(recept_id):
    with db_lock:
        conn = get_db()
        rij = conn.execute("SELECT * FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        d = recept_naar_dict(conn, rij) if rij else None
        conn.close()
    if not d:
        abort(404)
    return jsonify(d)


# --- Beheer-API (afgeschermd door nginx op /api/beheer) --------------------
def _velden_uit_verzoek():
    labels = request.form.get("labels", "")
    return {
        "titel": request.form.get("titel", "").strip(),
        "categorie": request.form.get("categorie", "uitproberen").strip().lower(),
        "ingredienten": request.form.get("ingredienten", "").strip(),
        "bereiding": request.form.get("bereiding", "").strip(),
        "bron": request.form.get("bron", "").strip(),
        "labels": [x for x in labels.split(",") if x.strip()],
        "foto_naam": request.form.get("foto_naam", "").strip(),
    }


@app.route("/api/beheer/recept", methods=["POST"])
def beheer_maak():
    v = _velden_uit_verzoek()
    if not v["titel"]:
        abort(400, "Titel is verplicht.")
    if v["categorie"] not in CATEGORIEEN:
        v["categorie"] = "uitproberen"

    # De foto komt als bestand mee, of staat al in de fotomap (tekstherkenning
    # vooraf, of een foto die bij een webadres is opgehaald).
    foto_naam = bewaar_foto(request.files.get("foto")) or bestaande_foto(v["foto_naam"])
    # Tekstherkenning alleen als er nog geen tekst is. Bij een recept van een
    # webadres staan ingrediënten en bereiding er al in.
    herken = (
        v["categorie"] == "uitproberen"
        and not v["ingredienten"]
        and not v["bereiding"]
    )
    ocr_tekst = ocr_van_foto(foto_naam) if herken else ""

    tijd = nu()
    with db_lock:
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO recepten
               (titel, categorie, foto, ingredienten, bereiding, bron, ocr_tekst, aangemaakt, bijgewerkt)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (v["titel"], v["categorie"], foto_naam, v["ingredienten"], v["bereiding"],
             v["bron"], ocr_tekst, tijd, tijd),
        )
        recept_id = cur.lastrowid
        zet_labels(conn, recept_id, v["labels"])
        conn.commit()
        rij = conn.execute("SELECT * FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        d = recept_naar_dict(conn, rij)
        conn.close()
    return jsonify(d), 201


@app.route("/api/beheer/recept/<int:recept_id>", methods=["POST"])
def beheer_wijzig(recept_id):
    v = _velden_uit_verzoek()
    with db_lock:
        conn = get_db()
        rij = conn.execute("SELECT * FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        if not rij:
            conn.close()
            abort(404)
        foto_naam = rij["foto"]
        nieuwe = request.files.get("foto")
        if nieuwe and nieuwe.filename:
            foto_naam = bewaar_foto(nieuwe)
        elif bestaande_foto(v["foto_naam"]):
            foto_naam = bestaande_foto(v["foto_naam"])
        categorie = v["categorie"] if v["categorie"] in CATEGORIEEN else rij["categorie"]
        conn.execute(
            """UPDATE recepten SET titel=?, categorie=?, foto=?, ingredienten=?,
               bereiding=?, bron=?, bijgewerkt=? WHERE id=?""",
            (v["titel"] or rij["titel"], categorie, foto_naam, v["ingredienten"],
             v["bereiding"], v["bron"], nu(), recept_id),
        )
        if v["labels"]:
            zet_labels(conn, recept_id, v["labels"])
        conn.commit()
        rij = conn.execute("SELECT * FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        d = recept_naar_dict(conn, rij)
        conn.close()
    return jsonify(d)


@app.route("/api/beheer/recept/<int:recept_id>/naar-favoriet", methods=["POST"])
def beheer_naar_favoriet(recept_id):
    """Zet een recept van 'Uitproberen' om naar 'Favoriete recepten'."""
    with db_lock:
        conn = get_db()
        rij = conn.execute("SELECT id FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        if not rij:
            conn.close()
            abort(404)
        conn.execute(
            "UPDATE recepten SET categorie='favoriet', bijgewerkt=? WHERE id=?",
            (nu(), recept_id),
        )
        conn.commit()
        conn.close()
    return jsonify({"ok": True, "categorie": "favoriet"})


@app.route("/api/beheer/recept/<int:recept_id>/verwijder", methods=["POST"])
def beheer_verwijder(recept_id):
    with db_lock:
        conn = get_db()
        rij = conn.execute("SELECT foto FROM recepten WHERE id = ?", (recept_id,)).fetchone()
        if not rij:
            conn.close()
            abort(404)
        conn.execute("DELETE FROM recepten WHERE id = ?", (recept_id,))
        conn.commit()
        conn.close()
    # Foto van schijf halen (buiten de databasevergrendeling).
    if rij["foto"]:
        try:
            os.remove(os.path.join(FOTO_DIR, rij["foto"]))
        except OSError:
            pass
    return jsonify({"ok": True})


@app.route("/api/beheer/ocr", methods=["POST"])
def beheer_ocr():
    """Herkent tekst op een geüploade foto zonder op te slaan als recept.
    Handig om de tekst te tonen voordat een 'Uitproberen'-recept wordt bewaard."""
    if not OCR_BESCHIKBAAR:
        return jsonify({"tekst": "", "ocr": False})
    bestand = request.files.get("foto")
    naam = bewaar_foto(bestand)
    tekst = ocr_van_foto(naam)
    return jsonify({"tekst": tekst, "ocr": True, "foto": naam})


@app.route("/api/beheer/importeer-url", methods=["POST"])
def beheer_importeer_url():
    """Haalt een recept op van een webadres en geeft de velden terug.

    Er wordt niets opgeslagen behalve de foto van het gerecht. De beheerpagina
    toont de velden ter controle; opslaan gebeurt daarna met de gewone route
    /api/beheer/recept.
    """
    if not IMPORT_BESCHIKBAAR:
        return jsonify({"fout": "Ophalen via een webadres is niet beschikbaar."}), 503

    url = (request.form.get("url") or "").strip()
    if not url and request.is_json:
        url = (request.get_json(silent=True) or {}).get("url", "").strip()

    try:
        gegevens = schraper.schraap(url, foto_dir=FOTO_DIR)
    except schraper.SchraapFout as fout:
        return jsonify({"fout": str(fout)}), 400
    except Exception as fout:  # onverwacht, wel leesbaar melden
        print("Ophalen mislukt:", fout, flush=True)
        return jsonify({"fout": "Het ophalen is onverwacht misgegaan."}), 500

    gegevens["categorie"] = "uitproberen"
    gegevens["foto_url"] = f"/foto/{gegevens['foto']}" if gegevens.get("foto") else None
    return jsonify(gegevens)


@app.route("/api/beheer/status")
def beheer_status():
    return jsonify({
        "ocr_beschikbaar": OCR_BESCHIKBAAR,
        "ocr_taal": OCR_TAAL,
        "import_beschikbaar": IMPORT_BESCHIKBAAR,
    })


def main():
    init_db()
    print(
        f"MijnRecepten gestart op poort {POORT}. "
        f"OCR beschikbaar: {OCR_BESCHIKBAAR} (taal: {OCR_TAAL}). "
        f"Ophalen via webadres beschikbaar: {IMPORT_BESCHIKBAAR}.",
        flush=True,
    )
    serve(app, host="0.0.0.0", port=POORT)


if __name__ == "__main__":
    main()
