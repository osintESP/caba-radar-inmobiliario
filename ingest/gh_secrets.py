"""Wrapper de `gh secret set`, usado tanto por el bootstrap manual
(ingest/meli_auth_bootstrap.py) como por el workflow diario cuando Mercado
Libre rota el refresh_token (ver ingest/run_daily.py).

En el workflow, `gh` necesita un token con permiso de escritura sobre
Secrets — el `GITHUB_TOKEN` automático de Actions NO lo tiene bajo ningún
valor de `permissions:`. Por eso `token` acá debe ser el PAT dedicado
guardado como secret `GH_SECRETS_PAT` (ver README, checklist manual).
"""

from __future__ import annotations

import os
import subprocess


def set_secret(name: str, value: str, repo: str | None = None, token: str | None = None) -> None:
    cmd = ["gh", "secret", "set", name, "--body", value]
    if repo:
        cmd += ["--repo", repo]
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    subprocess.run(cmd, check=True, env=env)
