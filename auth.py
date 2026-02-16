"""
Google OAuth authentication for DAK Sign Controller.
Restricts access to @cedargroveleeds.org and @cedargroveleedsmedia.org accounts.
"""
from flask import redirect, url_for, session, request, render_template_string
from flask_dance.contrib.google import make_google_blueprint, google
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user, login_required
from datetime import timedelta
import os

ALLOWED_DOMAINS = {"cedargroveleeds.org", "cedargroveleedsmedia.org"}
SESSION_DAYS    = 7

# ── User model ────────────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, email, name, picture):
        self.id      = email
        self.email   = email
        self.name    = name
        self.picture = picture

# Simple in-memory user store (keyed by email)
_users = {}

def get_or_create_user(email, name, picture):
    if email not in _users:
        _users[email] = User(email, name, picture)
    return _users[email]

# ── Login page ────────────────────────────────────────────────────
LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DAK Sign · Login</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f1117; color: #e2e8f0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    padding: 24px;
  }
  .card {
    background: #181c27; border: 1px solid #252d3d; border-radius: 16px;
    padding: 40px 32px; max-width: 360px; width: 100%; text-align: center;
  }
  .logo { font-weight: 800; font-size: 24px; letter-spacing: -0.02em; color: #fff; margin-bottom: 6px; }
  .logo em { color: #ff6b1a; font-style: normal; }
  .subtitle { font-size: 13px; color: #64748b; margin-bottom: 32px; }
  .google-btn {
    display: flex; align-items: center; justify-content: center; gap: 12px;
    width: 100%; padding: 14px 20px; border-radius: 10px;
    background: #fff; border: none; cursor: pointer;
    font-size: 15px; font-weight: 600; color: #1f2937;
    text-decoration: none; transition: background 0.15s;
  }
  .google-btn:hover { background: #f3f4f6; }
  .google-btn svg { flex-shrink: 0; }
  .notice { margin-top: 20px; font-size: 12px; color: #475569; line-height: 1.5; }
  {% if error %}
  .error {
    background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3);
    border-radius: 8px; padding: 10px 14px; margin-bottom: 20px;
    font-size: 13px; color: #ef4444;
  }
  {% endif %}
</style>
</head>
<body>
<div class="card">
  <div class="logo">DAK <em>Sign</em></div>
  <div class="subtitle">Cedar Grove Leeds</div>
  {% if error %}
  <div class="error">{{ error }}</div>
  {% endif %}
  <a class="google-btn" href="{{ url_for('google.login') }}">
    <svg width="20" height="20" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
      <path fill="none" d="M0 0h48v48H0z"/>
    </svg>
    Sign in with Google
  </a>
  <div class="notice">Access restricted to Cedar Grove Leeds staff accounts.</div>
</div>
</body>
</html>
"""

DENIED_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DAK Sign · Access Denied</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #181c27; border: 1px solid #252d3d; border-radius: 16px; padding: 40px 32px; max-width: 360px; width: 100%; text-align: center; }
  .logo { font-weight: 800; font-size: 24px; color: #fff; margin-bottom: 6px; }
  .logo em { color: #ff6b1a; font-style: normal; }
  .icon { font-size: 40px; margin: 20px 0; }
  .msg { font-size: 14px; color: #64748b; line-height: 1.6; margin-bottom: 24px; }
  .email { color: #ef4444; font-weight: 600; }
  .btn { display: inline-block; padding: 12px 24px; border-radius: 10px; background: #252d3d; color: #e2e8f0; text-decoration: none; font-size: 14px; font-weight: 600; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">DAK <em>Sign</em></div>
  <div class="icon">🚫</div>
  <div class="msg">
    <span class="email">{{ email }}</span> is not authorized.<br><br>
    Only Cedar Grove Leeds staff accounts can access this app.
  </div>
  <a class="btn" href="{{ url_for('logout') }}">Try a different account</a>
</div>
</body>
</html>
"""

def init_auth(app):
    """Attach Google OAuth and flask-login to the Flask app."""

    # Secret key — override with env var in production
    app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-use-env-var")
    app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=SESSION_DAYS)
    app.config["REMEMBER_COOKIE_SECURE"]   = True   # HTTPS only
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SECURE"]    = True
    app.config["SESSION_COOKIE_HTTPONLY"]  = True

    # Allow OAuth over HTTP on localhost only
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "0")

    # Google OAuth blueprint
    # Flask-Dance callback is at /oauth/google/authorized (must match Google Cloud Console)
    google_bp = make_google_blueprint(
        client_id     = os.environ.get("GOOGLE_CLIENT_ID",     ""),
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        scope         = ["openid", "https://www.googleapis.com/auth/userinfo.email",
                         "https://www.googleapis.com/auth/userinfo.profile"],
        redirect_to   = "index",
    )
    app.register_blueprint(google_bp, url_prefix="/oauth")

    # Handle the OAuth callback via flask-dance signal
    from flask_dance.consumer import oauth_authorized
    from flask import flash

    @oauth_authorized.connect_via(google_bp)
    def google_logged_in(blueprint, token):
        if not token:
            return redirect(url_for("login", error="Login failed. Please try again."))

        resp = blueprint.session.get("/oauth2/v2/userinfo")
        if not resp.ok:
            return redirect(url_for("login", error="Could not fetch your Google profile."))

        info    = resp.json()
        email   = info.get("email", "")
        name    = info.get("name", email)
        picture = info.get("picture", "")
        domain  = email.split("@")[-1].lower() if "@" in email else ""

        if domain not in ALLOWED_DOMAINS:
            logout_user()
            session["denied_email"] = email
            return False  # cancel token storage

        user = get_or_create_user(email, name, picture)
        login_user(user, remember=True)
        return False  # we handled it, don't store token

    # Flask-Login setup
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id):
        return _users.get(user_id)

    # ── Auth routes ───────────────────────────────────────────────

    @app.route("/login")
    def login():
        error = request.args.get("error")
        return render_template_string(LOGIN_HTML, error=error)

    @app.route("/logout")
    def logout():
        from flask_login import logout_user
        logout_user()
        session.clear()
        return redirect(url_for("login"))

    @app.route("/denied")
    def denied():
        email = session.pop("denied_email", "your account")
        return render_template_string(DENIED_HTML, email=email)

    # ── Protect all routes ────────────────────────────────────────

    @app.before_request
    def require_login():
        public = {"login", "logout", "denied",
                  "google.login", "google.authorized", "static"}
        if request.endpoint in public:
            return
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
