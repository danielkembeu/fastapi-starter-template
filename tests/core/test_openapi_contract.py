"""Contrat de l'API tel que publié dans OpenAPI : pagination partout, filtres documentés."""

import pytest

from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from app.server import server

SPEC = server.openapi()
PAGE_FIELDS = {"items", "total", "limit", "offset", "has_more"}


def _operations():
    for path, methods in SPEC["paths"].items():
        for method, operation in methods.items():
            yield method.upper(), path, operation


def _response_schema(operation):
    ok = next((r for code, r in operation["responses"].items() if code.startswith("2")), {})
    return ok.get("content", {}).get("application/json", {}).get("schema", {})


def _resolve(schema):
    if "$ref" in schema:
        return SPEC["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return schema


def test_no_get_endpoint_returns_a_bare_unbounded_list():
    """Règle d'architecture : toute collection est paginée, sans exception."""
    offenders = [
        f"{method} {path}"
        for method, path, op in _operations()
        if method == "GET" and _resolve(_response_schema(op)).get("type") == "array"
    ]
    assert offenders == []


def _paginated():
    return [
        (method, path, op)
        for method, path, op in _operations()
        if method == "GET"
        and set(_resolve(_response_schema(op)).get("properties", {})) == PAGE_FIELDS
    ]


def test_the_expected_endpoints_are_paginated():
    paginated = {f"{m} {p}" for m, p, _ in _paginated()}
    expected = {
        "GET /api/v1/projects",
        "GET /api/v1/admin/audit-logs",
    }
    assert expected <= paginated, expected - paginated


@pytest.mark.parametrize(
    ("method", "path", "operation"), _paginated(), ids=lambda v: v if isinstance(v, str) else ""
)
def test_paginated_endpoints_document_individual_query_parameters(method, path, operation):
    params = {p["name"]: p for p in operation.get("parameters", []) if p["in"] == "query"}

    assert {"limit", "offset"} <= set(params), f"{path} sans limit/offset"
    assert params["limit"]["schema"]["default"] == DEFAULT_LIMIT
    assert params["limit"]["schema"]["maximum"] == MAX_LIMIT
    assert params["offset"]["schema"]["minimum"] == 0
    assert params["limit"]["required"] is False
    # Un modèle de filtres non développé apparaîtrait comme un paramètre objet unique et requis.
    for name, param in params.items():
        assert name not in {"filters", "query", "f"}, f"{path}: paramètre non développé « {name} »"
        assert param["schema"].get("type") != "object"


def test_every_list_endpoint_documents_a_sort_whitelist_when_it_sorts():
    for _method, path, operation in _paginated():
        for param in operation.get("parameters", []):
            if param["name"] == "sort":
                assert param["schema"].get("enum"), f"{path}: tri sans liste blanche"


def test_documented_error_codes_cover_auth_failures():
    public = {
        "/api/v1/auth/register",
        "/api/v1/auth/login",
        "/api/v1/auth/refresh",
        "/api/v1/auth/logout",
    }
    for method, path, operation in _operations():
        if path.startswith("/api/") and path not in public:
            codes = set(operation["responses"])
            assert "401" in codes or "400" in codes, f"{method} {path}"
