"""
test_web_server.py
==================
Automated API test suite verifying all REST endpoints for the
Asianet Kerala Regional Operations Manager web server.
"""

from fastapi.testclient import TestClient
from web_server import app
import json

client = TestClient(app)

def test_routes():
    print("1. Testing GET / (Dashboard UI)...")
    res = client.get("/")
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    assert "Asianet Kerala Network Tracker" in res.text
    print("   [OK] Dashboard HTML served.")

    print("\n2. Testing GET /api/regions...")
    res = client.get("/api/regions")
    assert res.status_code == 200
    regions = res.json()
    assert len(regions) >= 14, f"Expected at least 14 regions, got {len(regions)}"
    thrissur = next((r for r in regions if r["id"] == "thrissur"), None)
    assert thrissur is not None
    assert thrissur["tl_count"] == 22
    assert thrissur["acso_count"] == 13
    print(f"   [OK] Loaded {len(regions)} regions. Thrissur: {thrissur['tl_count']} TLs, {thrissur['acso_count']} ACSOs.")

    print("\n3. Testing GET /api/regions/thrissur/config...")
    res = client.get("/api/regions/thrissur/config")
    assert res.status_code == 200
    data = res.json()
    assert len(data["tls"]) == 22
    assert len(data["acsos"]) == 13
    print(f"   [OK] Thrissur config: {len(data['tls'])} TLs, {len(data['acsos'])} ACSOs, {len(data['emps'])} employees.")

    print("\n4. Testing GET /api/regions/thrissur/test-engine (Calculation Parity)...")
    res = client.get("/api/regions/thrissur/test-engine")
    assert res.status_code == 200
    calc = res.json()
    assert calc["status"] == "PASS", f"Engine failed: {calc}"
    assert calc["adl_total"] == 51, f"Expected ADL total 51, got {calc['adl_total']}"
    assert calc["adtv_total"] == 457, f"Expected ADTv total 457, got {calc['adtv_total']}"
    print(f"   [OK] 100% Parity Verified! ADL Total: {calc['adl_total']} ({calc['adl_postpaid']} post + {calc['adl_prepaid']} pre), ADTv Total: {calc['adtv_total']} ({calc['adtv_postpaid']} post + {calc['adtv_prepaid']} pre).")

    print("\n5. Testing Team Leader CRUD on Ernakulam...")
    # Add
    tl_payload = {
        "center_name": "Aluva",
        "name": "Test TL",
        "pd_adl_name_key": "Test TL",
        "pd_adtv_name_key": "Test TL",
        "pp_adl_emp_code": "9999",
        "adtv_center": "Aluva",
        "adtv_name": "Test TL"
    }
    res = client.post("/api/regions/ernakulam/team-leaders", json=tl_payload)
    assert res.status_code == 200
    tl_id = res.json()["id"]
    print(f"   [OK] Created TL ID: {tl_id}")

    # Edit
    tl_payload["name"] = "Test TL Updated"
    res = client.put(f"/api/regions/ernakulam/team-leaders/{tl_id}", json=tl_payload)
    assert res.status_code == 200
    print("   [OK] Updated TL")

    # Verify
    res = client.get("/api/regions/ernakulam/config")
    tls = res.json()["tls"]
    assert any(t["id"] == tl_id and t["name"] == "Test TL Updated" for t in tls)

    # Delete
    res = client.delete(f"/api/regions/ernakulam/team-leaders/{tl_id}")
    assert res.status_code == 200
    print("   [OK] Deleted TL")

    print("\n6. Testing ACSO & Center CRUD on Ernakulam...")
    acso_payload = {
        "center_name": "Aluva",
        "acso_name": "Officer Rajesh",
        "pd_adl_center_key": "Aluva",
        "pd_adtv_center_key": "Aluva",
        "pp_adl_center_key": "Aluva",
        "pp_adtv_center_key": "Aluva",
        "adl_center_display": "Aluva",
        "adtv_center_display": "Aluva"
    }
    res = client.post("/api/regions/ernakulam/acsos", json=acso_payload)
    assert res.status_code == 200
    acso_id = res.json()["id"]
    print(f"   [OK] Created ACSO ID: {acso_id}")

    # Edit
    acso_payload["acso_name"] = "Officer Rajesh K"
    res = client.put(f"/api/regions/ernakulam/acsos/{acso_id}", json=acso_payload)
    assert res.status_code == 200
    print("   [OK] Updated ACSO")

    # Delete
    res = client.delete(f"/api/regions/ernakulam/acsos/{acso_id}")
    assert res.status_code == 200
    print("   [OK] Deleted ACSO")

    print("\n7. Testing Employee CRUD on Ernakulam...")
    emp_payload = {
        "emp_code": "5555",
        "name": "Kiran Kumar",
        "role": "Technician",
        "center_name": "Aluva",
        "phone": "9846123456"
    }
    res = client.post("/api/regions/ernakulam/employees", json=emp_payload)
    assert res.status_code == 200
    emp_id = res.json()["id"]
    print(f"   [OK] Created Employee ID: {emp_id}")

    # Edit
    emp_payload["phone"] = "9846999999"
    res = client.put(f"/api/regions/ernakulam/employees/{emp_id}", json=emp_payload)
    assert res.status_code == 200
    print("   [OK] Updated Employee")

    # Delete
    res = client.delete(f"/api/regions/ernakulam/employees/{emp_id}")
    assert res.status_code == 200
    print("   [OK] Deleted Employee")

    print("\n8. Testing Report Generation Endpoint...")
    res = client.post("/api/regions/thrissur/generate-reports")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "OK"
    assert len(data["images"]) == 4
    print("   [OK] Generated all 4 Retina report images via API.")

    print("\nALL TEST SUITE CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_routes()
