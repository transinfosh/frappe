# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import patch
from urllib.parse import parse_qs, quote_plus, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, generate_private_key
from werkzeug.test import TestResponse

import frappe
from frappe.integrations import oauth2_signing
from frappe.integrations.oauth2 import encode_params
from frappe.oauth import OAuthWebRequestValidator
from frappe.tests import IntegrationTestCase
from frappe.tests.test_api import get_test_client, make_request, suppress_stdout
from frappe.tests.utils import make_test_records
from frappe.utils.oauth import build_oauth_url

if TYPE_CHECKING:
	from frappe.integrations.doctype.social_login_key.social_login_key import SocialLoginKey


class FrappeRequestTestCase(IntegrationTestCase):
	@property
	def sid(self) -> str:
		if not getattr(self, "_sid", None):
			from frappe.auth import CookieManager, LoginManager
			from frappe.utils import set_request

			set_request(path="/")
			frappe.local.cookie_manager = CookieManager()
			frappe.local.login_manager = LoginManager()
			frappe.local.login_manager.login_as("test@example.com")
			self._sid = frappe.session.sid

		return self._sid

	def get(self, path: str, params: dict | None = None, **kwargs) -> TestResponse:
		return make_request(
			target=self.TEST_CLIENT.get, args=(path,), kwargs={"data": params, **kwargs}, site=self.site
		)

	def post(self, path, data, **kwargs) -> TestResponse:
		return make_request(
			target=self.TEST_CLIENT.post, args=(path,), kwargs={"data": data, **kwargs}, site=self.site
		)

	def put(self, path, data, **kwargs) -> TestResponse:
		return make_request(
			target=self.TEST_CLIENT.put, args=(path,), kwargs={"data": data, **kwargs}, site=self.site
		)

	def delete(self, path, **kwargs) -> TestResponse:
		return make_request(target=self.TEST_CLIENT.delete, args=(path,), kwargs=kwargs, site=self.site)


class TestOAuth20(FrappeRequestTestCase):
	site = frappe.local.site

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_test_records("User")

		cls.form_header = {"content-type": "application/x-www-form-urlencoded"}
		cls.scope = "all openid"
		cls.redirect_uri = "http://localhost"

		# Set Frappe server URL reqired for id_token generation
		frappe_login_key: SocialLoginKey = frappe.new_doc("Social Login Key")
		frappe_login_key.get_social_login_provider("Frappe", initialize=True)
		frappe_login_key.base_url = frappe.utils.get_url()
		frappe_login_key.enable_social_login = 0
		frappe_login_key.insert(ignore_if_duplicate=True)
		frappe.db.commit()

	def setUp(self):
		self.TEST_CLIENT = get_test_client()
		self.oauth_client = frappe.new_doc("OAuth Client")
		self.oauth_client.update(
			{
				"app_name": "_Test OAuth Client",
				"client_secret": "test_client_secret",
				"default_redirect_uri": "http://localhost",
				"docstatus": 0,
				"doctype": "OAuth Client",
				"grant_type": "Authorization Code",
				"name": "test_client_id",
				"redirect_uris": "http://localhost",
				"response_type": "Code",
				"scopes": "all openid",
				"skip_authorization": 1,
			}
		)
		self.oauth_client.insert()

		self.client_id = self.oauth_client.get("client_id")
		self.client_secret = self.oauth_client.get("client_secret")

	def tearDown(self):
		self.oauth_client.delete(force=True)
		frappe.db.rollback()

	def _delete_committed_client(self):
		frappe.db.delete("OAuth Bearer Token", {"client": self.client_id})
		frappe.db.delete("OAuth Authorization Code", {"client": self.client_id})
		self.oauth_client.delete(force=True, ignore_permissions=True, delete_permanently=True)
		frappe.db.commit()

	def _make_bearer_token(self):
		access_token = frappe.generate_hash()
		token = frappe.get_doc(
			doctype="OAuth Bearer Token",
			access_token=access_token,
			client=self.client_id,
			expires_in=3600,
			scopes=self.scope,
			status="Active",
			user="test@example.com",
		).insert(ignore_permissions=True)
		return access_token, token

	def test_bearer_token_rejects_disabled_owner(self):
		access_token, _token = self._make_bearer_token()
		frappe.db.set_value("User", "test@example.com", "enabled", 0)
		request = frappe._dict()

		self.assertFalse(OAuthWebRequestValidator().validate_bearer_token(access_token, ["openid"], request))
		self.assertNotIn("user", request)

	def test_bearer_token_rejects_missing_owner(self):
		access_token, token = self._make_bearer_token()
		frappe.db.set_value("OAuth Bearer Token", token.name, "user", "missing@example.com")
		request = frappe._dict()

		self.assertFalse(OAuthWebRequestValidator().validate_bearer_token(access_token, ["openid"], request))
		self.assertNotIn("user", request)

	def test_openid_profile_post_body_token(self):
		access_token, _token = self._make_bearer_token()
		# The HTTP request runs in another thread and only sees committed fixtures.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

		openid_response = self.post(
			"/api/method/frappe.integrations.oauth2.openid_profile",
			headers=self.form_header,
			data={"access_token": access_token},
		)

		self.assertEqual(openid_response.status_code, 200)
		self.assertEqual(openid_response.json.get("email"), "test@example.com")

	def test_invalid_login(self):
		with suppress_stdout():
			self.assertFalse(check_valid_openid_response(client=self))

	def test_authorize_post_preserves_parameters_through_login(self):
		params = {
			"client_id": self.client_id,
			"scope": self.scope,
			"response_type": "code",
			"redirect_uri": self.redirect_uri,
			"state": "opaque +/%?&= state",
		}

		response = self.post(
			"/api/method/frappe.integrations.oauth2.authorize",
			params,
			headers=self.form_header,
		)
		login_query = parse_qs(urlparse(response.location).query)
		redirect_query = parse_qs(urlparse(login_query["redirect-to"][0]).query)

		self.assertEqual(redirect_query, {key: [value] for key, value in params.items()})

	def test_authorize_post_rejects_unsupported_content_types(self):
		params = {
			"client_id": self.client_id,
			"scope": self.scope,
			"response_type": "code",
			"redirect_uri": self.redirect_uri,
		}

		for content_type, data in (
			("application/json", frappe.as_json(params)),
			("text/plain", encode_params(params)),
		):
			with self.subTest(content_type=content_type):
				response = self.post(
					"/api/method/frappe.integrations.oauth2.authorize",
					data,
					headers={"content-type": content_type},
				)

				self.assertEqual(response.status_code, 415)

	def test_login_using_authorization_code(self):
		update_client_for_auth_code_grant(self.client_id)

		# Go to Authorize url
		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		resp = self.get(
			"/api/method/frappe.integrations.oauth2.authorize",
			{
				"client_id": self.client_id,
				"scope": self.scope,
				"response_type": "code",
				"redirect_uri": self.redirect_uri,
			},
			follow_redirects=True,
		)
		query = parse_qs(resp.request.environ["QUERY_STRING"])
		auth_code = query.get("code")[0]

		# Request for bearer token
		token_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			headers=self.form_header,
			data={
				"grant_type": "authorization_code",
				"code": auth_code,
				"redirect_uri": self.redirect_uri,
				"client_id": self.client_id,
				"client_secret": self.client_secret,
				"scope": self.scope,
			},
		)

		# Parse bearer token json
		bearer_token = token_response.json

		self.assertTrue(bearer_token.get("access_token"))
		self.assertTrue(bearer_token.get("expires_in"))
		self.assertTrue(bearer_token.get("id_token"))
		self.assertTrue(bearer_token.get("refresh_token"))
		self.assertTrue(bearer_token.get("scope"))
		self.assertTrue(bearer_token.get("token_type") == "Bearer")
		self.assertTrue(
			check_valid_openid_response(access_token=bearer_token.get("access_token"), client=self)
		)

		decoded_token = self.decode_id_token(bearer_token.get("id_token"))
		self.assertEqual(decoded_token["email"], "test@example.com")

	def test_confidential_client_authentication_at_token_endpoint(self):
		self.addCleanup(self._delete_committed_client)
		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		backend = get_test_client(use_cookies=False)

		def exchange(grant, headers=None):
			return make_request(
				target=backend.post,
				args=("/api/method/frappe.integrations.oauth2.get_token",),
				kwargs={"data": grant, "headers": {**self.form_header, **(headers or {})}},
				site=self.site,
			)

		secret = "fixture:secret+with spaces"
		self.oauth_client.client_secret = secret
		for method in ("Client Secret Basic", "Client Secret Post"):
			with self.subTest(method=method):
				self.oauth_client.token_endpoint_auth_method = method
				self.oauth_client.save()
				frappe.db.commit()
				response = self.get(
					"/api/method/frappe.integrations.oauth2.authorize",
					{
						"client_id": self.client_id,
						"scope": "openid",
						"response_type": "code",
						"redirect_uri": self.redirect_uri,
					},
				)
				code = parse_qs(urlparse(response.location).query)["code"][0]
				grant = {
					"grant_type": "authorization_code",
					"code": code,
					"redirect_uri": self.redirect_uri,
				}
				missing = exchange({**grant, "client_id": self.client_id})
				self.assertEqual(missing.status_code, 401)
				self.assertEqual(missing.json["error"], "invalid_client")

				if method == "Client Secret Basic":
					invalid = exchange(grant, _client_basic_header(self.client_id, "wrong-secret"))
					self.assertEqual(invalid.headers["WWW-Authenticate"], 'Basic realm="OAuth"')
					headers = _client_basic_header(self.client_id, secret)
					credentials = {}
				else:
					invalid = exchange(
						{**grant, "client_id": self.client_id, "client_secret": "wrong-secret"}
					)
					headers = {}
					credentials = {"client_id": self.client_id, "client_secret": secret}
				self.assertEqual(invalid.status_code, 401)
				self.assertEqual(invalid.json["error"], "invalid_client")
				token = exchange(grant | credentials, headers)
				self.assertEqual(token.status_code, 200)
				self.assertTrue(token.json["access_token"])
				self.assertTrue(token.json["id_token"])
				refresh = {"grant_type": "refresh_token", "refresh_token": token.json["refresh_token"]}
				self.assertEqual(exchange(refresh).status_code, 401)
				self.assertEqual(exchange(refresh | credentials, headers).status_code, 200)

	def test_token_basic_auth_exception_applies_only_to_the_builtin_handler(self):
		from frappe.auth import _is_oauth_token_basic_auth

		method = "frappe.integrations.oauth2.get_token"
		request = SimpleNamespace(method="POST", path=f"/api/method/{method}")
		with (
			patch.object(frappe.local, "request", request),
			patch.object(frappe.local, "form_dict", frappe._dict()),
			patch(
				"frappe.core.doctype.server_script.server_script_utils.get_server_script_map",
				return_value={"_api": {method: "Test OAuth Server Script"}},
			),
		):
			self.assertFalse(_is_oauth_token_basic_auth(["Basic", "fixture"]))

	def test_login_using_authorization_code_with_pkce(self):
		self.addCleanup(self._delete_committed_client)
		client = update_client_for_auth_code_grant(self.client_id)
		client.token_endpoint_auth_method = "None"
		client.save()
		frappe.db.commit()

		# Go to Authorize url
		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		resp = self.get(
			"/api/method/frappe.integrations.oauth2.authorize",
			{
				"client_id": self.client_id,
				"scope": self.scope,
				"response_type": "code",
				"redirect_uri": self.redirect_uri,
				"code_challenge_method": "S256",
				"code_challenge": "21XaP8MJjpxCMRxgEzBP82sZ73PRLqkyBUta1R309J0",
			},
			follow_redirects=True,
		)

		# Get authorization code from redirected URL
		query = parse_qs(resp.request.environ["QUERY_STRING"])
		auth_code = query.get("code")[0]

		# Request for bearer token
		token_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			headers=self.form_header,
			data={
				"grant_type": "authorization_code",
				"code": auth_code,
				"redirect_uri": self.redirect_uri,
				"client_id": self.client_id,
				"scope": self.scope,
				"code_verifier": "420",
			},
		)

		# Parse bearer token json
		bearer_token = token_response.json

		self.assertTrue(bearer_token.get("access_token"))
		self.assertTrue(bearer_token.get("id_token"))

		decoded_token = self.decode_id_token(bearer_token.get("id_token"))
		self.assertEqual(decoded_token["email"], "test@example.com")

		refresh_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			headers=self.form_header,
			data={"grant_type": "refresh_token", "refresh_token": bearer_token["refresh_token"]},
		)
		self.assertEqual(refresh_response.status_code, 200)
		self.assertTrue(refresh_response.json["access_token"])

	def test_revoke_token(self):
		client = frappe.get_doc("OAuth Client", self.client_id)
		client.grant_type = "Authorization Code"
		client.response_type = "Code"
		client.save()
		frappe.db.commit()

		# Go to Authorize url
		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		resp = self.get(
			"/api/method/frappe.integrations.oauth2.authorize",
			{
				"client_id": self.client_id,
				"scope": self.scope,
				"response_type": "code",
				"redirect_uri": self.redirect_uri,
			},
			follow_redirects=True,
		)

		# Get authorization code from redirected URL
		query = parse_qs(resp.request.environ["QUERY_STRING"])
		auth_code = query.get("code")[0]

		# Request for bearer token
		token_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			headers=self.form_header,
			data={
				"grant_type": "authorization_code",
				"code": auth_code,
				"redirect_uri": self.redirect_uri,
				"client_id": self.client_id,
				"client_secret": self.client_secret,
			},
		)

		# Parse bearer token json
		bearer_token = token_response.json

		# Revoke Token
		revoke_token_response = self.post(
			"/api/method/frappe.integrations.oauth2.revoke_token",
			headers=self.form_header,
			data={"token": bearer_token.get("access_token")},
		)

		self.assertTrue(revoke_token_response.status_code == 200)

		# Check revoked token
		self.assertFalse(
			check_valid_openid_response(access_token=bearer_token.get("access_token"), client=self)
		)

	def test_resource_owner_password_credentials_grant_is_rejected(self):
		client = frappe.get_doc("OAuth Client", self.client_id)
		client.grant_type = "Authorization Code"
		client.response_type = "Code"
		client.save()
		frappe.db.commit()

		# Resource Owner Password Credentials Grant is not supported: validate_user
		# always rejects, so no token is issued even with valid client credentials.
		token_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			data={
				"grant_type": "password",
				"username": "test@example.com",
				"password": "Eastern_43A1W",
				"client_id": self.client_id,
				"client_secret": self.client_secret,
				"scope": self.scope,
			},
			headers=self.form_header,
		)

		self.assertEqual(token_response.status_code, 400)
		self.assertEqual(token_response.json.get("error"), "invalid_grant")

	def test_login_using_implicit_token(self):
		self.addCleanup(self._delete_committed_client)
		self.oauth_client.grant_type = "Implicit"
		self.oauth_client.response_type = "Token"
		self.oauth_client.save()
		frappe.db.commit()

		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		response = self.get(
			"/api/method/frappe.integrations.oauth2.authorize",
			{
				"client_id": self.client_id,
				"scope": self.scope,
				"response_type": "token",
				"redirect_uri": self.redirect_uri,
			},
		)
		response_dict = parse_qs(urlparse(response.location).fragment)

		self.assertTrue(response_dict.get("access_token"))
		self.assertTrue(response_dict.get("expires_in"))
		self.assertTrue(response_dict.get("scope"))
		self.assertTrue(response_dict.get("token_type"))
		self.assertTrue(check_valid_openid_response(self, response_dict["access_token"][0]))

	def test_openid_code_id_token(self):
		update_client_for_auth_code_grant(self.client_id)
		nonce = frappe.generate_hash()

		# Go to Authorize url
		self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
		resp = self.get(
			"/api/method/frappe.integrations.oauth2.authorize",
			{
				"client_id": self.client_id,
				"scope": self.scope,
				"response_type": "code",
				"redirect_uri": self.redirect_uri,
				"nonce": nonce,
			},
			follow_redirects=True,
		)

		# Get authorization code from redirected URL
		query = parse_qs(resp.request.environ["QUERY_STRING"])
		auth_code = query.get("code")[0]

		# Request for bearer token
		token_response = self.post(
			"/api/method/frappe.integrations.oauth2.get_token",
			headers=self.form_header,
			data=encode_params(
				{
					"grant_type": "authorization_code",
					"code": auth_code,
					"redirect_uri": self.redirect_uri,
					"client_id": self.client_id,
					"client_secret": self.client_secret,
					"scope": self.scope,
				}
			),
		)

		# Parse bearer token json
		bearer_token = token_response.json

		payload = self.decode_id_token(bearer_token.get("id_token"))
		self.assertEqual(payload["email"], "test@example.com")

		self.assertTrue(payload.get("nonce") == nonce)

	def _write_rs256_key(self, key_file: Path) -> RSAPrivateKey:
		private_key = generate_private_key(public_exponent=65537, key_size=2048)
		key_file.write_bytes(
			private_key.private_bytes(
				serialization.Encoding.PEM,
				serialization.PrivateFormat.PKCS8,
				serialization.NoEncryption(),
			)
		)
		return private_key

	def _patch_request_signing_key(self, key_file: Path | None):
		get_site_config = frappe.get_site_config

		def config_with_signing_key(*args, **kwargs):
			config = get_site_config(*args, **kwargs).copy()
			config["oauth2_rs256_key_file"] = str(key_file) if key_file else None
			return config

		return patch("frappe.get_site_config", side_effect=config_with_signing_key)

	def test_rs256_signing_uses_the_discovered_public_key(self):
		import jwt
		from jwt.utils import base64url_encode

		issuer = "https://issuer.example.com"
		base_url = frappe.db.get_value("Social Login Key", "frappe", "base_url")
		with TemporaryDirectory() as directory:
			key_file = Path(directory, "signing-key.pem")
			private_key = self._write_rs256_key(key_file)

			try:
				frappe.db.set_value("Social Login Key", "frappe", "base_url", issuer)
				with (
					self._patch_request_signing_key(key_file),
					patch.dict(frappe.conf, {"oauth2_rs256_key_file": str(key_file)}),
				):
					self.oauth_client.set("id_token_signing_alg", "RS256")
					self.oauth_client.save()
					frappe.db.commit()

					metadata = self.get("/.well-known/openid-configuration").json
					self.assertEqual(metadata["issuer"], issuer)
					self.assertEqual(metadata["id_token_signing_alg_values_supported"], ["HS256", "RS256"])
					self.assertEqual(metadata["jwks_uri"], issuer + "/.well-known/jwks.json")
					frappe.db.set_value("Social Login Key", "frappe", "base_url", issuer + "/")
					frappe.db.commit()
					self.assertEqual(self.get("/.well-known/openid-configuration").json, metadata)
					(jwk,) = self.get(urlparse(metadata["jwks_uri"]).path).json["keys"]
					self.assertEqual(set(jwk), {"alg", "e", "kid", "kty", "n", "use"})
					self.TEST_CLIENT.set_cookie(key="sid", value=self.sid)
					nonce = frappe.generate_hash()
					code_verifier = frappe.generate_hash(length=64)
					authorize_path = "/api/method/frappe.integrations.oauth2.authorize"
					authorization = {
						"client_id": self.client_id,
						"scope": "openid",
						"response_type": "code",
						"redirect_uri": self.redirect_uri,
						"nonce": nonce,
						"code_challenge_method": "S256",
						"code_challenge": base64url_encode(sha256(code_verifier.encode()).digest()).decode(),
					}
					response = self.get(authorize_path, authorization)
					code = parse_qs(urlparse(response.location).query)["code"][0]
					backend = get_test_client(use_cookies=False)
					grant = {
						"grant_type": "authorization_code",
						"code": code,
						"redirect_uri": self.redirect_uri,
						"code_verifier": code_verifier,
					}
					headers = {**self.form_header, **_client_basic_header(self.client_id, self.client_secret)}

					def exchange():
						return make_request(
							target=backend.post,
							args=("/api/method/frappe.integrations.oauth2.get_token",),
							kwargs={"data": grant, "headers": headers},
							site=self.site,
						)

					backup = key_file.with_suffix(".backup")
					key_file.rename(backup)
					try:
						unavailable = exchange()
						self.assertEqual(unavailable.status_code, 503)
						self.assertEqual(unavailable.json["error"], "server_error")
						self.assertNotIn("id_token", unavailable.json)
					finally:
						backup.rename(key_file)
					response = exchange()
					self.assertEqual(response.status_code, 200)
					token = response.json["id_token"]
					self.assertEqual(jwt.get_unverified_header(token)["kid"], jwk["kid"])
					payload = jwt.decode(
						token,
						key=jwt.PyJWK.from_dict(jwk),
						issuer=issuer,
						audience=self.client_id,
						algorithms=["RS256"],
					)
					self.assertEqual(payload["nonce"], nonce)
					self.assertEqual(payload["email"], "test@example.com")
					self.assertTrue(payload["sub"])
					response = self.get(authorize_path, {**authorization, "id_token_hint": token})
					self.assertIn("code", parse_qs(urlparse(response.location).query))

					for claim, invalid_value in (
						("aud", "another-client"),
						("iss", "https://other.example.com"),
					):
						with self.subTest(claim=claim):
							invalid_hint = jwt.encode(
								{**payload, claim: invalid_value}, private_key, algorithm="RS256"
							)
							response = self.get(
								authorize_path, {**authorization, "id_token_hint": invalid_hint}
							)
							self.assertEqual(response.json["error"], "login_required")
			finally:
				frappe.db.set_value("Social Login Key", "frappe", "base_url", base_url)
				self._delete_committed_client()

	def test_rs256_issuer_requires_a_valid_https_origin(self):
		for origin in ("https://issuer.example.com", "https://issuer.example.com:8443", "https://[::1]:8443"):
			with self.subTest(origin=origin):
				self.assertEqual(oauth2_signing.normalize_rs256_issuer(origin), origin)
				self.assertEqual(oauth2_signing.normalize_rs256_issuer(origin + "/"), origin)

		for invalid in (
			"http://issuer.example.com",
			"https://issuer.example.com:bad",
			"https://issuer.example.com:99999",
			"https://issuer.example.com:0",
			"https://issuer.example.com:",
			"https://issuer.example.com/path",
			"https://issuer.example.com?",
			"https://issuer.example.com#",
			"https://@issuer.example.com",
			"https://issuer.example.com\n",
			"https://[::1]suffix",
			"https://issuer|prod.example.com",
			"https://issuer%.example.com",
			"https://-issuer.example.com",
		):
			with self.subTest(invalid=invalid):
				self.assertIsNone(oauth2_signing.normalize_rs256_issuer(invalid))

	def test_rs256_public_endpoints_reload_the_key_only_when_the_file_changes(self):
		discovery_path = "/.well-known/openid-configuration"
		jwks_path = "/.well-known/jwks.json"
		with TemporaryDirectory() as directory:
			key_file = Path(directory, "signing-key.pem")
			self._write_rs256_key(key_file)
			with (
				self._patch_request_signing_key(key_file),
				patch(
					"frappe.integrations.oauth2.get_rs256_issuer", return_value="https://issuer.example.com"
				),
				patch.object(
					oauth2_signing, "load_pem_private_key", wraps=oauth2_signing.load_pem_private_key
				) as load,
			):
				self.assertIn("jwks_uri", self.get(discovery_path).json)
				original_keys = self.get(jwks_path).json
				self.assertEqual(self.get(jwks_path).json, original_keys)
				self.assertEqual(load.call_count, 1)

				replacement = key_file.with_name("replacement.pem")
				self._write_rs256_key(replacement)
				replacement.replace(key_file)
				rotated_keys = self.get(jwks_path).json
				self.assertNotEqual(rotated_keys["keys"][0]["kid"], original_keys["keys"][0]["kid"])
				self.assertEqual(load.call_count, 2)

				key_file.write_bytes(b"invalid PEM")
				self.assertEqual(self.get(jwks_path).status_code, 404)
				self.assertNotIn("jwks_uri", self.get(discovery_path).json)
				self.assertEqual(load.call_count, 3)

				self._write_rs256_key(key_file)
				self.assertEqual(self.get(jwks_path).status_code, 200)
				key_file.unlink()
				self.assertEqual(self.get(jwks_path).status_code, 404)
				self.assertEqual(
					self.get(discovery_path).json["id_token_signing_alg_values_supported"], ["HS256"]
				)
				self.assertEqual(load.call_count, 4)

	def test_rs256_jwks_retries_when_a_key_is_replaced_during_loading(self):
		open_path = Path.open
		with TemporaryDirectory() as directory:
			key_file = Path(directory, "key.pem")
			replacement = key_file.with_suffix(".new")
			self._write_rs256_key(key_file)
			self._write_rs256_key(replacement)

			def replace_before_open(path, *args, **kwargs):
				if path == key_file and replacement.exists():
					replacement.replace(key_file)
				return open_path(path, *args, **kwargs)

			with (
				self._patch_request_signing_key(key_file),
				patch(
					"frappe.integrations.oauth2.get_rs256_issuer", return_value="https://issuer.example.com"
				),
				patch.object(Path, "open", new=replace_before_open),
			):
				response = self.get("/.well-known/jwks.json")
				self.assertEqual(response.status_code, 200)
				self.assertFalse(replacement.exists())

	def test_rs256_concurrent_key_loads_share_the_validation_result(self):
		with TemporaryDirectory() as directory:
			key_file = Path(directory, "signing-key.pem")
			self._write_rs256_key(key_file)
			configuration = {oauth2_signing.RS256_KEY_CONFIG: str(key_file)}
			site_context = SimpleNamespace(local=SimpleNamespace(site=self.site), conf=configuration)
			ready = Barrier(4, timeout=5)

			def load_key(_):
				ready.wait()
				return oauth2_signing.get_rs256_signing_key()

			with (
				patch.object(oauth2_signing, "frappe", site_context),
				patch.object(
					oauth2_signing, "load_pem_private_key", wraps=oauth2_signing.load_pem_private_key
				) as parse_key,
			):
				try:
					with ThreadPoolExecutor(max_workers=4) as workers:
						first_key, *other_keys = workers.map(load_key, range(4))
					self.assertIsNotNone(first_key)
					for key in other_keys:
						self.assertIs(key, first_key)
					self.assertEqual(parse_key.call_count, 1)
				finally:
					configuration.clear()
					oauth2_signing.get_rs256_signing_key()

	def test_without_a_signing_key_discovery_still_supports_hs256(self):
		with self._patch_request_signing_key(None):
			metadata = self.get("/.well-known/openid-configuration").json
			self.assertEqual(metadata["id_token_signing_alg_values_supported"], ["HS256"])
			self.assertNotIn("jwks_uri", metadata)
			self.assertEqual(self.get("/.well-known/jwks.json").status_code, 404)

	def test_rs256_client_requires_a_signing_key(self):
		with (
			patch(
				"frappe.integrations.doctype.oauth_client.oauth_client.get_rs256_issuer",
				return_value="https://issuer.example.com",
			),
			patch.dict(frappe.conf, {"oauth2_rs256_key_file": None}),
		):
			for algorithm in ("RS256", " RS256 "):
				with self.subTest(algorithm=algorithm), self.assertRaises(frappe.ValidationError):
					self.oauth_client.set("id_token_signing_alg", algorithm)
					self.oauth_client.save()

	def test_build_oauth_url(self):
		self.assertEqual(build_oauth_url("https://example.com", "/endpoint"), "https://example.com/endpoint")

		self.assertEqual(build_oauth_url("https://example.com"), "https://example.com")

		self.assertEqual(build_oauth_url("https://example.com", None), "https://example.com")

		self.assertEqual(
			build_oauth_url("https://example.com", "//endpoint.com/test"),
			"https://example.com//endpoint.com/test",
		)

		self.assertEqual(
			build_oauth_url("https://example.com", "http://endpoint.com/test"), "http://endpoint.com/test"
		)

		self.assertEqual(
			build_oauth_url("https://example.com", "https://endpoint.com"), "https://endpoint.com"
		)

		self.assertEqual(build_oauth_url("https://example.com", ""), "https://example.com")

	def decode_id_token(self, id_token):
		import jwt

		return jwt.decode(
			id_token,
			audience=self.client_id,
			key=self.client_secret,
			algorithms=["HS256"],
			options={"verify_signature": True, "require": ["exp", "iat", "aud"]},
		)


def _client_basic_header(client_id: str, secret: str) -> dict[str, str]:
	credentials = f"{quote_plus(client_id)}:{quote_plus(secret)}"
	return {"Authorization": f"Basic {b64encode(credentials.encode()).decode()}"}


def check_valid_openid_response(client: FrappeRequestTestCase, access_token: str | None = None) -> bool:
	headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
	response = client.get("/api/method/frappe.integrations.oauth2.openid_profile", headers=headers)
	return response.status_code == 200


def update_client_for_auth_code_grant(client_id):
	client = frappe.get_doc("OAuth Client", client_id)
	client.grant_type = "Authorization Code"
	client.response_type = "Code"
	client.save()
	frappe.db.commit()
	return client
