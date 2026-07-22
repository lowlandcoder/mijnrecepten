# MijnRecepten

De receptensite `mijnrecepten.lab023.nl`: favoriete recepten en recepten om
uit te proberen, met filter op ingrediënten (labels). Een kleine Flask-backend
slaat de recepten, labels en foto's op in een SQLite-database en toont ze in de
Lab023-huisstijl. Opzet volgt het patroon van `mijnp2000/archief`.

De recepten zijn vrij te bekijken. Alleen het beheer (toevoegen, wijzigen,
verwijderen) is afgeschermd via de centrale aanmelding (oauth2-proxy, map
`mijnlogin`).

## Onderdelen

- `app.py` — de backend: database, publieke lees-API en afgeschermde beheer-API,
  foto-opslag en tekstherkenning (OCR) met Tesseract.
- `static/` — de pagina's: `index.html` (publiek) en `beheer.html` (beheer),
  met `style.css`, `beheer.css`, `script.js`, `beheer.js` en de gedeelde
  `huisstijl.css`.
- `tools/importeer_blog.py` — recepten van de blogspot-blog importeren.
- `Dockerfile`, `requirements.txt`, `docker-compose.yml` — om de container te
  bouwen en te draaien.
- `nginx-mijnrecepten.conf` — doorschakeling; afscherming alleen op het beheer.
- `data/` — database en foto's (blijft buiten de repository).

## Hoe het werkt

Twee categorieën: "Favoriete recepten" en "Uitproberen". Elk recept heeft een
titel, een foto van het gerecht, ingrediënten, bereiding en labels. Op de
pagina kan worden gefilterd op categorie en op een of meer ingrediënt-labels,
en worden gezocht in de tekst.

Bij "Uitproberen" kan snel een foto of printscreen van een recept worden
toegevoegd. De tekst op die foto wordt met Tesseract (Nederlands) herkend en
opgeslagen, zodat het recept doorzoekbaar en filterbaar wordt. Bevalt het, dan
zet één knop het recept om naar "Favoriete recepten".

## Categorie en labels

- Categorie staat als veld op het recept (`favoriet` of `uitproberen`).
  Omzetten gebeurt via de beheerpagina of de route
  `/api/beheer/recept/<id>/naar-favoriet`.
- Labels zijn ingrediënten. Filteren op meerdere labels toont alleen recepten
  die ze allemaal hebben.

## Afscherming

De publieke pagina en de lees-API (`/`, `/api/recepten`, `/api/labels`,
`/foto/...`) zijn vrij. De beheerpagina (`/beheer`) en de schrijf-API
(`/api/beheer/...`) staan achter de centrale aanmelding.

Dit is geregeld in `nginx-mijnrecepten.conf`. Het snippet
`snippets/lab023-login.conf` zet `auth_request` op serverniveau en schermt
daarmee standaard alles af; het snippet bevat zelf al de locaties `/oauth2/auth`
en `@lab023_login` en mag daarom niet in een location-blok staan. De publieke
locatie `/` zet de afscherming weer open met `auth_request off;`, zodat alleen
`/beheer` en `/api/beheer/` afgeschermd blijven. De backend zelf kent geen
inlog; hij mag daarom alleen op localhost luisteren, met nginx ervoor.

## Inrichting op de lab023-server

1. Repository klonen (of bijwerken) op de lab023-server.
2. De container bouwen en starten:

       sudo docker compose up -d --build

   De backend luistert nu op `127.0.0.1:8300`.
3. DNS-regel voor `mijnrecepten.lab023.nl` aanmaken.
4. De nginx-conf plaatsen en activeren:

       sudo cp nginx-mijnrecepten.conf /etc/nginx/sites-available/mijnrecepten
       sudo ln -s /etc/nginx/sites-available/mijnrecepten /etc/nginx/sites-enabled/
       sudo nginx -t && sudo systemctl reload nginx

5. HTTPS instellen:

       sudo certbot --nginx -d mijnrecepten.lab023.nl

   Controleer daarna dat de regel `include snippets/lab023-login.conf;` in het
   443-blok op serverniveau staat. Het snippet schermt standaard alles af; de
   publieke locatie `/` zet dat weer open met `auth_request off;`, zodat alleen
   `/beheer` en `/api/beheer/` afgeschermd blijven.
6. Op de startpagina (repository `start`) de kaart "MijnRecepten" toevoegen aan
   de lijst `PAGINAS` in `script.js` (zonder badge "Afgeschermd").

## Recepten van de blog importeren

Draai op de server, met de container actief:

    cd tools
    python3 importeer_blog.py --api http://127.0.0.1:8300 --proef   # eerst tonen
    python3 importeer_blog.py --api http://127.0.0.1:8300           # daarna echt

De berichten komen binnen als "Favoriet", met de volledige tekst in het veld
bereiding en de eerste afbeelding als foto. De veldindeling kan daarna per
recept worden bijgewerkt op de beheerpagina.

## Instellingen

In `docker-compose.yml` onder `environment`:

| Instelling | Betekenis | Waarde |
| --- | --- | --- |
| `OCR_TAAL` | taal voor de tekstherkenning | `nld` |
| `POORT` | poort binnen de container | `8000` |

## Geheimen

Geen geheimen in deze map. De database en de foto's staan in `data/` en worden
niet meegecommit.
