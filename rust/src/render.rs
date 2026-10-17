use crate::{
    graphics,
    listing::{self, Accounts},
    options::Options,
    preview,
    scan::{Entry, is_image},
    terminal, text,
};
use std::io::{self, IsTerminal, Write};
use std::os::unix::fs::FileTypeExt;
struct Card {
    entry: Entry,
    name: String,
    fields: Vec<String>,
    id: Option<u32>,
    dimensions: String,
}
pub struct Renderer<'a, W: Write> {
    opt: &'a Options,
    out: W,
    accounts: Accounts,
    graphics: bool,
    next_id: u32,
    pub errors: crate::errors::Errors,
    section_index: usize,
    started: std::time::Instant,
    used_ids: std::collections::HashSet<u32>,
}
impl<'a, W: Write> Renderer<'a, W> {
    pub fn new(opt: &'a Options, out: W) -> Self {
        let graphics = !opt.no_images && terminal::available();
        let mut bytes = [0; 4];
        let random = getrandom::fill(&mut bytes);
        let mut errors = crate::errors::Errors::new();
        if graphics && random.is_err() {
            errors.push("cannot obtain random image identifiers; showing names only".into());
        }
        if !opt.no_images && io::stdout().is_terminal() && !graphics {
            eprintln!("lsi: previews require Kitty without tmux/screen; showing names only.");
        }
        Self {
            opt,
            out,
            accounts: Accounts::new(),
            graphics: graphics && random.is_ok(),
            next_id: u32::from_ne_bytes(bytes) & 0xFFFFFF,
            errors,
            section_index: 0,
            started: std::time::Instant::now(),
            used_ids: std::collections::HashSet::new(),
        }
    }
    fn image(&mut self, card: &mut Card, width: usize, height: usize) -> io::Result<()> {
        if self.started.elapsed().as_secs() >= 120 {
            return Err(io::Error::other("listing exceeded 120 second deadline"));
        }
        let kind = card.entry.info.file_type();
        let raster = kind.is_file() && is_image(&card.entry.path);
        let result = if raster {
            crate::worker::load(&card.entry, width, height)
        } else {
            let icon = if kind.is_symlink() {
                preview::Icon::Link
            } else if kind.is_dir() {
                preview::Icon::Folder
            } else if kind.is_fifo() {
                preview::Icon::Fifo
            } else if kind.is_socket() {
                preview::Icon::Socket
            } else if kind.is_char_device() {
                preview::Icon::CharacterDevice
            } else if kind.is_block_device() {
                preview::Icon::BlockDevice
            } else if kind.is_file() {
                preview::extension_icon(&card.entry.path).unwrap_or(preview::Icon::File)
            } else {
                preview::Icon::Unknown
            };
            preview::icon(icon)
        };
        let decoded_image = raster && result.is_ok();
        let preview = match result {
            Ok(p) => p,
            Err(e) => {
                self.errors.push(format!("{}: {e}", card.name));
                preview::icon(preview::Icon::Error).map_err(io::Error::other)?
            }
        };
        loop {
            let mut random = [0; 4];
            getrandom::fill(&mut random).map_err(|e| io::Error::other(e.to_string()))?;
            self.next_id = u32::from_ne_bytes(random) & 0x0FFFFFFF;
            if self.next_id != 0 && self.used_ids.insert(self.next_id) {
                break;
            }
        }
        card.id = Some(self.next_id);
        if decoded_image {
            card.dimensions = format!("{} × {}", preview.dimensions.0, preview.dimensions.1);
        }
        graphics::transmit(&mut self.out, &preview.png, self.next_id, width, height)
    }
    fn image_row(card: &Card, row: usize, width: usize) -> String {
        card.id
            .map_or_else(|| " ".repeat(width), |id| graphics::row(id, row, width))
    }
    pub fn section(&mut self, heading: Option<String>, entries: Vec<Entry>) -> io::Result<()> {
        if self.section_index > 0 {
            writeln!(self.out)?;
        }
        self.section_index += 1;
        if let Some(heading) = heading {
            writeln!(self.out, "{}:", text::safe(&heading))?;
        }
        let mut cards = Vec::new();
        for entry in entries {
            let name = match listing::display_name(&entry, self.opt) {
                Ok(n) => n,
                Err(e) => {
                    self.errors.push(format!("{}: {e}", entry.path.display()));
                    continue;
                }
            };
            let fields = self
                .accounts
                .fields(&entry, self.opt)
                .into_iter()
                .map(|f| text::safe(&f))
                .collect();
            cards.push(Card {
                entry,
                name,
                fields,
                id: None,
                dimensions: String::new(),
            });
        }
        if cards.is_empty() {
            return Ok(());
        }
        let widths: Vec<_> = (0..cards[0].fields.len())
            .map(|i| {
                cards
                    .iter()
                    .map(|c| text::width(&c.fields[i]))
                    .max()
                    .unwrap_or(0)
            })
            .collect();
        for card in &mut cards {
            for (field, width) in card.fields.iter_mut().zip(&widths) {
                *field = text::padded(field, *width);
            }
        }
        let (columns, lines) = terminal::size().unwrap_or((80, 24));
        let width = usize::from(self.opt.width).min(columns.saturating_sub(12));
        let height = usize::from(self.opt.height).min(lines.saturating_sub(2).max(2));
        if !self.graphics || columns < 24 || width < 4 {
            for card in cards {
                if card.fields.is_empty() {
                    writeln!(self.out, "{}", card.name)?;
                } else {
                    writeln!(self.out, "{} {}", card.fields.join(" "), card.name)?;
                }
            }
        } else if self.opt.long || self.opt.one {
            self.rows(&mut cards, width, height, columns)?;
        } else {
            self.grid(&mut cards, width, height, columns)?;
        }
        self.out.flush()
    }
    fn grid(
        &mut self,
        cards: &mut [Card],
        width: usize,
        height: usize,
        columns: usize,
    ) -> io::Result<()> {
        let per_row = ((columns - 1) / (width + 3)).max(1);
        for batch in cards.chunks_mut(per_row) {
            for card in batch.iter_mut() {
                self.image(card, width, height)?;
            }
            for row in 0..height {
                let cells: Vec<_> = batch
                    .iter()
                    .map(|c| Self::image_row(c, row, width))
                    .collect();
                writeln!(self.out, "{}", cells.join("   "))?;
            }
            let labels: Vec<_> = batch
                .iter()
                .map(|c| {
                    let label = if c.fields.is_empty() {
                        c.name.clone()
                    } else {
                        format!("{} {}", c.fields.join(" "), c.name)
                    };
                    text::padded(&label, width)
                })
                .collect();
            writeln!(self.out, "{}\n", labels.join("   "))?;
        }
        Ok(())
    }
    fn rows(
        &mut self,
        cards: &mut [Card],
        width: usize,
        height: usize,
        columns: usize,
    ) -> io::Result<()> {
        let text_width = columns - width - 3;
        for card in cards {
            self.image(card, width, height)?;
            let mut labels = vec![card.name.clone()];
            if !card.fields.is_empty() {
                let mut line = String::new();
                for word in card.fields.join(" ").split_whitespace() {
                    let candidate = if line.is_empty() {
                        word.to_owned()
                    } else {
                        format!("{line} {word}")
                    };
                    if !line.is_empty() && text::width(&candidate) > text_width {
                        labels.push(line);
                        line = word.to_owned();
                    } else {
                        line = candidate;
                    }
                }
                labels.push(line);
            } else if !card.dimensions.is_empty() {
                labels.push(card.dimensions.clone());
            }
            let start = height.saturating_sub(labels.len()) / 2;
            for row in 0..height.max(labels.len()) {
                let image = if row < height {
                    Self::image_row(card, row, width)
                } else {
                    " ".repeat(width)
                };
                let label = row
                    .checked_sub(start)
                    .and_then(|i| labels.get(i))
                    .map_or("", |s| s.as_str());
                writeln!(self.out, "{image}  {}", text::truncate(label, text_width))?;
            }
            writeln!(self.out)?;
        }
        Ok(())
    }
}
