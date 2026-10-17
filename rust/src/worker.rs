//! Execute this same binary as a resource-limited decoder. No external tools.
use crate::{
    preview::{self, Preview},
    scan::Entry,
    secure_fs,
};
use std::{
    fs::File,
    io::{self, Read, Write},
    os::fd::{AsRawFd, FromRawFd},
    process::{Command, Stdio},
    time::{Duration, Instant},
};
const OUTPUT_LIMIT: usize = 8 * 1024 * 1024;
#[cfg(target_env = "musl")]
type Resource = libc::c_int;
#[cfg(not(target_env = "musl"))]
type Resource = libc::c_uint;
pub fn limit(resource: Resource, value: u64) -> io::Result<()> {
    let mut old = libc::rlimit {
        rlim_cur: 0,
        rlim_max: 0,
    };
    // SAFETY: valid writable rlimit, kernel copies only this structure.
    if unsafe { libc::getrlimit(resource, &mut old) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let value = value.min(old.rlim_cur).min(old.rlim_max);
    let limits = libc::rlimit {
        rlim_cur: value,
        rlim_max: value,
    };
    // SAFETY: valid readable rlimit; only reduces the current process limits.
    if unsafe { libc::setrlimit(resource, &limits) } != 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}
fn restrict(parent: libc::pid_t) -> io::Result<()> {
    // SAFETY: PR_SET_PDEATHSIG takes a signal number; getppid has no arguments.
    // Validate the expected parent after arming the signal to close the spawn race.
    unsafe {
        if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) != 0 {
            return Err(io::Error::last_os_error());
        }
        if libc::getppid() != parent {
            return Err(io::Error::other("decoder parent exited"));
        }
    }
    limit(libc::RLIMIT_AS, 768 * 1024 * 1024)?;
    limit(libc::RLIMIT_CPU, 3)?;
    limit(libc::RLIMIT_CORE, 0)?;
    limit(libc::RLIMIT_NOFILE, 32)?;
    // One allowed CPU makes avif-decode choose one thread, not up to 32.
    // SAFETY: zero is valid cpu_set_t; both calls receive its actual size.
    unsafe {
        let mut allowed: libc::cpu_set_t = std::mem::zeroed();
        if libc::sched_getaffinity(0, std::mem::size_of_val(&allowed), &mut allowed) != 0 {
            return Err(io::Error::last_os_error());
        }
        let cpu = (0..libc::CPU_SETSIZE as usize)
            .find(|&c| libc::CPU_ISSET(c, &allowed))
            .ok_or_else(|| io::Error::other("no CPU available"))?;
        libc::CPU_ZERO(&mut allowed);
        libc::CPU_SET(cpu, &mut allowed);
        if libc::sched_setaffinity(0, std::mem::size_of_val(&allowed), &allowed) != 0 {
            return Err(io::Error::last_os_error());
        }
    }
    lockdown()
}
#[cfg(target_arch = "x86_64")]
fn lockdown() -> io::Result<()> {
    // Linux x86-64 allowlist. Unknown syscalls fail closed with EPERM. The
    // architecture check rejects x32/compat ABIs; non-thread clone is denied.
    let mut filter = vec![
        libc::sock_filter {
            code: 0x20,
            jt: 0,
            jf: 0,
            k: 4,
        },
        libc::sock_filter {
            code: 0x15,
            jt: 1,
            jf: 0,
            k: 0xc000003e,
        },
        libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x80000000,
        },
        libc::sock_filter {
            code: 0x20,
            jt: 0,
            jf: 0,
            k: 0,
        },
        libc::sock_filter {
            code: 0x35,
            jt: 0,
            jf: 1,
            k: 0x40000000,
        },
        libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x80000000,
        },
        libc::sock_filter {
            code: 0x15,
            jt: 0,
            jf: 1,
            k: libc::SYS_clone3 as u32,
        },
        libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x50000 | libc::ENOSYS as u32,
        },
        libc::sock_filter {
            code: 0x15,
            jt: 0,
            jf: 4,
            k: libc::SYS_clone as u32,
        },
        libc::sock_filter {
            code: 0x20,
            jt: 0,
            jf: 0,
            k: 16,
        },
        libc::sock_filter {
            code: 0x45,
            jt: 1,
            jf: 0,
            k: libc::CLONE_THREAD as u32,
        },
        libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x50000 | libc::EPERM as u32,
        },
        libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x7fff0000,
        },
    ];
    for syscall in [
        libc::SYS_read,
        libc::SYS_write,
        libc::SYS_readv,
        libc::SYS_writev,
        libc::SYS_close,
        libc::SYS_fstat,
        libc::SYS_newfstatat,
        libc::SYS_lseek,
        libc::SYS_pread64,
        libc::SYS_fcntl,
        libc::SYS_dup,
        libc::SYS_brk,
        libc::SYS_mmap,
        libc::SYS_munmap,
        libc::SYS_mremap,
        libc::SYS_mprotect,
        libc::SYS_madvise,
        libc::SYS_futex,
        libc::SYS_rt_sigaction,
        libc::SYS_rt_sigprocmask,
        libc::SYS_rt_sigreturn,
        libc::SYS_sigaltstack,
        libc::SYS_getpid,
        libc::SYS_gettid,
        libc::SYS_set_tid_address,
        libc::SYS_set_robust_list,
        libc::SYS_rseq,
        libc::SYS_clock_gettime,
        libc::SYS_gettimeofday,
        libc::SYS_nanosleep,
        libc::SYS_clock_nanosleep,
        libc::SYS_sched_yield,
        libc::SYS_sched_getaffinity,
        libc::SYS_getrandom,
        libc::SYS_exit,
        libc::SYS_exit_group,
    ] {
        filter.push(libc::sock_filter {
            code: 0x15,
            jt: 0,
            jf: 1,
            k: syscall as u32,
        });
        filter.push(libc::sock_filter {
            code: 0x06,
            jt: 0,
            jf: 0,
            k: 0x7fff0000,
        });
    }
    filter.push(libc::sock_filter {
        code: 0x06,
        jt: 0,
        jf: 0,
        k: 0x50000 | libc::EPERM as u32,
    });
    let program = libc::sock_fprog {
        len: filter.len() as u16,
        filter: filter.as_mut_ptr(),
    };
    // SAFETY: prctl arguments follow PR_SET_NO_NEW_PRIVS/SECCOMP ABI; filter
    // and program live throughout the call and the kernel copies them.
    unsafe {
        if libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0
            || libc::prctl(libc::PR_SET_SECCOMP, 2, &program) != 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}
#[cfg(not(target_arch = "x86_64"))]
fn lockdown() -> io::Result<()> {
    Err(io::Error::other(
        "decoder sandbox currently supports x86-64 only",
    ))
}
pub fn entry() -> bool {
    let args: Vec<_> = std::env::args_os().collect();
    if args.get(1).is_none_or(|s| s != "--internal-preview-worker") {
        return false;
    }
    let result = (|| -> Result<(), String> {
        if args.len() != 5 {
            return Err("invalid worker arguments".into());
        }
        let width = args[2]
            .to_str()
            .and_then(|s| s.parse::<usize>().ok())
            .filter(|&n| (4..=60).contains(&n))
            .ok_or("invalid width")?;
        let height = args[3]
            .to_str()
            .and_then(|s| s.parse::<usize>().ok())
            .filter(|&n| (2..=16).contains(&n))
            .ok_or("invalid height")?;
        let parent = args[4]
            .to_str()
            .and_then(|s| s.parse::<libc::pid_t>().ok())
            .filter(|&pid| pid > 0)
            .ok_or("invalid worker parent")?;
        restrict(parent).map_err(|e| e.to_string())?;
        // SAFETY: dup returns a separately owned descriptor for stdin.
        let fd = unsafe { libc::dup(0) };
        if fd < 0 {
            return Err(io::Error::last_os_error().to_string());
        }
        // SAFETY: fd is a fresh successful dup, owned only here.
        let input = unsafe { File::from_raw_fd(fd) };
        let p = preview::load(input, width, height)?;
        let mut out = io::stdout().lock();
        out.write_all(&p.dimensions.0.to_le_bytes())
            .and_then(|_| out.write_all(&p.dimensions.1.to_le_bytes()))
            .and_then(|_| out.write_all(&p.png))
            .map_err(|e| e.to_string())
    })();
    if let Err(e) = result {
        let message = crate::text::safe(&e);
        let _ = io::stdout()
            .write_all(format!("ERR!{}", crate::text::truncate(&message, 1024)).as_bytes());
        std::process::exit(1);
    }
    true
}
pub fn load(entry: &Entry, columns: usize, rows: usize) -> Result<Preview, String> {
    let input =
        secure_fs::image(&entry.parent, &entry.leaf, &entry.info).map_err(|e| e.to_string())?;
    if input.metadata().map_err(|e| e.to_string())?.len() > 64 * 1024 * 1024 {
        return Err("file larger than 64 MiB".into());
    }
    let mut child = Command::new("/proc/self/exe")
        .args([
            "--internal-preview-worker",
            &columns.to_string(),
            &rows.to_string(),
            &std::process::id().to_string(),
        ])
        .env_clear()
        .stdin(Stdio::from(input))
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| e.to_string())?;
    let result = (|| -> Result<Preview, String> {
        let mut output = child.stdout.take().ok_or("missing worker pipe")?;
        // SAFETY: fcntl changes only flags on this live owned pipe descriptor.
        if unsafe { libc::fcntl(output.as_raw_fd(), libc::F_SETFL, libc::O_NONBLOCK) } < 0 {
            return Err(io::Error::last_os_error().to_string());
        }
        let start = Instant::now();
        let mut bytes = Vec::new();
        let mut buf = [0; 16384];
        loop {
            match output.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    if bytes.len() + n > OUTPUT_LIMIT {
                        return Err("decoder output limit exceeded".into());
                    }
                    bytes.extend_from_slice(&buf[..n]);
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => {
                    std::thread::sleep(Duration::from_millis(2))
                }
                Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
                Err(e) => return Err(e.to_string()),
            }
            if start.elapsed() > Duration::from_secs(5) {
                return Err("decoder exceeded 5 second deadline".into());
            }
        }
        // Do not block indefinitely if a compromised worker closes its output.
        let status = loop {
            if let Some(s) = child.try_wait().map_err(|e| e.to_string())? {
                break s;
            }
            if start.elapsed() > Duration::from_secs(5) {
                return Err("decoder exceeded 5 second deadline".into());
            }
            std::thread::sleep(Duration::from_millis(2));
        };
        if bytes.starts_with(b"ERR!") {
            return Err(crate::text::safe(&String::from_utf8_lossy(&bytes[4..])));
        }
        if !status.success() || bytes.len() < 16 || !bytes[8..].starts_with(b"\x89PNG\r\n\x1a\n") {
            return Err("image rejected or decoder resource limit exceeded".into());
        }
        let width = u32::from_le_bytes(bytes[..4].try_into().map_err(|_| "bad worker dimensions")?);
        let height = u32::from_le_bytes(
            bytes[4..8]
                .try_into()
                .map_err(|_| "bad worker dimensions")?,
        );
        if u64::from(width) * u64::from(height) > 40_000_000 {
            return Err("invalid worker dimensions".into());
        }
        Ok(Preview {
            png: bytes.split_off(8),
            dimensions: (width, height),
        })
    })();
    // Reap on every error, including timeout and output overflow.
    if result.is_err() {
        let _ = child.kill();
    }
    let _ = child.wait();
    result
}
