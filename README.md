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

**Verificado con una corrida real en Actions** (`.github/workflows/test-f2-browsers.yml`,
IP de datacenter, no local) — resultado dividido:

- **Zonaprop: funciona.** Pasa el challenge de Cloudflare igual desde
  Actions (25/25 avisos reales). `fuentes.zonaprop: true` en
  `config/barrios.yaml`, ya integrado a la corrida diaria.
- **Argenprop: NO funciona desde Actions** (0 avisos, aunque local anda
  perfecto) — su WAF sí distingue la IP de datacenter. `fuentes.argenprop`
  queda en `false` hasta investigar más o, como ya preveía el plan
  original, correrlo localmente en vez de en Actions y pushear el
  resultado desde ahí.

Para repetir la prueba (por ejemplo si se ajusta algo del scraper de
Argenprop):

```bash
gh workflow run test-f2-browsers.yml
```

## Segundo perfil: otro comprador buscando en la misma zona

Desde 2026-09-14 el sitio soporta más de un "perfil" comprador sobre el
mismo universo de candidatas. El primero (`config/mi_propiedad.yaml`) vende
un departamento en Monte Castro y busca 3+ ambientes; el segundo
(`config/mi_propiedad_papa.yaml`) vende una casa en Merlo (Buenos Aires) y
busca 2 ambientes en los mismos barrios (Vélez Sarsfield/Floresta/Monte
Castro/anillo). Vista simplificada en `site/papa.html`: menos columnas,
texto más grande, tarjetas en vez de tabla — pensada para navegarse fácil
desde el celular.

Piezas nuevas:

- `config/barrios.yaml: externas` — zonas fuera de CABA (hoy solo Merlo)
  que se scrapean únicamente para auditar la propiedad puntual de un
  perfil contra sus propios comparables, nunca aparecen como candidatas
  de compra (`ingest/snapshot.py` las marca con `zona_externa: true`,
  `analysis/latest.py` las excluye de la tabla y de la Vista de Mercado).
  Confirmado en vivo: Mercado Libre resuelve Merlo con la región
  `bsas-gba-oeste`, no `capital-federal` como el resto — por eso
  `meli_region` es un campo obligatorio ahí. Solo Mercado Libre por ahora;
  Zonaprop/Argenprop quedan para cuando haga falta más volumen de
  comparables.
- `config/barrios.yaml: alcance.ambientes_min` bajó de 3 a 2 — antes
  descartaba TODO aviso de 1-2 ambientes a nivel scraping, antes de llegar
  a ningún perfil. Cada perfil sigue filtrando a los ambientes que le
  interesan en su propia vista.
- `analysis/brecha_neta.py::brecha_neta()` ahora toma `percentil_zona`
  además del precio — cada candidata tiene una columna de brecha neta por
  perfil (`brecha_neta_usd`, `brecha_neta_papa_usd`), calculada contra el
  precio de venta de CADA perfil, pero comparten `pct_negociacion_estimado`
  (solo depende de la candidata, no de quién compra).

**Pendiente para que la auditoría de la casa de Merlo funcione de verdad:**
`config/mi_propiedad_papa.yaml` tiene `m2_cubiertos: null` — sin superficie
no hay con qué comparar (F4 la exige, nunca se imputa). Hasta completarlo,
el sitio muestra "faltan datos" en vez de un número inventado.

## Perímetro por barrio

`config/barrios.yaml: perimetros` acota un barrio a un polígono de
coordenadas `[[lat, lon], ...]` (ej. dejar afuera la traza del Sarmiento o
una avenida comercial). Los avisos fuera del polígono quedan guardados pero
marcados `fuera_de_perimetro` y no se muestran ni cuentan como comparables
(`ingest/perimetro.py`). Las coordenadas salen del detalle de Mercado Libre
(`fetch_detail`); los avisos ya conocidos sin coordenadas se re-piden de a
poco dentro del cupo diario. Un aviso sin coordenadas no se oculta (no hay
dato para decidirlo). Zonaprop trae calle/altura pero no lat/lon, así que por
ahora el perímetro solo aplica a ML. Sin polígono configurado no hay filtro.

## Vista del sitio: tabla compacta, galería y ficha

`index.html` muestra 6 columnas (foto, propiedad, precio, brecha neta, vs.
zona, acciones) o, con el botón "Galería", tarjetas con foto grande (vista
por defecto en el celular; la elección se recuerda en el navegador). Todo
el detalle que no entra —baños, cochera, expensas, antigüedad, piso,
portal, duplicados, historial de precio— está en la ficha, que se abre
haciendo click en cualquier parte de la fila o tarjeta.

Las fotos salen de `imagen_url` (scrapeada del listado de cada portal,
~99% de cobertura). `analysis/latest.py` la pasa a https (ML la devuelve
con http) y `site/fotos.js` pide a cada CDN el tamaño adecuado: la URL del
listado de ML es una miniatura de 90×90.

## Avisos descartados ("no me gusta")

Cada aviso tiene un botón para ocultarlo (✕ en la tabla de `index.html`,
"No me gusta, ocultar" en las tarjetas de `papa.html`), con "Deshacer" por
unos segundos y una opción para ver los ocultados y recuperarlos. La lista
se guarda en `localStorage` del navegador (`site/descartados.js`), no en el
repo: el sitio es estático y no tiene dónde escribir. Consecuencias: es por
dispositivo (lo ocultado en la compu no se oculta en el celular) y por
perfil (cada página tiene su propia lista). La clave es `portal:portal_id`,
así que un aviso ocultado sigue oculto en los snapshots siguientes.

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
