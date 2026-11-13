# Registrar outreach kit — one pilot

The spec is proven in demo; it is unproven on real data. The highest-leverage
hour is getting one registrar / exam officer / bootcamp ops person to run the
CLI for 30 minutes.

## The email (send to ~10 people, personalize the first line)

> Subject: 30-minute pilot: issue a batch of credentials on a public ledger
>
> Hi [Name],
>
> I built a spec-compliant credential issuer/verifier: a university (or
> bootcamp) issues diplomas in batches, and anyone can verify a PDF against
> the chain in seconds — no wallet, no node, no account. It signs each
> credential with post-quantum ML-DSA and stores only hashes.
>
> I'm looking for one registrar to run a small pilot: issue a CSV batch,
> verify the PDFs, and tell me what's confusing. No integration required —
> it's a command-line tool, ~30 minutes, no commitment.
>
> Can I send you the one-page setup?
>
> Best,
> [Name]

## Pilot scope (agreed up front)

- 5–20 sample or consented credentials
- one CSV batch issue (`scripts/batch_verify.py` or the admin tab)
- verify the PDFs back + one revoked credential
- collect: time-to-verify, false mismatches, confusing steps, missing fields

## Definition of done

One real registrar runs the CLI on real-ish data and gives written feedback
on: time-to-verify, any false mismatches, which steps were confusing, and
which fields were missing.
