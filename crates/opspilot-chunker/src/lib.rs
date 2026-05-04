use opspilot_core::chunker::{self, ChunkConfig};
use pyo3::prelude::*;

/// Python-facing Chunk object. Attribute names mirror the Python dataclass.
#[pyclass]
#[derive(Clone)]
pub struct PyChunk {
    #[pyo3(get)]
    pub seq: usize,
    #[pyo3(get)]
    pub content: String,
    #[pyo3(get)]
    pub char_start: usize,
    #[pyo3(get)]
    pub char_end: usize,
    #[pyo3(get)]
    pub line_start: usize,
    #[pyo3(get)]
    pub line_end: usize,
    #[pyo3(get)]
    pub heading_path: Vec<String>,
    #[pyo3(get)]
    pub anchor: Option<String>,
    #[pyo3(get)]
    pub token_count: usize,
}

impl From<chunker::Chunk> for PyChunk {
    fn from(c: chunker::Chunk) -> Self {
        PyChunk {
            seq: c.seq,
            content: c.content,
            char_start: c.char_start,
            char_end: c.char_end,
            line_start: c.line_start,
            line_end: c.line_end,
            heading_path: c.heading_path,
            anchor: c.anchor,
            token_count: c.token_count,
        }
    }
}

/// chunk_markdown(text, target_size_tokens=512, max_size_tokens=1024) -> list[PyChunk]
///
/// Fast Rust implementation of the headings_then_size chunker.
/// Returns a list of PyChunk objects with the same attributes as
/// the Python Chunk dataclass.
#[pyfunction]
#[pyo3(signature = (text, target_size_tokens=512, max_size_tokens=1024))]
fn chunk_markdown(text: &str, target_size_tokens: usize, max_size_tokens: usize) -> Vec<PyChunk> {
    let cfg = ChunkConfig { target_size_tokens, max_size_tokens };
    chunker::chunk_markdown(text, &cfg)
        .into_iter()
        .map(PyChunk::from)
        .collect()
}

#[pymodule]
fn opspilot_chunker(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyChunk>()?;
    m.add_function(wrap_pyfunction!(chunk_markdown, m)?)?;
    Ok(())
}
