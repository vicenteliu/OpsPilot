"""Benchmark: Rust tokenizer vs Python tokenizer.

Usage:
    python benchmarks/bench_tokenizer.py

Exits with code 1 if speedup < 5x.
"""

from __future__ import annotations

import sys
import timeit
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = REPO_ROOT / "examples" / "scn_ticket_summary_zh" / "kb" / "sop_vpn_zh.md"

REPEATS = 500
text = SAMPLE.read_text(encoding="utf-8") * REPEATS

from opspilot.memory.tokenizer import _py_count_tokens

try:
    import opspilot_tokenizer as _rs_mod
except ImportError:
    print("ERROR: opspilot_tokenizer Rust extension not installed. Run: make rust-dev")
    sys.exit(1)

N = 30


def _py() -> None:
    _py_count_tokens(text)


def _rs() -> None:
    _rs_mod.count_tokens(text)


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
