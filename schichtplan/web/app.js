"use strict";

const TAGE = ["mo", "di", "mi", "do", "fr", "sa"];
const TAG_LANG = { mo: "Montag", di: "Dienstag", mi: "Mittwoch",
                   do: "Donnerstag", fr: "Freitag", sa: "Samstag" };
const SCHWERE = [["fehler", "Fehler", "so nicht aushaengen"],
                 ["warnung", "Warnung", "geht, ist aber ein Zugestaendnis"],
                 ["hinweis", "Hinweis", "nur zur Kenntnis"]];

let aktuelle = null;     // Name der offenen Woche
let daten = null;        // Antwort von /api/woche/<name>

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

async function sende(pfad, koerper) {
  return hole(pfad, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(koerper || {}),
  });
}

// ---- Wochenliste ------------------------------------------------------ //
async function ladeListe() {
  const wochen = await hole("/api/wochen");
  const nav = $("wochenliste");
  nav.replaceChildren();
  for (const w of wochen) {
    const knopf = document.createElement("button");
    knopf.textContent = w.woche.replace("2026-", "");
    knopf.title = `zuletzt geaendert ${w.geaendert}`;
    if (w.uebernommen) knopf.insertAdjacentHTML("beforeend",
      ' <span class="punkt" title="in der Historie">●</span>');
    else if (w.geplant) knopf.insertAdjacentHTML("beforeend",
      ' <span class="punkt" title="geplant, noch nicht uebernommen">○</span>');
    if (w.woche === aktuelle) knopf.classList.add("aktiv");
    knopf.onclick = () => oeffne(w.woche);
    nav.append(knopf);
  }
}

// ---- Eine Woche ------------------------------------------------------- //
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
  $("wochentitel").textContent = k
    ? `${name}   ${k.von} bis ${k.bis}${k.modus === "manuell" ? "   (Handplan)" : ""}`
    : name;
  $("yaml").value = daten.yaml;
  $("speicherstand").textContent = "";
  $("uebernahme").textContent = "";
  if (daten.fehler) {
    melde(`Die Wochendatei laesst sich nicht laden: ${daten.fehler}`, true);
    $("rohtext").open = true;
  } else {
    $("stand").hidden = true;
  }
  zeichnePlan();
  zeichneBefunde(daten.befunde);
  zeigeDateien(daten.plan ? standardDateien(name) : null);
  await ladeListe();
}

function standardDateien(name) {
  return [`${name}.html`, `${name}-teamleiter.html`, `${name}.csv`,
          `${name}-e2n-schichten.csv`, `${name}-e2n-abwesenheiten.csv`];
}

// ---- Plantafel -------------------------------------------------------- //
function zeichnePlan() {
  const ziel = $("plantafel");
  ziel.replaceChildren();
  if (!daten.plan) {
    ziel.innerHTML = '<p class="hinweis">Fuer diese Woche gibt es noch keinen ' +
      'Plan. Oben rechts auf <em>Plan rechnen</em>.</p>';
    return;
  }
  const tabelle = document.createElement("table");
  tabelle.className = "plan";
  const kopf = tabelle.insertRow();
  kopf.insertCell().outerHTML = "<th>Mitarbeiter</th>";
  for (const t of TAGE) kopf.insertCell().outerHTML = `<th>${TAG_LANG[t]}</th>`;
  kopf.insertCell().outerHTML = "<th>Summe</th>";

  const fest = festeZellen();
  for (const ma of daten.mitarbeiter) {
    const reihe = daten.plan.plan[ma.id];
    if (!reihe) continue;
    const zeile = tabelle.insertRow();
    const name = zeile.insertCell();
    name.className = "name";
    name.textContent = ma.name;
    let stunden = 0, tage = 0;
    for (const t of TAGE) {
      const zelle = reihe[t] || { art: "frei" };
      const td = zeile.insertCell();
      if (zelle.art !== "frei" && zelle.art !== "schicht") {
        td.className = "abwesend";
        td.textContent = beschriftung(zelle);
        continue;
      }
      if (zelle.art === "schicht") {
        // Wie in der Papierausgabe: bezahlte Zeit, also abzueglich Pause.
        stunden += (zu(zelle.bis) - zu(zelle.von)) / 60 - pause();
        tage += 1;
      }
      td.className = zelle.art === "frei" ? "istfrei" : "";
      if (fest[ma.id] && fest[ma.id].has(t)) td.classList.add("istfest");
      td.append(auswahl(ma, t, zelle));
    }
    const summe = zeile.insertCell();
    summe.className = "summe";
    summe.textContent = `${stunden.toFixed(1)} h / ${tage} T`;
  }
  const fuss = tabelle.insertRow();
  fuss.className = "fuss";
  fuss.insertCell().textContent = "Koepfe";
  let brutto = 0;
  for (const t of TAGE) {
    const besetzt = Object.values(daten.plan.plan)
      .filter((r) => r[t] && r[t].art === "schicht");
    for (const r of besetzt) brutto += (zu(r[t].bis) - zu(r[t].von)) / 60;
    fuss.insertCell().textContent = besetzt.length;
  }
  fuss.insertCell();
  ziel.append(tabelle);

  const soll = (daten.kopf || {}).budget;
  if (soll) {
    const zeile = document.createElement("p");
    zeile.className = "notiz";
    const weg = brutto - soll;
    zeile.textContent =
      `${brutto.toFixed(1)} h brutto gegen ein Budget von ${soll} h ` +
      `(${weg >= 0 ? "+" : ""}${weg.toFixed(1)} h). ` +
      `Die Summenspalte rechts ist die bezahlte Zeit, also ohne Pausen.`;
    ziel.append(zeile);
  }
}

function pause() {
  return ((daten.kopf || {}).pause_h) || 0;
}

function beschriftung(zelle) {
  return { urlaub: "Urlaub", krank: "Krank", schule: "Schule",
           feiertag: "zu", sonstige: "abw." }[zelle.art] || zelle.art;
}

function zu(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function festeZellen() {
  // Aus dem Rohtext lesen, damit die Markierung auch ohne Neuladen stimmt.
  const karte = {};
  const text = $("yaml").value;
  const zeilen = text.split("\n");
  const anfang = zeilen.findIndex((z) => z.startsWith("fest:"));
  if (anfang < 0) return karte;
  for (let i = anfang + 1; i < zeilen.length; i++) {
    const z = zeilen[i];
    if (z && !/^\s/.test(z)) break;
    const treffer = z.match(/^ {2}([a-z_]+):\s*\{(.*?)\}/);
    if (!treffer) continue;
    karte[treffer[1]] = new Set(
      [...treffer[2].matchAll(/\b(mo|di|mi|do|fr|sa)\s*:/g)].map((m) => m[1]));
  }
  return karte;
}

function auswahl(ma, tag, zelle) {
  const feld = document.createElement("select");
  const jetzt = zelle.art === "schicht" ? `${zelle.von}-${zelle.bis}` : "";
  const moeglich = ma.schichten[tag] || [];
  feld.append(new Option("Frei", "frei", false, zelle.art === "frei"));
  let getroffen = zelle.art === "frei";
  for (const sid of moeglich) {
    const passt = zelle.art === "schicht" && gleich(sid, jetzt);
    if (passt) getroffen = true;
    feld.append(new Option(sid, sid, false, passt));
  }
  if (!getroffen && zelle.art === "schicht") {
    // Schicht, die der Katalog an dem Tag nicht kennt - trotzdem anzeigen.
    const eigen = `${kurz(zelle.von)}-${kurz(zelle.bis)}`;
    feld.append(new Option(eigen + " (fest)", eigen, false, true));
  }
  feld.append(new Option("— Planer entscheidet", "auto"));
  feld.onchange = () => setzeZelle(ma.id, tag, feld.value);
  return feld;
}

function kurz(hhmm) {
  const [h, m] = hhmm.split(":");
  return m === "00" ? String(Number(h)) : `${Number(h)}:${m}`;
}

function gleich(sid, zeiten) {
  const [a, b] = zeiten.split("-");
  return sid === `${kurz(a)}-${kurz(b)}`;
}

async function setzeZelle(mid, tag, wert) {
  try {
    const antwort = await sende(
      `/api/woche/${encodeURIComponent(aktuelle)}/zelle`,
      { mitarbeiter: mid, tag, wert });
    $("yaml").value = antwort.yaml;
    melde(`${TAG_LANG[tag]} festgehalten. Der Eintrag steht jetzt unter ` +
          `'fest:' und bleibt beim naechsten Rechnen stehen.`);
    zeichnePlan();
  } catch (fehler) {
    melde(`Nicht uebernommen: ${fehler.message}`, true);
  }
}

// ---- Rechnen ---------------------------------------------------------- //
async function rechne() {
  const knopf = $("rechnen");
  knopf.disabled = true;
  melde("Rechnet … das dauert je nach Iterationen eine knappe Minute.");
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
      melde(`Abgebrochen: ${ergebnis.fehler}`, true);
      return;
    }
    daten = await hole(`/api/woche/${encodeURIComponent(aktuelle)}`);
    $("yaml").value = daten.yaml;
    zeichnePlan();
    zeichneBefunde(ergebnis.befunde);
    zeigeDateien(ergebnis.dateien);
    const schlimm = ergebnis.befunde.some((b) => b.schwere === "fehler");
    melde(`${ergebnis.punkte} Strafpunkte (Greedy-Start ${ergebnis.start}). ` +
          (schlimm ? "Es gibt Fehler – so nicht aushaengen."
                   : "Kein Fehler.") +
          (ergebnis.meldungen.length ? "  " + ergebnis.meldungen.join("  ") : ""),
          schlimm);
  } catch (fehler) {
    melde(`Abgebrochen: ${fehler.message}`, true);
  } finally {
    knopf.disabled = false;
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

function melde(text, schlecht) {
  const kasten = $("stand");
  kasten.hidden = false;
  kasten.textContent = text;
  kasten.classList.toggle("schlecht", Boolean(schlecht));
}

// ---- Befunde ---------------------------------------------------------- //
function zeichneBefunde(befunde) {
  const ziel = $("befunde");
  ziel.replaceChildren();
  if (!befunde || !befunde.length) return;
  for (const [schluessel, titel, erklaerung] of SCHWERE) {
    const treffer = befunde.filter((b) => b.schwere === schluessel);
    if (!treffer.length) continue;
    const summe = treffer.reduce((a, b) => a + b.punkte, 0);
    const block = document.createElement("div");
    block.className = `grad ${schluessel}`;
    block.innerHTML =
      `<h4>${titel} (${treffer.length}, ${summe} Punkte) – ${erklaerung}</h4>`;
    const liste = document.createElement("ul");
    for (const b of treffer) {
      const punkt = document.createElement("li");
      punkt.textContent = b.text;
      punkt.insertAdjacentHTML("beforeend",
        ` <span class="pkt">(${b.regel}, ${b.punkte})</span>`);
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
  const titel = {
    ".html": "Papierplan", "-teamleiter.html": "Teamleiteruebersicht",
    ".pdf": "Papierplan PDF", "-teamleiter.pdf": "Teamleiteruebersicht PDF",
    ".csv": "Tabelle", "-e2n-schichten.csv": "e2n Schichten",
    "-e2n-abwesenheiten.csv": "e2n Abwesenheiten", ".json": "Rohdaten",
  };
  for (const name of dateien) {
    const rest = name.slice(aktuelle.length);
    const a = document.createElement("a");
    a.href = `/ausgabe/${encodeURIComponent(name)}`;
    a.target = "_blank";
    a.rel = "noopener";
    a.textContent = titel[rest] || name;
    liste.append(a);
  }
}

// ---- Rohtext und Historie --------------------------------------------- //
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
  $("kontenblatt").scrollIntoView({ behavior: "smooth" });
}

$("rechnen").onclick = rechne;
$("speichern").onclick = speichere;
$("uebernehmen").onclick = uebernimm;
$("zeigekonten").onclick = zeigeKonten;

// Beim Start die Woche aus der Adresse oeffnen, sonst die, an der gerade
// gearbeitet wird: die erste geplante, die noch nicht in der Historie steht.
(async () => {
  const wochen = await hole("/api/wochen");
  await ladeListe();
  const gewuenscht = new URLSearchParams(location.search).get("woche");
  const offen = wochen.find((w) => w.geplant && !w.uebernommen);
  const start = (gewuenscht && wochen.some((w) => w.woche === gewuenscht))
    ? gewuenscht : (offen || wochen[wochen.length - 1] || {}).woche;
  if (start) await oeffne(start);
})();
