// Sin build step. Lista/ordena/filtra los avisos de latest.json (F1-F5).
// La ficha de propiedad y la vista de Mercado (F6) usan Chart.js por CDN
// (única dependencia externa, cargada como <script> en index.html) y dos
// JSON separados (price_history.json, market_trends.json) que solo se
// piden cuando hacen falta, para no inflar la carga inicial de la tabla.

const DATA_URL = "data/latest.json";
const HISTORY_URL = "data/price_history.json";
const MARKET_TRENDS_URL = "data/market_trends.json";
// Ninguno de estos puede acercarse al negro/blanco: --ink y --bg cambian
// de rol entre modo claro/oscuro y una línea de esos colores se vuelve
// invisible contra el fondo en alguno de los dos temas.
const MERCADO_COLORES = ["#cc0000", "#0a7d34", "#0077cc", "#7a5cff", "#e08a00", "#d6336c"];

const fmtNum = (n) => (n === null || n === undefined ? "s/d" : Math.round(n).toLocaleString("es-AR"));
const fmtSigned = (n) => {
  if (n === null || n === undefined) return "s/d";
  const rounded = Math.round(n);
  return `${rounded > 0 ? "+" : ""}${rounded.toLocaleString("es-AR")}`;
};
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("es-AR") : "s/d");
const fmtPct = (n) => (n === null || n === undefined ? "s/d" : `${Math.round(n * 100)}%`);

let currentData = [];
// Brecha neta ("cuánto tengo que poner") es la métrica que el plan pide
// como orden por defecto (sección 11), no el USD/m² de lista.
let sortState = { key: "brecha_neta_usd", dir: "asc" };
let updateTableFade = () => {};
let rowsByClave = {};
let priceHistoryCache = null;
let marketTrendsCache = null;
let fichaChart = null;
let mercadoChart = null;
const descartados = crearDescartados("radar.descartados");
let vista = "tabla";

async function fetchJsonSafe(url) {
  try {
    const resp = await fetch(url);
    return resp.ok ? await resp.json() : {};
  } catch {
    return {};
  }
}

async function loadData() {
  const banner = document.getElementById("status-banner");
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    currentData = data.avisos || [];
    rowsByClave = Object.fromEntries(currentData.map((r) => [`${r.portal}:${r.portal_id}`, r]));
    const desaparecidos =
      data.n_desaparecidos_hoy !== undefined
        ? ` · ${data.n_desaparecidos_hoy} avisos desaparecieron hoy (posible reserva/venta)`
        : "";
    const recortes =
      data.n_recortes_mes !== undefined ? ` · ${data.n_recortes_mes} recortes de precio en los últimos 30 días` : "";
    banner.textContent =
      `Generado: ${fmtDate(data.generated_at)} · ` +
      `Dólar MEP: ${data.fx_rate ? data.fx_rate.toLocaleString("es-AR") : "s/d"} (${data.fx_source || "s/d"}) · ` +
      `${data.n_avisos} avisos mostrados de ${data.n_avisos_total} obtenidos${desaparecidos}${recortes}`;
    populateFilters(currentData);
    renderMiPropiedad(data.mi_propiedad);
    render();
    renderMercadoStats(currentData);
    renderMercadoChart();
  } catch (err) {
    banner.textContent = `Error cargando ${DATA_URL}: ${err.message}. ¿Corrió ya el workflow diario al menos una vez?`;
  }
}

function renderMiPropiedad(mp) {
  const section = document.getElementById("mi-propiedad");
  const body = document.getElementById("mi-propiedad-body");
  if (!mp) {
    section.hidden = true;
    return;
  }
  section.hidden = false;

  const lugar = `${mp.barrio} · ${mp.tipo} · ${mp.ambientes} amb. · ${mp.m2_cubiertos} m² cub.`;

  const stats = [
    { value: `USD ${fmtNum(mp.precio_venta_max_usd)}`, label: "Precio" },
    { value: fmtNum(mp.usd_m2_declarado), label: "USD/m² declarado" },
  ];

  let detalle;
  if (mp.veredicto === "insuficiente") {
    detalle =
      `<p class="mi-propiedad__insuficiente">Todavía no hay suficientes comparables para auditar este valor ` +
      `(${mp.n_comparables} de 30 necesarios, contando barrio + adyacentes). ` +
      `Se completa solo a medida que se acumulan más datos.</p>`;
  } else {
    stats.push(
      { value: fmtNum(mp.usd_m2_mediana), label: "Mediana de la zona" },
      { value: mp.percentil_sujeto === null ? "—" : `Percentil ${Math.round(mp.percentil_sujeto)}`, label: "Tu posición" },
    );
    detalle =
      `<p class="mp-detail">Comparado contra <strong>${mp.n_comparables}</strong> avisos reales ` +
      `(${mp.scope === "barrio" ? "mismo barrio" : "barrio + adyacentes"}): rango ` +
      `${fmtNum(mp.usd_m2_p25)}–${fmtNum(mp.usd_m2_p75)} USD/m².</p>`;
  }

  const statsHtml = stats
    .map((s) => `<div class="mp-stat"><span class="mp-stat__value">${s.value}</span><span class="mp-stat__label">${s.label}</span></div>`)
    .join("");

  body.innerHTML = `<span class="mp-place">${lugar}</span><div class="mp-stats">${statsHtml}</div>${detalle}`;
}

function renderMercadoStats(rows) {
  const el = document.getElementById("mercado-stats");
  const porBarrio = {};
  for (const r of rows) {
    if (!r.barrio) continue;
    porBarrio[r.barrio] = (porBarrio[r.barrio] || 0) + 1;
  }
  el.innerHTML = Object.keys(porBarrio)
    .sort()
    .map(
      (barrio) =>
        `<div class="mp-stat"><span class="mp-stat__value">${porBarrio[barrio]}</span><span class="mp-stat__label">${barrio}</span></div>`,
    )
    .join("");
}

async function renderMercadoChart() {
  if (!marketTrendsCache) marketTrendsCache = await fetchJsonSafe(MARKET_TRENDS_URL);
  const barriosActivos = new Set(currentData.map((r) => r.barrio).filter(Boolean));
  const barrios = Object.keys(marketTrendsCache)
    .filter((b) => barriosActivos.has(b))
    .sort();
  const canvas = document.getElementById("mercado-chart");
  if (mercadoChart) {
    mercadoChart.destroy();
    mercadoChart = null;
  }
  if (barrios.length === 0) return;

  const fechas = [...new Set(barrios.flatMap((b) => marketTrendsCache[b].map((p) => p.fecha)))].sort();
  const datasets = barrios.map((barrio, i) => {
    const porFecha = new Map(marketTrendsCache[barrio].map((p) => [p.fecha, p.mediana_usd_m2]));
    return {
      label: barrio,
      data: fechas.map((f) => porFecha.get(f) ?? null),
      borderColor: MERCADO_COLORES[i % MERCADO_COLORES.length],
      spanGaps: true,
      tension: 0.15,
    };
  });

  mercadoChart = new Chart(canvas, {
    type: "line",
    data: { labels: fechas, datasets },
    options: { plugins: { legend: { position: "bottom" } }, scales: { y: { title: { display: true, text: "USD/m² (mediana)" } } } },
  });
}

async function openFicha(clave) {
  const modal = document.getElementById("ficha-modal");
  const title = document.getElementById("ficha-title");
  const foto = document.getElementById("ficha-foto");
  const datos = document.getElementById("ficha-datos");
  const acciones = document.getElementById("ficha-acciones");
  const canvas = document.getElementById("ficha-canvas");
  const empty = document.getElementById("ficha-empty");
  const descuento = document.getElementById("ficha-descuento");
  const r = rowsByClave[clave];
  if (!r) return;

  title.textContent = lugarDe(r);
  document.getElementById("ficha-titulo-aviso").textContent = r.titulo || "";
  foto.hidden = !r.imagen_url;
  if (r.imagen_url) foto.src = fotoUrl(r.imagen_url, "grande");

  // Todo lo que no entra en la tabla compacta vive acá.
  const filas = [
    ["Precio", `USD ${fmtNum(r.price_usd)}`],
    ["Brecha neta", `${fmtSigned(r.brecha_neta_usd)} USD`],
    ["USD/m²", fmtNum(r.usd_m2)],
    ["Mediana zona", r.veredicto_zona === "ok" ? `${fmtNum(r.usd_m2_mediana_zona)} USD/m²` : "s/d"],
    ["Percentil zona", r.veredicto_zona === "ok" ? `${Math.round(r.percentil_zona)} (de ${r.n_comparables_zona} comparables)` : "s/d"],
    ["Desc. a pedir", fmtPct(r.pct_negociacion_estimado)],
    ["m² cubiertos", fmtNum(r.m2_cubiertos)],
    ["Ambientes", r.ambientes ?? "s/d"],
    ["Baños", r.banos ?? "s/d"],
    ["Cochera", r.cocheras === null || r.cocheras === undefined ? "s/d" : r.cocheras > 0 ? `Sí (${r.cocheras})` : "No"],
    ["Condición", r.condicion ?? "s/d"],
    ["Antigüedad", r.antiguedad === null || r.antiguedad === undefined ? "s/d" : `${r.antiguedad} años`],
    ["Piso", r.piso ?? "s/d"],
    ["Ascensor", r.ascensor === null || r.ascensor === undefined ? "s/d" : r.ascensor ? "Sí" : "No"],
    ["Expensas", r.expensas_ars ? `ARS ${fmtNum(r.expensas_ars)}` : "s/d"],
    ["Portal", `${r.portal ?? "s/d"}${(r.n_duplicados ?? 1) > 1 ? ` · publicado ×${r.n_duplicados}` : ""}`],
    ["Capturado", fmtDate(r.captured_at)],
  ];
  if (r.tags) filas.push(["Tags", r.tags.split(",").join(", ")]);
  datos.innerHTML = filas.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("");

  acciones.innerHTML =
    `<a class="btn btn--primary" href="${esc(r.url)}" target="_blank" rel="noopener">Ver aviso completo</a>` +
    botonDescarte(clave, "btn");

  modal.hidden = false;

  if (r.pct_negociacion_estimado !== null && r.pct_negociacion_estimado !== undefined) {
    const ubicacion =
      r.veredicto_zona === "ok" && r.percentil_zona !== null
        ? `está en el percentil ${Math.round(r.percentil_zona)} de sus ${r.n_comparables_zona} comparables de zona`
        : "todavía no tiene comparables suficientes en su zona";
    descuento.textContent = `Descuento a pedir en la negociación: ${fmtPct(r.pct_negociacion_estimado)} — ${ubicacion}.`;
    descuento.hidden = false;
  } else {
    descuento.hidden = true;
  }

  if (fichaChart) {
    fichaChart.destroy();
    fichaChart = null;
  }
  if (!priceHistoryCache) priceHistoryCache = await fetchJsonSafe(HISTORY_URL);
  const historial = priceHistoryCache[clave] || [];

  if (historial.length < 2) {
    canvas.hidden = true;
    empty.hidden = false;
    return;
  }
  canvas.hidden = false;
  empty.hidden = true;
  fichaChart = new Chart(canvas, {
    type: "line",
    data: {
      labels: historial.map((p) => p.fecha),
      datasets: [{ label: "USD", data: historial.map((p) => p.price_usd), borderColor: "#cc0000", tension: 0.15 }],
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: false } } },
  });
}

function closeFicha() {
  document.getElementById("ficha-modal").hidden = true;
}

// Un solo listener para tabla, galería y ficha: descartar, abrir ficha
// (botón, foto o click en cualquier parte de la fila/tarjeta que no sea un
// link o botón propio).
function setupAcciones() {
  const onClick = (e) => {
    const descartar = e.target.closest(".descartar-btn");
    if (descartar) {
      toggleDescarte(decodeURIComponent(descartar.dataset.clave));
      return;
    }
    if (e.target.closest("a, button:not(.ficha-link)")) return;
    const item = e.target.closest("[data-clave]");
    if (item) openFicha(decodeURIComponent(item.dataset.clave));
  };
  ["listings-body", "vista-galeria", "ficha-acciones"].forEach((id) => document.getElementById(id).addEventListener("click", onClick));
  document.querySelectorAll('[data-close="ficha"]').forEach((el) => el.addEventListener("click", closeFicha));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeFicha();
  });
}

function toggleDescarte(clave) {
  if (descartados.tiene(clave)) {
    descartados.quitar(clave);
    render();
    if (!document.getElementById("ficha-modal").hidden) openFicha(clave);
    return;
  }
  descartados.agregar(clave);
  closeFicha();
  render();
  mostrarToastDeshacer("Aviso descartado.", () => {
    descartados.quitar(clave);
    render();
  });
}

function populateFilters(rows) {
  const portales = [...new Set(rows.map((r) => r.portal).filter(Boolean))].sort();
  const barrios = [...new Set(rows.map((r) => r.barrio).filter(Boolean))].sort();
  const tipos = [...new Set(rows.map((r) => r.tipo).filter(Boolean))].sort();
  fillSelect("filter-portal", portales);
  fillSelect("filter-barrio", barrios);
  fillSelect("filter-tipo", tipos);
}

function fillSelect(id, values) {
  const select = document.getElementById(id);
  for (const v of values) {
    const opt = document.createElement("option");
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  }
}

function numFilterValue(id) {
  const raw = document.getElementById(id).value;
  return raw === "" ? null : Number(raw);
}

function applyFilters(rows) {
  const portal = document.getElementById("filter-portal").value;
  const barrio = document.getElementById("filter-barrio").value;
  const tipo = document.getElementById("filter-tipo").value;
  const condicion = document.getElementById("filter-condicion").value;
  const ambientesMin = numFilterValue("filter-ambientes-min");
  const ambientesMax = numFilterValue("filter-ambientes-max");
  const banosMin = numFilterValue("filter-banos-min");
  const precioMin = numFilterValue("filter-precio-min");
  const precioMax = numFilterValue("filter-precio-max");
  const soloConCochera = document.getElementById("filter-cochera").checked;
  const soloNuevos = document.getElementById("filter-nuevo").checked;
  const tagsQuery = document.getElementById("filter-tags").value.trim().toLowerCase();
  const verDescartados = document.getElementById("filter-descartados").checked;

  return rows.filter((r) => {
    if (portal && r.portal !== portal) return false;
    if (barrio && r.barrio !== barrio) return false;
    if (tipo && r.tipo !== tipo) return false;
    if (condicion && r.condicion !== condicion) return false;
    if (ambientesMin !== null && !(r.ambientes >= ambientesMin)) return false;
    if (ambientesMax !== null && !(r.ambientes <= ambientesMax)) return false;
    if (banosMin !== null && !(r.banos >= banosMin)) return false;
    if (precioMin !== null && !(r.price_usd >= precioMin)) return false;
    if (precioMax !== null && !(r.price_usd <= precioMax)) return false;
    if (soloConCochera && !(r.cocheras > 0)) return false;
    if (soloNuevos && !r.es_nuevo) return false;
    if (tagsQuery && !(r.tags || "").toLowerCase().includes(tagsQuery)) return false;
    if (!verDescartados && descartados.tiene(`${r.portal}:${r.portal_id}`)) return false;
    return true;
  });
}

function sortRows(rows) {
  const { key, dir } = sortState;
  const mult = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * mult;
    return String(av).localeCompare(String(bv)) * mult;
  });
}

const TIPO_CORTO = { departamento: "Depto", ph: "PH", casa: "Casa" };

function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function lugarDe(r) {
  const tipo = TIPO_CORTO[r.tipo] || r.tipo || "s/d";
  return `${r.barrio ?? "s/d"} · ${tipo} · ${r.ambientes ?? "s/d"} amb.`;
}

// Datos secundarios en una sola línea, solo los que el aviso tiene.
function resumenDe(r) {
  const partes = [];
  if (r.m2_cubiertos) partes.push(`${fmtNum(r.m2_cubiertos)} m²`);
  if (r.banos) partes.push(`${r.banos} ${r.banos === 1 ? "baño" : "baños"}`);
  if (r.cocheras > 0) partes.push("cochera");
  if (r.antiguedad !== null && r.antiguedad !== undefined) partes.push(r.antiguedad === 0 ? "a estrenar" : `${r.antiguedad} años`);
  return partes.join(" · ");
}

function badgesDe(r) {
  const b = [];
  if (r.es_nuevo) b.push('<span class="badge-new">Nuevo</span>');
  if (r.condicion === "pozo") b.push('<span class="badge-new">Pozo</span>');
  if (esBuenPrecio(r)) b.push('<span class="badge-good">Buen precio</span>');
  if (esPrecioAlto(r)) b.push('<span class="badge-high">Precio alto</span>');
  if ((r.n_duplicados ?? 1) > 1) b.push(`<span class="badge-dup" title="Publicado por ${r.n_duplicados} avisos/portales">×${r.n_duplicados}</span>`);
  return b.join(" ");
}

const esBuenPrecio = (r) => r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona <= 25;
const esPrecioAlto = (r) => r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona >= 75;

function fotoDe(r, clase) {
  return r.imagen_url
    ? `<img class="${clase}" src="${esc(fotoUrl(r.imagen_url, "chica"))}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'${clase} foto--vacia',textContent:'Sin foto'}))" />`
    : `<div class="${clase} foto--vacia">Sin foto</div>`;
}

function botonDescarte(clave, claseExtra = "") {
  const c = encodeURIComponent(clave);
  return descartados.tiene(clave)
    ? `<button type="button" class="descartar-btn ${claseExtra}" data-clave="${c}" title="Volver a mostrar este aviso">Recuperar</button>`
    : `<button type="button" class="descartar-btn ${claseExtra}" data-clave="${c}" title="No me gusta: ocultar este aviso" aria-label="No me gusta, ocultar">${claseExtra ? "No me gusta" : "✕"}</button>`;
}

function filaTabla(r, clave) {
  const zona =
    r.veredicto_zona === "ok"
      ? `<span class="cell-main">P${Math.round(r.percentil_zona)}</span><span class="cell-sub">med. ${fmtNum(r.usd_m2_mediana_zona)}/m²</span>`
      : '<span class="cell-sub">s/d</span>';
  return `
    <td class="col-foto">${fotoDe(r, "thumb")}</td>
    <td class="col-propiedad">
      <span class="cell-main">${esc(lugarDe(r))}</span>
      <span class="cell-sub">${esc(resumenDe(r))}</span>
      <span class="cell-badges">${badgesDe(r)}</span>
    </td>
    <td><span class="cell-main">${fmtNum(r.price_usd)}</span><span class="cell-sub">${r.usd_m2 ? `${fmtNum(r.usd_m2)}/m²` : ""}</span></td>
    <td><span class="cell-main">${fmtSigned(r.brecha_neta_usd)}</span><span class="cell-sub">desc. ${fmtPct(r.pct_negociacion_estimado)}</span></td>
    <td>${zona}</td>
    <td class="col-acciones">
      <a href="${esc(r.url)}" target="_blank" rel="noopener">Ver</a>
      <button type="button" class="ficha-link">Ficha</button>
      ${botonDescarte(clave)}
    </td>
  `;
}

function tarjetaGaleria(r, clave) {
  const brecha = r.brecha_neta_usd;
  const brechaTexto =
    brecha === null || brecha === undefined
      ? ""
      : brecha > 0
        ? `Hay que poner ${fmtNum(brecha)} USD`
        : `Sobran ${fmtNum(Math.abs(brecha))} USD`;
  return `
    <article class="gcard${descartados.tiene(clave) ? " is-descartado" : ""}" data-clave="${encodeURIComponent(clave)}">
      <div class="gcard__foto">
        ${fotoDe(r, "gcard__img")}
        <span class="gcard__badges">${badgesDe(r)}</span>
      </div>
      <div class="gcard__body">
        <div class="gcard__precio">USD ${fmtNum(r.price_usd)}</div>
        <div class="gcard__lugar">${esc(lugarDe(r))}</div>
        <div class="gcard__resumen">${esc(resumenDe(r))}</div>
        <div class="gcard__brecha${brecha !== null && brecha !== undefined && brecha <= 0 ? " is-sobra" : ""}">${brechaTexto}</div>
        <div class="gcard__acciones">
          <a href="${esc(r.url)}" target="_blank" rel="noopener">Ver aviso</a>
          ${botonDescarte(clave)}
        </div>
      </div>
    </article>
  `;
}

// Galería: se pinta de a tandas para no crear 1.000+ tarjetas de una.
const GALERIA_TANDA = 60;
let galeriaRows = [];
let galeriaMostradas = 0;
let galeriaObserver = null;

function pintarTandaGaleria() {
  const cont = document.getElementById("vista-galeria");
  const hasta = Math.min(galeriaMostradas + GALERIA_TANDA, galeriaRows.length);
  const html = galeriaRows
    .slice(galeriaMostradas, hasta)
    .map((r) => tarjetaGaleria(r, `${r.portal}:${r.portal_id}`))
    .join("");
  document.getElementById("galeria-sentinel")?.remove();
  cont.insertAdjacentHTML("beforeend", html);
  galeriaMostradas = hasta;
  if (galeriaMostradas < galeriaRows.length) {
    cont.insertAdjacentHTML("beforeend", '<div id="galeria-sentinel" class="gallery__sentinel"></div>');
    galeriaObserver.observe(document.getElementById("galeria-sentinel"));
  }
}

function render() {
  const rows = sortRows(applyFilters(currentData));
  const nDescartados = currentData.filter((r) => descartados.tiene(`${r.portal}:${r.portal_id}`)).length;
  document.getElementById("filter-descartados-label").textContent = `Ver descartados (${nDescartados})`;
  document.getElementById("results-count").textContent = `${rows.length.toLocaleString("es-AR")} avisos`;
  const sortValue = `${sortState.key}:${sortState.dir}`;
  const sortSelect = document.getElementById("sort-select");
  sortSelect.value = [...sortSelect.options].some((o) => o.value === sortValue) ? sortValue : "";

  const tbody = document.getElementById("listings-body");
  const galeria = document.getElementById("vista-galeria");
  tbody.innerHTML = "";
  galeria.innerHTML = "";

  if (vista === "galeria") {
    galeriaRows = rows;
    galeriaMostradas = 0;
    if (rows.length === 0) galeria.innerHTML = '<p class="gallery__empty">Ningún aviso coincide con el filtro.</p>';
    else pintarTandaGaleria();
    return;
  }

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6">Ningún aviso coincide con el filtro.</td></tr>';
    return;
  }

  const frag = document.createDocumentFragment();
  for (const r of rows) {
    const tr = document.createElement("tr");
    const clave = `${r.portal}:${r.portal_id}`;
    tr.dataset.clave = encodeURIComponent(clave);
    if (r.es_nuevo) tr.classList.add("is-new");
    if (esBuenPrecio(r)) tr.classList.add("is-good-value");
    if (esPrecioAlto(r)) tr.classList.add("is-high-value");
    if (descartados.tiene(clave)) tr.classList.add("is-descartado");
    tr.innerHTML = filaTabla(r, clave);
    frag.appendChild(tr);
  }
  tbody.appendChild(frag);
  updateTableFade();
}

function setVista(nueva) {
  vista = nueva;
  try {
    localStorage.setItem("radar.vista", nueva);
  } catch {}
  document.getElementById("vista-tabla").hidden = nueva !== "tabla";
  document.getElementById("vista-galeria").hidden = nueva !== "galeria";
  document.querySelectorAll(".view-toggle button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.vista === nueva)));
  if (currentData.length) render();
}

function setupVistaYOrden() {
  galeriaObserver = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        galeriaObserver.disconnect();
        pintarTandaGaleria();
      }
    },
    { rootMargin: "600px" },
  );
  document.querySelectorAll(".view-toggle button").forEach((b) => b.addEventListener("click", () => setVista(b.dataset.vista)));
  document.getElementById("sort-select").addEventListener("change", (e) => {
    if (!e.target.value) return;
    const [key, dir] = e.target.value.split(":");
    sortState = { key, dir };
    render();
  });
  let inicial = null;
  try {
    inicial = localStorage.getItem("radar.vista");
  } catch {}
  if (window.innerWidth < 700) document.getElementById("filters-wrap").open = false;
  // En el celular la tabla no entra cómoda: galería por defecto.
  setVista(inicial || (window.innerWidth < 700 ? "galeria" : "tabla"));
}

function setupTableFade() {
  const scroll = document.querySelector(".table-scroll");
  const fade = document.getElementById("table-fade");
  const update = () => {
    const atEnd = scroll.scrollLeft + scroll.clientWidth >= scroll.scrollWidth - 2;
    fade.classList.toggle("table-card__fade--hidden", atEnd || scroll.scrollWidth <= scroll.clientWidth);
  };
  scroll.addEventListener("scroll", update);
  window.addEventListener("resize", update);
  update();
  return update;
}

function setupSortableHeaders() {
  document.querySelectorAll("#listings-table th[data-key]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      if (sortState.key === key) {
        sortState.dir = sortState.dir === "asc" ? "desc" : "asc";
      } else {
        sortState = { key, dir: key === "es_nuevo" || key === "m2_cubiertos" ? "desc" : "asc" };
      }
      render();
    });
  });
}

function setupFilters() {
  const changeIds = ["filter-portal", "filter-barrio", "filter-tipo", "filter-condicion", "filter-cochera", "filter-nuevo", "filter-descartados"];
  const inputIds = ["filter-ambientes-min", "filter-ambientes-max", "filter-banos-min", "filter-precio-min", "filter-precio-max", "filter-tags"];
  changeIds.forEach((id) => document.getElementById(id).addEventListener("change", render));
  inputIds.forEach((id) => document.getElementById(id).addEventListener("input", render));
}

setupSortableHeaders();
setupFilters();
setupAcciones();
updateTableFade = setupTableFade();
setupVistaYOrden();
loadData();
