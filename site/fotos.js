// Tamaño de foto según dónde se muestra. Los scrapers guardan la URL del
// listado tal cual (en ML suele ser la miniatura de 90×90, sufijo "-I"),
// pero ambas CDNs sirven la misma foto en otros tamaños cambiando la URL:
// - Mercado Libre: sufijo antes de la extensión, "-O" ≈ 500px, "-F" ≈ 1200px.
// - Zonaprop: tamaño en la ruta, ".../360x266/..." → ".../720x532/...".
// - Argenprop: sufijo "_u_small" (480px) / "_u_medium" (1024px).
function fotoUrl(url, tamano) {
  if (!url) return null;
  const grande = tamano === "grande";
  if (url.includes("mlstatic.com")) return url.replace(/-[A-Z]\.(jpe?g|webp|png)$/i, `-${grande ? "F" : "O"}.$1`);
  if (url.includes("zonapropcdn.com")) return url.replace(/\/\d+x\d+\//, grande ? "/720x532/" : "/360x266/");
  if (url.includes("argenprop.com")) return url.replace(/_u_(small|medium|large)\./, grande ? "_u_medium." : "_u_small.");
  return url;
}
