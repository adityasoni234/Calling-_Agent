#!/usr/bin/env python3
"""Interactive provider setup.

Prompts for credentials and writes them into `.env`. Secrets are read with
`getpass`, so they are never echoed to the terminal, never printed back, and
never appear in shell history or in any transcript. Run it yourself:

    make configure
"""

from __future__ import annotations

import argparse
import re
import sys
from getpass import getpass
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"

# (env key, prompt, secret?)
PROVIDERS: dict[str, dict[str, object]] = {
    "telephony": {
        "options": {
            "telnyx": [
                ("TELNYX_API_KEY", "Telnyx API key (portal → API Keys)", True),
                ("TELNYX_CONNECTION_ID", "Telnyx Call Control app / connection ID", False),
                ("TELNYX_CALLER_ID", "Your Telnyx number in E.164 (e.g. +13195368347)", False),
            ],
            "plivo": [
                ("PLIVO_AUTH_ID", "Plivo Auth ID", False),
                ("PLIVO_AUTH_TOKEN", "Plivo Auth Token", True),
                ("PLIVO_CALLER_ID", "Your Plivo number in E.164", False),
            ],
            "twilio": [
                ("TWILIO_ACCOUNT_SID", "Twilio Account SID", False),
                ("TWILIO_AUTH_TOKEN", "Twilio Auth Token", True),
                ("TWILIO_CALLER_ID", "Your Twilio number in E.164", False),
            ],
            "mock": [],
        },
        "var": "TELEPHONY_PROVIDER",
    },
    "stt": {
        "options": {
            "deepgram": [("DEEPGRAM_API_KEY", "Deepgram API key", True)],
            "mock": [],
        },
        "var": "STT_PROVIDER",
    },
    "llm": {
        "options": {
            "anthropic": [
                ("ANTHROPIC_API_KEY", "Anthropic API key", True),
                ("ANTHROPIC_WORKSPACE_ID", "Workspace ID (only for identity-linked keys)", False),
            ],
            "openai": [("OPENAI_API_KEY", "OpenAI API key", True)],
            "mock": [],
        },
        "var": "LLM_PROVIDER",
    },
    "tts": {
        "options": {
            "cartesia": [
                ("CARTESIA_API_KEY", "Cartesia API key", True),
                ("TTS_VOICE_ID", "Default Cartesia voice ID", False),
            ],
            "deepgram": [("DEEPGRAM_API_KEY", "Deepgram API key (shared with STT)", True)],
            "elevenlabs": [
                ("ELEVENLABS_API_KEY", "ElevenLabs API key", True),
                ("TTS_VOICE_ID", "Default ElevenLabs voice ID", False),
            ],
            "mock": [],
        },
        "var": "TTS_PROVIDER",
    },
    "embeddings": {
        "options": {
            "openai": [("OPENAI_API_KEY", "OpenAI API key", True)],
            "mock": [],
        },
        "var": "EMBEDDING_PROVIDER",
    },
}


def read_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        sys.exit(f"{ENV_PATH} does not exist. Run `make setup` first.")
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str]) -> None:
    """Rewrite `.env` in place, preserving comments, order, and untouched keys."""
    lines = ENV_PATH.read_text().splitlines()
    remaining = dict(updates)

    for index, line in enumerate(lines):
        if "=" in line and not line.lstrip().startswith("#"):
            key = line.partition("=")[0].strip()
            if key in remaining:
                lines[index] = f"{key}={remaining.pop(key)}"

    for key, value in remaining.items():
        lines.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(lines) + "\n")
    ENV_PATH.chmod(0o600)


def ask(prompt: str, *, secret: bool, current: str, show: bool) -> str | None:
    """Return the new value, or None to leave it unchanged."""
    marker = " [set, press Enter to keep]" if current else ""
    if secret and not show:
        # Nothing appears while typing -- that is expected, not a hang.
        value = getpass(f"  {prompt}{marker} (typing is hidden): ")
    elif secret:
        value = input(f"  {prompt}{marker}: ").strip()
    else:
        shown = f" [{current}]" if current else ""
        value = input(f"  {prompt}{shown}: ").strip()
    return value or None


def choose(capability: str, options: list[str], current: str) -> str:
    print(f"\n{capability}: {', '.join(options)}")
    while True:
        choice = input(f"  provider [{current or 'mock'}]: ").strip().lower() or current or "mock"
        if choice in options:
            return choice
        print(f"  '{choice}' is not one of: {', '.join(options)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure providers in .env")
    parser.add_argument(
        "--show",
        action="store_true",
        help="show secrets as you type them (easier to spot a bad paste)",
    )
    parser.add_argument(
        "--only",
        default="",
        help="configure just one capability, e.g. --only telephony",
    )
    args = parser.parse_args()

    print("Provider setup. Values are written straight to .env — never printed")
    print("back, never sent anywhere. Press Enter at any prompt to keep what's there.")
    if not args.show:
        print("Secrets are hidden as you type: the cursor will not move. That is normal.")
        print("Paste, press Enter. Re-run with `make configure show=1` to see them.")
    print()

    env = read_env()
    updates: dict[str, str] = {}

    selected_capabilities = (
        {name.strip() for name in args.only.split(",") if name.strip()}
        if args.only
        else set(PROVIDERS)
    )
    unknown = selected_capabilities - set(PROVIDERS)
    if unknown:
        sys.exit(f"Unknown capability: {', '.join(sorted(unknown))}")

    for capability, spec in PROVIDERS.items():
        if capability not in selected_capabilities:
            continue
        options = spec["options"]  # type: ignore[index]
        var = str(spec["var"])
        selected = choose(capability, sorted(options), env.get(var, "mock"))
        updates[var] = selected

        for key, prompt, secret in options[selected]:
            value = ask(prompt, secret=bool(secret), current=env.get(key, ""), show=args.show)
            if value is not None:
                updates[key] = value

    print()
    current_base = env.get("PUBLIC_BASE_URL", "")
    base = input(f"Public https URL for carrier webhooks [{current_base}]: ").strip()
    if base:
        updates["PUBLIC_BASE_URL"] = base.rstrip("/")

    write_env(updates)

    print("\nWrote .env (permissions set to 0600).")
    for capability, spec in PROVIDERS.items():
        var = str(spec["var"])
        if var in updates:
            print(f"  {capability:<11} {updates[var]}")
    if not re.match(r"^https://", updates.get("PUBLIC_BASE_URL", env.get("PUBLIC_BASE_URL", ""))):
        print("\n  Warning: PUBLIC_BASE_URL is not https. Carriers will not reach your webhooks.")
    print("\nNext: make up   then check http://localhost:5173/settings")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled. Nothing was written.")
        raise SystemExit(130) from None
