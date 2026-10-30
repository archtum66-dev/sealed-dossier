"""secp256k1 ECDSA (EIP-191 personal sign, address recovery)."""

from __future__ import annotations

import hashlib
import hmac

from sealed.keccak import keccak256

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
A = 0
B = 7
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _int_to_bytes32(value: int) -> bytes:
    return value.to_bytes(32, "big")


def _bytes_to_int(data: bytes) -> int:
    return int.from_bytes(data, "big")


def eip191_hash(text: str) -> bytes:
    """EIP-191 personal message hash (32 bytes)."""
    b = text.encode("utf-8")
    prefix = b"\x19Ethereum Signed Message:\n" + str(len(b)).encode() + b
    return keccak256(prefix)


def _inv(value: int, modulus: int) -> int:
    return pow(value, -1, modulus)


def _point_add(p1: tuple[int, int] | None, p2: tuple[int, int] | None) -> tuple[int, int] | None:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        if y1 == 0:
            return None
        s = (3 * x1 * x1 + A) * _inv(2 * y1, P) % P
    else:
        s = (y2 - y1) * _inv(x2 - x1, P) % P
    x3 = (s * s - x1 - x2) % P
    y3 = (s * (x1 - x3) - y1) % P
    return (x3, y3)


def _scalar_mult(k: int, point: tuple[int, int] | None) -> tuple[int, int] | None:
    if k % N == 0 or point is None:
        return None
    result: tuple[int, int] | None = None
    addend = point
    k = k % N
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def address_from_private_key(priv: int) -> str:
    """Return lowercase 0x + 40 hex address for a private key."""
    if priv <= 0 or priv >= N:
        raise ValueError("invalid private key")
    pub = _scalar_mult(priv, (GX, GY))
    if pub is None:
        raise ValueError("invalid private key")
    x, y = pub
    digest = keccak256(_int_to_bytes32(x) + _int_to_bytes32(y))
    return "0x" + digest[-20:].hex()


def _deterministic_k(msg_hash: bytes, priv: int) -> int:
    x = _int_to_bytes32(priv)
    z = _int_to_bytes32(_bytes_to_int(msg_hash) % N)
    v = b"\x01" * 32
    k = b"\x00" * 32
    k = hmac.new(k, v + b"\x00" + x + z, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + z, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        candidate = _bytes_to_int(v)
        if 1 <= candidate < N:
            return candidate
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def personal_sign(text: str, priv: int) -> str:
    """EIP-191 signature as 0x + 130 hex (r||s||v), v in {27, 28}, low-s."""
    msg_hash = eip191_hash(text)
    z = _bytes_to_int(msg_hash) % N
    k = _deterministic_k(_int_to_bytes32(z), priv)
    r_point = _scalar_mult(k, (GX, GY))
    if r_point is None:
        raise ValueError("failed to sign")
    r, y = r_point
    s_raw = _inv(k, N) * (z + r * priv) % N
    v = 27 + ((y % 2) ^ (0 if s_raw * 2 < N else 1))
    s = s_raw if s_raw * 2 < N else N - s_raw
    return "0x" + _int_to_bytes32(r).hex() + _int_to_bytes32(s).hex() + f"{v:02x}"


def _ecdsa_verify(message_hash: bytes, r: int, s: int, pub: tuple[int, int], r_point: tuple[int, int]) -> bool:
    if r % N == 0 or s % N == 0:
        return False
    z = _bytes_to_int(message_hash) % N
    left = _scalar_mult(s, r_point)
    right = _point_add(_scalar_mult(z, (GX, GY)), _scalar_mult(r, pub))
    return left is not None and right is not None and left == right


def recover_address(message_hash: bytes, signature_hex: str) -> str:
    """Recover signer address from 32-byte hash and 0x + 130 hex signature."""
    if not signature_hex.startswith("0x"):
        raise ValueError("signature must start with 0x")
    sig = signature_hex[2:]
    if len(sig) != 130 or not all(c in "0123456789abcdefABCDEF" for c in sig):
        raise ValueError("malformed signature")
    sig = sig.lower()
    r = int(sig[:64], 16)
    s = int(sig[64:128], 16)
    v_raw = int(sig[128:130], 16)
    if v_raw in (27, 28):
        recid = v_raw - 27
    elif v_raw in (0, 1):
        recid = v_raw
    else:
        raise ValueError("invalid recovery id")
    if r < 1 or r >= N or s < 1 or s >= N:
        raise ValueError("invalid r or s")
    if len(message_hash) != 32:
        raise ValueError("message hash must be 32 bytes")

    if v_raw in (0, 1):
        candidates = [0, 1]
    else:
        candidates = [recid]

    last_error: ValueError | None = None
    for rid in candidates:
        try:
            v = rid + 27
            x = r
            xcubedaxb = (pow(x, 3, P) + A * x + B) % P
            beta = pow(xcubedaxb, (P + 1) // 4, P)
            y = beta if (v % 2) ^ (beta % 2) else (P - beta)
            if (xcubedaxb - y * y) % P != 0:
                raise ValueError("no valid point")
            z = _bytes_to_int(message_hash)
            gz = _scalar_mult((N - z) % N, (GX, GY))
            sr = _scalar_mult(s, (x, y))
            if gz is None or sr is None:
                raise ValueError("no valid point")
            qr = _point_add(gz, sr)
            if qr is None:
                raise ValueError("no valid point")
            pub = _scalar_mult(_inv(r, N), qr)
            if pub is None:
                raise ValueError("no valid point")
            if not _ecdsa_verify(message_hash, r, s, pub, (x, y)):
                raise ValueError("invalid signature")
            px, py = pub
            digest = keccak256(_int_to_bytes32(px) + _int_to_bytes32(py))
            return "0x" + digest[-20:].hex()
        except ValueError as exc:
            last_error = exc
            continue
    raise last_error or ValueError("no valid point")
