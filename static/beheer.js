// Beheer van MijnRecepten: snel toevoegen met foto en OCR, volledig recept
// toevoegen of wijzigen, en een recept omzetten naar favoriet of verwijderen.
// Deze pagina is via nginx afgeschermd met de centrale aanmelding.

const $ = (id) => document.getElementById(id);
const CAT_TEKST = { favoriet: "Favoriet", uitproberen: "Uitproberen" };
let huidigeCategorie = "";

async function haal(pad, opties) {
  const r = await fetch(pad, opties);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

/* --- Snel toevoegen met OCR --------------------------------------------- */
// Zodra een foto is gekozen, alvast de tekst herkennen en tonen.
$("snelFoto").addEventListener("change", async (e) => {
  const bestand = e.target.files[0];
  if (!bestand) return;
  $("status").textContent = "Tekst herkennen…";
  const fd = new FormData();
  fd.append("foto", bestand);
  try {
    const res = await haal("/api/beheer/ocr", { method: "POST", body: fd });
    if (res.ocr && res.tekst) {
      $("ocrTekst").textContent = res.tekst;
      $("ocrVoorbeeld").hidden = false;
    } else {
      $("ocrVoorbeeld").hidden = true;
    }
    $("status").textContent = res.ocr ? "Tekst herkend." : "Tekstherkenning niet beschikbaar; foto wordt wel bewaard.";
  } catch (fout) {
    $("status").textContent = "Herkennen mislukt: " + fout.message;
  }
});

$("snelForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  fd.set("categorie", "uitproberen");
  try {
    await haal("/api/beheer/recept", { method: "POST", body: fd });
    e.target.reset();
    $("ocrVoorbeeld").hidden = true;
    $("status").textContent = "Toegevoegd aan Uitproberen.";
    laadLijst();
  } catch (fout) {
    $("status").textContent = "Toevoegen mislukt: " + fout.message;
  }
});

/* --- Volledig recept toevoegen of wijzigen ------------------------------ */
function maakLeeg() {
  $("receptId").value = "";
  $("receptForm").reset();
  $("volledigTitel").textContent = "Recept toevoegen";
}
$("leegKnop").addEventListener("click", maakLeeg);

$("receptForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("receptId").value;
  const fd = new FormData(e.target);
  const pad = id ? `/api/beheer/recept/${id}` : "/api/beheer/recept";
  try {
    await haal(pad, { method: "POST", body: fd });
    maakLeeg();
    $("status").textContent = id ? "Recept gewijzigd." : "Recept toegevoegd.";
    laadLijst();
  } catch (fout) {
    $("status").textContent = "Opslaan mislukt: " + fout.message;
  }
});

async function bewerk(id) {
  const r = await haal(`/api/recepten/${id}`);
  $("receptId").value = r.id;
  $("vTitel").value = r.titel || "";
  $("vCategorie").value = r.categorie || "uitproberen";
  $("vIngredienten").value = r.ingredienten || r.ocr_tekst || "";
  $("vBereiding").value = r.bereiding || "";
  $("vLabels").value = (r.labels || []).join(", ");
  $("vBron").value = r.bron || "";
  $("volledigTitel").textContent = "Recept wijzigen";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* --- Acties per recept -------------------------------------------------- */
async function naarFavoriet(id) {
  await haal(`/api/beheer/recept/${id}/naar-favoriet`, { method: "POST" });
  $("status").textContent = "Omgezet naar favoriet.";
  laadLijst();
}

async function verwijder(id) {
  if (!confirm("Dit recept verwijderen?")) return;
  await haal(`/api/beheer/recept/${id}/verwijder`, { method: "POST" });
  $("status").textContent = "Verwijderd.";
  laadLijst();
}

/* --- Overzicht ---------------------------------------------------------- */
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
  info.querySelector(".m").textContent =
    (CAT_TEKST[r.categorie] || r.categorie) +
    (r.labels && r.labels.length ? " · " + r.labels.join(", ") : "");
  rij.appendChild(info);

  const acties = document.createElement("div");
  acties.className = "acties";

  const bewerkKnop = knop("Bewerk", "grijs klein", () => bewerk(r.id));
  acties.appendChild(bewerkKnop);
  if (r.categorie === "uitproberen") {
    acties.appendChild(knop("→ Favoriet", "klein", () => naarFavoriet(r.id)));
  }
  acties.appendChild(knop("Verwijder", "rood klein", () => verwijder(r.id)));
  rij.appendChild(acties);
  return rij;
}

function knop(tekst, klasse, actie) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = klasse;
  b.textContent = tekst;
  b.addEventListener("click", actie);
  return b;
}

async function laadLijst() {
  const pad = "/api/recepten" + (huidigeCategorie ? "?categorie=" + huidigeCategorie : "");
  const recepten = await haal(pad);
  const lijst = $("beheerLijst");
  lijst.innerHTML = "";
  if (!recepten.length) {
    lijst.innerHTML = '<p class="hint">Nog geen recepten in deze categorie.</p>';
    return;
  }
  recepten.forEach((r) => lijst.appendChild(maakRij(r)));
}

$("beheerTabs").addEventListener("click", (e) => {
  const knop = e.target.closest(".tab");
  if (!knop) return;
  document.querySelectorAll("#beheerTabs .tab").forEach((t) => t.classList.remove("actief"));
  knop.classList.add("actief");
  huidigeCategorie = knop.dataset.categorie;
  laadLijst();
});

/* Melden of OCR beschikbaar is */
haal("/api/beheer/status").then((s) => {
  if (!s.ocr_beschikbaar) {
    $("status").textContent = "Let op: tekstherkenning (OCR) is niet beschikbaar in deze omgeving.";
  }
}).catch(() => {});

laadLijst();
