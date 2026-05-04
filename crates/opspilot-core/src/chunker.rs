/// headings_then_size chunker — Rust port of ``memory.chunker`` (PR-17).
///
/// char/byte duality: Python str uses Unicode code-point indices; Rust &str
/// uses byte offsets. We track both char_pos and byte_pos simultaneously
/// in O(1) per line. char_count() counts non-continuation bytes — LLVM
/// auto-vectorises this loop to ~16 bytes/cycle on ARM NEON / SSE2.
use std::collections::HashSet;

// ── Public types ──────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct ChunkConfig {
    pub target_size_tokens: usize,
    pub max_size_tokens: usize,
}

impl Default for ChunkConfig {
    fn default() -> Self {
        Self { target_size_tokens: 512, max_size_tokens: 1024 }
    }
}

#[derive(Debug, Clone)]
pub struct Chunk {
    pub seq: usize,
    pub content: String,
    /// Unicode code-point offset (matches Python str indexing).
    pub char_start: usize,
    /// Unicode code-point offset (exclusive, matches Python str indexing).
    pub char_end: usize,
    pub line_start: usize,
    pub line_end: usize,
    pub heading_path: Vec<String>,
    pub anchor: Option<String>,
    pub token_count: usize,
}

// ── Internal block ────────────────────────────────────────────────────────

struct Block {
    line_start: usize,
    line_end: usize,
    char_start: usize,
    char_end: usize,
    byte_start: usize,
    byte_end: usize,
    heading_text: String,
    has_content: bool,
    heading_path: Vec<String>,
}

// ── Helpers ───────────────────────────────────────────────────────────────

/// Count Unicode code points in a UTF-8 string.
/// Counts non-continuation bytes (not 0b10xxxxxx). LLVM auto-vectorises
/// this into SIMD on ARM NEON and x86 SSE2 — ~16 bytes/cycle.
#[inline]
fn char_count(s: &str) -> usize {
    s.as_bytes().iter().filter(|&&b| b & 0xC0 != 0x80).count()
}

/// URL-fragment slug. Mirrors Python's _slug().
fn slug(text: &str) -> String {
    let filtered: String = text
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == '_' || c.is_whitespace() || *c == '-')
        .collect();
    let lower = filtered.trim().to_lowercase();
    let mut out = String::with_capacity(lower.len());
    let mut prev_sep = false;
    for ch in lower.chars() {
        if ch.is_whitespace() || ch == '-' {
            if !prev_sep { out.push('-'); prev_sep = true; }
        } else {
            out.push(ch);
            prev_sep = false;
        }
    }
    out.trim_matches('-').to_string()
}

/// Parse an ATX heading line → (level, trimmed_text) or None.
fn parse_heading(line: &str) -> Option<(usize, &str)> {
    let b = line.as_bytes();
    let mut level = 0usize;
    while level < b.len() && level < 6 && b[level] == b'#' { level += 1; }
    if level == 0 || level >= b.len() { return None; }
    if b[level] != b' ' && b[level] != b'\t' { return None; }
    let rest = line[level..].trim();
    if rest.is_empty() { None } else { Some((level, rest)) }
}

// ── Frontmatter ───────────────────────────────────────────────────────────

/// Returns (body, body_byte_offset_in_text, body_1based_line).
pub fn strip_frontmatter(text: &str) -> (&str, usize, usize) {
    const FENCE: &str = "---";
    if !text.starts_with(FENCE) { return (text, 0, 1); }
    let mut byte_pos = 0usize;
    let mut line_num = 0usize;
    loop {
        let rem = &text[byte_pos..];
        if rem.is_empty() { break; }
        let (line_bytes, advance) = match rem.find('\n') {
            Some(nl) => (&rem[..nl], nl + 1),
            None => (rem, rem.len()),
        };
        let trimmed = line_bytes.trim_end_matches('\r');
        if line_num == 0 {
            if trimmed != FENCE { return (text, 0, 1); }
        } else if trimmed == FENCE {
            let body_start = (byte_pos + advance).min(text.len());
            return (&text[body_start..], body_start, line_num + 2);
        }
        byte_pos += advance;
        line_num += 1;
    }
    (text, 0, 1)
}

// ── Block parsing ─────────────────────────────────────────────────────────

fn make_block(
    cur_lines: &[&str],
    cur_heading: &Option<(usize, String)>,
    start_line: usize,
    char_start: usize,
    byte_start: usize,
    char_end: usize,
    byte_end: usize,
    end_line: usize,
    heading_stack: &[(usize, String)],
) -> Option<Block> {
    if cur_heading.is_none() && !cur_lines.iter().any(|l| !l.trim().is_empty()) {
        return None;
    }
    let body_start = if cur_heading.is_some() { 1 } else { 0 };
    let has_content = cur_lines[body_start..].iter().any(|l| !l.trim().is_empty());
    let heading_path: Vec<String> = heading_stack.iter().map(|(_, t)| t.clone()).collect();
    let heading_text = match cur_heading {
        Some((_, t)) => t.clone(),
        None => String::new(),
    };
    Some(Block { line_start: start_line, line_end: end_line, char_start, char_end, byte_start, byte_end, heading_text, has_content, heading_path })
}

/// Builds blocks tracking both char and byte offsets inline (no allocation).
fn parse_blocks<'a>(
    body: &'a str,
    body_byte_offset: usize,
    body_char_offset: usize,
    body_line_offset: usize,
) -> Vec<Block> {
    let mut blocks: Vec<Block> = Vec::new();
    if body.is_empty() { return blocks; }

    let mut heading_stack: Vec<(usize, String)> = Vec::new();
    let mut cur_lines: Vec<&'a str> = Vec::new();
    let mut cur_block_start_line = body_line_offset;
    let mut cur_block_char_start = body_char_offset;
    let mut cur_block_byte_start = body_byte_offset;
    let mut cur_heading: Option<(usize, String)> = None;
    let mut char_pos = body_char_offset;
    let mut byte_pos = 0usize;

    let mut lines = body.split('\n').peekable();
    let mut line_idx = 0usize;

    while let Some(line) = lines.next() {
        let is_last = lines.peek().is_none();
        let line_no = body_line_offset + line_idx;
        let orig_char = char_pos;
        let orig_byte = body_byte_offset + byte_pos;

        if let Some((level, text)) = parse_heading(line) {
            if !cur_lines.is_empty() || cur_heading.is_some() {
                if let Some(b) = make_block(
                    &cur_lines, &cur_heading,
                    cur_block_start_line,
                    cur_block_char_start, cur_block_byte_start,
                    orig_char, orig_byte,
                    line_no.saturating_sub(1),
                    &heading_stack,
                ) { blocks.push(b); }
                cur_lines.clear();
            }
            while heading_stack.last().map(|(l, _)| *l >= level).unwrap_or(false) {
                heading_stack.pop();
            }
            heading_stack.push((level, text.to_string()));
            cur_heading = Some((level, text.to_string()));
            cur_block_start_line = line_no;
            cur_block_char_start = orig_char;
            cur_block_byte_start = orig_byte;
            cur_lines.push(line);
        } else {
            cur_lines.push(line);
        }

        let line_char_len = char_count(line);
        char_pos += line_char_len;
        byte_pos += line.len();
        if !is_last { char_pos += 1; byte_pos += 1; }
        line_idx += 1;
    }

    if !cur_lines.is_empty() || cur_heading.is_some() {
        let end_byte = body_byte_offset + byte_pos;
        let end_line = body_line_offset + line_idx.saturating_sub(1);
        if let Some(b) = make_block(
            &cur_lines, &cur_heading,
            cur_block_start_line,
            cur_block_char_start, cur_block_byte_start,
            char_pos, end_byte,
            end_line,
            &heading_stack,
        ) { blocks.push(b); }
    }

    blocks
}

// ── Heading path merge ────────────────────────────────────────────────────

fn compute_heading_path(group: &[Block]) -> Vec<String> {
    let first = &group[0];
    if group.iter().all(|b| b.heading_path == first.heading_path) {
        return first.heading_path.clone();
    }
    let min_len = group.iter().map(|b| b.heading_path.len()).min().unwrap_or(0);
    let mut common_len = 0usize;
    for i in 0..min_len {
        if group.iter().all(|b| b.heading_path[i] == first.heading_path[i]) {
            common_len += 1;
        } else { break; }
    }
    let mut common = first.heading_path[..common_len].to_vec();
    let mut seen: HashSet<String> = HashSet::new();
    let mut unique_tails: Vec<String> = Vec::new();
    for b in group {
        let rest = &b.heading_path[common_len..];
        let tail = if !rest.is_empty() {
            rest.last().unwrap().clone()
        } else if !b.heading_text.is_empty() {
            b.heading_text.clone()
        } else { continue; };
        if seen.insert(tail.clone()) { unique_tails.push(tail); }
    }
    if !unique_tails.is_empty() { common.push(unique_tails.join(" / ")); }
    common
}

// ── Public entry point ────────────────────────────────────────────────────

pub fn chunk_markdown(text: &str, config: &ChunkConfig) -> Vec<Chunk> {
    let (body, body_byte_offset, body_line_offset) = strip_frontmatter(text);

    // Char offset for frontmatter end — usually just a few hundred bytes.
    let body_char_offset = char_count(&text[..body_byte_offset]);

    let blocks = parse_blocks(body, body_byte_offset, body_char_offset, body_line_offset);

    let est_tok = |char_start: usize, char_end: usize| -> usize {
        ((char_end - char_start) / 3).max(1)
    };

    let mut groups: Vec<Vec<Block>> = Vec::new();
    let mut pending: Vec<Block> = Vec::new();
    let mut pending_tokens = 0usize;

    for b in blocks {
        if !b.has_content { continue; }
        let btok = est_tok(b.char_start, b.char_end);
        if btok > config.max_size_tokens {
            if !pending.is_empty() {
                groups.push(std::mem::take(&mut pending));
                pending_tokens = 0;
            }
            groups.push(vec![b]);
        } else if !pending.is_empty() && pending_tokens + btok > config.target_size_tokens {
            groups.push(std::mem::take(&mut pending));
            pending = vec![b];
            pending_tokens = btok;
        } else {
            pending.push(b);
            pending_tokens += btok;
        }
    }
    if !pending.is_empty() { groups.push(pending); }

    groups
        .into_iter()
        .enumerate()
        .map(|(seq, group)| {
            let first = &group[0];
            let last = group.last().unwrap();
            let char_start = first.char_start;
            let char_end = last.char_end;
            let content = text[first.byte_start..last.byte_end].to_string();
            let heading_path = compute_heading_path(&group);
            let anchor = if !first.heading_text.is_empty() {
                Some(format!("#{}", slug(&first.heading_text)))
            } else { None };
            Chunk {
                seq,
                content,
                char_start,
                char_end,
                line_start: first.line_start,
                line_end: last.line_end,
                heading_path,
                anchor,
                token_count: ((char_end - char_start) / 3).max(1),
            }
        })
        .collect()
}
