"""Extracción de palabras clave relevantes para un comprador, a partir del
texto libre (descripción) de un aviso — cosas como "apto crédito" o "sin
expensas" no viven en ningún campo estructurado de ningún portal, solo en
la descripción que escribe la inmobiliaria.

Reglas simples de matching de frases (regex sobre un diccionario curado a
mano), no NLP pesado ni nada parecido a los modelos de Google/redes
sociales — es lo que hacen la mayoría de las herramientas reales de
proptech, y alcanza para la escala de este proyecto.

Maneja negaciones simples ("NO APTO CREDITO", "sin pileta"): si la frase
que matchea viene precedida de cerca por "no"/"sin"/"nunca", no se tagea.
Encontrado en el primer aviso real probado en esta sesión — sin esto,
"NO APTO CREDITO!" quedaba tageado como apto_credito, exactamente lo
opuesto de lo que dice el aviso.
"""

from __future__ import annotations

import re

_NEGATION_RE = re.compile(r"\b(no|sin|nunca)\b[^.,;!]{0,20}$", re.IGNORECASE)

KEYWORDS: dict[str, list[str]] = {
    "apto_credito": [r"apto\s+cr[eé]dito", r"apto\s+bancario"],
    "apto_profesional": [r"apto\s+profesional"],
    "a_reciclar": [r"a\s+reciclar", r"para\s+reciclar"],
    "a_estrenar": [r"a\s+estrenar"],
    "luminoso": [r"luminos[oa]"],
    "contrafrente": [r"contrafrente"],
    "al_frente": [r"\bal\s+frente\b"],
    "parrilla": [r"parrilla"],
    "quincho": [r"quincho"],
    "pileta": [r"pileta", r"piscina"],
    "amenities": [r"amenities"],
    "sum": [r"\bsum\b", r"sal[oó]n de usos m[uú]ltiples"],
    "baulera": [r"baulera"],
    "acepta_permuta": [r"permuta"],
    "sin_expensas": [r"no tiene expensas", r"sin expensas"],
    "aire_acondicionado": [r"aire acondicionado"],
    "placard": [r"placard"],
    "balcon": [r"balc[oó]n"],
    "terraza": [r"terraza"],
    "cochera": [r"cochera"],
    "seguridad": [r"seguridad\s+24", r"\bportero\b", r"vigilancia"],
}


def _has_unnegated_match(text: str, pattern: str) -> bool:
    for m in re.finditer(pattern, text, re.IGNORECASE):
        preceding = text[max(0, m.start() - 20) : m.start()]
        if not _NEGATION_RE.search(preceding):
            return True
    return False


def extract_tags(text: str | None) -> list[str]:
    if not text:
        return []
    tags: list[str] = []
    for tag, patterns in KEYWORDS.items():
        if any(_has_unnegated_match(text, p) for p in patterns):
            tags.append(tag)
    return tags
