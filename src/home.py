"""Google sign-in, settings storage and Google Assistant commands."""

import json
import os
import shutil
import sys
from pathlib import Path

import grpc
from gassist_text import TextAssistant
from google.auth.exceptions import RefreshError, TransportError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/assistant-sdk-prototype"]
APP_DIR = Path(os.environ.get("APPDATA", Path.home())) / "GoogleHomeWidget"
TOKEN_FILE = APP_DIR / "token.json"
CONFIG_FILE = APP_DIR / "config.json"
CLIENT_SECRET = "client_secret.json"

# "lamp" and "ac" must match the device names shown in the Google Home app.
DEFAULT_CONFIG = {"lamp": "lamp", "ac": "AC", "ac_temp": 24, "language": "en-US"}


class SignInRequired(Exception):
    """The saved Google sign-in is missing, expired or revoked."""


def _search_dirs() -> list[Path]:
    dirs = [APP_DIR]
    if getattr(sys, "frozen", False):
        dirs.append(Path(sys.executable).parent)  # next to the .exe
        dirs.append(Path(sys._MEIPASS))  # bundled into the .exe at build time
    else:
        dirs.append(Path(__file__).resolve().parent.parent)  # repo root
    return dirs


def find_client_secret() -> Path | None:
    for folder in _search_dirs():
        path = folder / CLIENT_SECRET
        if path.is_file():
            return path
    return None


def import_client_secret(path: str) -> None:
    if "installed" not in json.loads(Path(path).read_text("utf-8")):
        raise ValueError("That file is not a 'Desktop app' OAuth client. See README step 3.")
    APP_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(path, APP_DIR / CLIENT_SECRET)


def load_config() -> dict:
    try:
        return {**DEFAULT_CONFIG, **json.loads(CONFIG_FILE.read_text("utf-8"))}
    except (OSError, ValueError):
        return dict(DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2), "utf-8")


def load_credentials() -> Credentials | None:
    try:
        return Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    except (OSError, ValueError):
        return None


def sign_in() -> Credentials:
    """Open the browser for Google login. Blocks until done (5 min timeout)."""
    secret = find_client_secret()
    if secret is None:
        raise FileNotFoundError(f"{CLIENT_SECRET} not found")
    flow = InstalledAppFlow.from_client_secrets_file(str(secret), SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        timeout_seconds=300,
        success_message="Signed in. You can close this tab and go back to the Google Home widget.",
    )
    APP_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(creds.to_json(), "utf-8")
    return creds


def sign_out() -> None:
    TOKEN_FILE.unlink(missing_ok=True)


def send_command(creds: Credentials, query: str, language: str) -> str:
    """Send a text command to Google Assistant, e.g. "turn on the lamp"."""
    try:
        if not creds.valid:
            creds.refresh(Request())
        with TextAssistant(creds, language_code=language) as assistant:
            reply, _html, _audio = assistant.assist(query)
    except RefreshError as err:
        raise SignInRequired("Google sign-in expired. Please sign in again.") from err
    except TransportError as err:
        raise RuntimeError("No internet connection.") from err
    except grpc.RpcError as err:
        if err.code() == grpc.StatusCode.UNAUTHENTICATED:
            raise SignInRequired("Google sign-in expired. Please sign in again.") from err
        raise RuntimeError(err.details() or str(err.code())) from err
    return reply or "Done."
