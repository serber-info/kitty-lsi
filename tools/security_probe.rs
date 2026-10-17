extern crate libc;
use std::{
    fs,
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc,
    },
    time::Duration,
};
fn main() {
    let args: Vec<_> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("supervise") {
        let child = std::process::Command::new(&args[2])
            .args(&args[3..])
            .spawn()
            .unwrap();
        let mut status = 0;
        let mut usage: libc::rusage = unsafe { std::mem::zeroed() };
        let waited = unsafe { libc::wait4(child.id() as i32, &mut status, 0, &mut usage) };
        assert!(waited > 0);
        let cpu = usage.ru_utime.tv_sec as f64
            + usage.ru_utime.tv_usec as f64 / 1e6
            + usage.ru_stime.tv_sec as f64
            + usage.ru_stime.tv_usec as f64 / 1e6;
        eprintln!(
            "METRIC {{\"cpu_s\":{},\"maxrss_kib\":{}}}",
            cpu, usage.ru_maxrss
        );
        std::process::exit(if libc::WIFSIGNALED(status) {
            128 + libc::WTERMSIG(status)
        } else {
            libc::WEXITSTATUS(status)
        });
    }

    if args.get(1).map(String::as_str) == Some("closed-stdout") {
        let mut child = std::process::Command::new("/lsi")
            .args(["--no-images", "."])
            .stdout(std::process::Stdio::piped())
            .spawn()
            .unwrap();
        drop(child.stdout.take());
        assert!(child.wait().unwrap().success());
        println!("PASS closed stdout without panic");
        return;
    }

    if args.get(1).map(String::as_str) == Some("race") {
        use std::os::unix::fs::symlink;
        fs::create_dir_all("/images/race/slot").unwrap();
        fs::create_dir_all("/images/outside").unwrap();
        fs::write("/images/outside/SHOULD_NOT_APPEAR", b"test").unwrap();
        let stop = Arc::new(AtomicBool::new(false));
        let flag = stop.clone();
        let changer = std::thread::spawn(move || {
            while !flag.load(Ordering::Relaxed) {
                if fs::rename("/images/race/slot", "/images/race/held").is_ok() {
                    let _ = symlink("../outside", "/images/race/slot");
                    std::thread::yield_now();
                    let _ = fs::remove_file("/images/race/slot");
                    let _ = fs::rename("/images/race/held", "/images/race/slot");
                }
            }
        });
        let mut leaked = 0;
        for _ in 0..500 {
            let out = std::process::Command::new("/lsi")
                .args(["-R", "--no-images", "/images/race"])
                .output()
                .unwrap();
            if String::from_utf8_lossy(&out.stdout).contains("SHOULD_NOT_APPEAR") {
                leaked += 1;
            }
        }
        stop.store(true, Ordering::Relaxed);
        changer.join().unwrap();
        println!("race iterations=500 leaks={}", leaked);
        assert_eq!(leaked, 0);
        return;
    }
    if args.get(1).map(String::as_str) == Some("cpu") {
        loop {
            std::hint::black_box(17u64.wrapping_mul(37));
        }
    }
    if args.get(1).map(String::as_str) == Some("wall") {
        std::thread::sleep(Duration::from_secs(60));
        return;
    }
    println!(
        "net={}",
        fs::read_link("/proc/self/ns/net").unwrap().display()
    );
    println!(
        "pid={}",
        fs::read_link("/proc/self/ns/pid").unwrap().display()
    );
    println!(
        "root={:?}",
        fs::read_dir("/")
            .unwrap()
            .map(|e| e.unwrap().file_name())
            .collect::<Vec<_>>()
    );
    assert_eq!(fs::read_dir("/home").unwrap().count(), 1);
    assert!(!std::path::Path::new("/etc/passwd").exists());
    assert!(!std::path::Path::new("/usr").exists());
    assert_eq!(std::env::var("HOME").unwrap(), "/home/test");
    assert!(fs::read_dir("/home/test").unwrap().next().is_none());
    assert!(fs::write("/lsi", b"x").is_err());
    assert!(fs::write("/images/probe-write", b"x").is_err());
    println!(
        "limits={}",
        fs::read_to_string("/proc/self/limits").unwrap()
    );
    println!(
        "status={}",
        fs::read_to_string("/proc/self/status").unwrap()
    );
    let routes = fs::read_to_string("/proc/net/route").unwrap();
    assert!(routes.lines().count() <= 1);
    assert!(std::net::TcpStream::connect_timeout(
        &"1.1.1.1:443".parse().unwrap(),
        Duration::from_millis(100)
    )
    .is_err());
    let mut large: Vec<u8> = Vec::new();
    assert!(large.try_reserve(2 * 1024 * 1024 * 1024).is_err());
    println!("memory_limit=effective");
    let stop = Arc::new(AtomicBool::new(false));
    let mut threads = Vec::new();
    let mut blocked = false;
    for _ in 0..128 {
        let s = stop.clone();
        match std::thread::Builder::new()
            .stack_size(65536)
            .spawn(move || {
                while !s.load(Ordering::Relaxed) {
                    std::thread::sleep(Duration::from_millis(10));
                }
            }) {
            Ok(t) => threads.push(t),
            Err(e) => {
                println!("thread_limit={} error={}", threads.len(), e);
                blocked = true;
                break;
            }
        }
    }
    stop.store(true, Ordering::Relaxed);
    for t in threads {
        t.join().unwrap();
    }
    assert!(blocked, "process/thread limit not demonstrated");
    println!("PASS isolation and limits");
}
