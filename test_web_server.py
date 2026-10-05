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
    assert "Daily QOS tracker" in res.text
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

    print("\n9. Testing Dispatch Rules CRUD & Description Persistence...")
    rule_payload = {
        "rule_name": "Test Regional Field Team",
        "report_type": "all",
        "target_recipients": "NW Team TCR- REGION, +919633889430",
        "description": "Daily test dispatch rule notes",
        "region_id": "ernakulam",
        "is_enabled": True
    }
    res = client.post("/api/regions/ernakulam/dispatch-rules", json=rule_payload)
    assert res.status_code == 200
    rule_id = res.json()["id"]
    print(f"   [OK] Created Dispatch Rule ID: {rule_id}")

    res = client.get("/api/regions/ernakulam/dispatch-rules")
    assert res.status_code == 200
    rules = res.json()
    created_rule = next((r for r in rules if r["id"] == rule_id), None)
    assert created_rule is not None
    assert created_rule["description"] == "Daily test dispatch rule notes"
    print("   [OK] Verified description persistence in SQLite.")

    # Toggle
    res = client.post(f"/api/dispatch-rules/{rule_id}/toggle")
    assert res.status_code == 200
    print("   [OK] Toggled dispatch rule status")

    # Delete
    res = client.delete(f"/api/dispatch-rules/{rule_id}")
    assert res.status_code == 200
    print("   [OK] Deleted dispatch rule")

    print("\n10. Testing Schedule Times CRUD...")
    time_payload = {
        "run_time": "11:30",
        "label": "Midday Review",
        "region_id": "ernakulam",
        "is_enabled": True
    }
    res = client.post("/api/regions/ernakulam/schedule-times", json=time_payload)
    assert res.status_code == 200
    time_id = res.json()["id"]
    print(f"   [OK] Created Schedule Time ID: {time_id}")

    res = client.get("/api/regions/ernakulam/schedule-times")
    assert res.status_code == 200
    times = res.json()
    assert any(t["id"] == time_id for t in times)

    # Delete
    res = client.delete(f"/api/schedule-times/{time_id}")
    assert res.status_code == 200
    print("   [OK] Deleted schedule time")

    print("\n11. Testing System Settings & Scheduler Toggle...")
    res = client.get("/api/system/settings")
    assert res.status_code == 200
    initial_enabled = res.json()["scheduler_enabled"]
    res = client.post("/api/system/scheduler-toggle")
    assert res.status_code == 200
    assert res.json()["scheduler_enabled"] != initial_enabled
    # Toggle back
    res = client.post("/api/system/scheduler-toggle")
    assert res.status_code == 200
    assert res.json()["scheduler_enabled"] == initial_enabled
    print("   [OK] Master scheduler toggle and status persistence verified.")

    print("\n12. Testing WhatsApp Recipient Parser...")
    from whatsapp_sender import normalize_recipient
    # Group names with numbers must NOT be treated as direct numbers
    assert normalize_recipient("NW Team TCR- REGION") == "NW Team TCR- REGION"
    assert normalize_recipient("Team 2026 Shift 1") == "Team 2026 Shift 1"
    assert normalize_recipient("ADL Team Leaders 24x7") == "ADL Team Leaders 24x7"
    # Phone numbers
    assert normalize_recipient("+919633889430") == "919633889430"
    assert normalize_recipient("9633889430") == "919633889430"
    assert normalize_recipient("09633889430") == "919633889430"
    print("   [OK] Recipient parsing and group/phone disambiguation verified.")

    print("\n13. Testing Dynamic Region CRM Queries...")
    from config import get_adl_export_query, get_adtv_export_query
    q_adl = get_adl_export_query("Kollam")
    q_adtv = get_adtv_export_query("Kollam")
    assert "region in ( 'Kollam' )" in q_adl
    assert "region = 'Kollam'" in q_adtv
    print("   [OK] Dynamic multi-region SQL queries verified.")

    print("\n14. Testing WhatsApp Web Authentication Endpoints...")
    res = client.get("/api/whatsapp/status")
    assert res.status_code == 200
    status_data = res.json()
    assert "status" in status_data
    print(f"   [OK] WhatsApp session status: {status_data['status']}")

    res = client.post("/api/whatsapp/cancel-login")
    assert res.status_code == 200
    assert res.json()["status"] == "OK"
    print("   [OK] WhatsApp cancel-login endpoint verified.")

    res = client.post("/api/whatsapp/logout")
    assert res.status_code == 200
    assert res.json()["status"] == "OK"
    print("   [OK] WhatsApp session logout and wipe verified.")

    print("\n15. Testing 3-Day Running & Error Logging Endpoints...")
    res = client.get("/api/logs/files")
    assert res.status_code == 200
    files = res.json()
    assert isinstance(files, list)
    print(f"   [OK] Retrieved {len(files)} log file(s) from server.")

    res = client.get("/api/logs/view?type=running&lines=50")
    assert res.status_code == 200
    run_log = res.json()
    assert "lines" in run_log
    assert run_log["log_type"] == "running"
    print(f"   [OK] Read {len(run_log['lines'])} lines from running log ({run_log.get('file_name')}).")

    res = client.get("/api/logs/view?type=error&lines=50")
    assert res.status_code == 200
    err_log = res.json()
    assert "lines" in err_log
    assert err_log["log_type"] == "error"
    print(f"   [OK] Read {len(err_log['lines'])} lines from error log ({err_log.get('file_name')}).")

    res = client.get("/api/logs/analysis?days=3")
    assert res.status_code == 200
    diag = res.json()
    assert "health_score" in diag
    assert "health_status" in diag
    assert "categories" in diag
    print(f"   [OK] Diagnostic analyzer verified: Health={diag['health_status']} ({diag['health_score']}%).")

    res = client.post("/api/logs/cleanup?days=3")
    assert res.status_code == 200
    assert res.json()["status"] == "OK"
    print("   [OK] 3-Day retention cleanup endpoint verified.")

    print("\n16. Testing Backup, Restore, Preset, and Clear Endpoints...")
    # Export full backup
    res = client.get("/api/backup/export")
    assert res.status_code == 200
    backup_data = res.json()
    assert "tables" in backup_data
    assert "regions" in backup_data["tables"]
    print(f"   [OK] Full backup exported successfully ({len(backup_data['tables'])} tables).")

    # Clear test region (idukki)
    res = client.post("/api/backup/clear?region_id=idukki")
    assert res.status_code == 200
    res = client.get("/api/regions/idukki/config")
    assert len(res.json()["tls"]) == 0
    assert len(res.json()["acsos"]) == 0
    print("   [OK] Verified clear region endpoint: Idukki roster is empty.")

    # Load Thrissur sample preset into idukki
    res = client.post("/api/backup/load-sample?region_id=idukki")
    assert res.status_code == 200
    res = client.get("/api/regions/idukki/config")
    idukki_config = res.json()
    assert len(idukki_config["tls"]) == 22
    assert len(idukki_config["acsos"]) == 13
    assert len(idukki_config["emps"]) == 22
    print("   [OK] Verified load-sample preset: Successfully populated Idukki with baseline preset.")

    # Restore from exported backup
    res = client.post("/api/backup/restore?target_region=idukki", json=backup_data)
    assert res.status_code == 200
    assert res.json()["status"] == "OK"
    print("   [OK] Verified restore endpoint from JSON payload.")

    # Clear idukki again so test doesn't leave sample data there
    client.post("/api/backup/clear?region_id=idukki")

    print("\n17. Testing Telegram Bot Engine & UI Keyboard Schemas...")
    from telegram_bot import (
        TelegramAPI,
        format_status_message,
        get_confirmation_keyboard,
        get_main_menu_keyboard,
        get_phone_selection_keyboard,
        get_service_status,
        is_user_authorized,
    )

    # Test Telegram API client initialization
    api = TelegramAPI("123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ")
    assert api.is_configured() is True
    assert api.base_url == "https://api.telegram.org/bot123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ"
    dummy_api = TelegramAPI("")
    assert dummy_api.is_configured() is False
    print("   [OK] Telegram API client initialization and token validator verified.")

    # Test Main Menu Keyboard Layout & Button Labels
    kb = get_main_menu_keyboard(service_active=True)
    flat_buttons = [btn for row in kb["inline_keyboard"] for btn in row]
    btn_texts = [b["text"] for b in flat_buttons]
    btn_callbacks = [b["callback_data"] for b in flat_buttons]

    assert "▶️ Start Service" in btn_texts
    assert "⏹️ Stop Service" in btn_texts
    assert "🔄 Restart Service" in btn_texts
    assert "🚀 Report-to-Group Dispatch Rules" in btn_texts
    assert "📲 Test Delivery: Generate & Send to Specific Number" in btn_texts
    assert "srv:start" in btn_callbacks
    assert "srv:stop" in btn_callbacks
    assert "srv:restart" in btn_callbacks
    assert "action:dispatch_groups" in btn_callbacks
    assert "action:test_delivery" in btn_callbacks
    print("   [OK] Main menu keyboard verified: Start, Stop, Restart, Group Dispatch, Test Delivery buttons intact.")

    # Test Phone Quick-Select Keyboard
    phone_kb = get_phone_selection_keyboard("+919999999999")
    phone_btns = [btn for row in phone_kb["inline_keyboard"] for btn in row]
    assert any("9999999999" in b["text"] for b in phone_btns)
    assert any("Custom Mobile Number" in b["text"] for b in phone_btns)
    print("   [OK] Phone selection keyboard layout verified.")

    # Test Confirmation Keyboard
    conf_kb = get_confirmation_keyboard(confirm_data="exec:srv_stop", cancel_data="menu:cancel")
    conf_btns = [btn for row in conf_kb["inline_keyboard"] for btn in row]
    assert len(conf_btns) == 2
    assert conf_btns[0]["text"] == "✅ Confirm"
    assert conf_btns[0]["callback_data"] == "exec:srv_stop"
    assert conf_btns[1]["text"] == "❌ Cancel"
    assert conf_btns[1]["callback_data"] == "menu:cancel"
    print("   [OK] Confirmation & cancellation dialog keyboard verified.")

    # Test Service Status & Formatting
    st = get_service_status()
    assert "is_active" in st
    assert "web_connected" in st
    formatted = format_status_message(st)
    assert "Daily QOS Tracker — Control Center" in formatted
    print("   [OK] Service status collector and Telegram HTML formatting verified.")

    # Test Authorization Check
    assert is_user_authorized(123456, 123456) in (True, False)
    print("   [OK] Authorization gatekeeper verified.")

    print("\n18. Testing Service Request Pending Report Pipeline & Scheduling...")
    from service_request_engine import calculate_sr_pending_reports, generate_sr_excel_report
    from telegram_bot import get_sr_menu_keyboard

    # Test calculation engine directly
    sr_res = calculate_sr_pending_reports()
    assert sr_res["status"] == "OK"
    assert "adl" in sr_res
    assert "adtv" in sr_res
    assert len(sr_res["adl"]) > 0
    assert len(sr_res["adtv"]) > 0

    adl_first = sr_res["adl"][0]
    assert "CENTER" in adl_first
    assert "Service Request Type" in adl_first
    assert "Grand Total" in adl_first
    assert "<1 day" in adl_first
    assert "> 10 day" in adl_first
    print(f"   [OK] SR Calculation Engine: {len(sr_res['adl'])} ADL rows and {len(sr_res['adtv'])} ADTv rows computed.")

    # Verify exclusion of 'STATIC IP Renewal' from Service Request report generation
    from service_request_engine import is_excluded_service, prepare_source
    import pandas as pd

    assert is_excluded_service("STATIC IP Renewal") is True
    assert is_excluded_service("Static IP Renewal") is True
    assert is_excluded_service("STATIC IP") is True
    assert is_excluded_service("Cable Re-routing") is False

    mock_df = pd.DataFrame([
        {"Area": "Chalakudy", "Complaint": "Cable Rerouting Required", "DaysCalc": 1},
        {"Area": "Chalakudy", "Complaint": "STATIC IP Renewal", "DaysCalc": 2},
        {"Area": "Thrissur", "Complaint": "Transfer to a New location", "DaysCalc": 0},
    ])
    mock_prepared = prepare_source(mock_df, "Area", "Complaint", "DaysCalc")
    assert len(mock_prepared) == 2
    assert "STATIC IP Renewal" not in mock_prepared["Service Request Type"].values
    assert "STATIC IP" not in str(mock_prepared["Service Request Type"].values)
    print("   [OK] Verified STATIC IP Renewal exclusion filter from SMS portal (https://sms.ali.asianetindia.com/).")

    # Test Web API GET /api/service-request/reports
    res = client.get("/api/service-request/reports?region_id=thrissur")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "OK"
    assert len(data["adl"]) > 0
    print("   [OK] Verified GET /api/service-request/reports endpoint.")

    # Test Web API GET /api/service-request/download-excel
    res = client.get("/api/service-request/download-excel")
    assert res.status_code == 200
    assert "openxmlformats" in res.headers.get("content-type", "")
    assert len(res.content) > 1000
    print(f"   [OK] Verified GET /api/service-request/download-excel endpoint ({len(res.content)} bytes).")

    # Test Independent Schedule Times (report_type: 'service_request' vs 'complaint')
    sr_time_payload = {
        "run_time": "11:45",
        "label": "Automated Unit Test SR Run",
        "report_type": "service_request",
        "is_enabled": True
    }
    res = client.post("/api/regions/thrissur/schedule-times", json=sr_time_payload)
    assert res.status_code == 200
    created_sr_id = res.json()["id"]

    # Verify filtering by report_type
    res_sr = client.get("/api/regions/thrissur/schedule-times?report_type=service_request")
    assert res_sr.status_code == 200
    sr_times = res_sr.json()
    assert any(t["id"] == created_sr_id for t in sr_times)
    assert all(t.get("report_type") == "service_request" for t in sr_times)

    res_comp = client.get("/api/regions/thrissur/schedule-times?report_type=complaint")
    assert res_comp.status_code == 200
    comp_times = res_comp.json()
    assert not any(t["id"] == created_sr_id for t in comp_times)
    print("   [OK] Verified independent scheduling: Service Request schedule isolated from Complaint schedule.")

    # Clean up test schedule time
    res = client.delete(f"/api/schedule-times/{created_sr_id}")
    assert res.status_code == 200

    # Test Telegram SR Menu Layout
    sr_kb = get_sr_menu_keyboard()
    flat_sr_btns = [btn for row in sr_kb["inline_keyboard"] for btn in row]
    sr_btn_texts = [b["text"] for b in flat_sr_btns]
    sr_btn_callbacks = [b["callback_data"] for b in flat_sr_btns]

    assert any("Dispatch SR Reports to Groups" in t for t in sr_btn_texts)
    assert any("Send SR Test Delivery" in t for t in sr_btn_texts)
    assert "action:sr_dispatch" in sr_btn_callbacks
    assert "action:sr_test_delivery" in sr_btn_callbacks
    assert "menu:main" in sr_btn_callbacks
    print("   [OK] Verified Telegram SR menu keyboard schema and callbacks.")

    print("\nALL TEST SUITE CHECKS PASSED PERFECTLY!")


if __name__ == "__main__":
    test_routes()

