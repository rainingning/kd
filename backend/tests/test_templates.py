"""真实 DCR 参数模板 CRUD 测试。"""
from copy import deepcopy
from pathlib import Path

from app.param_schema import SCHEMA_VERSION, parse_params

VALID_PARAMS = parse_params(
    (Path(__file__).resolve().parents[2] / "docs" / "model_DC.dat").read_text(encoding="utf-8"))


async def test_param_schema_endpoint(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    resp = await client.get("/api/param-schema", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "model_DC.dat"
    assert body["schema_version"] == SCHEMA_VERSION
    assert any(field["name"] == "materials" for field in body["fields"])


async def test_template_crud(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    resp = await client.post("/api/templates", json={"name": "默认方案", "params": VALID_PARAMS}, headers=headers)
    assert resp.status_code == 201, resp.text
    tpl = resp.json()
    assert tpl["params"]["boundary_mode"] == 1
    assert tpl["parameter_schema_version"] == SCHEMA_VERSION

    resp = await client.get("/api/templates", headers=headers)
    assert [item["name"] for item in resp.json()] == ["默认方案"]

    changed = deepcopy(VALID_PARAMS)
    changed["boundary_mode"] = 2
    resp = await client.put(f"/api/templates/{tpl['id']}", json={"params": changed}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["params"]["boundary_mode"] == 2

    assert (await client.delete(f"/api/templates/{tpl['id']}", headers=headers)).status_code == 204
    assert (await client.get("/api/templates", headers=headers)).json() == []


async def test_template_name_unique(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    await client.post("/api/templates", json={"name": "方案A", "params": VALID_PARAMS}, headers=headers)
    resp = await client.post("/api/templates", json={"name": "方案A", "params": VALID_PARAMS}, headers=headers)
    assert resp.status_code == 409


async def test_template_invalid_params_422(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    bad = deepcopy(VALID_PARAMS)
    bad["materials"][0]["rho_x"] = -1
    resp = await client.post("/api/templates", json={"name": "坏参数", "params": bad}, headers=headers)
    assert resp.status_code == 422
    assert "$.materials[0].rho_x" in resp.json()["detail"]


async def test_template_isolation(client, auth_headers):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")
    resp = await client.post("/api/templates", json={"name": "A的模板", "params": VALID_PARAMS}, headers=headers_a)
    tpl_id = resp.json()["id"]
    assert (await client.get("/api/templates", headers=headers_b)).json() == []
    assert (await client.put(f"/api/templates/{tpl_id}", json={"name": "篡改"}, headers=headers_b)).status_code == 404
    assert (await client.delete(f"/api/templates/{tpl_id}", headers=headers_b)).status_code == 404
