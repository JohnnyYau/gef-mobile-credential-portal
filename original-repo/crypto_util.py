"""crypto-util.py — cryptographic primitives for the Gef26 private chain.

Design (per JSONSTRUCTURE.md)
-----------------------------
* **Canonicalisation**: RFC 8785 (JCS) via the `jcs` package — the same logical
  JSON object always serialises to the same bytes, regardless of key order.
* **Hashing**: any `hashlib.new()` algorithm; the chain default is `sha3_512`.
  Digest is encoded **base64 urlsafe without padding**.
* **Data signers (DS)**: multiple signature algorithms are supported —
  ML-DSA (FIPS 204, post-quantum), RSA-PSS (MGF-1 uses the content hash
  algorithm), and ECDSA on SECP / Brainpool curves. Signer identity is the
  X.509 SubjectPublicKeyInfo fingerprint (`DSsha1fgpt` / `DSsha256fgpt`).
* **Signed message**: per JSONSTRUCTURE.md the payload hash is *not* signed
  directly; the signer signs
      b64urlsafe( HMAC(key=DSnonce, msg=payloadHash, algo=contentHashAlgo) )
  so the same payload hash yields a different signature per nonce.
"""

import base64
import hashlib
import re
import secrets

import jcs
from cryptography.hazmat.primitives import hashes, hmac as crypto_hmac, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
try:
    from cryptography.hazmat.primitives.asymmetric import mldsa
except ImportError:  # pragma: no cover — cryptography < 43 has no ML-DSA
    mldsa = None


# --------------------------------------------------------------------------
# Hash algorithm table
# --------------------------------------------------------------------------

_HASH_OBJ = {
    "sha256": hashes.SHA256,
    "sha384": hashes.SHA384,
    "sha512": hashes.SHA512,
    "sha3_256": hashes.SHA3_256,
    "sha3_384": hashes.SHA3_384,
    "sha3_512": hashes.SHA3_512,
}

MLDSA_VARIANTS = {"44", "65", "87"}
RSA_SIZES = {2048, 3072, 4096, 8192, 15360}
EC_CURVES = {
    "SECP256R1": ec.SECP256R1,
    "SECP384R1": ec.SECP384R1,
    "BRAINPOOLP256R1": ec.BrainpoolP256R1,
    "BRAINPOOLP384R1": ec.BrainpoolP384R1,
}


def _hash_cls(algo: str):
    try:
        return _HASH_OBJ[algo]
    except KeyError:
        raise ValueError(f"Unsupported hash algorithm: {algo}") from None


# --------------------------------------------------------------------------
# Canonical JSON + hashing
# --------------------------------------------------------------------------


def json_rfc8785(obj):
    """RFC 8785 (JCS) canonical serialisation of a JSON object."""
    return jcs.canonicalize(obj)


def hash_json(json_input, hashalgo="sha3_512"):
    """Canonicalise + hash a JSON object; return b64urlsafe (no padding) digest."""
    try:
        hashobj = hashlib.new(hashalgo)
    except ValueError as exc:
        raise ValueError(f"Unsupported hash algorithm: {hashalgo}") from exc

    canonical_json = json_rfc8785(json_input)
    if isinstance(canonical_json, str):
        canonical_json = canonical_json.encode("utf-8")

    hashobj.update(canonical_json)
    return base64.urlsafe_b64encode(hashobj.digest()).decode("ascii").rstrip("=")


def hash_bytes(data: bytes, hashalgo="sha3_512") -> str:
    """Hash raw bytes; return b64urlsafe (no padding) digest."""
    try:
        hashobj = hashlib.new(hashalgo)
    except ValueError as exc:
        raise ValueError(f"Unsupported hash algorithm: {hashalgo}") from exc
    hashobj.update(data)
    return base64.urlsafe_b64encode(hashobj.digest()).decode("ascii").rstrip("=")


def merkle_root(leaf_hashes, hashalgo="sha3_512"):
    """Merkle root over a list of existing digests (odd level duplicates last).

    Used by ``HashedDocument`` = merkle tree hash of the three part-hashes.
    """
    if not leaf_hashes:
        raise ValueError("merkle_root requires at least one leaf")
    level = list(leaf_hashes)
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(hash_bytes((left + right).encode("ascii"), hashalgo))
        level = nxt
    return level[0]


# --------------------------------------------------------------------------
# Data signer key generation
# --------------------------------------------------------------------------


def gen_dskey(algo):
    """Generate a data-signer keypair for a supported algorithm string.

    Returns ``(private_key, public_key)``. Supported:
    ``ML_DSA_44 / ML_DSA_65 / ML_DSA_87``,
    ``RSA-2048/3072/4096/8192/15360``,
    ``ec.SECP256R1/SECP384R1/BRAINPOOLP256R1/BRAINPOOLP384R1``.
    """
    if not isinstance(algo, str) or not algo.strip():
        raise ValueError("Algorithm must be a non-empty string.")

    normalized = algo.strip()
    upper_algo = normalized.upper()

    if upper_algo.startswith("ML_DSA_"):
        if mldsa is None:
            raise ValueError("ML-DSA is not available in the installed cryptography package.")
        variant = upper_algo.split("_")[-1]
        if variant not in MLDSA_VARIANTS:
            raise ValueError(f"Unsupported ML-DSA variant: {normalized}")
        key_cls_name = f"MLDSA{variant}PrivateKey"
        key_cls = getattr(mldsa, key_cls_name, None)
        if key_cls is None or not hasattr(key_cls, "generate"):
            raise ValueError(f"ML-DSA variant not supported by runtime: {normalized}")
        priv_key = key_cls.generate()
        return priv_key, priv_key.public_key()

    if upper_algo.startswith("RSA"):
        match = re.search(r"(\d+)$", upper_algo)
        if not match:
            raise ValueError(f"RSA algorithm must include key length: {normalized}")
        key_size = int(match.group(1))
        if key_size not in RSA_SIZES:
            raise ValueError(f"Unsupported RSA key size: {key_size}")
        priv_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        return priv_key, priv_key.public_key()

    if upper_algo.startswith("EC."):
        curve_name = normalized.split(".", 1)[1].strip().upper()
        curve_cls = EC_CURVES.get(curve_name)
        if curve_cls is None:
            raise ValueError(f"Unsupported EC curve: {curve_name}")
        priv_key = ec.generate_private_key(curve_cls())
        return priv_key, priv_key.public_key()

    raise ValueError(f"Unsupported signature algorithm: {normalized}")


def ds_algo_of_key(priv_key) -> str:
    """Best-effort reverse lookup: a human-readable algorithm string for a key."""
    if isinstance(priv_key, rsa.RSAPrivateKey):
        return f"RSA-{priv_key.key_size}"
    if isinstance(priv_key, ec.EllipticCurvePrivateKey):
        return f"ec.{priv_key.curve.name.upper()}"
    if mldsa is not None and isinstance(priv_key, (mldsa.MLDSA44PrivateKey, mldsa.MLDSA65PrivateKey, mldsa.MLDSA87PrivateKey)):
        name = type(priv_key).__name__  # e.g. MLDSA87PrivateKey
        return "ML_DSA_" + name[5:-11]
    return "UNKNOWN"

# --------------------------------------------------------------------------
# Signer fingerprint (X.509 SubjectPublicKeyInfo)
# --------------------------------------------------------------------------


def getfgpt(pub_key):
    """Return (sha1fgpt, sha256fgpt): colon-separated lowercase hex of the
    SHA-1 / SHA-256 digest of the DER SubjectPublicKeyInfo."""
    der = pub_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    sha1fgpt = ":".join(f"{byte:02x}" for byte in hashlib.sha1(der).digest())
    sha256fgpt = ":".join(f"{byte:02x}" for byte in hashlib.sha256(der).digest())
    return sha1fgpt, sha256fgpt


# --------------------------------------------------------------------------
# Key storage
# --------------------------------------------------------------------------


def save_privkey(priv_key, algo, keyfile_addr, password):
    _ = algo
    password_bytes = password.encode("utf-8") if isinstance(password, str) else password
    encryption = (
        serialization.BestAvailableEncryption(password_bytes)
        if password_bytes
        else serialization.NoEncryption()
    )
    key_bytes = priv_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=encryption,
    )
    with open(keyfile_addr, "wb") as key_file:
        key_file.write(key_bytes)


def save_pubkey(pub_key, algo, keyfile_addr):
    _ = algo
    key_bytes = pub_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    with open(keyfile_addr, "wb") as key_file:
        key_file.write(key_bytes)


def fetch_privkey(keyfile_addr, password):
    password_bytes = password.encode("utf-8") if isinstance(password, str) else password
    with open(keyfile_addr, "rb") as key_file:
        key_data = key_file.read()
    try:
        return serialization.load_pem_private_key(key_data, password_bytes)
    except ValueError:
        return serialization.load_der_private_key(key_data, password_bytes)


def fetch_pubkey(keyfile_addr):
    with open(keyfile_addr, "rb") as key_file:
        key_data = key_file.read()
    try:
        return serialization.load_pem_public_key(key_data)
    except ValueError:
        return serialization.load_der_public_key(key_data)


# --------------------------------------------------------------------------
# Sign / verify — per JSONSTRUCTURE.md "DataSignatureInfo"
# --------------------------------------------------------------------------


def _hmac_b64(payload_hash: str, nonce: str, content_hash_algo: str) -> str:
    """b64urlsafe( HMAC(key=nonce, msg=payload_hash, algo=contentHashAlgo) )."""
    h = crypto_hmac.HMAC(nonce.encode("utf-8"), _hash_cls(content_hash_algo)())
    h.update(payload_hash.encode("utf-8"))
    digest = h.finalize()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_json(json_input, ds_algo, private_key, content_hash_algo="sha3_512", nonce=None):
    """Sign a JSON object with a data-signer key.

    Returns ``(nonce, signature_b64urlsafe)``. The signed message is
    ``b64urlsafe(HMAC(key=nonce, msg=payloadHash, algo=contentHashAlgo))``
    where ``payloadHash = hash_json(json_input, content_hash_algo)``.
    """
    payload_hash = hash_json(json_input, content_hash_algo)
    nonce = nonce or secrets.token_urlsafe(32)
    message = _hmac_b64(payload_hash, nonce, content_hash_algo).encode("utf-8")

    if mldsa is not None and isinstance(private_key, (mldsa.MLDSA44PrivateKey, mldsa.MLDSA65PrivateKey, mldsa.MLDSA87PrivateKey)):
        signature = private_key.sign(message)
    elif isinstance(private_key, rsa.RSAPrivateKey):
        h = _hash_cls(content_hash_algo)
        signature = private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(h()), salt_length=h().digest_size),
            h(),
        )
    elif isinstance(private_key, ec.EllipticCurvePrivateKey):
        signature = private_key.sign(message, ec.ECDSA(_hash_cls(content_hash_algo)()))
    else:
        raise ValueError(f"Unsupported data-signer key type: {type(private_key).__name__}")

    return nonce, base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")


def verify_ds(json_input, ds_algo, public_key, signature_b64, nonce, content_hash_algo="sha3_512"):
    """Verify a data-signer signature over a JSON object.

    Returns True/False. ``ds_algo`` is used only for the registry match;
    verification itself dispatches on the key type.
    """
    try:
        payload_hash = hash_json(json_input, content_hash_algo)
        message = _hmac_b64(payload_hash, nonce, content_hash_algo).encode("utf-8")
        raw_signature = base64.urlsafe_b64decode(signature_b64 + "=" * (-len(signature_b64) % 4))

        if mldsa is not None and isinstance(public_key, (mldsa.MLDSA44PublicKey, mldsa.MLDSA65PublicKey, mldsa.MLDSA87PublicKey)):
            public_key.verify(raw_signature, message)
        elif isinstance(public_key, rsa.RSAPublicKey):
            h = _hash_cls(content_hash_algo)
            public_key.verify(
                raw_signature,
                message,
                padding.PSS(mgf=padding.MGF1(h()), salt_length=h().digest_size),
                h(),
            )
        elif isinstance(public_key, ec.EllipticCurvePublicKey):
            public_key.verify(raw_signature, message, ec.ECDSA(_hash_cls(content_hash_algo)()))
        else:
            return False
        return True
    except Exception:
        return False
