"""OAuth de la API de Mercado Libre.

**DORMIDO / SIN USO** por ahora — ver la nota al inicio de
`ingest/meli_client.py`: la API de búsqueda/items está bloqueada para apps
no certificadas. `ingest/run_daily.py` ya no llama a este módulo.

Referencia: https://developers.mercadolibre.com.ar/es_ar/autenticacion-y-autorizacion
(la doc pública devolvió 403 al intentar leerla programáticamente durante la
planificación; este módulo sigue el flujo Authorization Code estándar de ML,
a confirmar contra el comportamiento real durante el bootstrap manual — ver
ingest/meli_auth_bootstrap.py y el spike de ingest/meli_explore.py).
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import httpx

AUTH_BASE_URL = "https://auth.mercadolibre.com.ar/authorization"
TOKEN_URL = "https://api.mercadolibre.com/oauth/token"


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def build_auth_url(client_id: str, redirect_uri: str, state: str | None = None) -> tuple[str, str]:
    """Devuelve (url_de_autorizacion, state_usado)."""
    state = state or secrets.token_urlsafe(16)
    params = httpx.QueryParams(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
    )
    return f"{AUTH_BASE_URL}?{params}", state


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> TokenPair:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return TokenPair(
        access_token=data["access_token"],
        refresh_token=data["refresh_token"],
        expires_in=data["expires_in"],
    )


def refresh_access_token(client_id: str, client_secret: str, refresh_token: str) -> TokenPair:
    """Canjea el refresh_token por un access_token nuevo.

    ML puede rotar el refresh_token en cada canje (comportamiento estándar de
    OAuth2, a confirmar en la práctica). El caller SIEMPRE debe comparar
    `resultado.refresh_token` contra el que tenía guardado y, si cambió,
    persistir el nuevo (ver ingest/run_daily.py) — asumir que no rota y
    descartarlo sería el bug más caro posible acá: el próximo refresh fallaría.
    """
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=15.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return TokenPair(
        access_token=data["access_token"],
        refresh_token=data.get("refresh_token", refresh_token),
        expires_in=data["expires_in"],
    )
