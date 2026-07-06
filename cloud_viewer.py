"""
cloud_viewer.py
────────────────
A small, standalone, READ-ONLY dashboard viewer meant to be deployed on
Render's free tier (or any similar host). It has no connection to email,
models, or the review/approve-reject logic — it only displays whatever
dashboard files were most recently pushed to it from the incharge's PC.

Two ways in:
  1. Anyone with the VIEWER_USERNAME / VIEWER_PASSWORD can open "/" and
     browse the latest dashboard (same login concept as the LAN version).
  2. The incharge's PC pushes new dashboard files to "/push" using a
     separate secret key (PUSH_SECRET) — this is NOT the same as the
     viewer login and should never be shared with normal viewers.

IMPORTANT — Render free-tier disk note:
  Render's free web services use ephemeral disk. Files pushed here will
  usually survive sleep/wake cycles, but WILL be wiped on every new
  deploy (e.g. if you push code changes to GitHub) or occasional host
  maintenance. This app is meant for "latest snapshot" viewing only —
  it is NOT a permanent archive. Keep your real data / review actions
  on the incharge's PC; this cloud copy is disposable and easily
  refreshed by pushing again.

Environment variables to set on Render (Dashboard → your service →
Environment):
  VIEWER_USERNAME   e.g. FailureAI
  VIEWER_PASSWORD   e.g. FailureAI@123      (use a strong one for real use)
  PUSH_SECRET       a long random string, shared only with the pusher script
"""

import os
import io
import zipfile
import shutil
from functools import wraps
from pathlib import Path

from flask import Flask, request, Response, send_from_directory, abort

app = Flask(__name__)

# ── Config (from environment variables, with safe local-testing defaults) ──
VIEWER_USERNAME = os.environ.get("VIEWER_USERNAME", "FailureAI")
VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD", "FailureAI@123")
PUSH_SECRET     = os.environ.get("PUSH_SECRET", "change-this-secret")

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", "/tmp/dashboard_storage"))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


# ── Viewer login (Basic Auth) — protects all read routes ──
def _check_viewer_auth(username, password):
    return username == VIEWER_USERNAME and password == VIEWER_PASSWORD


def _viewer_login_prompt():
    return Response(
        "Login required to view the dashboard.",
        401,
        {"WWW-Authenticate": 'Basic realm="Failure Dashboard"'},
    )


def requires_viewer_login(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or not _check_viewer_auth(auth.username, auth.password):
            return _viewer_login_prompt()
        return f(*args, **kwargs)
    return wrapper


# ── Public (read-only) routes ──
@app.route("/")
@requires_viewer_login
def dashboard():
    html_path = STORAGE_DIR / "daily_reports" / "daily_dashboard.html"
    if not html_path.exists():
        return (
            "<p style='font-family:sans-serif;padding:20px'>"
            "No dashboard has been pushed yet. Once the incharge's PC "
            "sends an update, it will appear here.</p>"
        )
    return send_from_directory(html_path.parent, html_path.name)


@app.route("/daily_reports/<path:filename>")
@requires_viewer_login
def daily_report_assets(filename):
    folder = STORAGE_DIR / "daily_reports"
    return send_from_directory(folder, filename)


@app.route("/with_production_loss/<path:filename>")
@requires_viewer_login
def with_loss_assets(filename):
    folder = STORAGE_DIR / "with_production_loss"
    return send_from_directory(folder, filename)


@app.route("/without_production_loss/<path:filename>")
@requires_viewer_login
def without_loss_assets(filename):
    folder = STORAGE_DIR / "without_production_loss"
    return send_from_directory(folder, filename)


# ── Push endpoint: the incharge's PC uploads a zip of the latest dashboard ──
@app.route("/push", methods=["POST"])
def push_dashboard():
    secret = request.headers.get("X-Push-Secret", "")
    if secret != PUSH_SECRET:
        abort(401, "Invalid push secret.")

    if "file" not in request.files:
        abort(400, "No file uploaded. Expected a multipart field named 'file'.")

    upload = request.files["file"]
    data = upload.read()

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        abort(400, "Uploaded file is not a valid zip archive.")

    # Wipe old snapshot and extract the new one fresh, so stale files
    # from a previous push never linger.
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    zf.extractall(STORAGE_DIR)

    return {"status": "ok", "message": "Dashboard updated."}, 200


@app.route("/health")
def health():
    return {"status": "ok"}, 200


if __name__ == "__main__":
    # Local testing only — Render will use gunicorn via the Procfile instead.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
