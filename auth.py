"""
Google OAuth authentication for DAK Sign Controller.
Uses Authlib directly — no Flask-Dance — so the redirect URI is fully hardcoded.
Restricts access to @cedargroveleeds.org and @cedargroveleedsmedia.org accounts.
"""
import os
from datetime import timedelta
from flask import redirect, url_for, session, request, render_template_string
from flask_login import LoginManager, UserMixin, login_user, logout_user, current_user
from authlib.integrations.requests_client import OAuth2Session

ALLOWED_DOMAINS  = {"cedargroveleeds.org", "cedargroveleedsmedia.org"}
SESSION_DAYS     = 7
REDIRECT_URI     = "https://dak.cedargroveleedsmedia.org/oauth/callback"
GOOGLE_AUTH_URL  = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_INFO_URL  = "https://www.googleapis.com/oauth2/v2/userinfo"
SCOPES           = "openid email profile"

# ── User model ────────────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, email, name, picture):
        self.id      = email
        self.email   = email
        self.name    = name
        self.picture = picture

_users = {}

def get_or_create_user(email, name, picture):
    if email not in _users:
        _users[email] = User(email, name, picture)
    return _users[email]

# ── Templates ─────────────────────────────────────────────────────
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DAK Sign · Login</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f1117; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; }
  .card { background: #181c27; border: 1px solid #252d3d; border-radius: 16px; padding: 40px 32px; max-width: 360px; width: 100%; text-align: center; }
  .logo { font-weight: 800; font-size: 24px; color: #fff; margin-bottom: 6px; }
  .logo em { color: #ff6b1a; font-style: normal; }
  .sub { font-size: 13px; color: #64748b; margin-bottom: 32px; }
  .google-btn { display: flex; align-items: center; justify-content: center; gap: 12px; width: 100%; padding: 14px 20px; border-radius: 10px; background: #fff; border: none; cursor: pointer; font-size: 15px; font-weight: 600; color: #1f2937; text-decoration: none; }
  .google-btn:hover { background: #f3f4f6; }
  .notice { margin-top: 20px; font-size: 12px; color: #475569; line-height: 1.5; }
  .error { background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3); border-radius: 8px; padding: 10px 14px; margin-bottom: 20px; font-size: 13px; color: #ef4444; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">DAK <em>Sign</em></div>
  <div class="sub">Cedar Grove Leeds</div>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <a class="google-btn" href="/oauth/login">
    <svg width="20" height="20" viewBox="0 0 48 48">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/>
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/>
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/>
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/>
    </svg>
    Sign in with Google
  </a>
  <div class="notice">Access restricted to Cedar Grove Leeds staff accounts.</div>
</div>
</body>
</html>"""

DENIED_HTML = """<!DOCTYPE html>
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
  <div class="msg"><span class="email">{{ email }}</span> is not authorized.<br><br>Only Cedar Grove Leeds staff accounts can access this app.</div>
  <a class="btn" href="/logout">Try a different account</a>
</div>
</body>
</html>"""


def init_auth(app):
    app.secret_key = os.environ.get("SECRET_KEY", "change-me-use-env-var")
    app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=SESSION_DAYS)
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_HTTPONLY"]  = True

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
        logout_user()
        session.clear()
        return redirect("/login")

    @app.route("/oauth/login")
    def oauth_login():
        """Redirect user to Google — redirect URI is fully hardcoded as https."""
        client = OAuth2Session(
            client_id    = os.environ.get("GOOGLE_CLIENT_ID", ""),
            redirect_uri = REDIRECT_URI,
            scope        = SCOPES,
        )
        uri, state = client.create_authorization_url(
            GOOGLE_AUTH_URL,
            access_type = "online",
        )
        session["oauth_state"] = state
        return redirect(uri)

    @app.route("/oauth/callback")
    def oauth_callback():
        """Google redirects here. Exchange code for token, verify domain."""
        state = session.pop("oauth_state", None)
        client = OAuth2Session(
            client_id     = os.environ.get("GOOGLE_CLIENT_ID", ""),
            client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", ""),
            redirect_uri  = REDIRECT_URI,
            state         = state,
        )

        # Build the full callback URL but force https scheme
        callback_url = request.url
        if callback_url.startswith("http://"):
            callback_url = "https://" + callback_url[7:]

        try:
            token = client.fetch_token(GOOGLE_TOKEN_URL, authorization_response=callback_url)
        except Exception as e:
            app.logger.error(f"OAuth token fetch failed: {e}")
            return redirect("/login?error=Login+failed.+Please+try+again.")

        resp = client.get(GOOGLE_INFO_URL)
        if not resp.ok:
            return redirect("/login?error=Could+not+fetch+your+Google+profile.")

        info    = resp.json()
        email   = info.get("email", "")
        name    = info.get("name", email)
        picture = info.get("picture", "")
        domain  = email.split("@")[-1].lower() if "@" in email else ""

        if domain not in ALLOWED_DOMAINS:
            return render_template_string(DENIED_HTML, email=email)

        user = get_or_create_user(email, name, picture)
        login_user(user, remember=True)
        return redirect("/")

    # ── Protect all routes ────────────────────────────────────────

    @app.before_request
    def require_login():
        public = {"login", "logout", "oauth_login", "oauth_callback", "static"}
        if request.endpoint in public:
            return
        if not current_user.is_authenticated:
            return redirect("/login")
