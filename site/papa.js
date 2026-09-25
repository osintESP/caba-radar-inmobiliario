// Vista simplificada para otro perfil de comprador (config/mi_propiedad_papa.yaml):
// mismos datos que index.html/app.js (data/latest.json), pero acotada a sus
// propios criterios de búsqueda (2 ambientes, misma zona) y pensada para ser
// fácil de leer y navegar: pocas columnas, texto grande, tarjetas en vez de
// una tabla densa de 20 columnas.

const DATA_URL = "data/latest.json";

const fmtNum = (n) => (n === null || n === undefined ? "s/d" : Math.round(n).toLocaleString("es-AR"));
const fmtSigned = (n) => {
  if (n === null || n === undefined) return "s/d";
  const rounded = Math.round(n);
  return `${rounded > 0 ? "+" : ""}${rounded.toLocaleString("es-AR")}`;
};
const fmtPct = (n) => (n === null || n === undefined ? "s/d" : `${Math.round(n * 100)}%`);
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("es-AR") : "s/d");

let currentData = [];
let busqueda = { ambientes_objetivo: 2, tipos: ["departamento", "ph"] };
// Lista propia, separada de la de index.html: lo que no le gusta a un
// perfil no tiene por qué ocultarse para el otro.
const descartados = crearDescartados("radar.descartados.papa");
let verDescartados = false;
const claveDe = (r) => `${r.portal}:${r.portal_id}`;

async function loadData() {
  const banner = document.getElementById("status-banner");
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    currentData = data.avisos || [];
    busqueda = (data.papa && data.papa.busqueda) || busqueda;

    banner.textContent = `Actualizado: ${fmtDate(data.generated_at)} · ${data.n_avisos} avisos en la zona`;

    renderSuPropiedad(data.papa && data.papa.mi_propiedad);
    populateBarrioFilter(currentData);
    render();
  } catch (err) {
    banner.textContent = `No se pudo cargar la información (${err.message}). Probá recargar la página en un rato.`;
  }
}

function renderSuPropiedad(mp) {
  const section = document.getElementById("su-propiedad");
  const body = document.getElementById("su-propiedad-body");
  if (!mp) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  if (mp.veredicto === "sin_datos") {
    body.innerHTML =
      `<p class="papa-faltan-datos">Todavía faltan datos de la casa (metros cuadrados) para poder compararla ` +
      `contra el resto de Merlo. Se completa en <code>config/mi_propiedad_papa.yaml</code>.</p>`;
    return;
  }

  const lugar = mp.direccion || `${mp.barrio} · ${mp.tipo}`;
  const stats = [{ value: `USD ${fmtNum(mp.precio_venta_max_usd)}`, label: "Precio de venta" }];

  let detalle;
  if (mp.veredicto === "insuficiente") {
    detalle = `<p class="mi-propiedad__insuficiente">Todavía no hay suficientes casas comparables en la zona para poder decir si el precio es justo (${mp.n_comparables} de 30 necesarias).</p>`;
  } else {
    stats.push(
      { value: fmtNum(mp.usd_m2_mediana), label: "Mediana de la zona (USD/m²)" },
      { value: mp.percentil_sujeto === null ? "—" : `Percentil ${Math.round(mp.percentil_sujeto)}`, label: "Su posición" },
    );
    detalle = `<p class="mp-detail">Comparado contra <strong>${mp.n_comparables}</strong> casas reales de la zona.</p>`;
  }

  const statsHtml = stats
    .map((s) => `<div class="mp-stat"><span class="mp-stat__value">${s.value}</span><span class="mp-stat__label">${s.label}</span></div>`)
    .join("");

  body.innerHTML = `<span class="mp-place">${lugar}</span><div class="mp-stats">${statsHtml}</div>${detalle}`;
}

function populateBarrioFilter(rows) {
  const select = document.getElementById("papa-filter-barrio");
  const barrios = [...new Set(rows.map((r) => r.barrio).filter(Boolean))].sort();
  for (const b of barrios) {
    const opt = document.createElement("option");
    opt.value = b;
    opt.textContent = b;
    select.appendChild(opt);
  }
}

function ambientesPermitidos() {
  const valor = document.getElementById("papa-filter-ambientes").value;
  return valor === "2-3" ? [2, 3] : [2];
}

function applyFilters(rows) {
  const ambientesOk = ambientesPermitidos();
  const barrio = document.getElementById("papa-filter-barrio").value;
  const tipos = busqueda.tipos || ["departamento", "ph"];

  return rows.filter((r) => {
    if (!ambientesOk.includes(r.ambientes)) return false;
    if (!tipos.includes(r.tipo)) return false;
    if (barrio && r.barrio !== barrio) return false;
    if (descartados.tiene(claveDe(r)) !== verDescartados) return false;
    return true;
  });
}

function sortRows(rows) {
  const sortKey = document.getElementById("papa-sort").value;
  const key = sortKey === "precio" ? "price_usd" : "brecha_neta_papa_usd";
  return [...rows].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    return av - bv;
  });
}

function tarjeta(r) {
  const esBuenPrecio = r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona <= 25;
  const esPrecioAlto = r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona >= 75;
  const badge = esBuenPrecio
    ? '<span class="badge-good">Buen precio</span>'
    : esPrecioAlto
      ? '<span class="badge-high">Precio alto</span>'
      : "";

  const brecha = r.brecha_neta_papa_usd;
  const brechaTexto =
    brecha === null || brecha === undefined
      ? "s/d"
      : brecha > 0
        ? `Hay que poner ${fmtNum(Math.abs(brecha))} USD más`
        : `Sobran ${fmtNum(Math.abs(brecha))} USD`;
  const brechaClase = brecha !== null && brecha !== undefined && brecha <= 0 ? "papa-listing__brecha--sobra" : "";

  const clave = encodeURIComponent(claveDe(r));
  const botonDescarte = verDescartados
    ? `<button type="button" class="papa-listing__descartar" data-clave="${clave}">Volver a mostrar</button>`
    : `<button type="button" class="papa-listing__descartar" data-clave="${clave}">No me gusta, ocultar</button>`;

  const foto = r.imagen_url
    ? `<a href="${r.url}" target="_blank" rel="noopener"><img class="papa-listing__foto" src="${fotoUrl(r.imagen_url, "chica")}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.remove()" /></a>`
    : "";

  return `
    <article class="papa-listing">
      ${foto}
      <div class="papa-listing__head">
        <span class="papa-listing__lugar">${r.barrio ?? "s/d"} · ${r.tipo ?? "s/d"} · ${r.ambientes ?? "s/d"} amb.</span>
        ${r.condicion === "pozo" ? '<span class="badge-new">A estrenar</span>' : ""}
      </div>
      <div class="papa-listing__precio">USD ${fmtNum(r.price_usd)}</div>
      <div class="papa-listing__datos">
        <span>${fmtNum(r.m2_cubiertos)} m²</span>
        <span>Descuento a pedir: ${fmtPct(r.pct_negociacion_estimado)}</span>
        ${badge}
      </div>
      <div class="papa-listing__brecha ${brechaClase}">${brechaTexto}</div>
      <a class="papa-listing__link" href="${r.url}" target="_blank" rel="noopener">Ver aviso completo</a>
      ${botonDescarte}
    </article>
  `;
}

function render() {
  const nDescartados = currentData.filter((r) => descartados.tiene(claveDe(r))).length;
  // Recuperado el último ocultado, no tiene sentido quedarse en una lista vacía.
  if (nDescartados === 0) verDescartados = false;
  const rows = sortRows(applyFilters(currentData));
  const contenedor = document.getElementById("papa-resultados");
  const vacio = document.getElementById("papa-vacio");

  const toggle = document.getElementById("papa-ver-descartados");
  toggle.hidden = nDescartados === 0 && !verDescartados;
  toggle.textContent = verDescartados ? "Volver a la búsqueda" : `Ver avisos ocultados (${nDescartados})`;

  if (rows.length === 0) {
    contenedor.innerHTML = "";
    vacio.hidden = false;
    return;
  }
  vacio.hidden = true;
  contenedor.innerHTML = rows.map(tarjeta).join("");
}

function setupControls() {
  ["papa-filter-ambientes", "papa-filter-barrio", "papa-sort"].forEach((id) => {
    document.getElementById(id).addEventListener("change", render);
  });

  document.getElementById("papa-ver-descartados").addEventListener("click", () => {
    verDescartados = !verDescartados;
    render();
    window.scrollTo({ top: 0 });
  });

  document.getElementById("papa-resultados").addEventListener("click", (e) => {
    const btn = e.target.closest(".papa-listing__descartar");
    if (!btn) return;
    const clave = decodeURIComponent(btn.dataset.clave);
    if (descartados.tiene(clave)) {
      descartados.quitar(clave);
      render();
      return;
    }
    descartados.agregar(clave);
    render();
    mostrarToastDeshacer("Aviso ocultado.", () => {
      descartados.quitar(clave);
      render();
    });
  });
}

setupControls();
loadData();
