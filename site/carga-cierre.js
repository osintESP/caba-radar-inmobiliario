// Carga de cierres (F6, PLAN-radar-inmobiliario.md sección 3.2 fuente A5 y
// sección 14 pregunta 13: "la pregunta más valiosa de todas"). El sitio es
// estático (GitHub Pages) y el repo es privado: sin backend ni secretos,
// el formulario arma un GitHub Issue pre-completado y lo abre en una
// pestaña nueva — quien lo carga lo manda con su propia cuenta de GitHub.
// Procesamiento hacia data/manual/cierres_terceros.csv: manual por ahora,
// ver scripts/import_cierres_from_issues.py.

const REPO = "osintESP/caba-radar-inmobiliario";

function campo(id) {
  return document.getElementById(id).value.trim();
}

function armarIssueUrl() {
  const barrio = campo("c-barrio");
  const direccion = campo("c-direccion");
  const tipo = campo("c-tipo");
  const ambientes = campo("c-ambientes");
  const m2 = campo("c-m2");
  const precioPublicado = campo("c-precio-publicado");
  const precioCierre = campo("c-precio-cierre");
  const fuente = campo("c-fuente");
  const confianza = document.getElementById("c-confianza").value;
  const fecha = new Date().toISOString().slice(0, 10);

  const titulo = `Cierre: ${barrio} · ${tipo}${ambientes ? ` ${ambientes} amb.` : ""}${m2 ? ` ${m2}m²` : ""} — USD ${precioCierre}`;
  const cuerpo = [
    `- **fecha**: ${fecha}`,
    `- **barrio**: ${barrio}`,
    `- **direccion_aprox**: ${direccion || "s/d"}`,
    `- **tipo**: ${tipo}`,
    `- **ambientes**: ${ambientes || "s/d"}`,
    `- **m2**: ${m2 || "s/d"}`,
    `- **precio_publicado_usd**: ${precioPublicado || "s/d"}`,
    `- **precio_cierre_usd**: ${precioCierre}`,
    `- **fuente**: ${fuente || "s/d"}`,
    `- **confianza**: ${confianza}`,
  ].join("\n");

  const params = new URLSearchParams({ title: titulo, body: cuerpo, labels: "cierre" });
  return `https://github.com/${REPO}/issues/new?${params.toString()}`;
}

document.getElementById("cierre-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const error = document.getElementById("cierre-error");
  const valido = campo("c-barrio") && campo("c-tipo") && campo("c-precio-cierre");
  if (!valido) {
    error.hidden = false;
    return;
  }
  error.hidden = true;
  window.open(armarIssueUrl(), "_blank", "noopener");
});
