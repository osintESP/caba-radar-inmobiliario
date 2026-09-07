// Sin build step, sin dependencias. F1: solo lista y ordena/filtra los
// avisos de latest.json. Sin valuación ni brecha neta todavía (F4/F5).

const DATA_URL = "data/latest.json";

const fmtNum = (n) => (n === null || n === undefined ? "s/d" : Math.round(n).toLocaleString("es-AR"));
const fmtBool = (b) => (b === null || b === undefined ? "s/d" : b ? "Sí" : "No");
const fmtDate = (iso) => (iso ? new Date(iso).toLocaleString("es-AR") : "s/d");

let currentData = [];
let sortState = { key: "usd_m2", dir: "asc" };

async function loadData() {
  const banner = document.getElementById("status-banner");
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    currentData = data.avisos || [];
    banner.textContent =
      `Generado: ${fmtDate(data.generated_at)} · ` +
      `Dólar MEP: ${data.fx_rate ? data.fx_rate.toLocaleString("es-AR") : "s/d"} (${data.fx_source || "s/d"}) · ` +
      `${data.n_avisos} avisos mostrados de ${data.n_avisos_total} obtenidos`;
    populateFilters(currentData);
    renderMiPropiedad(data.mi_propiedad);
    render();
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

  const encabezado =
    `${mp.barrio} · ${mp.tipo} · ${mp.ambientes} amb. · ${mp.m2_cubiertos} m² cub. · ` +
    `USD ${fmtNum(mp.precio_venta_max_usd)} (${fmtNum(mp.usd_m2_declarado)} USD/m²)`;

  let veredicto;
  if (mp.veredicto === "insuficiente") {
    veredicto =
      `<p class="mi-propiedad__insuficiente">Todavía no hay suficientes comparables para auditar este valor ` +
      `(${mp.n_comparables} de 30 necesarios, contando barrio + adyacentes). ` +
      `Se completa solo a medida que se acumulan más datos.</p>`;
  } else {
    const posicion =
      mp.percentil_sujeto === null
        ? ""
        : ` — está en el percentil ${Math.round(mp.percentil_sujeto)} de esos comparables`;
    veredicto =
      `<p>Comparado contra <strong>${mp.n_comparables}</strong> avisos reales (${mp.scope === "barrio" ? "mismo barrio" : "barrio + adyacentes"}): ` +
      `mediana <strong>${fmtNum(mp.usd_m2_mediana)} USD/m²</strong> (rango ${fmtNum(mp.usd_m2_p25)}–${fmtNum(mp.usd_m2_p75)})${posicion}.</p>`;
  }

  body.innerHTML = `<p>${encabezado}</p>${veredicto}`;
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
    tbody.innerHTML = '<tr><td colspan="17">Ningún aviso coincide con el filtro.</td></tr>';
    return;
  }

  for (const r of rows) {
    const tr = document.createElement("tr");
    const dup = r.n_duplicados ?? 1;
    tr.innerHTML = `
      <td>${r.portal ?? "s/d"}</td>
      <td>${r.barrio ?? "s/d"}</td>
      <td>${r.tipo ?? "s/d"}</td>
      <td>${r.condicion ?? "s/d"}</td>
      <td>${r.ambientes ?? "s/d"}</td>
      <td>${r.banos ?? "s/d"}</td>
      <td>${r.cocheras ?? "s/d"}</td>
      <td>${fmtNum(r.m2_cubiertos)}</td>
      <td>${fmtNum(r.price_usd)}</td>
      <td>${fmtNum(r.usd_m2)}</td>
      <td>${fmtNum(r.expensas_ars)}</td>
      <td>${r.antiguedad ?? "s/d"}</td>
      <td>${r.piso ?? "s/d"}</td>
      <td>${fmtBool(r.ascensor)}</td>
      <td>${dup > 1 ? `×${dup}` : "—"}</td>
      <td>${fmtDate(r.captured_at)}</td>
      <td><a href="${r.url}" target="_blank" rel="noopener">Ver</a></td>
    `;
    tbody.appendChild(tr);
  }
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
  const changeIds = ["filter-portal", "filter-barrio", "filter-tipo", "filter-condicion", "filter-cochera"];
  const inputIds = ["filter-ambientes-min", "filter-ambientes-max", "filter-banos-min", "filter-precio-min", "filter-precio-max"];
  changeIds.forEach((id) => document.getElementById(id).addEventListener("change", render));
  inputIds.forEach((id) => document.getElementById(id).addEventListener("input", render));
}

setupSortableHeaders();
setupFilters();
loadData();
