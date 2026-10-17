use crate::options::{Options, Sort};
use crate::{errors::Errors, secure_fs};
use std::cmp::Ordering;
use std::collections::{HashMap, HashSet};
use std::fs::{self, Metadata};
use std::io;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};
use std::{ffi::OsString, fs::File, sync::Arc};
const MAX_ENTRIES: usize = 20_000;
const MAX_DIRECTORIES: usize = 512;
const MAX_DEPTH: usize = 64;
const MAX_PATH_BYTES: usize = 4096;

#[derive(Debug)]
pub struct Entry {
    pub path: PathBuf,
    pub name: String,
    pub info: Metadata,
    pub parent: Arc<File>,
    pub leaf: OsString,
    depth: usize,
}
impl Entry {
    fn load(
        path: PathBuf,
        name: String,
        parents: &mut HashMap<PathBuf, Arc<File>>,
    ) -> io::Result<Self> {
        if path.as_os_str().len() > MAX_PATH_BYTES {
            return Err(io::Error::other("path length limit exceeded (4096 bytes)"));
        }
        let key = path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(if path.is_absolute() {
                Path::new("/")
            } else {
                Path::new(".")
            })
            .to_path_buf();
        let (parent, leaf) = if let Some(parent) = parents.get(&key) {
            let leaf = match path.components().next_back() {
                None | Some(std::path::Component::RootDir) => OsString::from("."),
                Some(part) => part.as_os_str().to_owned(),
            };
            (parent.clone(), leaf)
        } else {
            if parents.len() >= MAX_DIRECTORIES {
                return Err(io::Error::other(
                    "operand parent directory limit exceeded (512)",
                ));
            }
            let (parent, leaf) = secure_fs::parent(&path)?;
            parents.insert(key, parent.clone());
            (parent, leaf)
        };
        Self::at(path, name, parent, leaf)
    }
    fn at(path: PathBuf, name: String, parent: Arc<File>, leaf: OsString) -> io::Result<Self> {
        if path.as_os_str().len() > MAX_PATH_BYTES {
            return Err(io::Error::other("path length limit exceeded (4096 bytes)"));
        }
        let info = secure_fs::metadata(&parent, &leaf)?;
        Ok(Self {
            path,
            name,
            info,
            parent,
            leaf,
            depth: 0,
        })
    }
}
fn natural(a: &str, b: &str) -> Ordering {
    let (a, b) = (a.as_bytes(), b.as_bytes());
    let (mut i, mut j) = (0, 0);
    while i < a.len() && j < b.len() {
        if a[i].is_ascii_digit() && b[j].is_ascii_digit() {
            let (start_a, start_b) = (i, j);
            while i < a.len() && a[i].is_ascii_digit() {
                i += 1;
            }
            while j < b.len() && b[j].is_ascii_digit() {
                j += 1;
            }
            let (mut x, mut y) = (start_a, start_b);
            while x < i && a[x] == b'0' {
                x += 1;
            }
            while y < j && b[y] == b'0' {
                y += 1;
            }
            let cmp = (i - x).cmp(&(j - y)).then_with(|| a[x..i].cmp(&b[y..j]));
            if cmp != Ordering::Equal {
                return cmp;
            }
        } else {
            let cmp = a[i].cmp(&b[j]);
            if cmp != Ordering::Equal {
                return cmp;
            }
            i += 1;
            j += 1;
        }
    }
    (a.len() - i).cmp(&(b.len() - j))
}
fn extension(name: &str) -> &str {
    // Match pathlib suffix semantics for dotfiles and trailing periods.
    name.rfind('.')
        .filter(|&i| i > 0 && i + 1 < name.len())
        .map_or("", |i| &name[i..])
}
fn sort(entries: &mut [Entry], opt: &Options) {
    if !matches!(opt.order(), Sort::None) {
        entries.sort_by(|a, b| {
            let primary = match opt.order() {
                Sort::Name | Sort::None => Ordering::Equal,
                Sort::Size => b.info.size().cmp(&a.info.size()),
                Sort::Time => (b.info.mtime(), b.info.mtime_nsec())
                    .cmp(&(a.info.mtime(), a.info.mtime_nsec())),
                Sort::Extension => extension(&a.name).cmp(extension(&b.name)),
                Sort::Version => natural(&a.name, &b.name),
            };
            primary.then_with(|| a.name.cmp(&b.name))
        });
        if opt.reverse {
            entries.reverse();
        }
    }
    if opt.directories_first() {
        entries.sort_by_key(|e| !e.info.is_dir());
    }
}

pub fn walk(
    opt: &Options,
    mut show: impl FnMut(Option<String>, Vec<Entry>) -> io::Result<()>,
    errors: &mut Errors,
    budget: &crate::budget::Budget,
) -> io::Result<()> {
    if opt.paths.len() > MAX_ENTRIES {
        return Err(io::Error::other("operand limit exceeded (20000)"));
    }
    let mut total = 0usize;
    let (mut files, mut folders) = (Vec::new(), Vec::new());
    let mut parents = HashMap::new();
    for path in &opt.paths {
        match Entry::load(
            path.clone(),
            path.to_string_lossy().into_owned(),
            &mut parents,
        ) {
            Ok(entry) if entry.info.is_dir() && !opt.directory => folders.push(entry),
            Ok(entry) => files.push(entry),
            Err(e) => errors.push(format!("{}: {e}", path.display())),
        }
    }
    sort(&mut files, opt);
    sort(&mut folders, opt);
    if !files.is_empty() {
        show(None, files)?;
    }
    let mut stack: Vec<Entry> = folders.into_iter().rev().collect();
    if stack.len() > MAX_DIRECTORIES {
        return Err(io::Error::other("pending directory limit exceeded (512)"));
    }
    let mut seen = HashSet::new();
    while let Some(entry) = stack.pop() {
        budget.check()?;
        let depth = entry.depth;
        let folder = entry.path;
        let directory = match secure_fs::directory(&entry.parent, &entry.leaf, &entry.info) {
            Ok(file) => file,
            Err(e) => {
                errors.push(format!("{}: {e}", folder.display()));
                continue;
            }
        };
        let info = directory.metadata()?;
        if opt.recursive && !seen.insert((info.dev(), info.ino())) {
            errors.push(format!(
                "recursive directory already visited: {}",
                folder.display()
            ));
            continue;
        }
        let children =
            match fs::read_dir(secure_fs::anchored(&directory, std::ffi::OsStr::new("."))) {
                Ok(children) => children,
                Err(e) => {
                    errors.push(format!("{}: {e}", folder.display()));
                    continue;
                }
            };
        let mut entries = Vec::new();
        for child in children {
            budget.check()?;
            match child {
                Ok(child) => {
                    let name = child.file_name().to_string_lossy().into_owned();
                    if !opt.all && !opt.almost_all && name.starts_with('.') {
                        continue;
                    }
                    total += 1;
                    if total > MAX_ENTRIES {
                        return Err(io::Error::other("entry limit exceeded (20000)"));
                    }
                    match Entry::at(
                        folder.join(child.file_name()),
                        name,
                        directory.clone(),
                        child.file_name(),
                    ) {
                        Ok(mut entry) => {
                            entry.depth = depth + 1;
                            entries.push(entry);
                        }
                        Err(e) => errors.push(e.to_string()),
                    }
                }
                Err(e) => errors.push(format!("{}: {e}", folder.display())),
            }
        }
        sort(&mut entries, opt);
        if opt.recursive {
            for e in entries.iter().rev().filter(|e| e.info.is_dir()) {
                if e.depth > MAX_DEPTH {
                    return Err(io::Error::other("recursive depth limit exceeded (64)"));
                }
                if stack.len() >= MAX_DIRECTORIES || seen.len() >= MAX_ENTRIES {
                    return Err(io::Error::other("recursive directory limit exceeded"));
                }
                stack.push(Entry {
                    path: e.path.clone(),
                    name: e.name.clone(),
                    info: e.info.clone(),
                    parent: e.parent.clone(),
                    leaf: e.leaf.clone(),
                    depth: e.depth,
                });
            }
        }
        if opt.all {
            let mut dots = Vec::new();
            for name in [".", ".."] {
                match Entry::at(
                    folder.join(name),
                    name.into(),
                    directory.clone(),
                    name.into(),
                ) {
                    Ok(entry) => dots.push(entry),
                    Err(e) => errors.push(e.to_string()),
                }
            }
            dots.append(&mut entries);
            entries = dots;
        }
        let heading =
            (opt.recursive || opt.paths.len() > 1).then(|| folder.to_string_lossy().into_owned());
        show(heading, entries)?;
    }
    Ok(())
}

pub fn is_image(path: &Path) -> bool {
    path.extension().is_some_and(|ext| {
        matches!(
            ext.to_string_lossy().to_ascii_lowercase().as_str(),
            "png" | "jpg" | "jpeg" | "gif" | "webp" | "bmp" | "tif" | "tiff" | "ico" | "avif"
        )
    })
}
