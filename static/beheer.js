// Beheeroverzicht van MijnRecepten: alle recepten tonen met acties. Toevoegen
// en wijzigen gebeurt op een aparte pagina (/beheer/toevoegen).
// Deze pagina is via nginx afgeschermd met de centrale aanmelding.

const $ = (id) => document.getElementById(id);
const CAT_TEKST = { favoriet: "Favoriet", uitproberen: "Uitproberen", afgeserveerd: "Afgeserveerd" };
let huidigeCategorie = "";
let huidigeZoek = "";
const gekozenLabels = new Set();

async function haal(pad, opties) {
  const r = await fetch(pad, opties);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

/* Acties per recept */
async function naarFavoriet(id) {
  await haal(`/api/beheer/recept/${id}/naar-favoriet`, { method: "POST" });
  $("status").textContent = "Omgezet naar favoriet.";
  laadLijst();
}

async function verwijder(id) {
  if (!confirm("Dit recept verwijderen?")) return;
  await haal(`/api/beheer/recept/${id}/verwijder`, { method: "POST" });
  $("status").textContent = "Verwijderd.";
  laadLabels();
  laadLijst();
}

function knop(tekst, klasse, actie) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = klasse;
  b.textContent = tekst;
  b.addEventListener("click", actie);
  return b;
}

function maakRij(r) {
  const rij = document.createElement("div");
  rij.className = "beheer-rij";

  if (r.foto_url) {
    const img = document.createElement("img");
    img.src = r.foto_url; img.alt = r.titel; img.loading = "lazy";
    rij.appendChild(img);
  } else {
    const leeg = document.createElement("div");
    leeg.className = "geen-foto"; leeg.textContent = "geen foto";
    rij.appendChild(leeg);
  }

  const info = document.createElement("div");
  info.className = "info";
  info.innerHTML = `<div class="t"></div><div class="m"></div>`;
  info.querySelector(".t").textContent = r.titel;
  info.querySelector(".m").textContent = CAT_TEKST[r.categorie] || r.categorie;
  if (r.labels && r.labels.length) {
    const labelrij = document.createElement("div");
    labelrij.className = "recept-labels";
    r.labels.forEach((naam) => {
      const l = document.createElement("span");
      l.className = "mini-label";
      l.textContent = naam;
      labelrij.appendChild(l);
    });
    info.appendChild(labelrij);
  }
  rij.appendChild(info);

  const acties = document.createElement("div");
  acties.className = "acties";
  // Bewerken opent de aparte toevoeg-/wijzigpagina met dit recept.
  const bewerkKnop = knop("Bewerk", "grijs klein", () => {
    window.location.href = `/beheer/toevoegen?id=${r.id}`;
  });
  acties.appendChild(bewerkKnop);
  if (r.categorie === "uitproberen") {
    acties.appendChild(knop("→ Favoriet", "klein", () => naarFavoriet(r.id)));
  }
  acties.appendChild(knop("Verwijder", "rood klein", () => verwijder(r.id)));
  rij.appendChild(acties);
  return rij;
}

/* Labelfilter: alle labels met het aantal recepten, net als op de site. */
async function laadLabels() {
  const labels = await haal("/api/labels");
  const houder = $("labels");
  houder.innerHTML = "";
  labels.forEach((l) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "label-chip" + (gekozenLabels.has(l.naam) ? " actief" : "");
    chip.textContent = l.naam;
    const aantal = document.createElement("span");
    aantal.className = "aantal";
    aantal.textContent = l.aantal;
    chip.appendChild(aantal);
    chip.addEventListener("click", () => {
      if (gekozenLabels.has(l.naam)) gekozenLabels.delete(l.naam);
      else gekozenLabels.add(l.naam);
      chip.classList.toggle("actief");
      laadLijst();
    });
    houder.appendChild(chip);
  });
}

async function laadLijst() {
  const p = new URLSearchParams();
  if (huidigeCategorie) p.set("categorie", huidigeCategorie);
  if (huidigeZoek) p.set("zoek", huidigeZoek);
  if (gekozenLabels.size) p.set("labels", [...gekozenLabels].join(","));
  const recepten = await haal("/api/recepten?" + p.toString());
  const lijst = $("beheerLijst");
  lijst.innerHTML = "";
  if (!recepten.length) {
    lijst.innerHTML = '<p class="hint">Geen recepten gevonden.</p>';
    return;
  }
  recepten.forEach((r) => lijst.appendChild(maakRij(r)));
  $("status").textContent =
    recepten.length + (recepten.length === 1 ? " recept" : " recepten");
}

/* Tabs en zoeken */
$("beheerTabs").addEventListener("click", (e) => {
  const k = e.target.closest(".tab");
  if (!k) return;
  document.querySelectorAll("#beheerTabs .tab").forEach((t) => t.classList.remove("actief"));
  k.classList.add("actief");
  huidigeCategorie = k.dataset.categorie;
  laadLijst();
});

let zoekTimer;
$("zoekveld").addEventListener("input", (e) => {
  clearTimeout(zoekTimer);
  zoekTimer = setTimeout(() => {
    huidigeZoek = e.target.value.trim();
    laadLijst();
  }, 220);
});

/* Melding als er zojuist iets is toegevoegd of gewijzigd (via ?melding=) */
const melding = new URLSearchParams(location.search).get("melding");
if (melding) $("status").textContent = melding;

laadLabels();
laadLijst();
