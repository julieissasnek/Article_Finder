# AF PDF Attachment Integrity Authority

Date: 2026-05-10
Status: authoritative

## Purpose

This contract governs the truthfulness of AF paper-to-PDF attachment state.
It exists because a feeder system must not claim that a paper has a PDF
unless the file exists, the file is materially the paper in question, and
the handoff fields that depend on that file remain coherent.

## Canonical Fields

In `papers`:

- `pdf_path`
- `pdf_sha256`
- `pdf_bytes`
- `ae_job_path`
- `ae_output_path`
- `ae_status`

## Rules

1. A non-empty `pdf_path` must resolve to an existing file.
2. A non-empty `pdf_sha256` must correspond to the bytes of the file at `pdf_path`.
3. Multiple rows may not simultaneously claim the same attached PDF content
   unless the conflict has been resolved by clearing the misleading attachment
   from the non-canonical rows.
4. If `ae_output_path` is non-empty, it must resolve to an existing output
   bundle directory.
5. If an attachment is detached because it was misleading, the row must retain
   a human-readable note explaining the detachment.

## Canonical Executables

- `scripts/verify_af_integrity.py`
- `scripts/repair_af_integrity.py`

## Last Mile Requirement

No attachment claim is valid merely because a row exists. The file and the
derived handoff references must resolve on disk.
