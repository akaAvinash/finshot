# Dependency advisory triage

Record of audit findings against backend dependencies and what was done.
`python qa/scripts/dependency_audit.py` (pip-audit) runs in the nightly QA.

## 2026-11-26: cryptography 46.0.7 (QA DEF-002)

The backend pinned `cryptography>=43,<47`; pip-audit reported four advisories
against 46.0.7. The backend uses cryptography only for AES-GCM
(`app/auth/totp.py`, encrypting TOTP secrets at rest). SMTP STARTTLS uses the
standard library `ssl` module, which links the system OpenSSL, not the wheel's.

| Advisory | Area | Fixed in | Reachable in Tradeo? |
| --- | --- | --- | --- |
| GHSA-g6cj-pr64-35w5 / CVE-2026-69247 | PKCS#7 decrypt Bleichenbacher oracle | 50.0.0 | No: no PKCS#7 use |
| GHSA-jwv3-5hgf-82ww / CVE-2026-69249 | X.509 chain building, exponential time on duplicate self-signed certs | 49.0.0 | No: no `cryptography.x509` verification |
| GHSA-m2h6-j472-rp4c / CVE-2026-69248 | X.509 name constraints accept too-broad wildcard SAN | 49.0.0 | No: no `cryptography.x509` verification |
| GHSA-537c-gmf6-5ccf | Bundled OpenSSL in wheels (OpenSSL advisory 2026-06-09, 18 CVEs) | 48.0.1 | Not shown reachable: the advisory's issues are in PKCS#7/CMS, TLS/QUIC, X.509/OCSP, PKCS#12, CMP, DH, AES-OCB and AES-SIV/GCM-SIV; plain AES-GCM through EVP is not listed |

Assessment: none of the four is reachable through current backend code paths
(inference from a code search; no exploit testing). They were still fixed so
the audit stays clean and future use of these APIs is safe.

Action: pin raised to `cryptography>=50.0.2,<51` (bundles OpenSSL 4.0.3,
abi3 wheels for CPython 3.11+, so the `python:3.12` Docker image is covered).
Full backend suite, the QA suite and pip-audit (0 findings) passed on it.
