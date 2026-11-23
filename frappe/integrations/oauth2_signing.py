# Copyright (c) Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import hashlib
import json
import re
from collections import OrderedDict
from ipaddress import IPv6Address
from os import fstat, stat_result
from pathlib import Path
from stat import S_ISREG
from threading import Lock
from typing import NamedTuple
from urllib.parse import urlsplit

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from jwt.algorithms import RSAAlgorithm
from jwt.utils import base64url_encode

import frappe

RS256_KEY_CONFIG = "oauth2_rs256_key_file"


class RS256SigningKey(NamedTuple):
	private_key: RSAPrivateKey
	public_jwk: dict[str, str]


type FileVersion = tuple[int, int, int, int, int]
_key_cache: OrderedDict[str, tuple[Path, FileVersion, RS256SigningKey | None]] = OrderedDict()
_key_lock = Lock()


def get_rs256_issuer() -> str | None:
	return normalize_rs256_issuer(frappe.get_value("Social Login Key", "frappe", "base_url"))


def normalize_rs256_issuer(value: str | None) -> str | None:
	if not value or re.search(r"[\x00-\x1f\x7f\s\\%?#]", value):
		return None
	try:
		parsed = urlsplit(value)
		port = parsed.port
		if (
			parsed.scheme != "https"
			or not parsed.hostname
			or parsed.path not in ("", "/")
			or port == 0
			or not re.fullmatch(r"(?:\[[^\]]+\]|[a-zA-Z0-9.-]+)(?::[0-9]+)?", parsed.netloc)
		):
			return None
		if parsed.netloc.startswith("["):
			IPv6Address(parsed.hostname)
		else:
			host = parsed.hostname.removesuffix(".")
			if len(host) > 253 or not all(
				re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in host.split(".")
			):
				return None
	except ValueError:
		return None
	return f"https://{parsed.netloc}"


def get_rs256_signing_key() -> RS256SigningKey | None:
	site = frappe.local.site
	configured_path = frappe.conf.get(RS256_KEY_CONFIG)
	path = Path(configured_path) if isinstance(configured_path, str) else None
	with _key_lock:
		if path and path.is_absolute():
			try:
				return _read_signing_key(site, path)
			except OSError, ValueError:
				pass
		_key_cache.pop(site, None)
	return None


def _read_signing_key(site: str, path: Path) -> RS256SigningKey | None:
	for _attempt in range(2):
		info = path.stat()
		if not S_ISREG(info.st_mode):
			break
		version = _file_version(info)
		cached = _key_cache.get(site)
		if cached and cached[:2] == (path, version):
			_key_cache.move_to_end(site)
			return cached[2]

		with path.open("rb") as key_file:
			pem = key_file.read()
			# Retry a key rotation that happens between stat, open, and read.
			if _file_version(fstat(key_file.fileno())) != version or _file_version(path.stat()) != version:
				continue

		key = _parse_key(pem)
		_key_cache[site] = (path, version, key)
		_key_cache.move_to_end(site)
		if len(_key_cache) > 32:
			_key_cache.popitem(last=False)
		return key

	_key_cache.pop(site, None)
	return None


def _file_version(info: stat_result) -> FileVersion:
	return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _parse_key(pem: bytes) -> RS256SigningKey | None:
	try:
		key = load_pem_private_key(pem, password=None)
	except ValueError, TypeError, UnsupportedAlgorithm:
		return None
	if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
		return None
	public_key = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
	jwk = {name: public_key[name] for name in ("e", "kty", "n")}
	# RFC 7638 thumbprints identify the same public key across processes.
	canonical = json.dumps(jwk, sort_keys=True, separators=(",", ":"))
	kid = base64url_encode(hashlib.sha256(canonical.encode()).digest()).decode()
	return RS256SigningKey(key, {**jwk, "kid": kid, "use": "sig", "alg": "RS256"})
