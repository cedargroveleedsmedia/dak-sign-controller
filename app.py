from flask import Flask, render_template, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone
import json

app = Flask(__name__)

# --- Config ---
SIGN_IP = "192.168.1.51"
USERNAME = "Dak"
PASSWORD = "DakPassword"
BASE_URL = f"http://{SIGN_IP}"
ECCB_URL = f"{BASE_URL}/ECCB"
API_URL  = f"{BASE_URL}/daktronics/syscontrol/1.0"

def auth():
    return HTTPBasicAuth(USERNAME, PASSWORD)

def sign_get(path):
    try:
        r = requests.get(f"{BASE_URL}{path}", auth=auth(), timeout=5)
        return r.json() if r.headers.get("content-type","").startswith("application/json") else r.text, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign — check IP/network"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

def sign_put(path, data=None):
    try:
        r = requests.put(f"{BASE_URL}{path}", auth=auth(), json=data, timeout=5)
        return r.text, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

def sign_post(path, data=None):
    try:
        r = requests.post(f"{BASE_URL}{path}", auth=auth(), data=data, timeout=5)
        return r.text, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign"}, 503
    except Exception as e:
        return {"error": str(e)}, 500

# Routes

@app.route("/")
def index():
    return render_template("index.html", sign_ip=SIGN_IP)

# Status & config
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

# Messages — strip UTF-8 BOM that ECCB firmware prepends, normalize key to lowercase
@app.route("/api/messages")
def api_messages():
    try:
        r = requests.get(f"{BASE_URL}/ECCB/getmessagelist.php", auth=auth(), timeout=5)
        # utf-8-sig codec automatically strips the BOM (0xEF 0xBB 0xBF / ï»¿)
        raw = r.content.decode("utf-8-sig").strip()
        data = json.loads(raw)
        msgs = data.get("Messages") or data.get("messages") or data.get("messageList") or []
        return jsonify({"messages": msgs}), r.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/save", methods=["POST"])
def api_save_message():
    payload = request.json or {}
    text, code = sign_post("/ECCB/savemessage.php", data=payload)
    return jsonify({"result": text, "status": code}), code

@app.route("/api/messages/delete", methods=["POST"])
def api_delete_message():
    payload = request.json or {}
    text, code = sign_post("/ECCB/deletemessage.php", data=payload)
    return jsonify({"result": text, "status": code}), code

@app.route("/api/messages/reorder", methods=["POST"])
def api_reorder_messages():
    payload = request.json or {}
    text, code = sign_post("/ECCB/updateMessageSchedulePosition.php", data=payload)
    return jsonify({"result": text, "status": code}), code

# Datetime sync
@app.route("/api/sync-time", methods=["POST"])
def api_sync_time():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    text, code = sign_put(f"/daktronics/syscontrol/1.0/datetime?Time={now}")
    return jsonify({"result": text, "time_sent": now, "status": code}), code

# Brightness
@app.route("/api/brightness", methods=["POST"])
def api_set_brightness():
    body = request.json or {}
    text, code = sign_put("/daktronics/syscontrol/1.0/configuration/output/0/dimming", data=body)
    return jsonify({"result": text, "status": code}), code

# Settings update (live)
@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    global SIGN_IP, USERNAME, PASSWORD, BASE_URL, ECCB_URL, API_URL
    body = request.json or {}
    SIGN_IP  = body.get("ip", SIGN_IP)
    USERNAME = body.get("username", USERNAME)
    PASSWORD = body.get("password", PASSWORD)
    BASE_URL = f"http://{SIGN_IP}"
    ECCB_URL = f"{BASE_URL}/ECCB"
    API_URL  = f"{BASE_URL}/daktronics/syscontrol/1.0"
    return jsonify({"ok": True, "ip": SIGN_IP, "username": USERNAME})

@app.route("/api/settings", methods=["GET"])
def api_get_settings():
    return jsonify({"ip": SIGN_IP, "username": USERNAME, "password": PASSWORD})

# Raw proxy
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
            timeout=5
        )
        try:
            return jsonify(r.json()), r.status_code
        except Exception:
            return jsonify({"raw": r.text}), r.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
