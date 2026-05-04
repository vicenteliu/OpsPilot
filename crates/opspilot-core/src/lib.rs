/// Shared types for OpsPilot Rust crates.
/// PR-17 will use these in the Rust chunker implementation.

#[derive(Debug, Clone)]
pub struct ChunkConfig {
    pub target_size_tokens: usize,
    pub max_size_tokens: usize,
    pub overlap_tokens: usize,
}

impl Default for ChunkConfig {
    fn default() -> Self {
        Self {
            target_size_tokens: 512,
            max_size_tokens: 1024,
            overlap_tokens: 64,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Chunk {
    pub seq: usize,
    pub content: String,
    pub char_start: usize,
    pub char_end: usize,
    pub line_start: usize,
    pub line_end: usize,
    pub heading_path: Vec<String>,
    pub anchor: Option<String>,
    pub token_count: usize,
}
