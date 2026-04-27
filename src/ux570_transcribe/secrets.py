"""OS-keychain wrapper. API keys NEVER touch disk in plaintext."""

from __future__ import annotations

import getpass

SERVICE = "ux570-transcribe"


def _keyring():
    try:
        import keyring

        return keyring
    except ImportError as e:
        raise RuntimeError(
            "keyring is not installed. Install the cloud extras: "
            "`uv pip install -e '.[cloud]'`"
        ) from e


def get_anthropic_key() -> str | None:
    return _keyring().get_password(SERVICE, "anthropic_api_key")


def set_anthropic_key(key: str) -> None:
    _keyring().set_password(SERVICE, "anthropic_api_key", key)


def delete_anthropic_key() -> None:
    try:
        _keyring().delete_password(SERVICE, "anthropic_api_key")
    except Exception:
        pass


def prompt_and_store_anthropic_key() -> str:
    key = getpass.getpass("Paste Anthropic API key (input hidden): ").strip()
    if not key.startswith("sk-ant-"):
        raise ValueError("That doesn't look like an Anthropic API key (expected sk-ant-...).")
    set_anthropic_key(key)
    return key


def require_anthropic_key() -> str:
    key = get_anthropic_key()
    if not key:
        raise RuntimeError(
            "No Anthropic API key in OS keychain. "
            "Run `ux570 config set-key anthropic` first."
        )
    return key
