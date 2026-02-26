from flask import Flask, render_template, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
from datetime import datetime, timezone
import json
import copy
import threading

app = Flask(__name__)

# Google OAuth — must be initialised before any routes
from auth import init_auth
init_auth(app)

# --- Config ---
SIGN_IP  = "192.168.1.51"
USERNAME = "Dak"
PASSWORD = "DakPassword"
BASE_URL = f"http://{SIGN_IP}"

# --- Session management ---
# We keep a persistent requests.Session so cookies are maintained between calls.
# The ECCB PHP backend requires a valid session cookie set by login.cgi.
_session_lock  = threading.Lock()
_session       = None
_session_valid = False


def _make_session():
    s = requests.Session()
    s.auth = HTTPBasicAuth(USERNAME, PASSWORD)
    return s


def get_session():
    """Return a logged-in session, creating/refreshing as needed."""
    global _session, _session_valid
    with _session_lock:
        if _session is None:
            _session = _make_session()
        if not _session_valid:
            _login(_session)
    return _session


def _login(s):
    """POST credentials to login.cgi to obtain a session cookie."""
    global _session_valid
    try:
        # First hit cookiechecker so the sign knows we want a session
        s.get(f"{BASE_URL}/cookiechecker?uri=/ECCB/index.html", timeout=60)
        # Then POST to login.cgi with the credentials
        r = s.post(
            f"{BASE_URL}/login.cgi",
            data={"username": USERNAME, "password": PASSWORD, "uri": "/ECCB/index.html"},
            timeout=60,
            allow_redirects=True,
        )
        app.logger.info(f"login.cgi -> {r.status_code}, cookies: {dict(s.cookies)}")
        _session_valid = True
        return True
    except Exception as e:
        app.logger.error(f"Login failed: {e}")
        _session_valid = False
        return False


def invalidate_session():
    global _session_valid
    with _session_lock:
        _session_valid = False


def strip_bom(raw_bytes):
    text = raw_bytes.decode("utf-8-sig").strip()
    while text.startswith("\ufeff"):
        text = text.lstrip("\ufeff").strip()
    return text


def eccb_get(path):
    s = get_session()
    try:
        r = s.get(f"{BASE_URL}{path}", timeout=60)
        raw = strip_bom(r.content)
        try:
            return json.loads(raw), r.status_code
        except Exception:
            return raw, r.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "Cannot reach sign"}, 503
    except Exception as e:
        return {"error": str(e)}, 500


def eccb_put(path, data=None):
    s = get_session()
    try:
        r = s.put(f"{BASE_URL}{path}", json=data, timeout=60)
        return r.text, r.status_code
    except Exception as e:
        return {"error": str(e)}, 500


def get_messages():
    s = get_session()
    r = s.get(f"{BASE_URL}/ECCB/getmessagelist.php", timeout=60)
    raw = strip_bom(r.content)
    data = json.loads(raw)
    return data.get("Messages") or data.get("messages") or []


def save_message_obj(msg_obj):
    """POST message to savemessage.php.

    Confirmed from Fiddler capture of native UI:
    - Content-Type: application/x-www-form-urlencoded
    - Field name: 'json'
    - Value: JSON-serialized message object
    - Success response: BOM-only (0 bytes after stripping BOM) with HTTP 200
      (BOM-only IS the success indicator — the sign does not return {"Status":"OK"})
    """
    msg_json = json.dumps(msg_obj)
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/ECCB/EditMessage.html",
        "Origin": BASE_URL,
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    s = get_session()
    r = s.post(
        f"{BASE_URL}/ECCB/savemessage.php",
        data={"json": msg_json},
        headers=headers,
        timeout=60,
    )
    app.logger.info(f"savemessage status={r.status_code} bytes={len(r.content)}")
    return strip_bom(r.content), r.status_code


def delete_message_by_name(name):
    """Delete via POST to deletemessage.php.

    Confirmed from Fiddler capture of native UI:
    - Method: POST
    - Content-Type: application/x-www-form-urlencoded
    - Field name: 'Message'
    - Value: 'name.vmpl'  (filename with .vmpl extension, not just the name)
    - Success response: BOM-only with HTTP 200
    """
    s = get_session()
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE_URL}/ECCB/EditMessage.html",
        "Accept": "*/*",
    }
    filename = f"{name}.vmpl"
    r = s.post(
        f"{BASE_URL}/ECCB/deletemessage.php",
        data={"Message": filename},
        headers=headers,
        timeout=60,
    )
    app.logger.info(f"deletemessage POST '{filename}' -> {r.status_code}: {r.content[:200]}")
    return strip_bom(r.content), r.status_code


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html", sign_ip=SIGN_IP)

@app.route("/api/status")
def api_status():
    data, code = eccb_get("/daktronics/syscontrol/1.0/status")
    return jsonify(data), code

@app.route("/api/configuration")
def api_configuration():
    data, code = eccb_get("/daktronics/syscontrol/1.0/configuration")
    return jsonify(data), code

@app.route("/api/dimming")
def api_dimming():
    data, code = eccb_get("/daktronics/syscontrol/1.0/configuration/output/0/dimming")
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
    body       = request.json or {}
    name       = body.get("name", "").strip()
    text       = body.get("text", "").strip()
    extra      = body.get("extraLines", [])          # additional line texts for multi-line
    font       = body.get("font", "dak_eccb_black-webfont.ttf")
    font_size  = float(body.get("fontSize", 17.5))
    hold       = body.get("holdTime", "P0Y0M0DT0H0M5S")
    sched_in   = body.get("schedule", {})
    if not name:
        return jsonify({"error": "name is required"}), 400

    # Build lines list: first line from text, rest from extraLines
    all_lines = [text] + [l for l in extra if isinstance(l, str)]
    all_lines = [l for l in all_lines if l.strip()] or [text or ""]
    print(f"[CREATE] name={name!r} text={text!r} extra={extra!r} all_lines={all_lines!r}", flush=True)

    # Pad to 4 lines (sign expects exactly 4 lines per frame)
    while len(all_lines) < 4:
        all_lines.append("")

    msg = {
        "Name": name,
        "Height": 32,
        "Width": 72,
        "IsPermanent": False,
        "DataSrc": "",
        "DataFormat": "",
        "DataCategory": "",
        "Frames": [{
            "HoldTime": hold,
            "Lines": [{"Font": font, "FontSize": font_size, "Text": l} for l in all_lines],
            "LineSpacing": 0,
        }],
        "CurrentSchedule": {
            "Enabled":   body.get("enabled", True),
            "StartTime": sched_in.get("StartTime", "PT0H0M0S"),
            "EndTime":   sched_in.get("EndTime",   "PT0H0M0S"),
            "Dow":       sched_in.get("Dow", 127),
            "IsAllDay":  sched_in.get("IsAllDay", True),
        },
    }
    import json
    print(f"[MSG] Sending to sign: {json.dumps(msg, indent=2)}", flush=True)
    try:
        result, code = save_message_obj(msg)
        return jsonify({"result": result, "status": code, "message": msg}), code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/update", methods=["POST"])
def api_update_message():
    body          = request.json or {}
    original_name = body.get("name")
    if not original_name:
        return jsonify({"error": "name required"}), 400
    try:
        msgs = get_messages()
        msg  = next((m for m in msgs if m.get("Name") == original_name), None)
        if msg is None:
            return jsonify({"error": f"Message '{original_name}' not found"}), 404
        msg = copy.deepcopy(msg)

        # Apply frame text edits — supports line count changes from template picker
        for fu in (body.get("frames") or []):
            fi = fu.get("frameIndex", 0)
            if fi < len(msg["Frames"]):
                new_lines = fu.get("lines", [])
                frame     = msg["Frames"][fi]
                font      = (frame["Lines"][0].get("Font", "dak_eccb_black-webfont.ttf")
                             if frame.get("Lines") else "dak_eccb_black-webfont.ttf")
                font_size = (frame["Lines"][0].get("FontSize", 17.5)
                             if frame.get("Lines") else 17.5)
                if len(new_lines) != len(frame.get("Lines", [])):
                    # Line count changed — rebuild lines
                    frame["Lines"] = [{"Font": font, "FontSize": font_size, "Text": t}
                                      for t in new_lines]
                else:
                    for li, text in enumerate(new_lines):
                        frame["Lines"][li]["Text"] = text

        # Apply schedule changes
        if body.get("schedule") is not None:
            msg["CurrentSchedule"].update(body["schedule"])

        # Rename if requested
        new_name = body.get("newName", "").strip()
        if new_name and new_name != original_name:
            msg["Name"] = new_name

        # Delete old then save updated
        del_text, del_code = delete_message_by_name(original_name)
        app.logger.info(f"pre-update delete '{original_name}' -> {del_code}: {del_text[:100]}")

        import json
        print(f"[UPDATE] Sending to sign: {json.dumps(msg, indent=2)}", flush=True)
        save_result, save_code = save_message_obj(msg)
        return jsonify({"result": save_result, "status": save_code, "message": msg}), save_code

    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/toggle", methods=["POST"])
def api_toggle_message():
    body    = request.json or {}
    name    = body.get("name")
    enabled = body.get("enabled")
    if name is None or enabled is None:
        return jsonify({"error": "name and enabled required"}), 400
    try:
        msgs = get_messages()
        msg  = next((m for m in msgs if m.get("Name") == name), None)
        if msg is None:
            return jsonify({"error": f"Message '{name}' not found"}), 404
        msg = copy.deepcopy(msg)
        msg["CurrentSchedule"]["Enabled"] = enabled
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

@app.route("/api/messages/reorder", methods=["POST"])
def api_reorder_messages():
    s = get_session()
    try:
        r = s.post(f"{BASE_URL}/ECCB/updateMessageSchedulePosition.php",
                   data=request.json or {}, timeout=60)
        return jsonify({"result": r.text, "status": r.status_code}), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/messages/probe", methods=["POST"])
def api_probe_save():
    body = request.json or {}
    name = body.get("name")
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        msgs = get_messages()
        msg  = next((m for m in msgs if m.get("Name") == name), None)
        if not msg:
            return jsonify({"error": f"'{name}' not found"}), 404
        msg = copy.deepcopy(msg)
        s   = get_session()
        results = []

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE_URL}/ECCB/EditMessage.html",
            "Origin": BASE_URL,
        }
        msg_json = json.dumps(msg)
        results.append({"info": "session_cookies", "cookies": dict(s.cookies)})

        for field in ["message", "Message", "data", "json", "msg"]:
            r = s.post(f"{BASE_URL}/ECCB/savemessage.php",
                       data={field: msg_json}, headers=headers, timeout=60)
            body = strip_bom(r.content)
            results.append({"format": f"form_{field}", "status": r.status_code,
                            "body": body or "(empty-BOM-only)"})

        r = s.post(f"{BASE_URL}/ECCB/savemessage.php",
                   json=msg, headers=headers, timeout=60)
        results.append({"format": "raw_json", "status": r.status_code,
                        "body": strip_bom(r.content) or "(empty-BOM-only)"})

        r2 = s.get(f"{BASE_URL}/ECCB/deletemessage.php",
                   params={"Name": name}, headers=headers, timeout=60)
        results.append({"format": "delete_GET_Name", "status": r2.status_code,
                        "body": strip_bom(r2.content) or "(empty-BOM-only)"})
        r3 = s.post(f"{BASE_URL}/ECCB/deletemessage.php",
                    data={"Name": name}, headers=headers, timeout=60)
        results.append({"format": "delete_POST_Name", "status": r3.status_code,
                        "body": strip_bom(r3.content) or "(empty-BOM-only)"})

        msgs_after = get_messages()
        return jsonify({
            "session_cookies": dict(s.cookies),
            "results": results,
            "msg_count_after": len(msgs_after),
            "msg_names_after": [m.get("Name") for m in msgs_after],
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sync-time", methods=["POST"])
def api_sync_time():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    text, code = eccb_put(f"/daktronics/syscontrol/1.0/datetime?Time={now}")
    return jsonify({"result": text, "time_sent": now, "status": code}), code

@app.route("/api/brightness", methods=["POST"])
def api_set_brightness():
    body = request.json or {}
    text, code = eccb_put("/daktronics/syscontrol/1.0/configuration/output/0/dimming", data=body)
    return jsonify({"result": text, "status": code}), code

@app.route("/api/settings", methods=["POST"])
def api_update_settings():
    global SIGN_IP, USERNAME, PASSWORD, BASE_URL, _session, _session_valid
    body     = request.json or {}
    SIGN_IP  = body.get("ip", SIGN_IP)
    USERNAME = body.get("username", USERNAME)
    PASSWORD = body.get("password", PASSWORD)
    BASE_URL = f"http://{SIGN_IP}"
    with _session_lock:
        _session       = None
        _session_valid = False
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
    s      = get_session()
    try:
        r = s.request(method, f"{BASE_URL}{path}",
                      json=json.loads(data) if data and method != "GET" else None,
                      timeout=60)
        try:
            raw = strip_bom(r.content)
            return jsonify(json.loads(raw)), r.status_code
        except Exception:
            return jsonify({"raw": strip_bom(r.content)}), r.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({"error": "Cannot reach sign"}), 503
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/diag")
def api_diag():
    """Hit /diag in a browser for a full readable diagnostic of sign connectivity and save/delete formats."""
    results = []

    def test(label, fn):
        try:
            result = fn()
            results.append({"label": label, "ok": True, "result": result})
        except Exception as e:
            results.append({"label": label, "ok": False, "result": str(e)})

    # 1. Basic connectivity
    test("GET getmessagelist.php", lambda: (
        lambda r: {"status": r.status_code, "bytes": len(r.content), "bom": r.content[:6].hex()}
    )(requests.get(f"{BASE_URL}/ECCB/getmessagelist.php", auth=HTTPBasicAuth(USERNAME, PASSWORD), timeout=30)))

    # 2. Get first real message name
    msg_name = None
    try:
        r = requests.get(f"{BASE_URL}/ECCB/getmessagelist.php", auth=HTTPBasicAuth(USERNAME, PASSWORD), timeout=30)
        raw = strip_bom(r.content)
        msgs = json.loads(raw).get("Messages", [])
        real = [m for m in msgs if m.get("Name","").strip()]
        if real:
            msg_name = real[-1]["Name"]  # use last (least important)
            msg_obj = real[-1]
    except Exception as e:
        results.append({"label": "parse messages", "ok": False, "result": str(e)})

    results.append({"label": "test message", "ok": bool(msg_name), "result": msg_name or "none found"})

    if msg_name and msg_obj:
        msg_json = json.dumps(msg_obj)
        headers_xhr = {
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE_URL}/ECCB/EditMessage.html",
            "Origin": BASE_URL,
        }
        auth = HTTPBasicAuth(USERNAME, PASSWORD)

        # 3. Test every save format - look for 34 or 45 byte response
        for field in ["message", "Message", "data", "json", "msg", "content", "payload"]:
            def do_save(f=field):
                r = requests.post(f"{BASE_URL}/ECCB/savemessage.php",
                    data={f: msg_json}, headers=headers_xhr, auth=auth, timeout=30)
                body = strip_bom(r.content)
                return {"status": r.status_code, "bytes": len(r.content), "body": body[:80] or "(bom-only)"}
            test(f"save form field='{field}'", do_save)

        # 4. Raw JSON body
        def do_raw():
            r = requests.post(f"{BASE_URL}/ECCB/savemessage.php",
                json=msg_obj, headers=headers_xhr, auth=auth, timeout=30)
            body = strip_bom(r.content)
            return {"status": r.status_code, "bytes": len(r.content), "body": body[:80] or "(bom-only)"}
        test("save raw JSON body", do_raw)

        # 5. Delete via GET
        def do_del_get():
            r = requests.get(f"{BASE_URL}/ECCB/deletemessage.php",
                params={"Name": msg_name}, headers=headers_xhr, auth=auth, timeout=30)
            return {"status": r.status_code, "bytes": len(r.content), "body": strip_bom(r.content)[:80] or "(bom-only)"}
        test("delete GET ?Name=", do_del_get)

        # 6. Delete via POST form
        def do_del_post():
            r = requests.post(f"{BASE_URL}/ECCB/deletemessage.php",
                data={"Name": msg_name}, headers=headers_xhr, auth=auth, timeout=30)
            return {"status": r.status_code, "bytes": len(r.content), "body": strip_bom(r.content)[:80] or "(bom-only)"}
        test("delete POST form", do_del_post)

        # 7. Delete with exact headers a real Chrome browser sends (no X-Requested-With)
        def do_del_browser():
            browser_headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Referer": f"{BASE_URL}/ECCB/EditMessage.html",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/144.0.0.0 Safari/537.36",
            }
            r = requests.post(f"{BASE_URL}/ECCB/deletemessage.php",
                data={"Name": msg_name}, headers=browser_headers, auth=auth, timeout=30)
            return {"status": r.status_code, "bytes": len(r.content), "body": strip_bom(r.content)[:80] or "(bom-only)"}
        test("delete POST browser-headers", do_del_browser)

        # 8. Check what our Flask server IP appears as
        try:
            import socket
            local_ip = socket.gethostbyname(socket.gethostname())
            results.append({"label": "flask server IP", "ok": True, "result": local_ip})
        except:
            pass

    # Render as readable HTML
    html = ["<!DOCTYPE html><html><head><meta charset=utf-8>",
            "<title>Dak Diag</title>",
            "<style>body{font:13px/1.6 monospace;background:#0d0d0d;color:#ccc;padding:24px}",
            "h1{color:#00ff88;margin-bottom:16px}",
            ".r{display:flex;gap:16px;padding:8px 12px;border-bottom:1px solid #1a1a1a;align-items:flex-start}",
            ".ok{color:#00ff88}.fail{color:#ff4444}",
            ".label{min-width:280px;color:#aaa}",
            ".val{color:#fff;word-break:break-all}",
            "pre{background:#111;padding:12px;border-radius:4px;overflow:auto}",
            "</style></head><body>",
            "<h1>DAK SIGN DIAGNOSTIC</h1>",
            f"<p style='color:#666;margin-bottom:16px'>Sign: {BASE_URL} &nbsp; User: {USERNAME}</p>",
            "<div>"]

    for r in results:
        icon = "✓" if r["ok"] else "✗"
        cls = "ok" if r["ok"] else "fail"
        val = json.dumps(r["result"], indent=2) if isinstance(r["result"], dict) else str(r["result"])
        html.append(f'<div class="r"><span class="label {cls}">{icon} {r["label"]}</span>'
                    f'<span class="val">{val}</span></div>')

    html.append("</div></body></html>")
    from flask import Response
    return Response("".join(html), mimetype="text/html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
