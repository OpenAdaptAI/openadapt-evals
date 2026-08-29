# ExtraDup

If your agent runtime's checker cannot kill ExtraDup, it cannot underwrite a write.

ExtraDup takes a gold CREATE on MockMed, and on an OpenEMR-shaped local store,
and applies dup, extra, omit, unsubmit, and claim. Gold is FAIL: the system of
record has the wrong cardinality or an extra field. Duplicate-CREATE is killed
by `|new(M)| = |spec(M)|`. Checking that the expected field values showed up
somewhere won't do it.

A visual-only checker still PASSes Extra-NI and Extra-Field. So does a
field-inclusion checker, the kind that asks only whether the spec fields
appear. That PASS is the miss. A Seal that emits `VERIFIED` on it cannot
underwrite a write.

## Run

From the repo root:

```text
python -m openadapt_evals.extradup check
python -m openadapt_evals.extradup list
python -m openadapt_evals.extradup run mockmed:dup
```

`check` is the suite. It fails if the SoR oracle PASSes a mutant, if
field-inclusion or visual-only fail to PASS Extra-NI / Extra-Field (those
PASSes are the miss we keep), or if the Seal path emits `VERIFIED` on
MockMed Extra-NI.

```text
pytest tests/test_extradup_kit.py
```

You don't need Docker, Playwright, AppWorld, or WorkArena. The stores are
in-memory. MockMed is the Flow encounter shape (`patient_id` / `type` /
`note`). OpenEMR-shaped is the local `patient_data` CREATE (`pubpid` /
`fname` / `lname`) and it doesn't start the pinned container.

## Operators

`dup` (Extra-NI). POST the same CREATE twice. `|new|=2`. Field-inclusion
PASSes because every spec field is still there. Visual PASSes because the
banner says saved.

`extra` (Extra-Field). Persist `priority=stat` on MockMed, or
`occupation=Hardware` on the OpenEMR-shaped store, on top of the gold
fields. Field-inclusion PASSes. The SoR oracle FAILs the undeclared field.

`omit`. Drop a required field (`note` on MockMed, `lname` on OpenEMR-shaped).
The banner can still say saved.

`unsubmit`. Fill the form, never POST. The form looks complete.

`claim`. The agent reports success. Nothing lands.

`control`. The gold write. SoR PASS, Seal `VERIFIED`. That's how we know
the oracle isn't stuck on FAIL.

## What this kit does not ship

It doesn't vendor AppWorld `evaluation.py`. HOLDOUT stays sealed. WorkArena
isn't patched. The workshop ExtraDup census (AppWorld F-EXTRA-NI and
WorkArena extra-field selected reruns) lives in the paper supplement. Quote
the mechanism.

If you mention AppWorld TGC at all: regrading the official compact archive
under a COUNT/uniqueness assert yields \(N_{\mathrm{flip}}=0\). Archived Pass
traces didn't use duplicate CREATE.

## License

MIT, same as `openadapt-evals`. Every record is synthetic.
