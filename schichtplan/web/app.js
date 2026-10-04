"use strict";

const TAGE = ["mo", "di", "mi", "do", "fr", "sa"];
const TAG_LANG = { mo: "Montag", di: "Dienstag", mi: "Mittwoch",
                   do: "Donnerstag", fr: "Freitag", sa: "Samstag" };
const SCHWERE = [
  ["fehler", "Fehler", "so nicht aushängen"],
  ["warnung", "Warnung", "geht, ist aber ein Zugeständnis"],
  ["hinweis", "Hinweis", "nur zur Kenntnis"],
];
const ABWESEND = { urlaub: "Urlaub", krank: "Krank", schule: "Schule",
                   feiertag: "zu", sonstige: "Sonstige" };
// Vorgaben, die statt einer Schicht in der Zelle stehen koennen. Die
// Reihenfolge ist die im Auswahlfeld.
const ZUSTAENDE = [
  ["frei", "Frei (fest)"],
  ["wunsch_frei", "Wunsch frei"],
  ["urlaub", "Urlaub"],
  ["krank", "Krank"],
  ["schule", "Schule"],
  ["sonstige", "Sonstige"],
];
const DATEITITEL = [
  [".html", "Papierplan", "HTML"],
  ["-teamleiter.html", "Teamleiterübersicht", "HTML"],
  [".pdf", "Papierplan", "PDF"],
  ["-teamleiter.pdf", "Teamleiterübersicht", "PDF"],
  [".csv", "Tabelle", "CSV"],
  ["-e2n-schichten.csv", "e2n Schichten", "CSV"],
  ["-e2n-abwesenheiten.csv", "e2n Abwesenheiten", "CSV"],
  [".json", "Rohdaten", "JSON"],
];

let aktuelle = null;
let daten = null;

const $ = (id) => document.getElementById(id);

async function hole(pfad, optionen) {
  const antwort = await fetch(pfad, optionen);
  const text = await antwort.text();
  let inhalt;
  try { inhalt = text ? JSON.parse(text) : {}; }
  catch { inhalt = { fehler: text.slice(0, 300) }; }
  if (!antwort.ok) throw new Error(inhalt.fehler || antwort.statusText);
  return inhalt;
}

const sende = (pfad, koerper) => hole(pfad, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(koerper || {}),
});

// ---- Wochenleiste ----------------------------------------------------- //
async function ladeListe() {
  const wochen = await hole("/api/wochen");
  const nav = $("wochenliste");
  nav.replaceChildren();
  for (const w of wochen) {
    const knopf = document.createElement("button");
    knopf.append(w.woche.replace(/^\d{4}-/, ""));
    if (w.uebernommen || w.geplant) {
      const marker = document.createElement("span");
      marker.className = `marker ${w.uebernommen ? "fertig" : "entwurf"}`;
      marker.title = w.uebernommen ? "in der Historie" : "geplant, noch offen";
      knopf.append(marker);
    }
    knopf.title = `zuletzt geändert ${w.geaendert}`;
    if (w.woche === aktuelle) knopf.classList.add("aktiv");
    knopf.onclick = () => oeffne(w.woche);
    nav.append(knopf);
  }
  return wochen;
}

// ---- Woche oeffnen ---------------------------------------------------- //
async function oeffne(name) {
  aktuelle = name;
  const adresse = new URL(location);
  adresse.searchParams.set("woche", name);
  history.replaceState(null, "", adresse);

  $("kontenblatt").hidden = true;
  daten = await hole(`/api/woche/${encodeURIComponent(name)}`);
  $("leer").hidden = true;
  $("arbeitsflaeche").hidden = false;

  const k = daten.kopf;
  $("wochentitel").textContent = name.replace("-", " ");
  $("wochenspanne").textContent = k
    ? `${datum(k.von)} bis ${datum(k.bis)}` +
      (k.modus === "manuell" ? "  ·  Handplan, wird nur geprueft" : "")
    : "";
  $("yaml").value = daten.yaml;
  $("speicherstand").textContent = "";
  $("uebernahme").textContent = "";

  if (daten.fehler) {
    melde(`Die Wochendatei lässt sich nicht laden: ${daten.fehler}`, "schlecht");
    $("rohtext").open = true;
  } else {
    $("stand").hidden = true;
  }
  zeichnePlan();
  zeichneBefunde(daten.befunde);
  zeigeDateien(daten.plan ? vorhandeneDateien(name) : null);
  await ladeListe();
}

function datum(iso) {
  if (!iso) return "";
  const [j, m, t] = iso.split("-");
  return `${t}.${m}.${j}`;
}

function vorhandeneDateien(name) {
  return [`${name}.html`, `${name}-teamleiter.html`, `${name}.csv`,
          `${name}-e2n-schichten.csv`, `${name}-e2n-abwesenheiten.csv`];
}

// ---- Plantafel -------------------------------------------------------- //
function zeichnePlan() {
  const ziel = $("plantafel");
  ziel.replaceChildren();
  $("kacheln").hidden = true;
  if (!daten.mitarbeiter) return;
  const geplant = Boolean(daten.plan);
  if (!geplant) {
    const hinweis = document.createElement("p");
    hinweis.className = "leise hinweiszeile";
    hinweis.textContent = "Noch kein Plan gerechnet. Urlaub, Wunschfrei und " +
      "feste Schichten lassen sich hier schon eintragen – dann oben auf " +
      "„Plan rechnen“.";
    ziel.append(hinweis);
  }

  const vorgabe = daten.vorgabe || {};
  const tabelle = document.createElement("table");
  tabelle.className = "plan";

  const kopf = tabelle.createTHead().insertRow();
  kopf.insertCell().outerHTML = "<th>Mitarbeiter</th>";
  const montag = daten.kopf && daten.kopf.von ? new Date(daten.kopf.von) : null;
  TAGE.forEach((t, i) => {
    let tagdatum = "";
    if (montag) {
      const d = new Date(montag);
      d.setDate(d.getDate() + i);
      tagdatum = `${d.getDate()}.${d.getMonth() + 1}.`;
    }
    kopf.insertCell().outerHTML =
      `<th class="tag">${TAG_LANG[t]}<span>${tagdatum}</span></th>`;
  });
  kopf.insertCell().outerHTML = "<th>Bezahlt</th>";

  const koerper = tabelle.createTBody();
  for (const ma of daten.mitarbeiter) {
    const reihe = geplant ? daten.plan.plan[ma.id] : zellenAusVorgabe(ma.id);
    if (!reihe) continue;
    const zeile = koerper.insertRow();
    const name = zeile.insertCell();
    name.className = "name";
    name.append(ma.name);
    if (ma.aushilfe) {
      const rolle = document.createElement("span");
      rolle.className = "rolle";
      rolle.textContent = "Aushilfe";
      name.append(rolle);
    }

    let stunden = 0, tage = 0;
    const gesetzt = vorgabe[ma.id] || {};
    for (const t of TAGE) {
      const zelle = reihe[t] || { art: "frei" };
      const td = zeile.insertCell();
      if (zelle.art === "feiertag") {
        td.className = "abwesend";
        td.textContent = "zu";
        continue;
      }
      if (zelle.art === "schicht") {
        stunden += (min(zelle.bis) - min(zelle.von)) / 60 - pause();
        tage += 1;
      }
      td.className = "zelle " + (zelle.art === "schicht"
        ? kategorie(ma, t, zelle) : zelle.art === "frei" ? "" : "abw");
      // Der blaue Balken meint "von Hand festgehalten". Abwesenheiten
      // tragen ihn nicht - die sieht man ohnehin.
      if (gesetzt[t] !== undefined && !(gesetzt[t] in ABWESEND)) {
        td.classList.add("fest");
      }
      td.append(auswahl(ma, t, zelle));
    }
    const summe = zeile.insertCell();
    summe.className = "summe";
    summe.innerHTML = `<b>${stunden.toFixed(1)} h</b> / ${tage} T`;
    if (ma.soll_h && !ma.aushilfe && stunden < ma.soll_h - 4) {
      summe.classList.add("knapp");
      summe.title = `Soll ${ma.soll_h} h`;
    }
  }

  const fuss = tabelle.createTFoot().insertRow();
  fuss.className = "fusszeile";
  fuss.insertCell().textContent = "Köpfe";
  let brutto = 0;
  const ziele = (daten.bedarf || {}).kopfzahl || {};
  for (const t of TAGE) {
    const besetzt = Object.values(daten.plan.plan)
      .filter((r) => r[t] && r[t].art === "schicht");
    for (const r of besetzt) brutto += (min(r[t].bis) - min(r[t].von)) / 60;
    const td = fuss.insertCell();
    td.className = "koepfe";
    td.textContent = ziele[t] ? `${besetzt.length} / ${ziele[t]}` : besetzt.length;
    if (ziele[t] && besetzt.length < ziele[t]) {
      td.classList.add("daneben");
      td.title = `Ziel sind ${ziele[t]} Köpfe`;
    }
  }
  fuss.insertCell();
  ziel.append(tabelle);
  if (geplant) zeigeKacheln(brutto);
}

function zellenAusVorgabe(mid) {
  const gesetzt = (daten.vorgabe || {})[mid] || {};
  const reihe = {};
  for (const t of TAGE) {
    const wert = gesetzt[t];
    if (wert === undefined || wert === "frei") {
      reihe[t] = { art: "frei" };
    } else if (ZUSTAENDE.some(([schluessel]) => schluessel === wert)) {
      reihe[t] = { art: wert };
    } else {
      const [von, bis] = String(wert).split("-");
      reihe[t] = { art: "schicht", von: lang(von), bis: lang(bis) };
    }
  }
  return reihe;
}

function lang(teil) {
  const [h, m] = String(teil).split(":");
  return `${String(Number(h)).padStart(2, "0")}:${m || "00"}`;
}

function kategorie(ma, tag, zelle) {
  if (zelle.art !== "schicht") return "";
  const eigen = `${kurz(zelle.von)}-${kurz(zelle.bis)}`;
  const liste = (ma.schichten || {})[tag] || [];
  const treffer = liste.find((s) => s.id === eigen);
  if (treffer) return treffer.kategorie;
  return (daten.kategorien || {})[eigen] || "";
}

function min(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}
function kurz(hhmm) {
  const [h, m] = hhmm.split(":");
  return m === "00" ? String(Number(h)) : `${Number(h)}:${m}`;
}
const pause = () => ((daten.kopf || {}).pause_h) || 0;


function auswahl(ma, tag, zelle) {
  const feld = document.createElement("select");
  feld.title = `${ma.name}, ${TAG_LANG[tag]}`;
  const gesetzt = ((daten.vorgabe || {})[ma.id] || {})[tag];
  const eigen = zelle.art === "schicht"
    ? `${kurz(zelle.von)}-${kurz(zelle.bis)}` : "";

  // Oben die Vorgaben, darunter die Schichten, die diese Person an diesem
  // Tag ueberhaupt arbeiten darf.
  // Der Normalfall heisst schlicht "Frei": die Zelle ist offen, der Planer
  // darf sie belegen. "Frei (fest)" unten haelt sie dagegen frei.
  feld.append(new Option("Frei", "auto", false,
                         gesetzt === undefined && zelle.art === "frei"));
  const vorgaben = document.createElement("optgroup");
  vorgaben.label = "Vorgabe";
  for (const [schluessel, beschriftung] of ZUSTAENDE) {
    const gewaehlt = schluessel === "frei"
      ? gesetzt === "frei"
      : (gesetzt === schluessel || zelle.art === schluessel);
    vorgaben.append(new Option(beschriftung, schluessel, false, gewaehlt));
  }
  feld.append(vorgaben);

  const moeglich = (ma.schichten || {})[tag] || [];
  if (moeglich.length) {
    const schichten = document.createElement("optgroup");
    schichten.label = "Schicht";
    for (const s of moeglich) {
      schichten.append(new Option(s.id, s.id, false, s.id === eigen));
    }
    feld.append(schichten);
  }
  if (eigen && !moeglich.some((s) => s.id === eigen)) {
    // Schicht, die der Katalog an dem Tag nicht vorsieht - trotzdem zeigen.
    const ausnahme = document.createElement("optgroup");
    ausnahme.label = "Ausnahme";
    ausnahme.append(new Option(eigen, eigen, false, true));
    feld.append(ausnahme);
  }
  feld.onchange = () => setzeZelle(ma.id, tag, feld.value);
  return feld;
}

async function setzeZelle(mid, tag, wert) {
  try {
    const antwort = await sende(
      `/api/woche/${encodeURIComponent(aktuelle)}/zelle`,
      { mitarbeiter: mid, tag, wert });
    $("yaml").value = antwort.yaml;
    // Der Server zieht die Aenderung im gespeicherten Plan nach und schickt
    // ihn zurueck - ohne ihn spraenge die Zelle beim Neuzeichnen wieder auf
    // den gerechneten Wert.
    daten = await hole(`/api/woche/${encodeURIComponent(aktuelle)}`);
    zeichneBefunde(daten.befunde);
    melde(wert === "auto"
      ? `${TAG_LANG[tag]} wieder freigegeben – der Planer entscheidet.`
      : `${TAG_LANG[tag]} festgehalten. Steht jetzt unter „fest:“ und ` +
        `bleibt beim naechsten Rechnen stehen.`);
    zeichnePlan();
  } catch (fehler) {
    melde(`Nicht übernommen: ${fehler.message}`, "schlecht");
  }
}

// ---- Kacheln ---------------------------------------------------------- //
function zeigeKacheln(brutto) {
  const kasten = $("kacheln");
  const soll = (daten.kopf || {}).budget;
  const befunde = daten.befunde || [];
  const zaehler = {};
  for (const [s] of SCHWERE) {
    zaehler[s] = befunde.filter((b) => b.schwere === s).length;
  }
  // Die Gesamtpunkte kommen vom Server; die Summe der angezeigten Befunde
  // waere kleiner, weil vieles Punkte kostet, ohne einen Satz wert zu sein.
  const punkte = daten.punkte != null
    ? daten.punkte : befunde.reduce((a, b) => a + b.punkte, 0);
  const weg = soll ? brutto - soll : 0;

  const kacheln = [
    { titel: "Arbeitszeit", wert: `${brutto.toFixed(1)} h`,
      zusatz: soll ? `Budget ${soll} h (${weg >= 0 ? "+" : ""}${weg.toFixed(1)})` : "",
      ton: !soll ? "" : Math.abs(weg) <= 5 ? "gut" : weg > 0 ? "warn" : "" },
    { titel: "Befunde", wert: String(befunde.length),
      zusatz: `${zaehler.fehler} Fehler, ${zaehler.warnung} Warnung, ` +
              `${zaehler.hinweis} Hinweis`,
      ton: zaehler.fehler ? "schlecht" : zaehler.warnung ? "warn" : "gut" },
    { titel: "Strafpunkte", wert: String(Math.round(punkte)),
      zusatz: "je niedriger, desto regelkonformer" },
  ];
  kasten.replaceChildren();
  for (const k of kacheln) {
    const d = document.createElement("div");
    d.className = `kachel ${k.ton || ""}`;
    d.innerHTML = `<span class="titel">${k.titel}</span>` +
      `<span class="wert">${k.wert}</span>` +
      (k.zusatz ? `<span class="zusatz">${k.zusatz}</span>` : "");
    kasten.append(d);
  }
  kasten.hidden = false;
}

// ---- Rechnen ---------------------------------------------------------- //
async function rechne() {
  const knopf = $("rechnen");
  knopf.disabled = true;
  knopf.querySelector(".punkt-laeuft").hidden = false;
  $("rechnen-text").textContent = "Rechnet …";
  melde("Rechnet – je nach Iterationen eine knappe Minute.");
  try {
    const { auftrag } = await sende(
      `/api/woche/${encodeURIComponent(aktuelle)}/plan`, {
        iterationen: Number($("iterationen").value),
        neustarts: Number($("neustarts").value),
        seed: Number($("seed").value),
        pdf: $("mitpdf").checked,
      });
    const ergebnis = await warte(auftrag);
    if (ergebnis.stand === "fehler") {
      melde(`Abgebrochen: ${ergebnis.fehler}`, "schlecht");
      return;
    }
    daten = await hole(`/api/woche/${encodeURIComponent(aktuelle)}`);
    $("yaml").value = daten.yaml;
    zeichnePlan();
    zeichneBefunde(ergebnis.befunde);
    zeigeDateien(ergebnis.dateien);
    const schlimm = ergebnis.befunde.some((b) => b.schwere === "fehler");
    melde(
      `${ergebnis.punkte} Strafpunkte, aus einem Greedy-Start von ${ergebnis.start}. ` +
      (schlimm ? "Es gibt Fehler – so nicht aushaengen."
               : "Kein Fehler – der Plan kann so raus.") +
      (ergebnis.meldungen.length ? "  " + ergebnis.meldungen.join("  ") : ""),
      schlimm ? "schlecht" : "gut");
  } catch (fehler) {
    melde(`Abgebrochen: ${fehler.message}`, "schlecht");
  } finally {
    knopf.disabled = false;
    knopf.querySelector(".punkt-laeuft").hidden = true;
    $("rechnen-text").textContent = "Plan rechnen";
    ladeListe();
  }
}

function warte(auftrag) {
  return new Promise((fertig, schief) => {
    const takt = setInterval(async () => {
      try {
        const stand = await hole(`/api/auftrag/${encodeURIComponent(auftrag)}`);
        if (stand.stand === "laeuft") return;
        clearInterval(takt);
        fertig(stand);
      } catch (fehler) { clearInterval(takt); schief(fehler); }
    }, 1000);
  });
}

function melde(text, ton) {
  const kasten = $("stand");
  kasten.hidden = false;
  kasten.textContent = text;
  kasten.className = `stand ${ton || ""}`;
}

// ---- Befunde ---------------------------------------------------------- //
function zeichneBefunde(befunde) {
  const ziel = $("befunde");
  ziel.replaceChildren();
  $("befundkarte").hidden = !befunde || !befunde.length;
  if (!befunde || !befunde.length) return;
  for (const [schluessel, titel, erklaerung] of SCHWERE) {
    const treffer = befunde.filter((b) => b.schwere === schluessel);
    if (!treffer.length) continue;
    const summe = Math.round(treffer.reduce((a, b) => a + b.punkte, 0));
    const block = document.createElement("div");
    block.className = `grad ${schluessel}`;
    const kopf = document.createElement("h3");
    kopf.append(`${titel} (${treffer.length}, ${summe} Punkte) `);
    const em = document.createElement("em");
    em.textContent = `– ${erklaerung}`;
    kopf.append(em);
    block.append(kopf);
    const liste = document.createElement("ul");
    for (const b of treffer) {
      const punkt = document.createElement("li");
      punkt.append(b.text + " ");
      const quelle = document.createElement("span");
      quelle.className = "pkt";
      quelle.textContent = `(${b.regel}, ${b.punkte})`;
      punkt.append(quelle);
      liste.append(punkt);
    }
    block.append(liste);
    ziel.append(block);
  }
}

// ---- Dateien ---------------------------------------------------------- //
function zeigeDateien(dateien) {
  const kasten = $("ausgaben");
  if (!dateien || !dateien.length) { kasten.hidden = true; return; }
  kasten.hidden = false;
  const liste = $("dateiliste");
  liste.replaceChildren();
  for (const name of dateien) {
    const rest = name.slice(aktuelle.length);
    const eintrag = DATEITITEL.find(([endung]) => endung === rest);
    const a = document.createElement("a");
    a.href = `/ausgabe/${encodeURIComponent(name)}`;
    a.target = "_blank";
    a.rel = "noopener";
    a.append(eintrag ? eintrag[1] : name);
    if (eintrag) {
      const art = document.createElement("span");
      art.className = "art";
      art.textContent = eintrag[2];
      a.append(art);
    }
    liste.append(a);
  }
}

// ---- Rohtext, Historie, Konten ---------------------------------------- //
async function speichere() {
  try {
    await sende(`/api/woche/${encodeURIComponent(aktuelle)}/speichern`,
                { yaml: $("yaml").value });
    $("speicherstand").textContent = "gespeichert";
    zeichnePlan();
  } catch (fehler) {
    $("speicherstand").textContent = fehler.message;
  }
}

async function uebernimm() {
  try {
    const antwort = await sende(
      `/api/woche/${encodeURIComponent(aktuelle)}/uebernehmen`);
    $("uebernahme").textContent =
      `uebernommen – die Historie umfasst jetzt ${antwort.wochen} Wochen`;
    ladeListe();
  } catch (fehler) {
    $("uebernahme").textContent = fehler.message;
  }
}

async function zeigeKonten() {
  const antwort = await fetch("/api/konten");
  $("kontenhtml").innerHTML = await antwort.text();
  $("kontenblatt").hidden = false;
  $("kontenblatt").scrollIntoView({ behavior: "smooth", block: "start" });
}

// ---- Farbschema ------------------------------------------------------- //
function schemaUmschalten() {
  const jetzt = document.documentElement.dataset.schema;
  const dunkel = jetzt
    ? jetzt === "dunkel"
    : matchMedia("(prefers-color-scheme: dark)").matches;
  const neu = dunkel ? "hell" : "dunkel";
  document.documentElement.dataset.schema = neu;
  try { localStorage.setItem("schema", neu); } catch { /* egal */ }
}
// Gemerkte Einstellung, sonst das Systemschema. ?schema=dunkel geht auch -
// praktisch, um die Darstellung ohne Klick zu pruefen.
try {
  const ausAdresse = new URLSearchParams(location.search).get("schema");
  const gemerkt = ausAdresse || localStorage.getItem("schema");
  if (gemerkt === "hell" || gemerkt === "dunkel") {
    document.documentElement.dataset.schema = gemerkt;
  }
} catch { /* privates Fenster: dann eben das Systemschema */ }

$("rechnen").onclick = rechne;
$("speichern").onclick = speichere;
$("uebernehmen").onclick = uebernimm;
$("zeigekonten").onclick = zeigeKonten;
$("farbschema").onclick = schemaUmschalten;

// Beim Start die Woche aus der Adresse, sonst die, an der gearbeitet wird.
(async () => {
  const wochen = await ladeListe();
  const gewuenscht = new URLSearchParams(location.search).get("woche");
  const offen = wochen.find((w) => w.geplant && !w.uebernommen);
  const start = (gewuenscht && wochen.some((w) => w.woche === gewuenscht))
    ? gewuenscht : (offen || wochen[wochen.length - 1] || {}).woche;
  if (start) await oeffne(start);
})();
