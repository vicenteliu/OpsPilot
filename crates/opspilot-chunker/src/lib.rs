use pyo3::prelude::*;

/// Stub — headings_then_size algorithm ships in PR-17.
/// Returns a list of dicts; type will be refined when the real impl lands.
#[pyfunction]
fn chunk_markdown(_text: &str) -> Vec<std::collections::HashMap<String, String>> {
    vec![]
}

#[pymodule]
fn opspilot_chunker(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(chunk_markdown, m)?)?;
    Ok(())
}
