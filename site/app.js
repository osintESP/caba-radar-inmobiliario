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
  const canvas = document.getElementById("ficha-canvas");
  const empty = document.getElementById("ficha-empty");
  const r = rowsByClave[clave];

  title.textContent = r ? r.titulo || `${r.barrio} · ${r.tipo} · ${r.ambientes ?? "s/d"} amb.` : "Ficha de propiedad";
  modal.hidden = false;

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

function setupFichaModal() {
  document.getElementById("listings-body").addEventListener("click", (e) => {
    const btn = e.target.closest(".ficha-link");
    if (!btn) return;
    openFicha(decodeURIComponent(btn.dataset.clave));
  });
  document.querySelectorAll('[data-close="ficha"]').forEach((el) => el.addEventListener("click", closeFicha));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeFicha();
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

function render() {
  const rows = sortRows(applyFilters(currentData));
  const tbody = document.getElementById("listings-body");
  tbody.innerHTML = "";

  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="19">Ningún aviso coincide con el filtro.</td></tr>';
    return;
  }

  rowsByClave = {};
  for (const r of rows) {
    const tr = document.createElement("tr");
    const dup = r.n_duplicados ?? 1;
    const clave = `${r.portal}:${r.portal_id}`;
    rowsByClave[clave] = r;
    const esBuenPrecio = r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona <= 25;
    const esPrecioAlto = r.veredicto_zona === "ok" && r.percentil_zona !== null && r.percentil_zona >= 75;
    if (r.es_nuevo) tr.classList.add("is-new");
    if (esBuenPrecio) tr.classList.add("is-good-value");
    if (esPrecioAlto) tr.classList.add("is-high-value");
    tr.innerHTML = `
      <td>${r.es_nuevo ? '<span class="badge-new">Nuevo</span>' : "—"}</td>
      <td>${r.barrio ?? "s/d"}</td>
      <td>${r.tipo ?? "s/d"}</td>
      <td>${fmtNum(r.price_usd)}</td>
      <td>${fmtSigned(r.brecha_neta_usd)}</td>
      <td>${fmtNum(r.usd_m2)}</td>
      <td>${fmtNum(r.usd_m2_mediana_zona)}</td>
      <td title="${r.veredicto_zona === "ok" ? `Sobre ${r.n_comparables_zona} comparables reales` : "Todavía no hay suficientes comparables en la zona"}">${
        r.veredicto_zona === "ok"
          ? `${Math.round(r.percentil_zona)}${esBuenPrecio ? ' <span class="badge-good">Buen precio</span>' : ""}${esPrecioAlto ? ' <span class="badge-high">Precio alto</span>' : ""}`
          : "s/d"
      }</td>
      <td>${fmtNum(r.m2_cubiertos)}</td>
      <td>${r.ambientes ?? "s/d"}</td>
      <td>${r.condicion ?? "s/d"}</td>
      <td>${r.banos ?? "s/d"}</td>
      <td>${r.cocheras ?? "s/d"}</td>
      <td>${fmtNum(r.expensas_ars)}</td>
      <td>${r.antiguedad ?? "s/d"}</td>
      <td>${r.portal ?? "s/d"}</td>
      <td>${dup > 1 ? `×${dup}` : "—"}</td>
      <td>${fmtDate(r.captured_at)}</td>
      <td>
        <a href="${r.url}" target="_blank" rel="noopener">Ver</a>
        <button type="button" class="ficha-link" data-clave="${encodeURIComponent(clave)}">Ficha</button>
      </td>
    `;
    tbody.appendChild(tr);
  }
  updateTableFade();
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
        sortState = { key, dir: "asc" };
      }
      render();
    });
  });
}

function setupFilters() {
  const changeIds = ["filter-portal", "filter-barrio", "filter-tipo", "filter-condicion", "filter-cochera", "filter-nuevo"];
  const inputIds = ["filter-ambientes-min", "filter-ambientes-max", "filter-banos-min", "filter-precio-min", "filter-precio-max", "filter-tags"];
  changeIds.forEach((id) => document.getElementById(id).addEventListener("change", render));
  inputIds.forEach((id) => document.getElementById(id).addEventListener("input", render));
}

setupSortableHeaders();
setupFilters();
setupFichaModal();
updateTableFade = setupTableFade();
loadData();
