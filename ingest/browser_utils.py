"""Utilidades de scraping con navegador real (Playwright).

Zonaprop (Cloudflare) y Argenprop (AWS WAF + render client-side) devuelven
403 o una página vacía a un cliente HTTP simple como httpx — confirmado en
vivo. Ambos SÍ responden con contenido real a un navegador headless real.
A diferencia de ingest/meli_scraper.py (httpx alcanza), estos dos portales
necesitan levantar un Chromium real.

**Hallazgo importante del spike**: reusar la misma pestaña/contexto de
Playwright para más de una navegación hace que Cloudflare vuelva a
desafiar en la segunda — y esta vez NO se resuelve solo (confirmado
esperando hasta 12s extra, se queda en "Just a moment..." indefinidamente).
Un browser nuevo por página lo evita pero es carísimo (>30s de arranque
por página). La solución que sí anda y es rápida (unos pocos segundos por
página): un **contexto nuevo de Playwright por página** (`browser.new_context()`),
reusando el mismo proceso de Chromium para toda la corrida.

**Advertencia operativa sin confirmar todavía** (ver PLAN-radar-inmobiliario.md,
sección 4 y 7, y el checklist de verificación en README.md): todo esto se
probó desde una IP residencial/de desarrollo. Los runners de GitHub Actions
usan IPs de datacenter, que Cloudflare/WAF suelen puntuar peor incluso
cuando el navegador pasa el challenge. Hace falta una corrida real en
Actions antes de asumir que esto funciona ahí — si falla, la alternativa
(ya prevista en el plan) es correr estos dos scrapers localmente en vez de
en Actions.
"""

from __future__ import annotations

import random
import time
from contextlib import contextmanager
from typing import Iterator

from playwright.sync_api import Browser, sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Rate limit cortés (PLAN-radar-inmobiliario.md, sección 7): 2-4s con
# jitter, sin paralelismo.
_MIN_DELAY = 2.0
_MAX_DELAY = 4.0


@contextmanager
def browser_session() -> Iterator[Browser]:
    """Un Chromium headless compartido para toda la corrida (levantar el
    proceso es caro). Cada página navegada abre su propio contexto — ver
    docstring del módulo sobre por qué reusar la misma pestaña rompe el
    scraping a la segunda navegación."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


def fetch_rendered_html(browser: Browser, url: str, extra_wait_ms: int = 4000) -> str:
    """Navega a `url` en un contexto nuevo, con el rate limit cortés, y
    devuelve el HTML ya renderizado (después del challenge de
    Cloudflare/WAF y de que el JS del cliente termine de pintar la lista
    de avisos)."""
    time.sleep(random.uniform(_MIN_DELAY, _MAX_DELAY))
    context = browser.new_context(user_agent=USER_AGENT)
    try:
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(extra_wait_ms)
        return page.content()
    finally:
        context.close()
