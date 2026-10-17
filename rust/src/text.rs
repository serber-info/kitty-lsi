use unicode_general_category::{GeneralCategory, get_general_category};
use unicode_width::UnicodeWidthStr;

pub fn safe(value: &str) -> String {
    value
        .chars()
        .map(|c| match get_general_category(c) {
            GeneralCategory::Control
            | GeneralCategory::Format
            | GeneralCategory::Surrogate
            | GeneralCategory::PrivateUse
            | GeneralCategory::Unassigned => '?',
            _ if matches!(c, '\u{2028}' | '\u{2029}' | '\u{10eeee}') => '?',
            _ => c,
        })
        .collect()
}
pub fn width(s: &str) -> usize {
    UnicodeWidthStr::width(s)
}
pub fn truncate(value: &str, columns: usize) -> String {
    if width(value) <= columns {
        return value.to_owned();
    }
    if columns == 0 {
        return String::new();
    }
    let mut result = String::new();
    for c in value.chars() {
        let mut candidate = result.clone();
        candidate.push(c);
        if width(&candidate) >= columns {
            break;
        }
        result.push(c);
    }
    result.push('…');
    result
}
pub fn padded(value: &str, columns: usize) -> String {
    let text = truncate(value, columns);
    let pad = columns.saturating_sub(width(&text));
    text + &" ".repeat(pad)
}
