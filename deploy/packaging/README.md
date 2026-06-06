# macOS CLI packaging

OpsPilot's CLI is distributed on macOS via [`uv`](https://docs.astral.sh/uv/)'s
isolated tool installs, not a frozen single-file binary. Rationale and rejected
alternatives: [ADR-0008](../../docs/adr/0008-macos-packaging-uv-tool.md).

## Prerequisite

Install `uv` (a single static binary; it manages its own Python):

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Build + install

```sh
make package-macos
```

This builds a wheel into `dist/` and runs `uv tool install` on it. `uv`
resolves the platform-native wheels (`lancedb`, `pyarrow`, `onnxruntime`, ...)
into an isolated environment and drops a single `opspilot` shim on PATH.

Equivalently, by hand:

```sh
uv build --wheel
uv tool install --force dist/opspilot-*.whl
```

## Run

Ensure the uv tool bin directory is on PATH (`uv tool dir --bin`, usually
`~/.local/bin`), then — from any shell, with no project venv active:

```sh
opspilot --version
opspilot --help
```

## Upgrade / uninstall

```sh
make package-macos          # rebuild + reinstall the latest wheel
uv tool uninstall opspilot  # remove
```

## Notes

- The optional Rust accelerators (`opspilot_chunker`, `opspilot_tokenizer`) are
  **not** part of the wheel; the CLI falls back to the pure-Python paths when
  they are absent. Build them separately with `make rust-build` if desired.
- This is not a zero-prerequisite installer — installing `uv` is required. See
  ADR-0008 for when a frozen binary would be reconsidered.
