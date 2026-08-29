"""试用部署验证：登录 → 提交 mock 任务 → 轮询到终态 → 检查结果文件。"""
import sys
import time

sys.path.insert(0, "backend")
import httpx

BASE = "http://127.0.0.1:8000"

client = httpx.Client(base_url=BASE, timeout=30)

r = client.get("/api/health")
assert r.status_code == 200, r.text
print("[ok] health:", r.json())

r = client.get("/")
assert r.status_code == 200 and 'id="app"' in r.text, r.text[:200]
print("[ok] SPA index.html served, bytes =", len(r.text))

r = client.post("/api/auth/login", json={"username": "admin", "password": "Admin@2026kd"})
assert r.status_code == 200, r.text
token = r.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("[ok] login as admin")

r = client.get("/api/tasks", headers=headers)
assert r.status_code == 200, r.text
print("[ok] task list before submit: total =", r.json()["total"])

mesh = b"# mock mesh file for trial smoke\n1.0 2.0 3.0\n"
r = client.post(
    "/api/tasks",
    data={"params": "{}", "program_key": "dcr_3d"},
    files={"file": ("mesh.mphtxt", mesh, "application/octet-stream")},
    headers=headers,
)
assert r.status_code == 201, r.text
task_id = r.json()["id"]
print("[ok] task submitted: id =", task_id)

for _ in range(120):
    r = client.get(f"/api/tasks/{task_id}", headers=headers)
    assert r.status_code == 200, r.text
    detail = r.json()
    status = detail["status"]
    if status in {"COMPLETED", "FAILED", "CANCELED", "TIMEOUT", "ARCHIVE_FAILED"}:
        break
    time.sleep(1)
else:
    print("[FAIL] task did not reach terminal state in 120s; last status =", status)
    sys.exit(1)

print("[ok] task terminal status =", status,
      "| exit_code =", detail.get("exit_code"),
      "| archive_status =", detail.get("archive_status"),
      "| result_files =", detail.get("result_file_count"),
      "| result_bytes =", detail.get("result_size_bytes"))
if status != "COMPLETED":
    print("[FAIL] error_message =", detail.get("error_message"))
    sys.exit(1)

r = client.get(f"/api/tasks/{task_id}/files", headers=headers)
if r.status_code == 200:
    names = [f.get("path") or f.get("name") for f in r.json().get("files", r.json() if isinstance(r.json(), list) else [])]
    print("[ok] task files:", names)

print("SMOKE TEST PASSED")
