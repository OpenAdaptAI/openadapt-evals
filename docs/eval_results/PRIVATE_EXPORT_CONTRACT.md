# Private-export contract (draft, not approved)

`import_files` refuses every file import until OpenAdapt approves one exact
private-export contract. This document is the template for that approval. It is
a draft. Nothing in it is approved, and the gate stays closed while the values
below are blank.

`PRODUCTION_READINESS.md` sets the bar the approval has to clear:

> The future approval must bind the complete payload schema and digest, the
> destination account, service, container, and prefix, the encryption-key
> identity, the immutable retention mode and period, the authorized importer
> workflow and ref, and the approval authority. A broad enable flag or approval
> of only the admission and campaign digests is not sufficient.

## Why an approval is needed at all, and what it fixes

The certificate already carries a `retention` block, and the importer already
validates its shape: every digest is well formed, the mode is Object Lock
`COMPLIANCE`, four verification booleans are true, the period is between one and
ten years, and the chronology runs `acceptance_verified_at <= retained_at <
retention_until`.

Shape is not identity. Today the certificate supplies its own
`storage_identity_sha256`, `kms_key_identity_sha256`, and
`uploader_identity_sha256`, and the importer checks only that they look like
digests. A certificate that named some other bucket, some other key, and some
other uploader would pass every check in the file.

The approval closes that. It supplies the expected digests from outside the
evidence, the way `--trusted-admission-signers` and
`APPROVED_CLOUD_ACCEPTANCE_COMMIT` already do for the qualification authority
and the Cloud commit. After approval the evidence can no longer select its own
destination, its own key, or its own uploader.

## The bindings

Each row is a value the approval fixes, the certificate field the importer must
compare it against, and the approved value. **Every approved value is blank in
this draft.** They are deployment facts, and only the account owner can supply
them.

### Payload

| Binding | Certificate field | Approved value |
| --- | --- | --- |
| Payload schema | `schema_version` on each imported artifact | `openadapt.execute-live-acceptance-record/v2`, `openadapt.qualification-admission/v2`, `openadapt.qualification-campaign/v2` |
| Ciphertext digest | `retention.ciphertext_sha256` | _(per export; the approval fixes the algorithm and the envelope shape, not one value)_ |
| Private envelope digest | `retention.private_envelope_sha256` | _(per export)_ |
| Candidate digest | `retention.candidate_sha256` | _(per export)_ |

### Destination

| Binding | Certificate field | Approved value |
| --- | --- | --- |
| Account | `retention.storage_identity_sha256` | **TO BE SUPPLIED** |
| Service | same digest input | **TO BE SUPPLIED** |
| Container | same digest input | **TO BE SUPPLIED** |
| Prefix | same digest input | **TO BE SUPPLIED** |

The four destination facts hash into one `storage_identity_sha256`. The
approval must state the exact preimage and its domain separator, so a reviewer
can recompute the digest rather than trust it.

### Encryption key

| Binding | Certificate field | Approved value |
| --- | --- | --- |
| Key identity | `retention.kms_key_identity_sha256` | **TO BE SUPPLIED** |
| Key rotation policy | not carried | **TO BE SUPPLIED** |

### Retention

| Binding | Certificate field | Approved value |
| --- | --- | --- |
| Mode | `retention.retention_mode` | `COMPLIANCE`, already enforced |
| Period | `retention_until - retained_at` | **TO BE SUPPLIED**, inside the enforced one-to-ten-year window |
| Object version | `retention.object_version_sha256` | _(per export)_ |
| Locator version | `retention.private_locator_version_sha256` | _(per export)_ |

### Importer

| Binding | Certificate field | Approved value |
| --- | --- | --- |
| Authorized importer workflow | not carried | **TO BE SUPPLIED** |
| Authorized importer ref | not carried | **TO BE SUPPLIED** |
| Uploader identity | `retention.uploader_identity_sha256` | **TO BE SUPPLIED** |

The importer workflow and ref are not in the certificate at all. The approval
has to name them, and the importer has to grow a check that it is running as the
named workflow on the named ref. That check does not exist yet.

### Authority

| Binding | Approved value |
| --- | --- |
| Approval authority | **TO BE SUPPLIED** |
| Approval date | **TO BE SUPPLIED** |
| Approval digest | computed over this document once the values are filled |

## Where the filled copy lives

This repository is public. The filled contract names an account, a container, a
prefix, and a key identity, which are deployment-derived facts and fall under
the source-availability boundary.

So: the shape stays here, the values do not. The approved instance belongs in
`openadapt-internal`, and this repository receives only its digest, supplied to
the importer as an external control input beside the signer registry and the
approved Cloud commit.

## How to fill and approve one

1. Copy `docs/eval_results/private-export-contract.template.json` into
   `openadapt-internal`.
2. Replace every `FILL_` value and delete the `_README` key.
3. Check it against the mechanism:

   ```bash
   python scripts/import_production_acceptance.py \
     --private-export-contract <path> \
     --certificate <path> --campaign <path> \
     --qualification-admission <path> --attestation-bundle <path> \
     --expected-cloud-source-commit <sha> \
     --trusted-admission-signers <path> --output <path>
   ```

   The run still refuses at the import gate. Before it gets there it validates
   the contract, derives all three identity digests from your preimages, and
   checks that this process is the importer workflow the contract names. A
   contract error is reported before any private evidence is read.

4. Approve the filled copy in `openadapt-internal` and record its
   `contract_sha256` here.

## What the mechanism now enforces

The importer derives each identity digest from a preimage under its own domain
separator, through canonical JSON:

| Digest | Domain | Preimage keys |
| --- | --- | --- |
| `storage_identity_sha256` | `OpenAdapt retained evidence storage identity v1\0` | `account`, `service`, `container`, `prefix` |
| `kms_key_identity_sha256` | `OpenAdapt retained evidence key identity v1\0` | `provider`, `key_identity` |
| `uploader_identity_sha256` | `OpenAdapt retained evidence uploader identity v1\0` | `provider`, `principal` |

The contract carries the preimages and never a digest, so an approval cannot
assert a hash whose input nobody can see. `verify_retention_against_contract`
compares all three against the certificate, and `verify_importer_identity`
requires `GITHUB_WORKFLOW_REF` to equal the approved ref exactly. The contract's
retention window must sit inside the fixed policy window, so an approval can
tighten that bound and never loosen it.

## Open items that block approval

1. ~~`provenance_attestation` names a route that cannot be produced.~~
   **Resolved.** The route is now `sigstore-public-good-slsa-provenance-v1`,
   held in one constant and referenced by the policy and both validators.
2. ~~The importer has no authorized-workflow check.~~ **Resolved.**
   `verify_importer_identity` refuses unless the process is the approved
   workflow and ref.
3. ~~The destination and key digests need a stated preimage.~~ **Resolved.**
   See the table above; a reviewer can recompute every value.
4. **The Cloud retention gate is still closed on purpose.**
   `tests/unit/execute-live-acceptance.test.mjs` forbids the signing step until
   this contract exists. That test should stay as it is until the approval
   lands, and it is the reason nothing on the Cloud side has moved.

Items 1 to 3 were code. Item 4 waits on this document being filled and approved.

## What approving this does not do

It does not set `production_acceptance: true` anywhere. It does not promote an
evidence set. It does not authorize exporting an admission or a campaign to this
repository. It opens exactly one path: `import_files` may compose four named
evidence inputs and derive one bounded result, under every check that is already
implemented.
