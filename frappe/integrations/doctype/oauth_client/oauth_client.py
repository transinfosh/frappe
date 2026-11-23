# Copyright (c) 2015, Frappe Technologies and contributors
# License: MIT. See LICENSE

import datetime
import time

import frappe
import frappe.utils
from frappe import _
from frappe.integrations.oauth2_signing import get_rs256_issuer, get_rs256_signing_key
from frappe.model.document import Document
from frappe.permissions import SYSTEM_USER_ROLE
from frappe.utils import cstr


class OAuthClient(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.integrations.doctype.oauth_client_role.oauth_client_role import OAuthClientRole
		from frappe.types import DF

		allowed_roles: DF.TableMultiSelect[OAuthClientRole]
		app_name: DF.Data
		client_id: DF.Data | None
		client_secret: DF.Data | None
		client_uri: DF.Data | None
		contacts: DF.SmallText | None
		default_redirect_uri: DF.Data
		grant_type: DF.Literal["Authorization Code", "Implicit"]
		logo_uri: DF.Data | None
		policy_uri: DF.Data | None
		redirect_uris: DF.Text | None
		response_type: DF.Literal["Code", "Token"]
		scopes: DF.Text
		skip_authorization: DF.Check
		software_id: DF.Data | None
		software_version: DF.Data | None
		token_endpoint_auth_method: DF.Literal["Client Secret Basic", "Client Secret Post", "None"]
		tos_uri: DF.Data | None
		user: DF.Link | None
	# end: auto-generated types

	def validate(self):
		self.client_id = self.name
		if not self.client_secret:
			self.client_secret = frappe.generate_hash(length=10)
		self.validate_grant_and_response()
		if cstr(self.get("id_token_signing_alg")).strip() == "RS256":
			if not get_rs256_issuer():
				frappe.throw(
					_("Set the Frappe Social Login Key Base URL to the HTTPS issuer before enabling RS256.")
				)
			if not get_rs256_signing_key():
				frappe.throw(_("Configure a valid RSA signing key for this site before enabling RS256."))
		self.add_default_role()

	def validate_grant_and_response(self):
		if (self.grant_type == "Authorization Code" and self.response_type != "Code") or (
			self.grant_type == "Implicit" and self.response_type != "Token"
		):
			frappe.throw(
				_(
					"Combination of Grant Type (<code>{0}</code>) and Response Type (<code>{1}</code>) not allowed"
				).format(self.grant_type, self.response_type)
			)

	def add_default_role(self):
		if not self.allowed_roles:
			self.append("allowed_roles", {"role": SYSTEM_USER_ROLE})

	def user_has_allowed_role(self) -> bool:
		"""Returns true if session user is allowed to use this client."""
		allowed_roles = {d.role for d in self.allowed_roles}
		return bool(allowed_roles & set(frappe.get_roles()))

	def is_public_client(self) -> bool:
		return self.token_endpoint_auth_method == "None"

	def client_id_issued_at(self) -> int:
		"""Returns UNIX timestamp (seconds since epoch) of the client creation time."""

		if isinstance(self.creation, datetime.datetime):
			return int(self.creation.timestamp())

		try:
			d = datetime.datetime.fromisoformat(self.creation)
			return int(d.timestamp())
		except Exception:
			return int(frappe.utils.now_datetime().timestamp())
