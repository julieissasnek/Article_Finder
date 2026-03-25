# Production Run (Safe Gates)

This is a non-destructive, stepwise production path for Article Finder. The goal
is to aggressively prune off-topic papers while protecting theoretical/high-value
papers (HBE certified venues, neuroscience venues, and high-citation items).

## Pre-Flight

- Ensure `config/settings.local.yaml` is set up (API email, DB path).
- HBE allowlist: `config/hbe_journals_allowlist.txt`
- Neuroscience allowlist: `config/neuroscience_venues_allowlist.txt`

## Step 1: Ingest + PDFs

- Import references (CSV/XLS):
  ```bash
  python cli/main.py import path/to/references.csv
  ```
- Ingest PDFs (inbox/drop folder):
  ```bash
  python cli/main.py inbox
  ```
- Or catalog a PDF directory:
  ```bash
  python cli/main.py import-pdfs /path/to/pdfs --copy-to-storage --storage-dir data/pdfs
  ```

## Step 2: Enrich Abstracts

```bash
python cli/main.py enrich --limit 500
```

## Step 3: Classify + Triage

```bash
python cli/main.py classify --score-all --report
```

## Step 3.5: Abstract-First Thin Tables (Required)

Every paper must produce a thin/sparse table and a sparse rule set based on the
abstract. This is a gate before BN/Epistemic builds.

## Step 3.6: PDF Upgrade Queue (Required)

If a PDF exists, queue the paper for full table extraction and full rule
production. The PDF-based outputs must replace the abstract-based versions.

## Step 4: Run Production Gates (Non-Destructive)

This checks coverage, flags protected rejects, and blocks high-citation rejects.
High-citation threshold defaults to 150.

```bash
python3 scripts/production_run.py   --db data/article_finder.db   --hbe-allowlist config/hbe_journals_allowlist.txt   --neuro-allowlist config/neuroscience_venues_allowlist.txt   --high-cite-threshold 150   --export data/review/reject_candidates.csv
```

If any gate fails, review the output and adjust thresholds or metadata coverage.

## Step 5: Manual Review + Prune

Use the UI triage tools to review protected rejects and edge cases.

## Step 6: Build AE Job Bundles

```bash
python cli/main.py build-jobs --status send_to_eater --output data/job_bundles
```

## Step 7: Run Article Eater + Import Results

```bash
# Run AE on job bundles (external step)
python cli/main.py import-results data/ae_outputs
```

## Step 8: Build Graph Layer

```bash
python cli/main.py graph build
```

## Notes

- HBE allowlist and neuroscience allowlist are treated as "never auto-reject."
- High-citation papers (>=150) must never be auto-rejected.
- Gates are designed to stop the run before destructive pruning.
