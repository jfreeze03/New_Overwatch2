"""
Connection layer. Lazy imports so the Streamlit UI loads even if one driver is
missing. Credentials come from config/secrets.toml (never hardcoded).
"""
from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

try:
    import tomllib  # py3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "secrets.toml"


@dataclass
class Config:
    td: dict = field(default_factory=dict)
    sf: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    @property
    def pairs(self):
        """Positional pairing of TD databases to SF database.schema targets."""
        tds = self.td.get("databases", [])
        sfs = self.sf.get("schemas", [])
        n = min(len(tds), len(sfs))
        return list(zip(tds[:n], sfs[:n]))


def load_config(path: Path = CONFIG_PATH) -> Config:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config/secrets.example.toml -> config/secrets.toml"
        )
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return Config(td=raw.get("teradata", {}),
                  sf=raw.get("snowflake", {}),
                  options=raw.get("options", {}))


def connect_teradata(td: dict):
    import teradatasql
    kwargs = {
        "host": td["host"],
        "user": td["user"],
        "password": td.get("password") or os.environ.get("TD_PASSWORD", ""),
    }
    if td.get("logmech"):
        kwargs["logmech"] = td["logmech"]
    return teradatasql.connect(**kwargs)


def connect_snowflake(sf: dict):
    import snowflake.connector
    kwargs = {
        "account": sf["account"],
        "user": sf["user"],
        "role": sf.get("role"),
        "warehouse": sf.get("warehouse"),
    }
    key_path = sf.get("private_key_path")
    if key_path:
        kwargs["private_key"] = _load_private_key(key_path, sf.get("private_key_passphrase"))
    else:
        kwargs["password"] = sf.get("password") or os.environ.get("SF_PASSWORD", "")
    return snowflake.connector.connect(**{k: v for k, v in kwargs.items() if v is not None})


def _load_private_key(path: str, passphrase: Optional[str]):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
    with open(path, "rb") as f:
        p = serialization.load_pem_private_key(
            f.read(),
            password=passphrase.encode() if passphrase else None,
            backend=default_backend(),
        )
    return p.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
