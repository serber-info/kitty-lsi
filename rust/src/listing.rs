use crate::{options::Options, scan::Entry};
use chrono::{DateTime, Local, Utc};
use std::os::unix::fs::MetadataExt;
use std::{collections::HashMap, fs};

pub struct Accounts {
    users: HashMap<u32, String>,
    groups: HashMap<u32, String>,
}
fn names(path: &str) -> HashMap<u32, String> {
    fs::read_to_string(path)
        .unwrap_or_default()
        .lines()
        .filter_map(|line| {
            let fields: Vec<_> = line.split(':').collect();
            Some((fields.get(2)?.parse().ok()?, fields.first()?.to_string()))
        })
        .collect()
}
impl Accounts {
    pub fn new() -> Self {
        Self {
            users: names("/etc/passwd"),
            groups: names("/etc/group"),
        }
    }
    pub fn fields(&self, entry: &Entry, opt: &Options) -> Vec<String> {
        let mut result = Vec::new();
        let info = &entry.info;
        if opt.inode {
            result.push(info.ino().to_string());
        }
        if !opt.long {
            return result;
        }
        result.push(permissions(info.mode()));
        result.push(info.nlink().to_string());
        if !opt.no_owner {
            result.push(if opt.numeric_uid_gid {
                info.uid().to_string()
            } else {
                self.users
                    .get(&info.uid())
                    .cloned()
                    .unwrap_or_else(|| info.uid().to_string())
            });
        }
        if !opt.no_group {
            result.push(if opt.numeric_uid_gid {
                info.gid().to_string()
            } else {
                self.groups
                    .get(&info.gid())
                    .cloned()
                    .unwrap_or_else(|| info.gid().to_string())
            });
        }
        result.push(
            if matches!(info.mode() & libc::S_IFMT, libc::S_IFCHR | libc::S_IFBLK) {
                format!("{}, {}", libc::major(info.rdev()), libc::minor(info.rdev()))
            } else {
                size(info.size(), opt.human_readable, opt.si)
            },
        );
        let date = DateTime::<Utc>::from_timestamp(info.mtime(), 0);
        result.push(match date {
            Some(date) => {
                let age = Utc::now().timestamp().saturating_sub(date.timestamp());
                let fmt = if opt.full_time {
                    "%Y-%m-%d %H:%M:%S %z"
                } else if (-3600..=15_778_476).contains(&age) {
                    "%b %d %H:%M"
                } else {
                    "%b %d  %Y"
                };
                date.with_timezone(&Local).format(fmt).to_string()
            }
            None => "[invalid timestamp]".into(),
        });
        result
    }
}
pub fn display_name(entry: &Entry, opt: &Options) -> std::io::Result<String> {
    let mut name = entry.name.clone();
    let mode = entry.info.mode();
    if entry.info.is_dir() && (opt.classify || opt.slash) {
        name.push('/');
    } else if opt.classify {
        match mode & libc::S_IFMT {
            libc::S_IFLNK => name.push('@'),
            libc::S_IFIFO => name.push('|'),
            libc::S_IFSOCK => name.push('='),
            libc::S_IFREG if mode & 0o111 != 0 => name.push('*'),
            _ => (),
        }
    }
    if opt.long && entry.info.file_type().is_symlink() {
        name.push_str(" -> ");
        name.push_str(
            &fs::read_link(crate::secure_fs::anchored(&entry.parent, &entry.leaf))?
                .to_string_lossy(),
        );
    }
    Ok(crate::text::safe(&name))
}
fn permissions(mode: u32) -> String {
    let kind = match mode & libc::S_IFMT {
        libc::S_IFDIR => 'd',
        libc::S_IFLNK => 'l',
        libc::S_IFCHR => 'c',
        libc::S_IFBLK => 'b',
        libc::S_IFIFO => 'p',
        libc::S_IFSOCK => 's',
        _ => '-',
    };
    let mut result = String::from(kind);
    for (r, w, x, special, low, high) in [
        (0o400, 0o200, 0o100, 0o4000, 's', 'S'),
        (0o40, 0o20, 0o10, 0o2000, 's', 'S'),
        (0o4, 0o2, 0o1, 0o1000, 't', 'T'),
    ] {
        result.push(if mode & r != 0 { 'r' } else { '-' });
        result.push(if mode & w != 0 { 'w' } else { '-' });
        result.push(if mode & special != 0 {
            if mode & x != 0 { low } else { high }
        } else if mode & x != 0 {
            'x'
        } else {
            '-'
        });
    }
    result
}
fn size(bytes: u64, human: bool, si: bool) -> String {
    if !human && !si {
        return bytes.to_string();
    }
    let base = if si { 1000.0 } else { 1024.0 };
    let units = if si {
        ["", "k", "M", "G", "T", "P", "E"]
    } else {
        ["", "K", "M", "G", "T", "P", "E"]
    };
    let mut value = bytes as f64;
    for (i, unit) in units.iter().enumerate() {
        if value < base || i == units.len() - 1 {
            return if i == 0 {
                bytes.to_string()
            } else if value < 10.0 {
                format!("{value:.1}{unit}")
            } else {
                format!("{value:.0}{unit}")
            };
        }
        value /= base;
    }
    unreachable!()
}
