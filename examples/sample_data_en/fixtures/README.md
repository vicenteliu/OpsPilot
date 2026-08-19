# Frozen KB fixtures

Each directory holds a `doc-meta.json` + `chunks.jsonl` pair for one document in
[`../kb/`](../kb/): the same content, already chunked, with hand-authored
`document_id` and `chunk_id` values that stay stable across runs.

Load them with:

```bash
opspilot kb load-dir examples/sample_data_en/fixtures/
```

`load-dir` bypasses the chunker, the redactor and markitdown, so the ids you get
are the ids written here. That is the point of a frozen fixture — a test can name
`chk_f3a40001` and mean it.

**They live outside `../kb/` on purpose.** `README.md` tells a new user to run
`opspilot ingest examples/sample_data_en/kb/`, and `ingest` is the real pipeline:
it reads source documents, chunks them, and mints its own ids. Pointing it at a
directory that also contains these two files made it fail on every `.jsonl` and
silently ingest every `doc-meta.json` *as a knowledge document* — metadata that
then came back as an answer. One directory, two commands, neither wrong on its
own.

So: source documents in `../kb/`, their frozen projections here.
