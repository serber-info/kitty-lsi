//! Descriptor-anchored Linux traversal. Symlink ancestors are never followed.
use std::{
    ffi::{CString, OsStr},
    fs::{self, File, Metadata, OpenOptions},
    io,
    os::{
        fd::{AsRawFd, FromRawFd},
        unix::{
            ffi::OsStrExt,
            fs::{MetadataExt, OpenOptionsExt},
        },
    },
    path::{Component, Path, PathBuf},
    sync::Arc,
};
fn open_at(parent: &File, name: &OsStr, flags: i32) -> io::Result<File> {
    let name = CString::new(name.as_bytes()).map_err(|_| io::Error::other("NUL in path"))?;
    // SAFETY: parent is live, name is NUL-terminated; no create flag or mode.
    let fd = unsafe {
        libc::openat(
            parent.as_raw_fd(),
            name.as_ptr(),
            flags | libc::O_CLOEXEC | libc::O_NOFOLLOW,
        )
    };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: openat returned a new owned descriptor.
    Ok(unsafe { File::from_raw_fd(fd) })
}
pub fn parent(path: &Path) -> io::Result<(Arc<File>, std::ffi::OsString)> {
    let mut dir = File::open(if path.is_absolute() { "/" } else { "." })?;
    let parts: Vec<_> = path
        .components()
        .filter(|c| !matches!(c, Component::RootDir))
        .collect();
    for part in parts.iter().take(parts.len().saturating_sub(1)) {
        dir = open_at(&dir, part.as_os_str(), libc::O_RDONLY | libc::O_DIRECTORY)?;
    }
    let last = parts
        .last()
        .map_or(OsStr::new("."), |c| c.as_os_str())
        .to_os_string();
    Ok((Arc::new(dir), last))
}
pub fn anchored(parent: &File, name: &OsStr) -> PathBuf {
    PathBuf::from(format!("/proc/self/fd/{}", parent.as_raw_fd())).join(name)
}
pub fn directory(parent: &File, name: &OsStr, expected: &Metadata) -> io::Result<Arc<File>> {
    let file = open_at(parent, name, libc::O_RDONLY | libc::O_DIRECTORY)?;
    identity(expected, &file.metadata()?)?;
    Ok(Arc::new(file))
}
pub fn image(parent: &File, name: &OsStr, expected: &Metadata) -> io::Result<File> {
    // O_PATH does not invoke device open handlers or block on a FIFO. Pin and
    // verify the inode before requesting any readable descriptor.
    let pinned = open_at(parent, name, libc::O_PATH)?;
    let info = pinned.metadata()?;
    identity(expected, &info)?;
    if !info.is_file() {
        return Err(io::Error::other("not a regular image"));
    }
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NONBLOCK)
        .open(format!("/proc/self/fd/{}", pinned.as_raw_fd()))?;
    identity(expected, &file.metadata()?)?;

    Ok(file)
}
pub fn identity(a: &Metadata, b: &Metadata) -> io::Result<()> {
    if a.dev() == b.dev()
        && a.ino() == b.ino()
        && a.mode() == b.mode()
        && a.size() == b.size()
        && a.mtime() == b.mtime()
        && a.mtime_nsec() == b.mtime_nsec()
        && a.ctime() == b.ctime()
        && a.ctime_nsec() == b.ctime_nsec()
    {
        Ok(())
    } else {
        Err(io::Error::other("file changed during listing or read"))
    }
}
pub fn metadata(parent: &File, name: &OsStr) -> io::Result<Metadata> {
    fs::symlink_metadata(anchored(parent, name))
}
