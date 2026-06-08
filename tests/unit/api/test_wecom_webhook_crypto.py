"""Unit tests for WeComCrypto — F-11 EncodingAESKey AES-CBC webhook decryption."""

from __future__ import annotations

import pytest

from intellisource.core.webhook_crypto import (
    WeComCrypto,
    WeComCryptoError,
    build_encrypted_payload,
)

# ---------------------------------------------------------------------------
# Shared test fixtures — self-consistent (token / key / corp_id)
# ---------------------------------------------------------------------------

TOKEN = "test_token_abc"
# 43-char EncodingAESKey (URL-safe base64 without trailing '=')
ENCODING_AES_KEY = "abcdefghijklmnopqrstuvwxyz0123456789ABCDEFG"
CORP_ID = "wx1234567890abcdef"

TIMESTAMP = "1609459200"
NONCE = "random_nonce_xyz"


@pytest.fixture()
def crypto() -> WeComCrypto:
    return WeComCrypto(token=TOKEN, encoding_aes_key=ENCODING_AES_KEY, corp_id=CORP_ID)


# ---------------------------------------------------------------------------
# Test: URL verification (GET echostr decryption)
# ---------------------------------------------------------------------------


class TestVerifyUrl:
    def test_decrypt_echo_with_valid_signature(self, crypto: WeComCrypto) -> None:
        echo_message = "hello_echo_12345"
        encrypt_b64, sig = build_encrypted_payload(
            TOKEN, ENCODING_AES_KEY, CORP_ID, echo_message, TIMESTAMP, NONCE
        )
        result = crypto.verify_url(sig, TIMESTAMP, NONCE, encrypt_b64)
        assert result == echo_message

    def test_invalid_signature_raises_on_verify_url(self, crypto: WeComCrypto) -> None:
        echo_message = "some_echo"
        encrypt_b64, _correct_sig = build_encrypted_payload(
            TOKEN, ENCODING_AES_KEY, CORP_ID, echo_message, TIMESTAMP, NONCE
        )
        with pytest.raises(WeComCryptoError, match="Invalid msg_signature"):
            crypto.verify_url("wrong_signature_aabbcc", TIMESTAMP, NONCE, encrypt_b64)


# ---------------------------------------------------------------------------
# Test: POST message decryption
# ---------------------------------------------------------------------------


class TestDecryptMessage:
    def _make_encrypted_xml(self, encrypt_b64: str) -> str:
        return (
            "<xml>"
            f"<Encrypt><![CDATA[{encrypt_b64}]]></Encrypt>"
            "<ToUserName><![CDATA[wx_corp]]></ToUserName>"
            "</xml>"
        )

    def test_decrypt_message_body_extracts_plain_xml(self, crypto: WeComCrypto) -> None:
        plain_xml = "<xml><MsgType>text</MsgType><Content>hello</Content></xml>"
        encrypt_b64, sig = build_encrypted_payload(
            TOKEN, ENCODING_AES_KEY, CORP_ID, plain_xml, TIMESTAMP, NONCE
        )
        xml_body = self._make_encrypted_xml(encrypt_b64)
        result = crypto.decrypt_message(sig, TIMESTAMP, NONCE, xml_body)
        assert result == plain_xml

    def test_invalid_signature_returns_crypto_error(self, crypto: WeComCrypto) -> None:
        plain_xml = "<xml><Content>hi</Content></xml>"
        encrypt_b64, _sig = build_encrypted_payload(
            TOKEN, ENCODING_AES_KEY, CORP_ID, plain_xml, TIMESTAMP, NONCE
        )
        xml_body = self._make_encrypted_xml(encrypt_b64)
        with pytest.raises(WeComCryptoError, match="Invalid msg_signature"):
            crypto.decrypt_message("bad_sig", TIMESTAMP, NONCE, xml_body)

    def test_missing_encrypt_field_raises(self, crypto: WeComCrypto) -> None:
        xml_body = "<xml><ToUserName>corp</ToUserName></xml>"
        with pytest.raises(WeComCryptoError, match="Missing <Encrypt>"):
            crypto.decrypt_message("any", TIMESTAMP, NONCE, xml_body)


# ---------------------------------------------------------------------------
# Test: Constructor validation
# ---------------------------------------------------------------------------


class TestInvalidAesKey:
    def test_invalid_aes_key_length_raises(self) -> None:
        with pytest.raises(WeComCryptoError, match="43 characters"):
            WeComCrypto(token=TOKEN, encoding_aes_key="tooshort", corp_id=CORP_ID)

    def test_valid_key_constructs_without_error(self) -> None:
        crypto = WeComCrypto(
            token=TOKEN, encoding_aes_key=ENCODING_AES_KEY, corp_id=CORP_ID
        )
        assert isinstance(crypto, WeComCrypto)


# ---------------------------------------------------------------------------
# Test: receiver_id strict match (F-11 follow-up)
# ---------------------------------------------------------------------------


class TestReceiverIdValidation:
    """Decrypted payload's trailing receiver_id must match configured corp_id."""

    def test_mismatched_receiver_id_raises(self) -> None:
        """Payload encrypted with a foreign corp_id must be rejected even when
        the signature and AES key are valid — guards against cross-tenant
        forgery on a shared callback endpoint."""
        foreign_corp_id = "wx_attacker_corp"
        plain_xml = "<xml><Content>spoofed</Content></xml>"

        # Build a payload as if a different corp had sent it
        encrypt_b64, sig = build_encrypted_payload(
            TOKEN, ENCODING_AES_KEY, foreign_corp_id, plain_xml, TIMESTAMP, NONCE
        )

        # Receiver is our corp; the signature & AES key happen to be the same
        # (a leaked token + key scenario), but receiver_id check must fail.
        crypto = WeComCrypto(
            token=TOKEN, encoding_aes_key=ENCODING_AES_KEY, corp_id=CORP_ID
        )
        xml_body = f"<xml><Encrypt><![CDATA[{encrypt_b64}]]></Encrypt></xml>"
        with pytest.raises(WeComCryptoError, match="receiver_id mismatch"):
            crypto.decrypt_message(sig, TIMESTAMP, NONCE, xml_body)
