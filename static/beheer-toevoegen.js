// Toevoegen en wijzigen van een recept op een aparte pagina.
// Nieuw: snel toevoegen met foto/OCR of een volledig recept.
// Wijzigen: via /beheer/toevoegen?id=<id>; dan wordt het recept ingevuld en
// het snel-toevoegen-blok verborgen. Na opslaan terug naar /beheer.

const $ = (id) => document.getElementById(id);
const bewerkId = new URLSearchParams(location.search).get("id");

async function haal(pad, opties) {
  const r = await fetch(pad, opties);
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

function terugNaarBeheer(melding) {
  window.location.href = "/beheer?melding=" + encodeURIComponent(melding);
}

/* --- Snel toevoegen met OCR (alleen bij een nieuw recept) --------------- */
function koppelSnel() {
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
      $("status").textContent = res.ocr
        ? "Tekst herkend."
        : "Tekstherkenning niet beschikbaar; foto wordt wel bewaard.";
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
      terugNaarBeheer("Toegevoegd aan Uitproberen.");
    } catch (fout) {
      $("status").textContent = "Toevoegen mislukt: " + fout.message;
    }
  });
}

/* --- Volledig recept: toevoegen of wijzigen ---------------------------- */
$("receptForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const pad = bewerkId ? `/api/beheer/recept/${bewerkId}` : "/api/beheer/recept";
  try {
    await haal(pad, { method: "POST", body: fd });
    terugNaarBeheer(bewerkId ? "Recept gewijzigd." : "Recept toegevoegd.");
  } catch (fout) {
    $("status").textContent = "Opslaan mislukt: " + fout.message;
  }
});

/* --- Wijzigmodus: recept inladen --------------------------------------- */
async function laadTeWijzigen() {
  const r = await haal(`/api/recepten/${bewerkId}`);
  $("paginaTitel").textContent = "wijzigen";
  $("volledigTitel").textContent = "Recept wijzigen";
  document.title = "MijnRecepten — Recept wijzigen";
  $("snelBlok").hidden = true;              // snel toevoegen niet tonen bij wijzigen
  $("receptId").value = r.id;
  $("vTitel").value = r.titel || "";
  $("vCategorie").value = r.categorie || "uitproberen";
  $("vIngredienten").value = r.ingredienten || r.ocr_tekst || "";
  $("vBereiding").value = r.bereiding || "";
  $("vLabels").value = (r.labels || []).join(", ");
  $("vBron").value = r.bron || "";
  if (r.foto_url) {
    $("huidigeFotoImg").src = r.foto_url;
    $("huidigeFoto").hidden = false;
  }
}

/* Opbouwen */
if (bewerkId) {
  laadTeWijzigen().catch((fout) => {
    $("status").textContent = "Laden mislukt: " + fout.message;
  });
} else {
  koppelSnel();
}
