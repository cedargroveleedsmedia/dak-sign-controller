from flask import Flask, render_template, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone
import json
import copy

app = Flask(__name__)

# --- Config ---
SIGN_IP = "192.168.1.51"
USERNAME = "Dak"
PASSWORD = "DakPassword"
BASE_URL = f"http://{SIGN_IP}"

def auth():
    return HTTPBasicAuth(USERNAME, PASSWORD)

def strip_bom(raw_bytes):
    text = raw_bytes.decode("utf-8-sig").strip()
    while text.startswith("\ufeff"):
        text = text.lstrip("\ufeff").strip()
    return text

def sign_get(path):
    try:
        r = requests.get(f"{BASE_URL}{path}", auth=auth(), timeout=60)
        raw = strip_bom(r.content)
        try:
            return json.loads(raw), r.status_code
        except Exception:
            return raw, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign — check IP/network"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

def sign_put(path, data=None):
    try:
        r = requests.put(f"{BASE_URL}{path}", auth=auth(), json=data, timeout=60)
        return r.text, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

def sign_post(path, data=None):
    try:
        r = requests.post(f"{BASE_URL}{path}", auth=auth(), data=data, timeout=60)
        return r.text, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

def get_messages():
    r = requests.get(f"{BASE_URL}/ECCB/getmessagelist.php", auth=auth(), timeout=60)
    raw = strip_bom(r.content)
    data = json.loads(raw)
    return data.get("Messages") or data.get("messages") or []

# Headers the native ECCB web UI sends
def _eccb_headers(host):
    return {
        "Content-Type": "application/json",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"http://{host}/ECCB/EditMessage.html",
        "Origin": f"http://{host}",
    }

def _delete_headers(host):
    return {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"http://{host}/ECCB/EditMessage.html",
        "Origin": f"http://{host}",
    }

def save_message_obj(msg_obj):
    """POST message as raw JSON body with the exact headers the native UI sends."""
    r = requests.post(
        f"{BASE_URL}/ECCB/savemessage.php",
        auth=auth(),
        headers=_eccb_headers(SIGN_IP),
        json=msg_obj,
        timeout=60,
    )
    app.logger.info(f"savemessage -> {r.status_code}: {r.content[:200]}")
    return r.text, r.status_code

def delete_message_by_name(name):
    """Delete using form-urlencoded body with AJAX headers (what the native browser sends)."""
    r = requests.post(
        f"{BASE_URL}/ECCB/deletemessage.php",
        auth=auth(),
        headers=_delete_headers(SIGN_IP),
        data={"Name": name},
        timeout=60,
    )
    app.logger.info(f"deletemessage '{name}' -> {r.status_code}: {r.content[:200]}")
    return r.text, r.status_code

def delete_message_by_name(name):
    """Delete a message by name."""
    r = requests.post(f"{BASE_URL}/ECCB/deletemessage.php",
                      auth=auth(),
                      data={"Name": name},
                      timeout=60)
    return r.text, r.status_code

# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", sign_ip=SIGN_IP)

@app.route("/api/status")
def api_status():
    data, code = sign_get("/daktronics/syscontrol/1.0/status")
    return jsonify(data), code

@app.route("/api/configuration")
def api_configuration():
    data, code = sign_get("/daktronics/syscontrol/1.0/configuration")
    return jsonify(data), code

@app.route("/api/dimming")
def api_dimming():
    data, code = sign_get("/daktronics/syscontrol/1.0/configuration/output/0/dimming")
    return jsonify(data), code

@app.route("/api/messages")
def api_messages():
    try:
        msgs = get_messages()
        return jsonify({"messages": msgs}), 200
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/create", methods=["POST"])
def api_create_message():
    """Create a brand new message from a simple form submission."""
    body = request.json or {}
    name = body.get("name", "").strip()
    text = body.get("text", "").strip()
    font = body.get("font", "dak_eccb_black-webfont.ttf")
    font_size = float(body.get("fontSize", 17.5))
    hold = body.get("holdTime", "P0Y0M0DT0H0M5S")

    if not name or not text:
        return jsonify({"error": "name and text are required"}), 400

    # Build a message object matching the ECCB structure
    msg = {
        "Name": name,
        "Height": 32,
        "Width": 72,
        "IsPermanent": False,
        "Frames": [
            {
                "HoldTime": hold,
                "Lines": [
                    {"Font": font, "FontSize": font_size, "Text": line}
                    for line in text.splitlines() if line
                ] or [{"Font": font, "FontSize": font_size, "Text": text}],
                "LineSpacing": 0
            }
        ],
        "CurrentSchedule": {
            "Enabled": body.get("enabled", True),
            "StartTime": "PT0H0M0S",
            "EndTime": "PT0H0M0S",
            "Dow": 127
        }
    }
    try:
        result, code = save_message_obj(msg)
        return jsonify({"result": result, "status": code, "message": msg}), code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/update", methods=["POST"])
def api_update_message():
    """Update an existing message.
    Strategy: delete the old one by name, then save the updated version.
    This avoids the ECCB creating duplicates when it can't match by name."""
    body = request.json or {}
    original_name = body.get("name")
    if not original_name:
        return jsonify({"error": "name required"}), 400

    try:
        msgs = get_messages()
        msg = next((m for m in msgs if m.get("Name") == original_name), None)
        if msg is None:
            return jsonify({"error": f"Message '{original_name}' not found"}), 404

        msg = copy.deepcopy(msg)

        # Apply frame text updates
        new_frames = body.get("frames")
        if new_frames:
            for fu in new_frames:
                fi = fu.get("frameIndex", 0)
                if fi < len(msg["Frames"]):
                    frame = msg["Frames"][fi]
                    new_lines = fu.get("lines", [])
                    for li, text in enumerate(new_lines):
                        if li < len(frame["Lines"]):
                            frame["Lines"][li]["Text"] = text

        # Apply schedule changes
        sched = body.get("schedule")
        if sched is not None:
            msg["CurrentSchedule"].update(sched)

        # Apply name change
        new_name = body.get("newName", "").strip()
        if new_name and new_name != original_name:
            msg["Name"] = new_name

        # Delete old, save new
        del_result, del_code = delete_message_by_name(original_name)
        if del_code not in (200, 204):
            # Log but continue — might still work
            app.logger.warning(f"Delete before update returned {del_code}: {del_result}")

        save_result, save_code = save_message_obj(msg)
        return jsonify({"result": save_result, "status": save_code, "message": msg}), save_code

    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/toggle", methods=["POST"])
def api_toggle_message():
    body = request.json or {}
    name = body.get("name")
    enabled = body.get("enabled")
    if name is None or enabled is None:
        return jsonify({"error": "name and enabled required"}), 400
    try:
        msgs = get_messages()
        msg = next((m for m in msgs if m.get("Name") == name), None)
        if msg is None:
            return jsonify({"error": f"Message '{name}' not found"}), 404
        msg = copy.deepcopy(msg)
        msg["CurrentSchedule"]["Enabled"] = enabled

        # Same delete-then-save strategy
        delete_message_by_name(name)
        result, code = save_message_obj(msg)
        return jsonify({"result": result, "status": code, "enabled": enabled}), code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/delete", methods=["POST"])
def api_delete_message():
    body = request.json or {}
    name = body.get("Name") or body.get("name")
    if not name:
        return jsonify({"error": "Name required"}), 400
    result, code = delete_message_by_name(name)
    return jsonify({"result": result, "status": code}), code

@app.route("/api/messages/probe", methods=["POST"])
def api_probe_save():
    """Debug endpoint: try all POST formats against savemessage.php and return all results."""
    body = request.json or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        msgs = get_messages()
        msg = next((m for m in msgs if m.get("Name") == name), None)
        if not msg:
            return jsonify({"error": f"'{name}' not found"}), 404
        msg = copy.deepcopy(msg)
        results = []
        formats = [
            ("raw_json",       dict(json=msg)),
            ("envelope_json",  dict(json={"MessageRequest": msg})),
            ("form_Message",   dict(data={"Message": json.dumps(msg)})),
            ("form_message_lc",dict(data={"message": json.dumps(msg)})),
            ("delete_test",    None),  # sentinel
        ]
        for label, kwargs in formats:
            if kwargs is None:
                # test delete with correct headers
                r = requests.post(f"{BASE_URL}/ECCB/deletemessage.php",
                                  auth=auth(), headers=_delete_headers(SIGN_IP),
                                  data={"Name": name}, timeout=60)
                results.append({"format": "delete_form_urlencoded_headers", "status": r.status_code, "body": r.text[:300]})
            else:
                # add correct headers to all save attempts
                h = _eccb_headers(SIGN_IP) if "json" in kwargs else _delete_headers(SIGN_IP)
                r = requests.post(f"{BASE_URL}/ECCB/savemessage.php",
                                  auth=auth(), headers=h, timeout=60, **kwargs)
                results.append({"format": label, "status": r.status_code, "body": r.text[:300]})
        # Check final message count
        msgs_after = get_messages()
        return jsonify({"results": results, "msg_count_after": len(msgs_after),
                        "msg_names_after": [m.get("Name") for m in msgs_after]}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/reorder", methods=["POST"])
def api_reorder_messages():
    payload = request.json or {}
    text, code = sign_post("/ECCB/updateMessageSchedulePosition.php", data=payload)
    return jsonify({"result": text, "status": code}), code

@app.route("/api/sync-time", methods=["POST"])
def api_sync_time():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    text, code = sign_put(f"/daktronics/syscontrol/1.0/datetime?Time={now}")
    return jsonify({"result": text, "time_sent": now, "status": code}), code

@app.route("/api/brightness", methods=["POST"])
def api_set_brightness():
    body = request.json or {}
    text, code = sign_put("/daktronics/syscontrol/1.0/configuration/output/0/dimming", data=body)
    return jsonify({"result": text, "status": code}), code

@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    global SIGN_IP, USERNAME, PASSWORD, BASE_URL
    body = request.json or {}
    SIGN_IP  = body.get("ip", SIGN_IP)
    USERNAME = body.get("username", USERNAME)
    PASSWORD = body.get("password", PASSWORD)
    BASE_URL = f"http://{SIGN_IP}"
    return jsonify({"ok": True, "ip": SIGN_IP, "username": USERNAME})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({"ip": SIGN_IP, "username": USERNAME, "password": PASSWORD})

@app.route("/api/raw", methods=["POST"])
def api_raw():
    body   = request.json or {}
    path   = body.get("path", "/")
    method = body.get("method", "GET").upper()
    data   = body.get("body", None)
    try:
        r = requests.request(
            method,
            f"{BASE_URL}{path}",
            auth=auth(),
            json=json.loads(data) if data and method != "GET" else None,
            timeout=60
        )
        try:
            raw = strip_bom(r.content)
            return jsonify(json.loads(raw)), r.status_code
        except Exception:
            return jsonify({"raw": strip_bom(r.content)}), r.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
