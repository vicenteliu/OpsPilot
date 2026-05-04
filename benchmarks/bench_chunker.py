"""Benchmark: Rust chunker vs Python chunker.

Usage:
    python benchmarks/bench_chunker.py

Prints timing and speedup; exits with code 1 if speedup < 5x.
"""

from __future__ import annotations

import sys
import timeit
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"

# Repeat small sample to get a file large enough to measure reliably.
REPEATS = 200
text = SAMPLE.read_text(encoding="utf-8") * REPEATS

from opspilot.memory.chunker import ChunkConfig, _py_chunk_markdown

try:
    import opspilot_chunker as _rs_mod
except ImportError:
    print("ERROR: opspilot_chunker Rust extension not installed. Run: make rust-dev")
    sys.exit(1)

N = 30  # benchmark iterations


def _py() -> None:
    _py_chunk_markdown(text)


def _rs() -> None:
    _rs_mod.chunk_markdown(text)


print(f"Input size: {len(text):,} chars ({len(text.encode()):,} bytes), {REPEATS}x repeat")
print(f"Iterations: {N}")
print()

py_time = timeit.timeit(_py, number=N)
rs_time = timeit.timeit(_rs, number=N)

py_ms = py_time / N * 1000
rs_ms = rs_time / N * 1000
speedup = py_time / rs_time

print(f"Python : {py_ms:7.2f} ms/call  (total {py_time:.2f}s)")
print(f"Rust   : {rs_ms:7.2f} ms/call  (total {rs_time:.2f}s)")
print(f"Speedup: {speedup:.1f}x")
print()

TARGET = 5.0
if speedup >= TARGET:
    print(f"PASS — speedup {speedup:.1f}x >= {TARGET}x target")
    sys.exit(0)
else:
    print(f"FAIL — speedup {speedup:.1f}x < {TARGET}x target")
    sys.exit(1)
