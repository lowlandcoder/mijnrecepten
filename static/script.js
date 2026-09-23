// Werking van de publieke MijnRecepten-pagina: recepten ophalen, filteren op
// categorie en labels (ingrediënten), zoeken en een recept in detail tonen.

const $ = (id) => document.getElementById(id);

const staat = {
  categorie: "favoriet", // "", "favoriet", "uitproberen" of "afgeserveerd"
  zoek: "",
  labels: new Set(),   // gekozen ingrediënt-labels
};

const CAT_TEKST = { favoriet: "Favoriet", uitproberen: "Uitproberen", afgeserveerd: "Afgeserveerd" };

async function haal(pad) {
  const r = await fetch(pad);
  if (!r.ok) throw new Error(pad + " gaf " + r.status);
  return r.json();
}

function bouwUrl() {
  const p = new URLSearchParams();
  if (staat.categorie) p.set("categorie", staat.categorie);
  if (staat.zoek) p.set("zoek", staat.zoek);
  if (staat.labels.size) p.set("labels", [...staat.labels].join(","));
  return "/api/recepten?" + p.toString();
}

/* Labelfilter opbouwen */
async function laadLabels() {
  const labels = await haal("/api/labels");
  const houder = $("labels");
  houder.innerHTML = "";
  labels.forEach((l) => {
    const knop = document.createElement("button");
    knop.className = "label-chip" + (staat.labels.has(l.naam) ? " actief" : "");
    knop.innerHTML = `${l.naam}<span class="aantal">${l.aantal}</span>`;
    knop.addEventListener("click", () => {
      if (staat.labels.has(l.naam)) staat.labels.delete(l.naam);
      else staat.labels.add(l.naam);
      knop.classList.toggle("actief");
      laadRecepten();
    });
    houder.appendChild(knop);
  });
}

/* Eén receptkaart */
function maakKaart(recept) {
  const kaart = document.createElement("div");
  kaart.className = "kaart recept-kaart";

  if (recept.foto_url) {
    const img = document.createElement("img");
    img.className = "recept-foto";
    img.src = recept.foto_url;
    img.alt = recept.titel;
    img.loading = "lazy";
    kaart.appendChild(img);
  } else {
    const leeg = document.createElement("div");
    leeg.className = "recept-foto leeg";
    leeg.textContent = "Nog geen foto";
    kaart.appendChild(leeg);
  }

  const body = document.createElement("div");
  body.className = "recept-body";

  const badge = document.createElement("span");
  badge.className = "badge-cat badge-" + recept.categorie;
  badge.textContent = CAT_TEKST[recept.categorie] || recept.categorie;
  body.appendChild(badge);

  const titel = document.createElement("div");
  titel.className = "recept-titel";
  titel.textContent = recept.titel;
  body.appendChild(titel);

  if (recept.labels && recept.labels.length) {
    const rij = document.createElement("div");
    rij.className = "recept-labels";
    recept.labels.slice(0, 4).forEach((naam) => {
      const l = document.createElement("span");
      l.className = "mini-label";
      l.textContent = naam;
      rij.appendChild(l);
    });
    body.appendChild(rij);
  }

  kaart.appendChild(body);
  kaart.addEventListener("click", () => toonDetail(recept));
  return kaart;
}

async function laadRecepten() {
  const recepten = await haal(bouwUrl());
  const rooster = $("rooster");
  rooster.innerHTML = "";
  recepten.forEach((r) => rooster.appendChild(maakKaart(r)));
  $("geenResultaat").hidden = recepten.length !== 0;
  $("teller").textContent =
    recepten.length + (recepten.length === 1 ? " recept" : " recepten");
}

/* Detailvenster */
function toonDetail(recept) {
  const inhoud = $("venster-inhoud");
  const delen = [];
  delen.push(`<span class="badge-cat badge-${recept.categorie}">${CAT_TEKST[recept.categorie] || recept.categorie}</span>`);
  delen.push(`<h2>${ontsnap(recept.titel)}</h2>`);
  if (recept.foto_url) delen.push(`<img class="venster-foto" src="${recept.foto_url}" alt="${ontsnap(recept.titel)}">`);
  if (recept.labels && recept.labels.length) {
    delen.push(`<div class="recept-labels">${recept.labels.map((l) => `<span class="mini-label">${ontsnap(l)}</span>`).join("")}</div>`);
  }
  if (recept.ingredienten) delen.push(`<h3>Ingrediënten</h3><div class="tekst">${ontsnap(recept.ingredienten)}</div>`);
  if (recept.bereiding) delen.push(`<h3>Bereiding</h3><div class="tekst">${ontsnap(recept.bereiding)}</div>`);
  if (recept.ocr_tekst && !recept.ingredienten && !recept.bereiding) {
    delen.push(`<h3>Herkende tekst</h3><div class="tekst">${ontsnap(recept.ocr_tekst)}</div>`);
  }
  if (recept.bron) delen.push(`<div class="bron">Bron: <a href="${ontsnap(recept.bron)}" target="_blank" rel="noopener">${ontsnap(recept.bron)}</a></div>`);
  inhoud.innerHTML = delen.join("");
  $("venster").hidden = false;
}

function ontsnap(t) {
  const d = document.createElement("div");
  d.textContent = t == null ? "" : String(t);
  return d.innerHTML;
}

/* Tabs */
function kiesTab(categorie) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("actief", t.dataset.categorie === categorie));
  staat.categorie = categorie;
}

$("tabs").addEventListener("click", (e) => {
  const knop = e.target.closest(".tab");
  if (!knop) return;
  kiesTab(knop.dataset.categorie);
  laadRecepten();
});

/* Zoektermen in- en uitklappen (standaard ingeklapt) */
$("labelsKnop").addEventListener("click", () => {
  const open = $("labels").hidden;
  $("labels").hidden = !open;
  $("labelsKnop").textContent = open ? "Verberg zoektermen" : "Toon zoektermen";
  $("labelsKnop").setAttribute("aria-expanded", String(open));
});

/* Start met favorieten; zonder favorieten terugvallen op Alles */
async function start() {
  try {
    const fav = await haal("/api/recepten?categorie=favoriet");
    if (!fav.length) kiesTab("");
  } catch (e) {
    kiesTab("");
  }
  laadRecepten();
}

/* Zoeken (met kleine vertraging) */
let zoekTimer;
$("zoekveld").addEventListener("input", (e) => {
  clearTimeout(zoekTimer);
  zoekTimer = setTimeout(() => {
    staat.zoek = e.target.value.trim();
    laadRecepten();
  }, 220);
});

/* Venster sluiten */
$("sluit").addEventListener("click", () => ($("venster").hidden = true));
$("venster").addEventListener("click", (e) => {
  if (e.target === $("venster")) $("venster").hidden = true;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("venster").hidden = true;
});

/* Opbouwen */
laadLabels();
start();
