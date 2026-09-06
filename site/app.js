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
    render();
  } catch (err) {
    banner.textContent = `Error cargando ${DATA_URL}: ${err.message}. ¿Corrió ya el workflow diario al menos una vez?`;
  }
}

function populateFilters(rows) {
  const barrios = [...new Set(rows.map((r) => r.barrio).filter(Boolean))].sort();
  const tipos = [...new Set(rows.map((r) => r.tipo).filter(Boolean))].sort();
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

function applyFilters(rows) {
  const barrio = document.getElementById("filter-barrio").value;
  const tipo = document.getElementById("filter-tipo").value;
  return rows.filter((r) => (!barrio || r.barrio === barrio) && (!tipo || r.tipo === tipo));
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
    tbody.innerHTML = '<tr><td colspan="13">Ningún aviso coincide con el filtro.</td></tr>';
    return;
  }

  for (const r of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.barrio ?? "s/d"}</td>
      <td>${r.tipo ?? "s/d"}</td>
      <td>${r.condicion ?? "s/d"}</td>
      <td>${r.ambientes ?? "s/d"}</td>
      <td>${fmtNum(r.m2_cubiertos)}</td>
      <td>${fmtNum(r.price_usd)}</td>
      <td>${fmtNum(r.usd_m2)}</td>
      <td>${fmtNum(r.expensas_ars)}</td>
      <td>${r.antiguedad ?? "s/d"}</td>
      <td>${r.piso ?? "s/d"}</td>
      <td>${fmtBool(r.ascensor)}</td>
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
  document.getElementById("filter-barrio").addEventListener("change", render);
  document.getElementById("filter-tipo").addEventListener("change", render);
}

setupSortableHeaders();
setupFilters();
loadData();
