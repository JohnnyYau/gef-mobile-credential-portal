---
 - Complete JSON template for DocumentInfo and MetaData Block 
 - Enhance the arrangement for payload block
 - Complete README.MD
 -  except fgpt for ds pub key , all hash shall be stored in base64.urlsafe_b64encode(hash.digest()).rstrip("=")
 - Dependencies Requirements: 
python 3.9+/ cryptography 49.0.0+/
to be continued 

---
planned file structure  TBC
./
blockchain-util.py 
crypto-util.py
humanfrdly-util.py
demo-issue.ipynb
demo-revoke.ipynb
demo-verify.ipynb
<chain name>/
>info.yaml #storage key location last block signer pwd etc.
>signer1.pfx
>signer2.pfx
>signer1.pem
>signer2.pem
>rawjsondocs/
-><Hashed Doc ID>
>blocks/
->block-000000000.json
->block-000000001.json
->block-000000002.json.temp #write in temp then rename
---
blockchain-util.py TBC

verify_chain()
Verify whole chain from the Genesis Block

verify_block(block_height)
Verify the payload signature, hash compare with recorded in i-1, i, i+1(if any) block

append_block(payload):
Create new block and update info.yaml

fetch_block(block_height)
Return verify_block and the whole json of block

fetch_status(HashedDocument Hashedalgo)
return if valid revoke block for the given checksum exists 

TBC
---



§For reference only AIGC:
1. Project Goal

Build a simple private blockchain demo in Python/Jupyter that allows a university to issue a digital academic credential, anchor it on a private chain, and let a verifier check that the credential is genuine, untampered, and not revoked.

The demo should clearly show:

1. A credential is issued by a trusted university.
2. The credential is recorded on a private blockchain.
3. A verifier can validate the credential.
4. Any tampering with the credential or chain is detected.
5. Revoked credentials fail verification.

---

2. Scope Boundaries

In Scope

· Single-node private blockchain.
· JSON-based credential and block data.
· Hash chaining with previous_hash.
· Digital signatures for issuer authenticity.
· Issuer registry.
· Credential issuance, verification, and revocation.
· Tamper detection.
· Jupyter Notebook demo.

Out of Scope

· Ethereum / EVM / smart contracts.
· Consensus algorithms (PoW, PoS, PBFT, etc.).
· P2P networking.
· IPFS / decentralized storage.
· Zero-knowledge proofs.
· Merkle trees.
· Production-grade security or scalability.

---

3. Suggested Architecture

```
Issuer Registry (JSON)
        |
        v
Credential JSON  --->  Hash + Signature
        |                     |
        v                     v
Private Blockchain (JSON blocks)
        |
        v
Verifier Notebook / Script
```

Main Components

· IssuerRegistry: stores issuer IDs and public keys.
· Credential: JSON document held by the student.
· Block: contains index, timestamp, previous hash, transactions, block hash.
· Blockchain: appends blocks, validates chain, saves/loads JSON.
· Verifier: checks hash, signature, chain record, and revocation status.

Important Design Choice

· Store only the credential hash on-chain, not the full personal data.
· The student keeps the full credential JSON.
· The verifier checks:
  1. Hash of presented credential matches on-chain record.
  2. Issuer signature is valid.
  3. Credential is not revoked.
  4. Chain integrity is intact.

---

Week Focus Tasks Deliverable
1 Scope & Design Define use cases, JSON schemas, architecture, threat model. Set up repo and Jupyter environment. Design doc + JSON schemas
2 Blockchain Core Implement Block and Blockchain classes. Add hashing, previous_hash, validation, JSON save/load. Notebook 01: core chain demo
3 Identity & Signatures Generate issuer key pairs. Sign credential hash. Verify signature. Build issuer registry. Notebook 02: sign/verify demo
4 Credential Lifecycle Issue credential, anchor hash on chain, verify credential, simulate tampering. Notebook 03: issue + verify demo
5 Revocation & Demo Flow Add revocation transactions. Test unknown issuer, revoked credential, tampered chain. Build clean demo notebook. Notebook 04: full demo
6 Documentation & Presentation Write README, final report, slides. Record demo video. Rehearse. Final report + demo video

---

Risks & Scope Control

Risk Mitigation
Scope creep into consensus/ZKP/Merkle Keep single-node, hash-chain only.
Crypto implementation too complex Use Python cryptography library, do not implement RSA/ECDSA manually.
Demo bugs Keep data small, deterministic, and use fixed test cases.
Time shortage Prioritize MVP: issue, verify, tamper, revoke.
Privacy concerns Store only credential hash on-chain.

---
§AIGC REFERENCE CONTENTS ENDS
