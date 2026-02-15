# DAK Sign Controller

Python/Flask web UI for Daktronics ECCB electronic signs.

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/cedargroveleedsmedia/dak-sign-controller.git
cd dak-sign-controller
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
```

### 3. Activate it

**Linux / macOS:**
```bash
source venv/bin/activate
```

**Windows:**
```cmd
venv\Scripts\activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure your sign

Edit the top of `app.py`:

```python
SIGN_IP  = "192.168.1.51"
USERNAME = "Dak"
PASSWORD = "DakPassword"
```

You can also change these live from the **Settings** page in the UI without restarting.

### 6. Run

```bash
python app.py
```

Open **http://localhost:5000** in your browser.

---

## Run on Startup (Linux — systemd)

This will keep the app running in the background and auto-restart it if it crashes or the machine reboots.

### 1. Copy the app to a permanent location

```bash
sudo cp -r . /opt/dak-sign-controller
```

### 2. Create the venv there

```bash
cd /opt/dak-sign-controller
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. Edit the service file

Open `dak-sign-controller.service` and replace `YOUR_USERNAME` with your Linux username (run `whoami` if unsure):

```bash
nano dak-sign-controller.service
```

### 4. Install and enable the service

```bash
sudo cp dak-sign-controller.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable dak-sign-controller
sudo systemctl start dak-sign-controller
```

### 5. Check it's running

```bash
sudo systemctl status dak-sign-controller
```

### Useful commands

```bash
sudo systemctl stop dak-sign-controller      # stop
sudo systemctl restart dak-sign-controller   # restart
sudo journalctl -u dak-sign-controller -f    # live logs
```

---

## Run on Startup (Windows)

### Option A — Task Scheduler (recommended)

1. Press `Win + R` → type `taskschd.msc` → Enter
2. Click **Create Basic Task**
3. Name: `DAK Sign Controller`
4. Trigger: **When the computer starts**
5. Action: **Start a program**
   - Program: `C:\path\to\dak-sign-controller\venv\Scripts\python.exe`
   - Arguments: `app.py`
   - Start in: `C:\path\to\dak-sign-controller`
6. Finish — check **"Open Properties"** and set to **Run whether user is logged on or not**

### Option B — run manually at login

Create a `run.bat` file in the project folder:

```bat
@echo off
cd /d C:\path\to\dak-sign-controller
call venv\Scripts\activate
python app.py
```

Then drop a shortcut to `run.bat` in your Startup folder:
`Win + R` → `shell:startup` → paste shortcut there.

---

## Run on Startup (macOS — launchd)

Create `/Library/LaunchDaemons/com.dak.signcontroller.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dak.signcontroller</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/dak-sign-controller/venv/bin/python</string>
    <string>/opt/dak-sign-controller/app.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/opt/dak-sign-controller</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/var/log/dak-sign-controller.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/dak-sign-controller.log</string>
</dict>
</plist>
```

Then load it:

```bash
sudo launchctl load /Library/LaunchDaemons/com.dak.signcontroller.plist
```

---

## Features

- **Dashboard** — live stats (connection, temp, brightness, message count, fan, health)
- **Status** — syntax-highlighted JSON from the sign's status & configuration endpoints
- **Messages** — list, create, and delete sign messages
- **Brightness** — read current dimming level and set via slider
- **Date / Time** — one-click UTC clock sync to the sign
- **Raw API Console** — send any GET/POST/PUT to any endpoint
- **Settings** — change IP/username/password at runtime
