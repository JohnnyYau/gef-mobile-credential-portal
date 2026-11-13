# Gef26-project-blockchain

A **single-node private blockchain demo** for university academic credentials
(diploma / transcript): a university issues a digital credential, anchors its
**hashes only** on a private chain, and any verifier can confirm the credential
is genuine, untampered, and not revoked.

This is the merged "best of both" version: it keeps the teammate's design
(JSONSTRUCTURE.md — RFC 8785 / JCS canonicalisation, SHA3-512 content hashes,
base64-urlsafe encoding, ML-DSA / RSA-PSS / ECDSA data signers with X.509 SPKI
fingerprints, nonce + HMAC signed messages, block-per-file storage) and adds a
complete, tested implementation: chain lifecycle, revocation, tamper
detection, a six-check verifier, 53 unit tests and three executed demo
notebooks.

---

## 1. Design highlights (see `JSONSTRUCTURE.md` for the full field spec)

| Aspect | Choice |
|--------|--------|
| Canonical JSON | RFC 8785 (JCS) via the `jcs` package — key order never matters |
| Content hash | `sha3_512` by default (`hashlib.new` names accepted) |
| Hash encoding | `base64.urlsafe_b64encode(digest).rstrip("=")` — except DS fingerprints |
| Signer identity | X.509 SPKI fingerprints `DSsha1fgpt` / `DSsha256fgpt` (`aa:bb:…` hex) |
| Signer algorithms | `ML_DSA_44/65/87`, `RSA-2048…15360` (PSS, MGF-1 = content hash), `ec.SECP256R1/SECP384R1/BRAINPOOLP256R1/BRAINPOOLP384R1` |
| Signed message | `b64urlsafe( HMAC(key=DSnonce, msg=payloadHash, algo=contentHashAlgo) )` — nonce ≥ 32 random bytes |
| Document hash | `HashedDocument` = Merkle root of `HashedPersonalParticulars`, `HashedAcademicInfo`, `HashedDocumentInfo` |
| Chain links | `prevHashSum` = whole hash of previous block; genesis has a blank `prevHashSum` |
| Block storage | `<chain>/blocks/block-000000000.json` … written to `.temp` then renamed (atomic) |

**Privacy**: only hashes are stored on the chain. The student keeps the full
document JSON (`PersonalParticulars` / `AcademicInfo` / `DocumentInfo`).

## 2. File layout

```
Gef26-project-blockchain-main/
├── crypto_util.py          # hashing, Merkle root, keygen, fingerprints, sign/verify
├── blockchain_util.py      # chain init, append, verify, fetch, status, verifier
├── build_demo_notebooks.py # (re)build + headless-execute the three notebooks
├── demo-issue.ipynb        # executed demo: init chain, register signer, issue
├── demo-verify.ipynb       # executed demo: genuine / tampered / forged cases
├── demo-revoke.ipynb       # executed demo: revocation lifecycle
├── tests/
│   ├── test_crypto.py      # 26 tests: hashing, merkle, keys, sign/verify, fgpt
│   └── test_chain.py       # 27 tests: lifecycle, tamper, revocation, registry
├── JSONSTRUCTURE.md        # field-by-field data spec (kept from the original)
├── TODO.md                 # original plan / leftover notes
├── BLOCK-1SPECIMEN.json / DIPLOMASPECIMEN.json / TRANSCRIPTSPECIMEN.json
├── test-block/BLOCK-0.json
├── demo-chain/             # runtime chain created by the notebooks (recreatable)
│   ├── info.yaml           # chain metadata + trusted signer registry
│   ├── blocks/block-0000000NN.json
│   ├── keys/signer-<fgpt>.pem
│   └── rawjsondocs/
├── requirements.txt
└── README.md
```

> File naming note: the original `crypto-util.py` / `blockchain-util.py` were
> renamed to `crypto_util.py` / `blockchain_util.py` — a module name with a
> hyphen is not importable in Python, so the stubs could not have been tested.

## 3. Setup

```bash
python -m pip install -r requirements.txt   # cryptography>=49, jcs, pyyaml
```

To rebuild / headlessly execute the notebooks you also need the Jupyter stack
(`nbformat`, `nbclient`, `ipykernel`).

## 4. Run the demos

```bash
jupyter notebook demo-issue.ipynb    # 1) issue a diploma (ML-DSA signer)
jupyter notebook demo-verify.ipynb   # 2) verify: genuine / tampered / forged
jupyter notebook demo-revoke.ipynb   # 3) revoke lifecycle
```

Headless re-run (deterministic assertions included):

```bash
python build_demo_notebooks.py --execute
python verify_notebooks.py
```

Unit tests:

```bash
python -m unittest discover -s tests -t . -v
```

## 5. The six verification checks

`blockchain_util.verify_document(chain, document)` returns per-check booleans
and a `valid` verdict; all six must pass for **VALID**:

1. **chain_integrity** — whole chain re-verifies from the genesis block
   (hashes, prevHashSum links, heights);
2. **signer_trusted** — every data signer of the ISSUE block is in the
   registry (matched by SPKI sha256 fingerprint);
3. **on_chain_record** — an ISSUE block exists whose `HashedDocument` matches;
4. **hash_match** — recomputed part hashes of the presented document equal the
   on-chain payload hashes;
5. **signature_valid** — each signer's `DSignature` verifies over the
   nonce-HMAC message with the registered public key;
6. **not_revoked** — no REVOKE block references the document hash.

`fetch_status(chain, hashed_document)` exposes the raw lifecycle
(issue/revoke block heights). Revocation is append-only: a REVOKE block is a
valid block, so `verify_chain` stays `True` while verification of the document
fails.

## 6. Threat model covered by the demo

| Attack | Detected by |
|--------|-------------|
| Edit document content (degree, courses, name) | 4 hash_match (+ 5 signature) |
| Edit a block file on disk | 1 chain_integrity (hash + links) |
| Delete / reorder blocks | 1 chain_integrity (missing/prevHashSum break) |
| Forge a document signed by an unregistered key | 2 signer_trusted / 5 signature_valid |
| Algorithm confusion (register RSA, sign with EC) | 5 signature_valid (key-type dispatch) |
| Present a revoked document | 6 not_revoked |

## 7. Scope

**In scope**: single-node private chain, JSON persistence (block files +
info.yaml), hash chaining, multi-algorithm data signatures (incl. post-quantum
ML-DSA), signer registry by SPKI fingerprint, issue / verify / revoke, tamper
detection, Jupyter demo.

**Out of scope** (same boundaries as `TODO.md` / JSONSTRUCTURE.md): Ethereum /
smart contracts, full consensus (PoW/PoS/PBFT), P2P networking, IPFS, ZK
proofs, production-grade security or scalability. ML-DSA keys come from the
`cryptography` package (v43+; requirements pin ≥49).

## 8. Changes vs. the teammate's original snapshot

* `crypto_util.py`: implemented `sign_json` / `verify_ds` (all DS algorithms,
  nonce+HMAC message), added `merkle_root`, `hash_bytes`, `ds_algo_of_key`;
  kept `hash_json`, `json_rfc8785`, `gen_dskey`, `getfgpt`, key IO unchanged
  in behaviour (EC algo names normalised to upper case for registry matching).
* `blockchain_util.py`: replaced the `pass` stubs with a full implementation
  (`init_block`, `register_signer`, `append_block`, `fetch_block`,
  `verify_block`, `verify_chain`, `fetch_status`, `verify_document`).
* Added `tests/` (53 tests), the three demo notebooks + builder, `README.md`,
  `requirements.txt`.

## 9. Notes & limitations

- `demo-chain/` is runtime data; delete it and re-run any notebook to rebuild.
- Private keys are stored in `keys/` only for the demo; a real deployment
  would keep them in a KMS / HSM.
- `verify_chain` scans every block and reports all problems (no early exit).
- RSA-PSS and ECDSA signatures are randomised; ML-DSA as implemented also
  randomises. Signatures therefore differ between runs — verification is
  what matters, not byte equality of signatures.
- See `TODO.md` for the remaining original plan items (e.g. `humanfrdly-util.py`,
  YAML signer-password handling) — intentionally left as future work.
