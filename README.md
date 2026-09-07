# Radar Inmobiliario

Monitoreo diario de avisos de Mercado Libre en barrios del oeste de CABA
(Vélez Sarsfield, Floresta, Monte Castro y anillo), para evaluar la venta de
una propiedad y candidatas de compra. Ver `PLAN-radar-inmobiliario.md` para
el diseño completo del proyecto (incluye un addendum al final documentando
el cambio descripto abajo).

**Esta implementación cubre F0+F1 (Mercado Libre + sitio estático) y F2
(Zonaprop/Argenprop)**. Todavía no hace dedupe (F3) ni valuación (F4).

## Nota importante: la ingesta es por scraping, no por la API de ML

El plan original preveía usar la API oficial de Mercado Libre. Confirmado en
vivo (septiembre 2026): `/sites/{site}/search` e `/items/{id}` devuelven 403
para apps no certificadas, **con o sin token válido** — no es un problema de
permisos mal tildados, es una restricción de plataforma (documentada en
varios reportes públicos de otros desarrolladores con el mismo síntoma). La
ingesta real (`ingest/meli_scraper.py`) scrapea la web pública de
`inmuebles.mercadolibre.com.ar`, que sí es accesible con un User-Agent
normal — mismo criterio que el plan ya aceptaba para Zonaprop/Argenprop.

El código OAuth (`ingest/meli_auth.py`, `meli_auth_bootstrap.py`,
`meli_client.py`, `meli_explore.py`) queda en el repo pero **sin uso**: si en
algún momento conseguís certificación de partner con Mercado Libre
(`vis-support@mercadolibre.com`), puede retomarse. Los secrets
`ML_CLIENT_ID`/`ML_CLIENT_SECRET`/`ML_REFRESH_TOKEN`/`GH_SECRETS_PAT` ya
cargados en el repo no se usan hoy — no hace falta borrarlos.

### Cómo funciona el scraping (importante para entender el ritmo de datos)

Dos niveles de costo muy distintos:
- **Página de listado** (barata, 1 request cada 48 avisos): da precio,
  vendedor, URL. Se recorre completa todos los días para cada barrio ×
  tipología.
- **Página de detalle de cada aviso** (cara, 1 request por aviso): da
  m²/ambientes/baños/expensas/etc. — la variable de valuación. Algunos
  barrios tienen muchísimo volumen (Flores: ~1.900 deptos en venta), así
  que **solo se pide el detalle de avisos nuevos**, hasta un tope diario
  (`config/barrios.yaml: scraping.max_new_detail_fetches_por_corrida`, 250
  por defecto). Los avisos ya conocidos reusan sus atributos de detalle de
  la corrida anterior (no cambian); los que no llegaron a enriquecerse hoy
  quedan con esos campos en blanco y se reintentan mañana. Con el volumen
  actual, completar el backlog inicial de barrios grandes toma varios días.

## F2: Zonaprop/Argenprop, y por qué no están prendidos por defecto

Ninguno de los dos portales responde con contenido real a un cliente HTTP
simple: Zonaprop lo bloquea Cloudflare, Argenprop necesita renderizar JS
(AWS WAF) para pintar los avisos. Ambos **sí** responden a un navegador real
headless (Playwright) — ver `ingest/browser_utils.py`, `zonaprop_scraper.py`,
`argenprop_scraper.py`. A diferencia de Mercado Libre, la página de listado
de estos dos portales ya trae precio/m²/ambientes/dirección: no hace falta
visitar el detalle de cada aviso.

**Hallazgo del spike, importante para no romperlo:** reusar la misma
pestaña de Playwright para navegar una segunda página hace que Cloudflare
vuelva a desafiar — y esa vez no se resuelve solo, ni esperando más. La
solución (ya aplicada) es abrir un **contexto nuevo de Playwright por
página** (no un browser nuevo, alcanza con eso y es rápido).

Todo esto se probó y confirmó **desde una máquina local** (IP residencial).
Lo que falta confirmar es si Cloudflare/AWS WAF puntúan distinto una IP de
datacenter (GitHub Actions) — por eso `fuentes.zonaprop`/`fuentes.argenprop`
arrancan en `false` en `config/barrios.yaml`, y hay un workflow separado
para probarlo sin arriesgar la corrida diaria:

```bash
gh workflow run test-f2-browsers.yml
```

Si ese workflow (`.github/workflows/test-f2-browsers.yml`) sale verde,
poner `fuentes.zonaprop: true` y `fuentes.argenprop: true` en
`config/barrios.yaml` para sumarlos a la corrida diaria de verdad. Si sale
rojo, la alternativa (ya prevista en el plan original) es correr estos dos
scrapers localmente en vez de en Actions, y pushear el resultado desde ahí.

## Desarrollo local

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # si no tenés uv
uv python install 3.11
uv sync
uv run pytest
```

## Puesta en marcha (una sola vez)

1. Crear el repo público en GitHub y conectar este directorio:
   ```bash
   gh repo create <owner>/caba-radar-inmobiliario --public --source=. --remote=origin
   git push -u origin main
   ```
   El repo es público porque GitHub Pages con cuenta Free no funciona sobre
   repos privados, y ni siquiera en plan pago da privacidad real (el sitio
   queda accesible por URL sin login). F0/F1 no expone nada sensible: solo
   avisos de terceros ya públicos en Mercado Libre. Cuando el proyecto llegue
   a auditar "mi propiedad" en el sitio (F4+), reevaluar con un gate de
   autenticación si hace falta privacidad real.

2. Activar GitHub Pages: **Settings → Pages → Source → "GitHub Actions"**
   (no "Deploy from a branch" — la carpeta servida es `site/`, no `docs/`).

3. Completar en `config/mi_propiedad.yaml` los campos `null`: `antiguedad`,
   `piso`, `ascensor`, `expensas_ars`.

4. Confirmar con un escribano la alícuota vigente de `sellos_pct` en
   `config/costos.yaml` (no bloquea F0/F1, ya queda copiado con la nota
   "confirmar vigencia").

5. Disparar el workflow manualmente la primera vez (Actions → Ingesta diaria
   → Run workflow) para no esperar al cron.

## Estructura

```
ingest/     scraping de ML + normalización (+ código OAuth dormido)
analysis/   schema SQLite (derivado, no versionado) + armado de latest.json
site/       sitio estático (sin build step)
config/     parámetros, nunca hardcodeados en el código
data/       snapshots diarios (parquet, versionados) + latest.json
tests/      tests de scraping/normalización, sin red (fixtures/mocks)
```
