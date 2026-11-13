This document aims to explain the field in the json file

---

    "PersonalParticulars" : {
            "Surname" : "CHAN",
            "GivenNames" : "TAI MAN",
            "Sex" : "M",
            "DOB" : "19880808",
            "StudentID": "22000000"
        },

This block is for saving the document holder’s information  just some demo stuff, not key structure

   RECORD Meaning 

 
`Surname` has the same meaning with primary identifiers in MRTD standard. Normally a.k.a. but NOT eqv to Family Name / Last Name. 
Str in Latin character ; MUST be presented

 

`GivenNames` has the same meaning with secondary identifier in MRTD standard. Normally a.k.a but NOT eqv to First Name / Forename. COULD be blanked for person without this name components 
Str in Latin char ; MUST be presented.

 `Sex` has the same meaning with it in the MRTD standard. 
 

    M / F / X 

 Str 1char ; MUST be presented 

`DOB` has the same meaning with the Date of Birth in MRTD standard.
in YYYYMMDD format.
Str 8char ; MUST be presented

`StudentID` a unique value to identify the person. 
Str 8char ; MUST be presented

---

    "DocumentInfo" :{
        "DateOfIssue": "20260901",
        "AuthorizedSignature": "PRESIDENT Prof. QUO, Vadis",
        "IssuingO": "UNIVERSITY OF UTOPIA",
        "IssuingOU":"DEPT OF EE",
        "DocType": "CERTIFICATE OF DIPLOMA"
    },

This block is for saving the document’s information, just some demo stuff, not key structure

`DateOfIssue` Date of issue
in YYYYMMDD format.
Str 8char ; MUST be presented

`AuthorizedSignature` The title/ person sign/issue the document
Str ; MUST be presented

`IssuingO` Issuing Organization 
Str ; MUST be presented

`IssuingOU` Issuing Organizational Unit may leave blank
Str ; MUST be presented

`DocType` Document Type, currently consists of two possible value( may be append new value):
    - `CERTIFICATE OF DIPLOMA` 
    - `TRANSCRIPT`

---

**KEY**

Block structure

`"height": 1,`
block height: int,  genesis block have value 0 than +1 for each block

`"contentHashAlgo": "sha3_512",`
content hash algo: str algo name

`"prevHashSum": "pp9zzKI6msXItWfcGFp1bpfJghZP4lhZ4NHcwUdcgKYVshI68fX5TBHj6UAsOsVY9QAZnZW20-MBdYWGKB3NJg",`
Whole hash for prev block(height-1)
crypto-util.hash_json(algo = contentHashAlgo)
for genesis block behaviour remain blank 


`"timestamp": 1789897799958309582`
int; time.time_ns() for time when create block

---

`"payload"`
 payload block

`"action"`
str; ISSUE / REVOKE

`HashedPersonalParticulars"`
crypto-util.hash_json(algo = contentHashAlgo) for `PersonalParticulars` in target json payload

`"HashedAcademicInfo"`
crypto-util.hash_json(algo = contentHashAlgo) for `AcademicInfo` in target json payload

`"HashedDocumentInfo"`
crypto-util.hash_json(algo = contentHashAlgo) for `DocumentInfo` in target json payload
        
`"HashedDocument"`
merkle tree hash Hash(json object of the above three hashsum)
    
`"DocumentInfo"`
Same as the `DocumentInfo` block in target JSON Payload


---

"DataSignatureInfo"

block
multiple json object:

            {
                "DSsha1fgpt": "pass",
                "DSsha256fgpt": "pass",
                "DSver": 1,
                "DSAlgo": "ML_DSA_87",
                
                "DSignature": "pass" // for HashedDocument field
            },

DS: abbrev of Data Signer

DSsha1fgpt
SAME AS X509v3 standard SubjectPublicKeyInfo all lower sep 2 hex with : like this "79:B4:59:E6:7B:B6:E5:E4:01:73:80:08:88:C8:1A:58:F6:E9:9B:6E" this field use sha1

DSsha256fgpt
SAME AS X509v3 standard SubjectPublicKeyInfo all lower sep 2 hex with : like this "79:B4:59:E6:7B:B6:E5:E4:01:73:80:08:88:C8:1A:58:F6:E9:9B:6E" this field use sha256

`DSver`
int; 1,  Currently no use

`DSAlgo`
str; 
ML_DSA_(44/65/87) , 
RSA-keylength (2048/3072/4096/8192/15360), PSS Padding, MGF-1(hash uses `"contentHashAlgo"` (maybe refer table required b/ hashlib names and cryptography.hazmat.primitives.hashes)
ec.SECP256R1/SECP384R1/BRAINPOOLP256R1/BRAINPOOLP384R1

`"nonce"`
nonce >= 32 byte urlsafe base64 random  different among block

`DSignature`
Signed by Data Signer
different ds algo may have different ds hash algo, should be declared in table in crypto-util.py
message to be signes: b64urlsafe HMAC(m=payloadhash, k=`nonce`, algo = `contentHashAlgo`)
base64 urlsafe encoded sig 
