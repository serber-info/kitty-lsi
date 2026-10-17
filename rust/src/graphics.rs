//! Direct Kitty PNG streaming with virtual placements and Unicode placeholders.
//! https://sw.kovidgoyal.net/kitty/graphics-protocol/#unicode-placeholders
use base64::{Engine, engine::general_purpose::STANDARD};
use std::io::{self, Write};
const MARKS: [char; 16] = [
    '\u{305}', '\u{30d}', '\u{30e}', '\u{310}', '\u{312}', '\u{33d}', '\u{33e}', '\u{33f}',
    '\u{346}', '\u{34a}', '\u{34b}', '\u{34c}', '\u{350}', '\u{351}', '\u{352}', '\u{357}',
];
pub fn transmit(
    out: &mut impl Write,
    png: &[u8],
    id: u32,
    cols: usize,
    rows: usize,
) -> io::Result<()> {
    let data = STANDARD.encode(png);
    let chunks = data.as_bytes().chunks(4096);
    let len = chunks.len();
    for (index, chunk) in chunks.enumerate() {
        let more = usize::from(index + 1 < len);
        write!(out, "\x1b_Gm={more},q=2")?;
        if index == 0 {
            write!(out, ",a=T,f=100,t=d,U=1,i={id},c={cols},r={rows}")?;
        }
        out.write_all(b";")?;
        out.write_all(chunk)?;
        out.write_all(b"\x1b\\")?;
    }
    Ok(())
}
pub fn row(id: u32, row: usize, columns: usize) -> String {
    let mut text = format!(
        "\x1b[38;2;{};{};{}m\u{10eeee}{}{}{}",
        (id >> 16) & 255,
        (id >> 8) & 255,
        id & 255,
        MARKS[row],
        MARKS[0],
        MARKS[(id >> 24) as usize]
    );
    for _ in 1..columns {
        text.push('\u{10eeee}');
    }
    text.push_str("\x1b[39m");
    text
}
