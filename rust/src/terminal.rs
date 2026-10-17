use std::{
    env,
    io::{self, IsTerminal},
    os::fd::AsRawFd,
};
pub fn available() -> bool {
    io::stdout().is_terminal()
        && (env::var_os("KITTY_WINDOW_ID").is_some()
            || env::var("TERM").as_deref() == Ok("xterm-kitty"))
        && env::var_os("TMUX").is_none()
        && env::var_os("STY").is_none()
}
pub fn size() -> Option<(usize, usize)> {
    let mut size = libc::winsize {
        ws_row: 0,
        ws_col: 0,
        ws_xpixel: 0,
        ws_ypixel: 0,
    };
    // SAFETY: stdout is a live descriptor; TIOCGWINSZ writes exactly a winsize
    // into the valid, aligned stack allocation passed here, during this call.
    let result = unsafe { libc::ioctl(io::stdout().as_raw_fd(), libc::TIOCGWINSZ, &mut size) };
    (result == 0 && size.ws_col > 0 && size.ws_row > 0)
        .then_some((size.ws_col as usize, size.ws_row as usize))
}
