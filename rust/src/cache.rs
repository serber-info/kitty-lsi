//! Private, bounded thumbnail cache. All cached PNGs are revalidated in a worker.
use crate::{preview::Preview, scan::Entry, secure_fs};
use std::{
    cell::{Cell, RefCell},
    collections::VecDeque,
    ffi::{CString, OsStr, OsString},
    fs::{self, File, Metadata},
    io::{self, Read, Seek, SeekFrom, Write},
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{ffi::OsStrExt, fs::MetadataExt},
    },
    path::{Component, Path, PathBuf},
};
const MAGIC: &[u8; 8] = b"LSIC0001";
const MAX_BYTES: u64 = 256 * 1024 * 1024;
const MAX_ENTRY: u64 = 8 * 1024 * 1024 + 16;
const MAX_ENTRIES: usize = 4096;
struct Item {
    name: OsString,
    info: Metadata,
}
pub struct Cache {
    dir: File,
    _lock: File,
    items: RefCell<VecDeque<Item>>,
    bytes: Cell<u64>,
    entry_count: Cell<usize>,
}
fn private(info: &Metadata) -> bool {
    // SAFETY: geteuid has no arguments and cannot fail.
    info.uid() == unsafe { libc::geteuid() } && info.mode() & 0o077 == 0
}
fn c_name(name: &OsStr) -> io::Result<CString> {
    CString::new(name.as_bytes()).map_err(|_| io::Error::other("NUL in cache path"))
}
fn open_at(dir: &File, name: &OsStr, flags: i32) -> io::Result<File> {
    let name = c_name(name)?;
    // SAFETY: live directory, NUL-terminated name, valid flags and creation mode.
    let fd = unsafe {
        libc::openat(
            dir.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_CLOEXEC | libc::O_NOFOLLOW | libc::O_NONBLOCK,
            0o600,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful openat returned a fresh owned descriptor.
    Ok(unsafe { File::from_raw_fd(fd) })
}
fn directory(path: &Path) -> io::Result<File> {
    if !path.is_absolute() {
        return Err(io::Error::other("cache path must be absolute"));
    }
    let mut dir = File::open("/")?;
    for part in path.components() {
        let Component::Normal(name) = part else {
            if matches!(part, Component::RootDir | Component::CurDir) {
                continue;
            }
            return Err(io::Error::other("invalid cache path component"));
        };
        dir = match open_at(&dir, name, libc::O_RDONLY | libc::O_DIRECTORY) {
            Ok(next) => next,
            Err(e) if e.kind() == io::ErrorKind::NotFound => {
                let c = c_name(name)?;
                // SAFETY: live parent directory and NUL-terminated single component.
                let status = unsafe { libc::mkdirat(dir.as_raw_fd(), c.as_ptr(), 0o700) };
                if status < 0 && io::Error::last_os_error().kind() != io::ErrorKind::AlreadyExists {
                    return Err(io::Error::last_os_error());
                }
                open_at(&dir, name, libc::O_RDONLY | libc::O_DIRECTORY)?
            }
            Err(e) => return Err(e),
        };
    }
    if !private(&dir.metadata()?) {
        return Err(io::Error::other("cache directory is not private"));
    }
    Ok(dir)
}
fn managed(name: &OsStr) -> bool {
    let s = name.as_bytes();
    (s.starts_with(b"v1-") && s.ends_with(b".thumb") || s.starts_with(b".tmp-"))
        && s.iter()
            .all(|c| c.is_ascii_hexdigit() || b"vtmpuh.-".contains(c))
}
fn key(entry: &Entry, columns: usize, rows: usize) -> OsString {
    let i = &entry.info;
    format!(
        "v1-{}-{:x}-{:x}-{:x}-{:x}-{:x}-{:x}-{:x}-{:x}-{columns:x}-{rows:x}.thumb",
        env!("CARGO_PKG_VERSION"),
        i.dev(),
        i.ino(),
        i.mode(),
        i.size(),
        i.mtime(),
        i.mtime_nsec(),
        i.ctime(),
        i.ctime_nsec()
    )
    .into()
}
impl Cache {
    pub fn open() -> io::Result<Self> {
        let base = match std::env::var_os("XDG_CACHE_HOME").filter(|s| !s.is_empty()) {
            Some(path) => PathBuf::from(path),
            None => PathBuf::from(
                std::env::var_os("HOME").ok_or_else(|| io::Error::other("HOME not set"))?,
            )
            .join(".cache"),
        };
        let dir = directory(&base.join("kitty-lsi"))?;
        let lock = match open_at(
            &dir,
            OsStr::new(".lock"),
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
        ) {
            Ok(file) => file,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                let info = secure_fs::metadata(&dir, OsStr::new(".lock"))?;
                secure_fs::image(&dir, OsStr::new(".lock"), &info)?
            }
            Err(e) => return Err(e),
        };
        let info = lock.metadata()?;
        if !info.is_file() || !private(&info) || info.nlink() != 1 {
            return Err(io::Error::other("unsafe cache lock"));
        }
        // SAFETY: flock operates on the live owned regular file; never waits.
        if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } < 0 {
            return Err(io::Error::last_os_error());
        }
        let mut items = Vec::new();
        let mut bytes = 0u64;
        let mut entry_count = 0usize;
        for (index, child) in fs::read_dir(secure_fs::anchored(&dir, OsStr::new(".")))?.enumerate()
        {
            if index >= 20_000 {
                return Err(io::Error::other("cache entry limit exceeded"));
            }
            let child = child?;
            let name = child.file_name();
            if !managed(&name) {
                continue;
            }
            let info = secure_fs::metadata(&dir, &name)?;
            // Even unreadable/corrupt candidates occupy space. Count them but
            // only delete entries independently recognized as our own format.
            bytes = bytes.saturating_add(info.len());
            entry_count += 1;
            if !info.is_file() || !private(&info) || info.nlink() != 1 {
                continue;
            }
            // Only evict files with our format marker; never unrelated user files.
            let mut file = secure_fs::image(&dir, &name, &info)?;
            let mut magic = [0; 8];
            if file.read_exact(&mut magic).is_err() || magic != *MAGIC {
                continue;
            }
            items.push(Item { name, info });
        }
        items.sort_by_key(|item| (item.info.mtime(), item.info.mtime_nsec()));
        let cache = Self {
            dir,
            _lock: lock,
            items: RefCell::new(items.into()),
            bytes: Cell::new(bytes),
            entry_count: Cell::new(entry_count),
        };
        cache.trim(0)?;
        Ok(cache)
    }
    fn unlink(&self, name: &OsStr) -> io::Result<()> {
        let name = c_name(name)?;
        // SAFETY: pinned cache directory and one NUL-terminated component; no recursion.
        if unsafe { libc::unlinkat(self.dir.as_raw_fd(), name.as_ptr(), 0) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
    fn trim(&self, incoming: u64) -> io::Result<()> {
        let mut items = self.items.borrow_mut();
        while self.bytes.get().saturating_add(incoming) > MAX_BYTES
            || self.entry_count.get() + usize::from(incoming > 0) > MAX_ENTRIES
        {
            let Some(item) = items.pop_front() else {
                return Err(io::Error::other("cache size limit exceeded"));
            };
            match secure_fs::metadata(&self.dir, &item.name) {
                Ok(info) => {
                    secure_fs::identity(&item.info, &info)?;
                    self.unlink(&item.name)?;
                }
                Err(e) if e.kind() == io::ErrorKind::NotFound => (),
                Err(e) => return Err(e),
            }
            self.bytes
                .set(self.bytes.get().saturating_sub(item.info.len()));
            self.entry_count
                .set(self.entry_count.get().saturating_sub(1));
        }
        Ok(())
    }
    pub fn get(
        &self,
        entry: &Entry,
        columns: usize,
        rows: usize,
    ) -> io::Result<(File, (u32, u32))> {
        let name = key(entry, columns, rows);
        let info = secure_fs::metadata(&self.dir, &name)?;
        if !private(&info) || info.nlink() != 1 || info.len() > MAX_ENTRY {
            return Err(io::Error::other("unsafe cache entry"));
        }
        let mut file = secure_fs::image(&self.dir, &name, &info)?;
        let mut header = [0; 40];
        file.read_exact(&mut header)?;
        let width = u32::from_le_bytes(header[8..12].try_into().unwrap());
        let height = u32::from_le_bytes(header[12..16].try_into().unwrap());
        let thumb_width = u32::from_be_bytes(header[32..36].try_into().unwrap());
        let thumb_height = u32::from_be_bytes(header[36..40].try_into().unwrap());
        let bound = (columns * 16).max(rows * 32) as u32;
        if header[..8] != *MAGIC
            || width == 0
            || height == 0
            || u64::from(width) * u64::from(height) > 40_000_000
            || &header[16..24] != b"\x89PNG\r\n\x1a\n"
            || header[24..28] != 13u32.to_be_bytes()
            || &header[28..32] != b"IHDR"
            || thumb_width == 0
            || thumb_height == 0
            || thumb_width > bound
            || thumb_height > bound
        {
            return Err(io::Error::other("invalid cache header"));
        }
        file.seek(SeekFrom::Start(16))?;
        Ok((file, (width, height)))
    }
    pub fn store(
        &self,
        entry: &Entry,
        columns: usize,
        rows: usize,
        preview: &Preview,
    ) -> io::Result<()> {
        let size = preview.png.len() as u64 + 16;
        if size > MAX_ENTRY {
            return Err(io::Error::other("thumbnail exceeds cache entry limit"));
        }
        let name = key(entry, columns, rows);
        match secure_fs::metadata(&self.dir, &name) {
            Ok(info) => {
                if !info.is_file() || !private(&info) || info.nlink() != 1 {
                    return Err(io::Error::other("unsafe cache destination"));
                }
                self.unlink(&name)?;
                self.bytes.set(self.bytes.get().saturating_sub(info.len()));
                self.entry_count
                    .set(self.entry_count.get().saturating_sub(1));
                let mut items = self.items.borrow_mut();
                if let Some(index) = items.iter().position(|item| item.name == name) {
                    items.remove(index);
                }
            }
            Err(e) if e.kind() == io::ErrorKind::NotFound => (),
            Err(e) => return Err(e),
        }
        self.trim(size)?;
        let mut random = [0; 16];
        getrandom::fill(&mut random).map_err(|e| io::Error::other(e.to_string()))?;
        let temp = OsString::from(format!(".tmp-{:032x}", u128::from_le_bytes(random)));
        let mut file = open_at(
            &self.dir,
            &temp,
            libc::O_WRONLY | libc::O_CREAT | libc::O_EXCL,
        )?;
        let written = (|| -> io::Result<()> {
            file.write_all(MAGIC)?;
            file.write_all(&preview.dimensions.0.to_le_bytes())?;
            file.write_all(&preview.dimensions.1.to_le_bytes())?;
            file.write_all(&preview.png)?;
            let from = c_name(&temp)?;
            let to = c_name(&name)?;
            // SAFETY: both names are single components under the same pinned directory.
            if unsafe {
                libc::renameat(
                    self.dir.as_raw_fd(),
                    from.as_ptr(),
                    self.dir.as_raw_fd(),
                    to.as_ptr(),
                )
            } < 0
            {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        })();
        if written.is_err() {
            let _ = self.unlink(&temp);
        }
        written?;
        self.items.borrow_mut().push_back(Item {
            name,
            info: file.metadata()?,
        });
        self.bytes.set(self.bytes.get() + size);
        self.entry_count.set(self.entry_count.get() + 1);
        Ok(())
    }
}
