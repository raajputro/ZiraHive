"""Batch 7: passkeys, voice chat signalling, plugins, linked servers."""
from __future__ import annotations

import base64
import hashlib
import json
import os

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

ORIGIN = "https://gharbox.example.ts.net"
HOST = {"Origin": ORIGIN, "Host": "gharbox.example.ts.net"}


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SoftKey:
    """A passkey the way a phone keeps it: an EC key pair, a credential id, a counter."""

    def __init__(self, rp_id: str = "gharbox.example.ts.net"):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.rp_id, self.count, self.user_handle = rp_id, 0, None

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def create(self, options: dict, origin: str = ORIGIN) -> dict:
        self.user_handle = options["user"]["id"]
        client = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": origin}).encode()
        auth = (hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x45]) + self.count.to_bytes(4, "big")
                + bytes(16) + len(self.cred_id).to_bytes(2, "big") + self.cred_id + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth})
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "attestationObject": b64u(att), "transports": ["internal"]}}

    def get(self, options: dict, origin: str = ORIGIN) -> dict:
        self.count += 1
        client = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": origin}).encode()
        auth = hashlib.sha256(self.rp_id.encode()).digest() + bytes([0x05]) + self.count.to_bytes(4, "big")
        sig = self.key.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
        return {"id": b64u(self.cred_id), "rawId": b64u(self.cred_id), "type": "public-key",
                "response": {"clientDataJSON": b64u(client), "authenticatorData": b64u(auth),
                             "signature": b64u(sig), "userHandle": self.user_handle}}


async def add_passkey(client, key: SoftKey, name="Pixel 7") -> dict:
    o = (await client.post("/api/auth/passkeys/register/options", headers=HOST)).json()
    assert o["options"]["rp"]["id"] == "gharbox.example.ts.net"
    assert o["options"]["authenticatorSelection"]["residentKey"] == "required"
    r = await client.post("/api/auth/passkeys/register", headers=HOST,
                          json={"state": o["state"], "credential": key.create(o["options"]), "name": name})
    assert r.status_code == 201, r.text
    return r.json()


async def passkey_login(client, key: SoftKey, origin=ORIGIN):
    o = (await client.post("/api/auth/passkeys/login/options", headers=HOST)).json()
    assert "allowCredentials" not in o["options"] or not o["options"]["allowCredentials"]
    return await client.post("/api/auth/passkeys/login", headers=HOST,
                             json={"state": o["state"], "credential": key.get(o["options"], origin)})


async def test_passkey_sign_in(client, admin):
    key = SoftKey()
    pk = await add_passkey(client, key)
    assert pk["name"] == "Pixel 7" and pk["rp_id"] == "gharbox.example.ts.net"
    assert [p["name"] for p in (await client.get("/api/auth/passkeys")).json()] == ["Pixel 7"]
    notes = (await client.get("/api/notifications")).json()["items"]
    assert any("passkey" in n["title"] for n in notes)

    client.headers.pop("Authorization")
    client.cookies.clear()
    r = await passkey_login(client, key)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == "mahbub" and r.headers.get("set-cookie")
    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.status_code == 200

    # a copied or replayed answer doesn't work, nor does another key or another site's answer
    o = (await client.post("/api/auth/passkeys/login/options", headers=HOST)).json()
    answer = key.get(o["options"])
    assert (await client.post("/api/auth/passkeys/login", headers=HOST,
                              json={"state": o["state"], "credential": answer})).status_code == 200
    assert (await client.post("/api/auth/passkeys/login", headers=HOST,
                              json={"state": o["state"], "credential": answer})).status_code == 400
    stranger = SoftKey()
    stranger.user_handle = key.user_handle
    assert (await passkey_login(client, stranger)).status_code == 401
    phished = await passkey_login(client, key, origin="https://gharbox-login.example.com")
    assert phished.status_code == 401


async def test_passkeys_need_a_secure_address_and_can_be_removed(client, admin):
    r = await client.post("/api/auth/passkeys/register/options",
                          headers={"Origin": "http://192.168.0.5:8080", "Host": "192.168.0.5:8080"})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "passkey_insecure"
    local = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "http://localhost:8080", "Host": "localhost:8080"})
    assert local.status_code == 200
    other = await client.post("/api/auth/passkeys/register/options",
                              headers={"Origin": "https://evil.example", "Host": "gharbox.example.ts.net"})
    assert other.status_code == 400

    key = SoftKey()
    pk = await add_passkey(client, key)
    assert (await client.delete(f"/api/auth/passkeys/{pk['id']}")).status_code == 204
    client.headers.pop("Authorization")
    client.cookies.clear()
    assert (await passkey_login(client, key)).status_code == 401
