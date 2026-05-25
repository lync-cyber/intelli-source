"""WeWork (企微) AES-CBC message encryption/decryption per official callback spec."""

from __future__ import annotations

import base64
import hashlib
import os
import struct
import xml.etree.ElementTree as ET

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(ValueError):
    """Raised on signature mismatch or decryption failure."""


class WeComCrypto:
    """Handles WeWork webhook URL verification and message decryption.

    Args:
        token: The callback token configured in WeWork admin console.
        encoding_aes_key: The 43-character EncodingAESKey from WeWork admin console.
        corp_id: The corpId (receiver identity validated after decryption).
    """

    def __init__(self, token: str, encoding_aes_key: str, corp_id: str) -> None:
        if len(encoding_aes_key) != 43:
            raise WeComCryptoError(
                f"EncodingAESKey must be 43 characters, got {len(encoding_aes_key)}"
            )
        self._token = token
        self._corp_id = corp_id
        raw_key = base64.b64decode(encoding_aes_key + "=")
        if len(raw_key) != 32:
            raise WeComCryptoError("Decoded AES key must be 32 bytes")
        self._aes_key: bytes = raw_key
        self._iv: bytes = raw_key[:16]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def verify_url(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        echostr: str,
    ) -> str:
        """Verify GET URL handshake; return decrypted echo plaintext on success."""
        self._check_signature(msg_signature, timestamp, nonce, echostr)
        plain = self._aes_decrypt(echostr)
        # plain = random(16B) + msg_len(4B BE) + msg + receiver_id
        return self._extract_message(plain)

    def decrypt_message(
        self,
        msg_signature: str,
        timestamp: str,
        nonce: str,
        encrypted_xml_body: str,
    ) -> str:
        """Verify POST callback signature and decrypt; return plaintext XML."""
        encrypt = self._extract_encrypt_field(encrypted_xml_body)
        self._check_signature(msg_signature, timestamp, nonce, encrypt)
        plain = self._aes_decrypt(encrypt)
        return self._extract_message(plain)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_signature(self, timestamp: str, nonce: str, data: str) -> str:
        parts = sorted([self._token, timestamp, nonce, data])
        return hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()  # noqa: S324

    def _check_signature(
        self, msg_signature: str, timestamp: str, nonce: str, data: str
    ) -> None:
        expected = self._make_signature(timestamp, nonce, data)
        if expected != msg_signature:
            raise WeComCryptoError("Invalid msg_signature")

    def _aes_decrypt(self, encrypted_b64: str) -> bytes:
        try:
            ciphertext = base64.b64decode(encrypted_b64)
        except Exception as exc:
            raise WeComCryptoError("Invalid base64 in encrypted payload") from exc
        cipher = Cipher(algorithms.AES(self._aes_key), modes.CBC(self._iv))
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        return self._pkcs7_unpad(padded)

    @staticmethod
    def _pkcs7_unpad(data: bytes) -> bytes:
        if not data:
            raise WeComCryptoError("Empty decrypted payload")
        pad_len = data[-1]
        if pad_len < 1 or pad_len > 32:
            raise WeComCryptoError(f"Invalid PKCS7 pad length: {pad_len}")
        return data[:-pad_len]

    def _extract_message(self, plain: bytes) -> str:
        """Parse random(16) + msg_len(4 BE) + msg + receiver_id.

        The trailing receiver_id is compared against the configured corp_id
        — a mismatch indicates a payload forged by a different tenant and is
        rejected per the WeWork callback spec.
        """
        if len(plain) < 20:
            raise WeComCryptoError("Decrypted payload too short")
        msg_len = struct.unpack(">I", plain[16:20])[0]
        if len(plain) < 20 + msg_len:
            raise WeComCryptoError("Decrypted payload length mismatch")
        msg = plain[20 : 20 + msg_len].decode("utf-8")
        receiver_id = plain[20 + msg_len :].decode("utf-8", errors="replace")
        if receiver_id != self._corp_id:
            raise WeComCryptoError(
                f"receiver_id mismatch: expected {self._corp_id!r}, got {receiver_id!r}"
            )
        return msg

    @staticmethod
    def _extract_encrypt_field(xml_body: str) -> str:
        try:
            root = ET.fromstring(xml_body)  # noqa: S314
        except ET.ParseError as exc:
            raise WeComCryptoError("Cannot parse encrypted XML body") from exc
        node = root.find("Encrypt")
        if node is None or not node.text:
            raise WeComCryptoError("Missing <Encrypt> field in XML body")
        return node.text


def _pkcs7_pad(data: bytes, block_size: int = 32) -> bytes:
    """PKCS7 padding to block_size (used in tests to construct fixtures)."""
    pad_len = block_size - (len(data) % block_size)
    return data + bytes([pad_len] * pad_len)


def build_encrypted_payload(
    token: str,
    encoding_aes_key: str,
    corp_id: str,
    message: str,
    timestamp: str,
    nonce: str,
) -> tuple[str, str]:
    """Encrypt *message* and return (encrypt_b64, msg_signature).

    Utility for constructing test fixtures — not part of the production API.
    """
    raw_key = base64.b64decode(encoding_aes_key + "=")
    iv = raw_key[:16]
    msg_bytes = message.encode("utf-8")
    random_bytes = os.urandom(16)
    msg_len = struct.pack(">I", len(msg_bytes))
    receiver = corp_id.encode("utf-8")
    plain = random_bytes + msg_len + msg_bytes + receiver
    padded = _pkcs7_pad(plain)
    cipher = Cipher(algorithms.AES(raw_key), modes.CBC(iv))
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    encrypt_b64 = base64.b64encode(ciphertext).decode("utf-8")
    parts = sorted([token, timestamp, nonce, encrypt_b64])
    sig = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()  # noqa: S324
    return encrypt_b64, sig
