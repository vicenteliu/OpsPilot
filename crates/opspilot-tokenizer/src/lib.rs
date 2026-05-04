use opspilot_core::tokenizer;
use pyo3::prelude::*;

/// count_tokens(text) -> int
///
/// Fast Rust BPE-ish token counter. ASCII alphanumeric runs count as 1 token;
/// ASCII whitespace is skipped; every other character counts as 1 token.
/// Matches Python re.compile(r'[a-zA-Z0-9]+|[^\s]', re.ASCII) token count.
#[pyfunction]
fn count_tokens(text: &str) -> usize {
    tokenizer::count_tokens(text)
}

#[pymodule]
fn opspilot_tokenizer(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(count_tokens, m)?)?;
    Ok(())
}
