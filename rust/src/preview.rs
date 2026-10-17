//! Bounded decoding inside the resource-limited same-executable worker.
use image::{DynamicImage, ImageDecoder, ImageFormat, ImageReader, Limits};
use std::{
    fs::File,
    io::{BufReader, Cursor, Read},
};
const MAX_BYTES: u64 = 64 * 1024 * 1024;
const MAX_PIXELS: u64 = 40_000_000;
type Result<T> = std::result::Result<T, String>;
pub struct Preview {
    pub png: Vec<u8>,
    pub dimensions: (u32, u32),
}

/// Neutral raster icons: no fonts, icon themes, external files or link following.
#[derive(Clone, Copy)]
pub enum Icon {
    Folder,
    File,
    Link,
    Fifo,
    Socket,
    CharacterDevice,
    BlockDevice,
    Unknown,
    Error,
    Extension {
        label: &'static str,
        category: Category,
    },
}

/// Match names only: never read content or resolve symbolic links.
/// Compound archive suffixes have priority over the final extension.
pub fn extension_icon(path: &std::path::Path) -> Option<Icon> {
    let name = path.file_name()?.to_string_lossy().to_ascii_lowercase();
    let suffix = if name.ends_with(".tar.gz") {
        "tar.gz"
    } else if name.ends_with(".tar.xz") {
        "tar.xz"
    } else {
        name.rsplit_once('.')?.1
    };
    use Category::*;
    let (label, category) = match suffix {
        "mp4" => ("MP4", Video),
        "mkv" => ("MKV", Video),
        "avi" => ("AVI", Video),
        "mov" => ("MOV", Video),
        "webm" => ("WEBM", Video),
        "mp3" => ("MP3", Audio),
        "wav" => ("WAV", Audio),
        "flac" => ("FLAC", Audio),
        "aac" => ("AAC", Audio),
        "ogg" => ("OGG", Audio),
        "m4a" => ("M4A", Audio),
        "jpg" | "jpeg" => ("JPG", Image),
        "png" => ("PNG", Image),
        "webp" => ("WEBP", Image),
        "gif" => ("GIF", Image),
        "svg" => ("SVG", Image),
        "bmp" => ("BMP", Image),
        "tif" | "tiff" => ("TIFF", Image),
        "ico" => ("ICO", Image),
        "avif" => ("AVIF", Image),
        "zip" => ("ZIP", Archive),
        "rar" => ("RAR", Archive),
        "7z" => ("7Z", Archive),
        "tar" => ("TAR", Archive),
        "gz" => ("GZ", Archive),
        "bz2" => ("BZ2", Archive),
        "xz" => ("XZ", Archive),
        "tar.gz" => ("TAR.GZ", Archive),
        "tar.xz" => ("TAR.XZ", Archive),
        "pdf" => ("PDF", Document),
        "doc" => ("DOC", Document),
        "docx" => ("DOCX", Document),
        "odt" => ("ODT", Document),
        "rtf" => ("RTF", Document),
        "txt" => ("TXT", Document),
        "md" => ("MD", Document),
        "xls" => ("XLS", Sheet),
        "xlsx" => ("XLSX", Sheet),
        "ods" => ("ODS", Sheet),
        "csv" => ("CSV", Sheet),
        "ppt" => ("PPT", Slides),
        "pptx" => ("PPTX", Slides),
        "odp" => ("ODP", Slides),
        "exe" => ("EXE", Script),
        "msi" => ("MSI", Script),
        "bat" => ("BAT", Script),
        "sh" => ("SH", Script),
        "py" => ("PY", Script),
        "js" => ("JS", Script),
        "iso" => ("ISO", Disk),
        "img" => ("IMG", Disk),
        "html" => ("HTML", Code),
        "css" => ("CSS", Code),
        "json" => ("JSON", Code),
        "xml" => ("XML", Code),
        "yaml" | "yml" => ("YAML", Code),
        "sql" => ("SQL", Code),
        _ => return None,
    };
    Some(Icon::Extension { label, category })
}

#[derive(Clone, Copy)]
pub enum Category {
    Video,
    Audio,
    Image,
    Archive,
    Document,
    Sheet,
    Slides,
    Script,
    Disk,
    Code,
}

// Embedded 3x5 bitmap alphabet, not a font dependency or terminal glyph. Labels
// are fixed ASCII constants above, never untrusted filename text.
fn glyph(c: u8) -> [u8; 5] {
    match c {
        b'A' => [2, 5, 7, 5, 5],
        b'B' => [6, 5, 6, 5, 6],
        b'C' => [3, 4, 4, 4, 3],
        b'D' => [6, 5, 5, 5, 6],
        b'E' => [7, 4, 6, 4, 7],
        b'F' => [7, 4, 6, 4, 4],
        b'G' => [3, 4, 5, 5, 3],
        b'H' => [5, 5, 7, 5, 5],
        b'I' => [7, 2, 2, 2, 7],
        b'J' => [1, 1, 1, 5, 2],
        b'K' => [5, 5, 6, 5, 5],
        b'L' => [4, 4, 4, 4, 7],
        b'M' => [5, 7, 7, 5, 5],
        b'N' => [5, 7, 7, 7, 5],
        b'O' => [2, 5, 5, 5, 2],
        b'P' => [6, 5, 6, 4, 4],
        b'Q' => [2, 5, 5, 7, 3],
        b'R' => [6, 5, 6, 5, 5],
        b'S' => [3, 4, 2, 1, 6],
        b'T' => [7, 2, 2, 2, 2],
        b'U' => [5, 5, 5, 5, 7],
        b'V' => [5, 5, 5, 5, 2],
        b'W' => [5, 5, 7, 7, 5],
        b'X' => [5, 5, 2, 5, 5],
        b'Y' => [5, 5, 2, 2, 2],
        b'Z' => [7, 1, 2, 4, 7],
        b'2' => [6, 1, 2, 4, 7],
        b'3' => [6, 1, 2, 1, 6],
        b'4' => [5, 5, 7, 1, 1],
        b'7' => [7, 1, 2, 2, 2],
        b'.' => [0, 0, 0, 0, 2],
        _ => [0; 5],
    }
}

pub fn icon(kind: Icon) -> Result<Preview> {
    let mut image = image::RgbaImage::new(96, 80);
    for y in 0..80 {
        for x in 0..96 {
            let color = match kind {
                Icon::Folder
                    if (22..58).contains(&y) && (24..72).contains(&x) && (y >= 28 || x < 45) =>
                {
                    Some(if y < 32 {
                        [208, 153, 52, 255]
                    } else {
                        [238, 190, 79, 255]
                    })
                }
                Icon::File | Icon::Link | Icon::Extension { .. } => {
                    if (26..70).contains(&y)
                        && (30..66).contains(&x)
                        && (y >= 36 || x < 54 || x - 54 <= y - 26)
                    {
                        let mark = match kind {
                            // An up-right arrow identifies every symlink, including dangling ones.
                            Icon::Link => {
                                ((39..57).contains(&x) && (39..43).contains(&y))
                                    || ((53..57).contains(&x) && (39..57).contains(&y))
                                    || ((38..57).contains(&x)
                                        && (39..58).contains(&y)
                                        && (x as i32 + y as i32 - 95).abs() <= 2)
                            }
                            _ => (39..59).contains(&x) && (y == 43 || y == 50 || y == 57),
                        };
                        Some(if mark {
                            [49, 104, 148, 255]
                        } else {
                            [195, 210, 222, 255]
                        })
                    } else {
                        None
                    }
                }
                Icon::Fifo => {
                    // Two connected pipe elbows.
                    let pipe = ((28..49).contains(&x) && (34..43).contains(&y))
                        || ((41..50).contains(&x) && (34..56).contains(&y))
                        || ((41..68).contains(&x) && (47..56).contains(&y));
                    pipe.then_some([89, 180, 178, 255])
                }
                Icon::Socket => {
                    // Plug with two pins.
                    let plug = ((35..61).contains(&x) && (34..52).contains(&y))
                        || ((39..44).contains(&x) && (25..36).contains(&y))
                        || ((52..57).contains(&x) && (25..36).contains(&y))
                        || ((45..51).contains(&x) && (50..65).contains(&y));
                    plug.then_some([164, 135, 207, 255])
                }
                Icon::CharacterDevice | Icon::BlockDevice => {
                    if (28..68).contains(&x) && (28..59).contains(&y) {
                        let indicator = match kind {
                            Icon::CharacterDevice => {
                                (36..60).contains(&x) && (y == 37 || y == 43 || y == 49)
                            }
                            _ => (36..60).contains(&x) && (36..51).contains(&y),
                        };
                        Some(if indicator {
                            [62, 77, 91, 255]
                        } else {
                            [154, 171, 185, 255]
                        })
                    } else {
                        None
                    }
                }
                Icon::Error => {
                    // Amber warning triangle and dark exclamation mark.
                    if (24..62).contains(&y) && (x as i32 - 48).abs() <= (y - 24) as i32 / 2 {
                        let mark = (46..51).contains(&x)
                            && ((37..50).contains(&y) || (54..58).contains(&y));
                        Some(if mark {
                            [65, 49, 34, 255]
                        } else {
                            [239, 167, 70, 255]
                        })
                    } else {
                        None
                    }
                }
                Icon::Unknown => {
                    let diamond = (x as i32 - 48).abs() + (y as i32 - 44).abs() < 24;
                    diamond.then_some([150, 155, 163, 255])
                }
                _ => None,
            };
            if let Some(color) = color {
                image.put_pixel(x, y, image::Rgba(color));
            }
        }
    }
    if let Icon::Extension { label, category } = kind {
        use Category::*;
        let tint = match category {
            Video => [163, 89, 126, 255],
            Audio => [148, 105, 183, 255],
            Image => [73, 153, 172, 255],
            Archive => [170, 126, 62, 255],
            Document => [78, 128, 177, 255],
            Sheet => [66, 141, 103, 255],
            Slides => [185, 106, 69, 255],
            Script => [95, 127, 151, 255],
            Disk => [110, 118, 128, 255],
            Code => [77, 137, 147, 255],
        };
        // A category-specific symbol on the page, and a high-contrast label.
        for y in 37u32..56 {
            for x in 36u32..60 {
                let symbol = match category {
                    Video => {
                        (41..55).contains(&x)
                            && (40..53).contains(&y)
                            && x - 41 <= 6 - (y as i32 - 46).unsigned_abs().min(6)
                    }
                    Audio => {
                        ((49..53).contains(&x) && y < 50)
                            || ((41..52).contains(&x) && (48..54).contains(&y))
                            || ((49..59).contains(&x) && y < 41)
                    }
                    Image => y >= 53 - (x as i32 - 44).unsigned_abs().min(10),
                    Archive => (46..50).contains(&x) && (y % 4 < 2),
                    Document => (39..57).contains(&x) && (y == 41 || y == 46 || y == 51),
                    Sheet => {
                        (39..58).contains(&x) && (40..54).contains(&y) && (x % 6 == 3 || y % 5 == 0)
                    }
                    Slides => {
                        ((39..58).contains(&x) && (40..51).contains(&y)) || (x == 48 && y >= 51)
                    }
                    Script => {
                        ((39..46).contains(&x) && (y as i32 - 46).abs() == (x - 39) as i32)
                            || ((49..57).contains(&x) && y == 52)
                    }
                    Disk => {
                        let r = (x as i32 - 48).pow(2) + (y as i32 - 46).pow(2);
                        (9..=64).contains(&r)
                    }
                    Code => {
                        ((38..45).contains(&x) && (y as i32 - 46).abs() == (44 - x) as i32)
                            || ((51..58).contains(&x) && (y as i32 - 46).abs() == (x - 51) as i32)
                    }
                };
                image.put_pixel(
                    x,
                    y,
                    image::Rgba(if symbol { tint } else { [195, 210, 222, 255] }),
                );
            }
        }
        for y in 58..67 {
            for x in 31..65 {
                image.put_pixel(x, y, image::Rgba(tint));
            }
        }
        let start = (96 - (label.len() as u32 * 4 - 1)) / 2;
        for (index, c) in label.bytes().enumerate() {
            for (row, bits) in glyph(c).iter().enumerate() {
                for col in 0..3 {
                    if bits & (1 << (2 - col)) != 0 {
                        image.put_pixel(
                            start + index as u32 * 4 + col,
                            60 + row as u32,
                            image::Rgba([255, 255, 255, 255]),
                        );
                    }
                }
            }
        }
    }
    let mut png = Cursor::new(Vec::new());
    DynamicImage::ImageRgba8(image)
        .write_to(&mut png, ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(Preview {
        png: png.into_inner(),
        dimensions: (96, 80),
    })
}
fn check(w: u32, h: u32) -> Result<()> {
    if u64::from(w) * u64::from(h) > MAX_PIXELS {
        Err("image exceeds 40 megapixels".into())
    } else {
        Ok(())
    }
}
pub fn load(file: File, columns: usize, rows: usize) -> Result<Preview> {
    let info = file.metadata().map_err(|e| e.to_string())?;
    if !info.is_file() || info.len() > MAX_BYTES {
        return Err("not a regular file or larger than 64 MiB".into());
    }
    let mut bytes = Vec::new();
    (&file)
        .take(MAX_BYTES + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| e.to_string())?;
    if bytes.len() as u64 > MAX_BYTES {
        return Err("file larger than 64 MiB".into());
    }
    crate::secure_fs::identity(&info, &file.metadata().map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    let mut format = image::guess_format(&bytes).map_err(|e| e.to_string())?;
    // Some valid ICOs embed an RGB PNG; image's ICO decoder insists on RGBA.
    // Decode the bounded embedded PNG directly, rather than dropping ICO support.
    let data = if format == ImageFormat::Ico {
        match ico_png(&bytes) {
            Some(png) => {
                format = ImageFormat::Png;
                png
            }
            None => &bytes,
        }
    } else {
        &bytes
    };
    let mut img = if format == ImageFormat::Avif {
        avif(&bytes)?
    } else {
        let mut reader = ImageReader::with_format(BufReader::new(Cursor::new(data)), format);
        let mut limits = Limits::default();
        limits.max_alloc = Some(256 * 1024 * 1024);
        limits.max_image_width = Some(40_000);
        limits.max_image_height = Some(40_000);
        reader.limits(limits);
        let mut decoder = reader.into_decoder().map_err(|e| e.to_string())?;
        let (w, h) = decoder.dimensions();
        check(w, h)?;
        let orientation = decoder.orientation().map_err(|e| e.to_string())?;
        let mut decoded = DynamicImage::from_decoder(decoder).map_err(|e| e.to_string())?;
        decoded.apply_orientation(orientation);
        decoded
    };
    let dimensions = (img.width(), img.height());
    check(dimensions.0, dimensions.1)?;
    let bound = (columns * 16).max(rows * 32) as u32;
    if img.width() > bound || img.height() > bound {
        img = img.thumbnail(bound, bound);
    }
    let rgba = DynamicImage::ImageRgba8(img.to_rgba8());
    let mut png = Cursor::new(Vec::new());
    rgba.write_to(&mut png, ImageFormat::Png)
        .map_err(|e| e.to_string())?;
    Ok(Preview {
        png: png.into_inner(),
        dimensions,
    })
}

fn ico_png(bytes: &[u8]) -> Option<&[u8]> {
    let count = u16::from_le_bytes(bytes.get(4..6)?.try_into().ok()?) as usize;
    let mut best = None;
    for index in 0..count.min(256) {
        let entry = bytes.get(6 + index * 16..6 + (index + 1) * 16)?;
        let length = u32::from_le_bytes(entry[8..12].try_into().ok()?) as usize;
        let offset = u32::from_le_bytes(entry[12..16].try_into().ok()?) as usize;
        let data = bytes.get(offset..offset.checked_add(length)?)?;
        if !data.starts_with(b"\x89PNG\r\n\x1a\n") {
            continue;
        }
        let width = if entry[0] == 0 { 256 } else { entry[0] as u32 };
        let height = if entry[1] == 0 { 256 } else { entry[1] as u32 };
        let area = width * height;
        if best.is_none_or(|(previous, _)| area > previous) {
            best = Some((area, data));
        }
    }
    best.map(|(_, png)| png)
}
fn avif(bytes: &[u8]) -> Result<DynamicImage> {
    // Validate both planes' declared sequence maxima before decoding frames.
    let parsed = avif_parse::read_avif(&mut Cursor::new(bytes)).map_err(|e| e.to_string())?;
    let primary = parsed.primary_item_metadata().map_err(|e| e.to_string())?;
    check(
        primary.max_frame_width.get(),
        primary.max_frame_height.get(),
    )?;
    if let Some(alpha) = parsed.alpha_item_metadata().map_err(|e| e.to_string())? {
        check(alpha.max_frame_width.get(), alpha.max_frame_height.get())?;
    }
    drop(parsed);
    use avif_decode::Image::*;
    let decoded = avif_decode::Decoder::from_avif(bytes)
        .and_then(|d| d.to_image())
        .map_err(|e| e.to_string())?;
    let (data, w, h): (Vec<u8>, usize, usize) = match decoded {
        Rgb8(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter().flat_map(|p| [p.r, p.g, p.b, 255]).collect(),
                w,
                h,
            )
        }
        Rgba8(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter().flat_map(|p| [p.r, p.g, p.b, p.a]).collect(),
                w,
                h,
            )
        }
        Rgb16(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter()
                    .flat_map(|p| [(p.r >> 8) as u8, (p.g >> 8) as u8, (p.b >> 8) as u8, 255])
                    .collect(),
                w,
                h,
            )
        }
        Rgba16(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter()
                    .flat_map(|p| {
                        [
                            (p.r >> 8) as u8,
                            (p.g >> 8) as u8,
                            (p.b >> 8) as u8,
                            (p.a >> 8) as u8,
                        ]
                    })
                    .collect(),
                w,
                h,
            )
        }
        Gray8(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter()
                    .flat_map(|p| [p.value(), p.value(), p.value(), 255])
                    .collect(),
                w,
                h,
            )
        }
        Gray16(img) => {
            let (b, w, h) = img.into_contiguous_buf();
            (
                b.into_iter()
                    .flat_map(|p| {
                        let v = (p.value() >> 8) as u8;
                        [v, v, v, 255]
                    })
                    .collect(),
                w,
                h,
            )
        }
    };
    image::RgbaImage::from_raw(w as u32, h as u32, data)
        .map(DynamicImage::ImageRgba8)
        .ok_or_else(|| "invalid AVIF buffer".into())
}
