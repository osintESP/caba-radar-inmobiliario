# Radar Inmobiliario

Monitoreo diario de avisos de Mercado Libre en barrios del oeste de CABA
(Vélez Sarsfield, Floresta, Monte Castro y anillo), para evaluar la venta de
una propiedad y candidatas de compra. Ver `PLAN-radar-inmobiliario.md` para
el diseño completo del proyecto.

**Esta implementación cubre F0 (ingesta + snapshots automáticos) y F1 (sitio
estático)**. Todavía no hace dedupe, valuación, brecha neta, ni scrapers de
Zonaprop/Argenprop — eso es F2+.

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
   git add -A && git commit -m "F0+F1: ingesta ML + sitio estático"
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
   Con eso ya sabés tu URL de Pages: `https://<owner>.github.io/caba-radar-inmobiliario/`.
   Hace falta antes del paso 5: Mercado Libre exige que el `redirect_uri`
   sea HTTPS (rechaza `http://localhost`), así que se usa
   `site/oauth-callback.html`, servido por Pages, en vez de un server local.

3. Crear una app en [ML Developers](https://developers.mercadolibre.com.ar/devcenter)
   y anotar `client_id` / `client_secret`. En el formulario de creación:
   - **Redirect URIs:** `https://<owner>.github.io/caba-radar-inmobiliario/oauth-callback.html`
   - **Flujos OAuth:** tildar **Authorization Code** y **Refresh Token**
     (son los que usa `ingest/meli_auth.py`). *Client Credentials* no hace
     falta. Dejar **PKCE** desactivado — el código no lo implementa todavía;
     si el spike revela que ML lo exige para este tipo de app, se agrega.
   - **Negocios:** tildar **VIS** (Vehículos, Inmuebles y Servicios — es la
     unidad de negocio real de Mercado Libre bajo la que vive Inmuebles).
     Dejar también "Mercado Libre" tildado si el formulario obliga a elegir
     al menos una.
   - **Permisos:** dejar todo en **"Sin acceso"** salvo lo que venga
     forzado por defecto (p. ej. "Usuarios", necesario para autenticar).
     No hace falta escritura sobre publicaciones, ventas, mensajes ni
     facturación — esto solo *lee* avisos de terceros. Si el spike (paso 6)
     da error de permisos al buscar, revisar esto.
   - **Tópicos / Notificaciones callbacks URL:** dejar vacío — F0/F1 no
     recibe webhooks, solo hace polling diario.

4. Cargar secrets del repo:
   ```bash
   gh secret set ML_CLIENT_ID
   gh secret set ML_CLIENT_SECRET
   ```
   Y un **PAT clásico dedicado** con scope `repo` (con expiración, p. ej.
   90 días, desde github.com/settings/tokens) — lo usa el workflow diario
   para rotar `ML_REFRESH_TOKEN` cuando Mercado Libre lo rota:
   ```bash
   gh secret set GH_SECRETS_PAT
   ```

5. Autorizar la app una vez, desde tu máquina (abre el navegador, y al
   volver a la terminal pedís que pegues el `code` que te muestra
   `oauth-callback.html`):
   ```bash
   ML_CLIENT_ID=... ML_CLIENT_SECRET=... uv run python -m ingest.meli_auth_bootstrap \
       --redirect-uri https://<owner>.github.io/caba-radar-inmobiliario/oauth-callback.html
   ```
   Esto carga `ML_REFRESH_TOKEN` en GitHub Secrets automáticamente, y al
   final imprime un `ML_ACCESS_TOKEN` de esa sesión para el paso 6.

6. Correr el spike de descubrimiento de la API una vez, con ese access_token:
   ```bash
   ML_ACCESS_TOKEN=... uv run python -m ingest.meli_explore
   ```
   Revisar las fixtures volcadas en `tests/fixtures/` y ajustar
   `ATTRIBUTE_IDS`/`SEARCH_CATEGORY` en `ingest/meli_client.py` y `snapshot.py`,
   y los `meli_neighborhood_id` en `config/barrios.yaml`, con los valores
   reales confirmados. Mercado Libre separa Inmuebles bajo la unidad de
   negocio VIS — si `/sites/MLA/search` no devuelve resultados de Inmuebles,
   este es el punto donde confirmar si hace falta un endpoint `/vis/...`
   en su lugar (no documentado públicamente sin cuenta de developer).

7. Completar en `config/mi_propiedad.yaml` los campos `null`: `antiguedad`,
   `piso`, `ascensor`, `expensas_ars`.

8. Confirmar con un escribano la alícuota vigente de `sellos_pct` en
   `config/costos.yaml` (no bloquea F0/F1, ya queda copiado con la nota
   "confirmar vigencia").

9. Disparar el workflow manualmente la primera vez (Actions → Ingesta diaria
   → Run workflow) para no esperar al cron.

## Estructura

```
ingest/     ingesta + normalización + auth de Mercado Libre
analysis/   schema SQLite (derivado, no versionado) + armado de latest.json
site/       sitio estático (sin build step)
config/     parámetros, nunca hardcodeados en el código
data/       snapshots diarios (parquet, versionados) + latest.json
tests/      tests de normalización, sin red
```
