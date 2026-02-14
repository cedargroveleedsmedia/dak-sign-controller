# DAK Sign Controller

Python/Flask web UI for Daktronics ECCB electronic signs.

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open http://localhost:5000 in your browser.

## Default credentials
Edit the top of `app.py` to set your sign's IP, username, and password:

```python
SIGN_IP  = "192.168.1.51"
USERNAME = "Dak"
PASSWORD = "DakPassword"
```

You can also change these live from the Settings page in the UI.

## Features
- Dashboard with live sign stats
- View raw status & configuration JSON
- List, create, and delete messages
- Brightness / dimming control
- One-click clock sync (UTC)
- Raw API console for any endpoint
