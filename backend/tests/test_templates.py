"""T3.2 参数模板 CRUD 测试（需要测试数据库）。"""

VALID_PARAMS = {"grid_size": 100, "time_step": 0.5}


async def test_param_schema_endpoint(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    resp = await client.get("/api/param-schema", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["format"] == "json"
    assert any(f["name"] == "grid_size" for f in body["fields"])


async def test_template_crud(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")

    resp = await client.post("/api/templates", json={"name": "默认方案", "params": VALID_PARAMS}, headers=headers)
    assert resp.status_code == 201
    tpl = resp.json()
    assert tpl["params"]["grid_size"] == 100
    assert tpl["params"]["method"] == "explicit"  # 默认值已补全

    resp = await client.get("/api/templates", headers=headers)
    assert [t["name"] for t in resp.json()] == ["默认方案"]

    resp = await client.put(f"/api/templates/{tpl['id']}",
                            json={"params": {"grid_size": 200}}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["params"]["grid_size"] == 200

    resp = await client.delete(f"/api/templates/{tpl['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get("/api/templates", headers=headers)
    assert resp.json() == []


async def test_template_name_unique(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    await client.post("/api/templates", json={"name": "方案A", "params": VALID_PARAMS}, headers=headers)
    resp = await client.post("/api/templates", json={"name": "方案A", "params": VALID_PARAMS}, headers=headers)
    assert resp.status_code == 409


async def test_template_invalid_params_422(client, auth_headers):
    headers = await auth_headers("carol", "carol@example.com")
    resp = await client.post("/api/templates", json={"name": "坏参数", "params": {"grid_size": -1}}, headers=headers)
    assert resp.status_code == 422
    assert "grid_size" in resp.json()["detail"]


async def test_template_isolation(client, auth_headers):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")

    resp = await client.post("/api/templates", json={"name": "A的模板", "params": VALID_PARAMS}, headers=headers_a)
    tpl_id = resp.json()["id"]

    assert (await client.get("/api/templates", headers=headers_b)).json() == []
    assert (await client.put(f"/api/templates/{tpl_id}", json={"name": "篡改"}, headers=headers_b)).status_code == 404
    assert (await client.delete(f"/api/templates/{tpl_id}", headers=headers_b)).status_code == 404
