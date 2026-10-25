"""A minimal software WebAuthn authenticator — stands in for a real
hardware passkey so auth/webauthn.py and auth/web.py can be exercised
without hardware. Used by the pytest suite; not imported by the actual
application code (auth/) — only by things that are themselves testing
or exercising it."""

from __future__ import annotations

import hashlib
import json
import os

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_encode
from fido2.webauthn import (
    AttestationObject,
    AttestedCredentialData,
    AuthenticationResponse,
    AuthenticatorAssertionResponse,
    AuthenticatorAttestationResponse,
    AuthenticatorData,
    CollectedClientData,
    RegistrationResponse,
)


class SoftAuthenticator:
    def __init__(self, rp_id: str, origin: str) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(16)
        self.counter = 0
        self.user_handle: bytes | None = None

    def _rp_id_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _client_data(self, type_: str, challenge: bytes) -> tuple[bytes, CollectedClientData]:
        raw = json.dumps(
            {"type": type_, "challenge": websafe_encode(challenge), "origin": self.origin},
            separators=(",", ":"),
        ).encode()
        return raw, CollectedClientData(raw)

    def register(self, options) -> RegistrationResponse:
        challenge = options.public_key.challenge
        self.user_handle = options.public_key.user.id
        cose_key = ES256.from_cryptography_key(self._private_key.public_key())
        attested = AttestedCredentialData.create(b"\x00" * 16, self.credential_id, cose_key)
        flags = AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV | AuthenticatorData.FLAG.AT
        auth_data = AuthenticatorData.create(
            self._rp_id_hash(), flags, self.counter, bytes(attested)
        )
        attestation_object = AttestationObject.create("none", auth_data, {})
        _, client_data = self._client_data("webauthn.create", challenge)
        return RegistrationResponse(
            raw_id=self.credential_id,
            response=AuthenticatorAttestationResponse(
                client_data=client_data, attestation_object=attestation_object
            ),
        )

    def authenticate(
        self, options, *, bump_counter: bool = True, challenge_override: bytes | None = None
    ) -> AuthenticationResponse:
        """Sign `options`'s challenge (or `challenge_override`, to simulate a
        forged/stale assertion in tests)."""
        challenge = (
            challenge_override if challenge_override is not None else options.public_key.challenge
        )
        if bump_counter:
            self.counter += 1
        flags = AuthenticatorData.FLAG.UP | AuthenticatorData.FLAG.UV
        auth_data = AuthenticatorData.create(self._rp_id_hash(), flags, self.counter, b"")
        client_data_json, client_data = self._client_data("webauthn.get", challenge)
        signature = self._private_key.sign(
            bytes(auth_data) + hashlib.sha256(client_data_json).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        return AuthenticationResponse(
            raw_id=self.credential_id,
            response=AuthenticatorAssertionResponse(
                client_data=client_data,
                authenticator_data=auth_data,
                signature=signature,
                # Real resident/discoverable credentials report the account
                # (user.id from registration) back in the assertion; this is
                # what lets passkey-only sign-in work with no account typed
                # first.
                user_handle=self.user_handle,
            ),
        )

    def register_json(self, public_key_json: dict) -> dict:
        """Like `register`, but takes the same `publicKey` JSON a real
        page would pass to `PublicKeyCredential.parseCreationOptionsFromJSON`,
        and returns the same JSON a real `credential.toJSON()` would — for
        driving the real HTTP endpoints without a browser."""
        from fido2.webauthn import CredentialCreationOptions

        options = CredentialCreationOptions.from_dict({"publicKey": public_key_json})
        return _response_to_json(self.register(options))

    def authenticate_json(self, public_key_json: dict) -> dict:
        from fido2.webauthn import CredentialRequestOptions

        options = CredentialRequestOptions.from_dict({"publicKey": public_key_json})
        return _response_to_json(self.authenticate(options))


def _response_to_json(response: RegistrationResponse | AuthenticationResponse) -> dict:
    base = {
        "id": websafe_encode(response.raw_id),
        "rawId": websafe_encode(response.raw_id),
        "type": "public-key",
        "clientExtensionResults": {},
    }
    if isinstance(response, RegistrationResponse):
        base["response"] = {
            "clientDataJSON": websafe_encode(bytes(response.response.client_data)),
            "attestationObject": websafe_encode(bytes(response.response.attestation_object)),
        }
    else:
        base["response"] = {
            "clientDataJSON": websafe_encode(bytes(response.response.client_data)),
            "authenticatorData": websafe_encode(bytes(response.response.authenticator_data)),
            "signature": websafe_encode(response.response.signature),
        }
        if response.response.user_handle:
            base["response"]["userHandle"] = websafe_encode(response.response.user_handle)
    return base
