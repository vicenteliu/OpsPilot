/// BPE-ish token counter (PR-18).
///
/// Algorithm (matches Python re.compile(r'[a-zA-Z0-9]+|[^\s]', re.ASCII)):
///   - ASCII alphanumeric runs → 1 token per run
///   - ASCII whitespace (space/tab/LF/CR/FF/VT) → 0 tokens (skipped)
///   - Everything else — ASCII punctuation, any multibyte Unicode code point
///     (CJK, emoji, diacritics, …) → 1 token per code point
///
/// Implemented as a byte scanner. Multibyte UTF-8 sequences are advanced by
/// their length (2/3/4 bytes) so each code point is counted exactly once.
/// LLVM auto-vectorises the inner whitespace/alphanumeric checks.
pub fn count_tokens(text: &str) -> usize {
    let bytes = text.as_bytes();
    let len = bytes.len();
    let mut i = 0usize;
    let mut count = 0usize;

    while i < len {
        let b = bytes[i];
        if b <= 0x7F {
            match b {
                b' ' | b'\t' | b'\n' | b'\r' | 0x0C | 0x0B => {
                    i += 1;
                }
                b'0'..=b'9' | b'A'..=b'Z' | b'a'..=b'z' => {
                    count += 1;
                    i += 1;
                    while i < len && bytes[i].is_ascii_alphanumeric() {
                        i += 1;
                    }
                }
                _ => {
                    // ASCII punctuation / other non-whitespace
                    count += 1;
                    i += 1;
                }
            }
        } else {
            // Multibyte UTF-8: advance by code-point length, count 1.
            let char_len: usize = if b & 0xE0 == 0xC0 {
                2
            } else if b & 0xF0 == 0xE0 {
                3
            } else if b & 0xF8 == 0xF0 {
                4
            } else {
                1 // invalid continuation byte — skip one
            };
            count += 1;
            i += char_len.min(len - i);
        }
    }

    count.max(1)
}
