"""????? MCP ?????????????????????"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from typing import Any


def json_text(value: Any) -> str:
    """???????????? JSON ???"""
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def auto_detect_encoding(value: str) -> dict:
    """?????????????????"""
    text = str(value or "").strip()
    candidates: list[str] = []
    if re.fullmatch(r"[0-9a-fA-F]+", text or "") and len(text) % 2 == 0:
        candidates.append("hex")
    if re.fullmatch(r"[A-Za-z0-9_\-]+={0,2}", text or "") and len(text) >= 8:
        candidates.append("base64url" if ("-" in text or "_" in text) else "base64")
    if "%" in text:
        candidates.append("url_encoded")
    return {"value_length": len(text), "candidates": candidates, "looks_json": text.startswith(("{", "["))}


def decode_payload(value: str, input_encoding: str = "auto") -> dict:
    """??????????????????????????"""
    text = str(value or "")
    encoding = input_encoding if input_encoding != "auto" else (auto_detect_encoding(text)["candidates"] or ["utf-8"])[0]
    raw: bytes
    if encoding == "hex":
        raw = bytes.fromhex(text)
    elif encoding == "base64url":
        raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    elif encoding == "base64":
        raw = base64.b64decode(text + "=" * (-len(text) % 4))
    else:
        raw = text.encode("utf-8")
    try:
        decoded = raw.decode("utf-8")
    except UnicodeDecodeError:
        decoded = ""
    return {"encoding": encoding, "bytes": len(raw), "text": decoded, "hex_preview": raw[:128].hex()}


def _decode_key(value: str, encoding: str) -> bytes:
    """? key_encoding ????? IV?"""
    if encoding == "hex":
        return bytes.fromhex(value)
    if encoding == "base64":
        return base64.b64decode(value + "=" * (-len(value) % 4))
    return value.encode("utf-8")


def _unpad_pkcs7(data: bytes) -> bytes:
    """???? PKCS#7 ?????????????"""
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and data.endswith(bytes([pad]) * pad):
        return data[:-pad]
    return data


def decrypt_payload(
    value: str,
    *,
    algorithm: str = "aes",
    key: str = "",
    mode: str = "cbc",
    iv: str = "",
    input_encoding: str = "base64",
    key_encoding: str = "utf-8",
    iv_encoding: str = "utf-8",
) -> dict:
    """???? AES/DES/3DES ????????????"""
    decoded = decode_payload(value, input_encoding)
    ciphertext = bytes.fromhex(decoded["hex_preview"])
    # ?? hex_preview ?????????????????
    enc = input_encoding if input_encoding != "auto" else decoded["encoding"]
    if enc == "hex":
        ciphertext = bytes.fromhex(value)
    elif enc == "base64url":
        ciphertext = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    elif enc == "base64":
        ciphertext = base64.b64decode(value + "=" * (-len(value) % 4))
    else:
        ciphertext = value.encode("utf-8")
    key_bytes = _decode_key(key, key_encoding)
    iv_bytes = _decode_key(iv, iv_encoding) if iv else b""
    algo = algorithm.lower()
    cipher_mode = mode.lower()
    if algo in {"md5", "sha1", "sha256", "hmac-sha256"}:
        if algo == "md5":
            digest = hashlib.md5(value.encode("utf-8")).hexdigest()
        elif algo == "sha1":
            digest = hashlib.sha1(value.encode("utf-8")).hexdigest()
        elif algo == "sha256":
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        else:
            digest = hmac.new(key_bytes, value.encode("utf-8"), hashlib.sha256).hexdigest()
        return {"algorithm": algo, "digest": digest}
    try:
        if algo == "aes":
            from Crypto.Cipher import AES
            cipher = AES.new(key_bytes, AES.MODE_ECB if cipher_mode == "ecb" else AES.MODE_CBC, iv=iv_bytes or None) if cipher_mode != "ecb" else AES.new(key_bytes, AES.MODE_ECB)
        elif algo in {"des3", "3des", "triple_des"}:
            from Crypto.Cipher import DES3
            cipher = DES3.new(key_bytes, DES3.MODE_ECB if cipher_mode == "ecb" else DES3.MODE_CBC, iv=iv_bytes or None) if cipher_mode != "ecb" else DES3.new(key_bytes, DES3.MODE_ECB)
        elif algo == "des":
            from Crypto.Cipher import DES
            cipher = DES.new(key_bytes, DES.MODE_ECB if cipher_mode == "ecb" else DES.MODE_CBC, iv=iv_bytes or None) if cipher_mode != "ecb" else DES.new(key_bytes, DES.MODE_ECB)
        else:
            return {"ok": False, "error": f"???????{algorithm}"}
        plaintext = _unpad_pkcs7(cipher.decrypt(ciphertext))
        return {"ok": True, "algorithm": algo, "mode": cipher_mode, "text": plaintext.decode("utf-8", errors="replace"), "hex": plaintext.hex()}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "algorithm": algo, "mode": cipher_mode}


def detect_ecb_pattern(value: str, input_encoding: str = "base64", block_size: int = 16) -> dict:
    """???????????????? ECB ???"""
    data = decode_payload(value, input_encoding)
    raw = bytes.fromhex(data["hex_preview"])
    if input_encoding == "hex":
        raw = bytes.fromhex(value)
    elif input_encoding == "base64":
        raw = base64.b64decode(value + "=" * (-len(value) % 4))
    blocks = [raw[i : i + block_size] for i in range(0, len(raw), block_size) if len(raw[i : i + block_size]) == block_size]
    repeated = len(blocks) - len(set(blocks))
    return {"blocks": len(blocks), "repeated_blocks": repeated, "possible_ecb": repeated > 0}


def identify_crypto_pattern(text: str) -> dict:
    """?????????????????"""
    source = str(text or "")
    patterns = {
        "cryptojs": "CryptoJS" in source,
        "aes": bool(re.search(r"AES|aes", source)),
        "rsa": bool(re.search(r"RSA|JSEncrypt|publicKey|privateKey", source)),
        "md5": bool(re.search(r"MD5|md5", source)),
        "sha_hmac": bool(re.search(r"Hmac|SHA\d+|sha\d+", source)),
        "base64": bool(re.search(r"Base64|atob|btoa|base64", source)),
        "jsvmp": bool(re.search(r"while\s*\([^)]*true|switch\s*\(|_0x[0-9a-fA-F]{4,}", source)),
        "webpack": "__webpack_require__" in source or "webpackJsonp" in source,
    }
    return {"patterns": patterns, "recommendation": "?????? Hook ????" if patterns["jsvmp"] else "????????????"}
