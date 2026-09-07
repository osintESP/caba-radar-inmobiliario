import io

import httpx
import pytest
import respx
from PIL import Image, ImageDraw

from ingest import dedupe


def _png_bytes(color: tuple[int, int, int], size: int = 64) -> bytes:
    img = Image.new("RGB", (size, size), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _pattern_png_bytes(variant: str, size: int = 64) -> bytes:
    """pHash mira estructura (frecuencias vía DCT), no color plano — un
    cuadrado de color sólido no alcanza para distinguir dos fotos
    distintas en el test. Se dibuja una figura geométrica distinta por
    variante para que el hash perceptual realmente difiera."""
    img = Image.new("RGB", (size, size), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    if variant == "a":
        draw.rectangle([4, 4, size - 20, size - 20], fill=(20, 20, 20))
    elif variant == "b":
        draw.ellipse([2, 30, size - 2, size - 2], fill=(200, 30, 30))
        draw.line([(0, 0), (size, size)], fill=(0, 0, 0), width=6)
    else:
        raise ValueError(variant)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _row(**overrides):
    base = {
        "portal_id": "MLA1",
        "barrio": "Monte Castro",
        "tipo": "departamento",
        "ambientes": 2,
        "m2_cubiertos": 50.0,
        "direccion": None,
        "imagen_url": None,
    }
    base.update(overrides)
    return base


def test_normalize_address_strips_accents_case_and_punctuation():
    assert dedupe.normalize_address("Benito Juárez  al 2100") == "benito juarez al 2100"
    assert dedupe.normalize_address("BENITO JUAREZ AL 2100.") == "benito juarez al 2100"
    assert dedupe.normalize_address(None) is None
    assert dedupe.normalize_address("") is None


def test_union_find_merges_transitively():
    uf = dedupe.UnionFind()
    uf.union("a", "b")
    uf.union("b", "c")
    assert uf.find("a") == uf.find("c")
    assert uf.find("a") != uf.find("d")


def test_duplicates_merged_by_matching_address():
    rows = [
        _row(portal_id="ZP1", direccion="Benito Juárez al 2100"),
        _row(portal_id="AP1", direccion="benito juarez al 2100."),
        _row(portal_id="ZP2", direccion="Otra Calle al 500"),
    ]
    result = dedupe.find_duplicates(rows, known_phashes={})
    assert result.fingerprint_by_portal_id["ZP1"] == result.fingerprint_by_portal_id["AP1"]
    assert result.fingerprint_by_portal_id["ZP2"] != result.fingerprint_by_portal_id["ZP1"]


def test_non_matching_address_and_different_ambientes_not_merged():
    rows = [
        _row(portal_id="ZP1", direccion="Calle Falsa 123", ambientes=2),
        _row(portal_id="AP1", direccion="Calle Falsa 123", ambientes=3),  # misma direccion, distinto tipo de unidad
    ]
    result = dedupe.find_duplicates(rows, known_phashes={})
    assert result.fingerprint_by_portal_id["ZP1"] != result.fingerprint_by_portal_id["AP1"]


@respx.mock
def test_duplicates_merged_by_matching_photo_phash():
    same_image = _png_bytes((10, 20, 30))
    respx.get("https://img.example/a.jpg").mock(return_value=httpx.Response(200, content=same_image))
    respx.get("https://img.example/b.jpg").mock(return_value=httpx.Response(200, content=same_image))

    rows = [
        _row(portal_id="MLA1", imagen_url="https://img.example/a.jpg", m2_cubiertos=50.0),
        _row(portal_id="ZP1", imagen_url="https://img.example/b.jpg", m2_cubiertos=52.0),  # dentro del 15%
    ]
    result = dedupe.find_duplicates(rows, known_phashes={}, max_new_phash_fetches=10)
    assert result.fingerprint_by_portal_id["MLA1"] == result.fingerprint_by_portal_id["ZP1"]
    # el phash calculado queda disponible para cachear en corridas futuras
    assert "MLA1" in result.phash_by_portal_id
    assert "ZP1" in result.phash_by_portal_id


@respx.mock
def test_different_photos_not_merged():
    respx.get("https://img.example/a.jpg").mock(return_value=httpx.Response(200, content=_pattern_png_bytes("a")))
    respx.get("https://img.example/b.jpg").mock(return_value=httpx.Response(200, content=_pattern_png_bytes("b")))

    rows = [
        _row(portal_id="MLA1", imagen_url="https://img.example/a.jpg"),
        _row(portal_id="ZP1", imagen_url="https://img.example/b.jpg"),
    ]
    result = dedupe.find_duplicates(rows, known_phashes={}, max_new_phash_fetches=10)
    assert result.fingerprint_by_portal_id["MLA1"] != result.fingerprint_by_portal_id["ZP1"]


@respx.mock
def test_m2_out_of_tolerance_prevents_merge_even_with_same_photo():
    same_image = _png_bytes((10, 20, 30))
    respx.get("https://img.example/a.jpg").mock(return_value=httpx.Response(200, content=same_image))
    respx.get("https://img.example/b.jpg").mock(return_value=httpx.Response(200, content=same_image))

    rows = [
        _row(portal_id="MLA1", imagen_url="https://img.example/a.jpg", m2_cubiertos=40.0),
        _row(portal_id="ZP1", imagen_url="https://img.example/b.jpg", m2_cubiertos=90.0),
    ]
    result = dedupe.find_duplicates(rows, known_phashes={}, max_new_phash_fetches=10)
    assert result.fingerprint_by_portal_id["MLA1"] != result.fingerprint_by_portal_id["ZP1"]


def test_known_phashes_are_reused_without_network_calls():
    # Sin respx.mock activo: cualquier request real fallaría/tiraría error de red.
    # Si el cache funciona, find_duplicates no debería intentar ninguna.
    same_hash = "8f8f8f8f8f8f8f8f"
    rows = [
        _row(portal_id="MLA1", imagen_url="https://img.example/a.jpg", m2_cubiertos=50.0),
        _row(portal_id="ZP1", imagen_url="https://img.example/b.jpg", m2_cubiertos=51.0),
    ]
    result = dedupe.find_duplicates(rows, known_phashes={"MLA1": same_hash, "ZP1": same_hash})
    assert result.fingerprint_by_portal_id["MLA1"] == result.fingerprint_by_portal_id["ZP1"]


@respx.mock
def test_max_new_phash_fetches_limits_network_calls():
    call_count = 0

    def _responder(request):
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, content=_png_bytes((10, 20, 30)))

    respx.get(url__regex=r"https://img\.example/.*").mock(side_effect=_responder)

    rows = [_row(portal_id=f"MLA{i}", imagen_url=f"https://img.example/{i}.jpg") for i in range(5)]
    dedupe.find_duplicates(rows, known_phashes={}, max_new_phash_fetches=2)
    assert call_count == 2


def test_single_listing_bucket_is_its_own_fingerprint_not_a_group():
    rows = [_row(portal_id="MLA1")]
    result = dedupe.find_duplicates(rows, known_phashes={})
    assert result.fingerprint_by_portal_id["MLA1"] == "MLA1"  # no tiene el prefijo "grp_"
