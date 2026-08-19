// Toevoegen en wijzigen van een recept op een aparte pagina.
// Nieuw: toevoegen via een webadres, snel toevoegen met foto/OCR, of een
// volledig recept met de hand.
// Wijzigen: via /beheer/toevoegen?id=<id>; dan wordt het recept ingevuld en
// worden het webadres-blok en het snel-toevoegen-blok verborgen. Na opslaan
// terug naar /beheer.

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

/* --- Toevoegen via een webadres (alleen bij een nieuw recept) ----------- */
function toonUrlMelding(tekst, soort) {
  const vak = $("urlMelding");
  vak.textContent = tekst;
  vak.className = "melding " + (soort || "");
  vak.hidden = !tekst;
}

function koppelUrl() {
  $("urlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const adres = $("urlVeld").value.trim();
    if (!adres) return;

    $("urlKnop").disabled = true;
    $("urlKnop").textContent = "Bezig…";
    toonUrlMelding("Het recept wordt opgehaald. Dit duurt meestal een paar tellen.", "");

    const fd = new FormData();
    fd.append("url", adres);
    try {
      const r = await fetch("/api/beheer/importeer-url", { method: "POST", body: fd });
      const res = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(res.fout || "Ophalen mislukt.");

      $("vTitel").value = res.titel || "";
      $("vCategorie").value = res.categorie || "uitproberen";
      $("vIngredienten").value = res.ingredienten || "";
      $("vBereiding").value = res.bereiding || "";
      $("vLabels").value = (res.labels || []).join(", ");
      $("vBron").value = res.bron || adres;
      $("vFotoNaam").value = res.foto || "";
      if (res.foto_url) {
        $("huidigeFotoLabel").textContent = "Opgehaalde foto:";
        $("huidigeFotoImg").src = res.foto_url;
        $("huidigeFoto").hidden = false;
      } else {
        $("huidigeFoto").hidden = true;
      }

      toonUrlMelding(
        res.foto
          ? "Opgehaald. Loop de velden hieronder na en sla daarna op."
          : "Opgehaald, maar zonder foto. Loop de velden hieronder na en sla daarna op.",
        "goed"
      );
      $("vTitel").scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (fout) {
      toonUrlMelding(fout.message, "fout");
    } finally {
      $("urlKnop").disabled = false;
      $("urlKnop").textContent = "Ophalen";
    }
  });
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
  $("urlBlok").hidden = true;               // ophalen via een webadres ook niet
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
  koppelUrl();
  koppelSnel();
}
