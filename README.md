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

2. Crear una app en [ML Developers](https://developers.mercadolibre.com.ar/devcenter)
   y anotar `client_id` / `client_secret`. Al registrar el `redirect_uri`,
   probar primero `http://localhost:8080/callback`; si la consola lo
   rechaza, usar como plan B una página estática (ver nota en
   `ingest/meli_auth_bootstrap.py`) y pasar el `code` a mano.

3. Cargar secrets del repo:
   ```bash
   gh secret set ML_CLIENT_ID
   gh secret set ML_CLIENT_SECRET
   ```

4. Generar un **PAT clásico dedicado** con scope `repo` (con expiración, p. ej.
   90 días, desde github.com/settings/tokens) y cargarlo como secret — lo usa
   el workflow diario para rotar `ML_REFRESH_TOKEN` cuando Mercado Libre lo
   rota:
   ```bash
   gh secret set GH_SECRETS_PAT
   ```

5. Autorizar la app una vez, desde tu máquina (abre el navegador):
   ```bash
   ML_CLIENT_ID=... ML_CLIENT_SECRET=... uv run python -m ingest.meli_auth_bootstrap
   ```
   Esto carga `ML_REFRESH_TOKEN` en GitHub Secrets automáticamente.

6. Correr el spike de descubrimiento de la API una vez, con un access_token
   fresco (lo imprime `meli_auth_bootstrap` o se puede generar corriendo
   `refresh_access_token` a mano):
   ```bash
   ML_ACCESS_TOKEN=... uv run python -m ingest.meli_explore
   ```
   Revisar las fixtures volcadas en `tests/fixtures/` y ajustar
   `ATTRIBUTE_IDS` en `ingest/meli_client.py` y los `meli_neighborhood_id` en
   `config/barrios.yaml` con los valores reales confirmados.

7. Completar en `config/mi_propiedad.yaml` los campos `null`: `antiguedad`,
   `piso`, `ascensor`, `expensas_ars`.

8. Activar GitHub Pages: **Settings → Pages → Source → "GitHub Actions"**
   (no "Deploy from a branch" — la carpeta servida es `site/`, no `docs/`).

9. Confirmar con un escribano la alícuota vigente de `sellos_pct` en
   `config/costos.yaml` (no bloquea F0/F1, ya queda copiado con la nota
   "confirmar vigencia").

10. Disparar el workflow manualmente la primera vez (Actions → Ingesta diaria
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
