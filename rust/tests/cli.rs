//! Command-level regression tests requiring no Python test framework.
use std::os::unix::fs::{PermissionsExt, symlink};
use std::{fs, path::PathBuf, process::Command};
struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let mut random = [0; 8];
        getrandom::fill(&mut random).unwrap();
        let path =
            std::env::temp_dir().join(format!("lsi-test-{:016x}", u64::from_ne_bytes(random)));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
    fn run(&self, args: &[&str]) -> std::process::Output {
        Command::new(env!("CARGO_BIN_EXE_lsi"))
            .args(args)
            .current_dir(&self.0)
            .env("TZ", "UTC")
            .env("LC_ALL", "C")
            .output()
            .unwrap()
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}
#[test]
fn names_and_hidden_entries() {
    let f = Fixture::new();
    fs::write(f.0.join("photo.png"), b"not decoded in pipe").unwrap();
    fs::write(f.0.join(".hidden"), b"").unwrap();
    let output = f.run(&[]);
    assert!(output.status.success());
    assert_eq!(output.stdout, b"photo.png\n");
    let output = f.run(&["-a"]);
    assert_eq!(output.stdout, b".\n..\n.hidden\nphoto.png\n");
}
#[test]
fn readable_sizes_and_permissions() {
    let f = Fixture::new();
    let file = f.0.join("photo.png");
    fs::write(&file, vec![0; 1536]).unwrap();
    fs::set_permissions(file, fs::Permissions::from_mode(0o640)).unwrap();
    let output = f.run(&["-lh"]);
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(output.status.success());
    assert!(text.starts_with("-rw-r-----"));
    assert!(text.contains("1.5K"));
}
#[test]
fn recursive_links_are_not_followed() {
    let f = Fixture::new();
    fs::create_dir(f.0.join("nested")).unwrap();
    fs::write(f.0.join("nested/file"), b"").unwrap();
    symlink(".", f.0.join("loop")).unwrap();
    let output = f.run(&["-RF"]);
    let text = String::from_utf8(output.stdout).unwrap();
    assert!(output.status.success());
    assert_eq!(text.matches("file").count(), 1);
    assert!(text.contains("loop@"));
}
#[test]
fn invalid_inputs_are_errors_not_panics() {
    let f = Fixture::new();
    for args in [&["--width", "0"][..], &["--height", "17"], &["--unknown"]] {
        let output = f.run(args);
        assert_eq!(output.status.code(), Some(2));
        assert!(!String::from_utf8_lossy(&output.stderr).contains("panicked"));
    }
    assert_eq!(f.run(&["missing"]).status.code(), Some(1));
}

#[test]
fn step_options_validate_the_size_not_the_number_of_entries() {
    let f = Fixture::new();
    fs::write(f.0.join("one.txt"), b"one").unwrap();
    for args in [
        &["-ls"][..],
        &["-s"],
        &["--step=5"],
        &["-l", "--step=25"],
        &["-l", "--step=50"],
        &["-ls", "--step=25"],
    ] {
        let output = f.run(args);
        assert!(
            output.status.success(),
            "{args:?}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(String::from_utf8_lossy(&output.stdout).contains("one.txt"));
        assert!(!String::from_utf8_lossy(&output.stdout).contains("Press ENTER"));
    }
    for args in [
        &["-l", "--step"][..],
        &["-l", "--step="],
        &["-l", "--step=culo"],
        &["-l", "--step=1"],
        &["-l", "--step=4"],
        &["-l", "--step=51"],
        &["-l", "--step=999999999999999999999"],
        &["-l", "--step", "25"],
        &["-lstep=1"],
    ] {
        let output = f.run(args);
        assert_eq!(output.status.code(), Some(2), "{args:?}");
        assert!(!output.stderr.is_empty());
        assert!(!String::from_utf8_lossy(&output.stderr).contains("panicked"));
        assert!(output.stdout.is_empty());
    }
}
#[test]
fn filenames_cannot_send_terminal_commands() {
    let f = Fixture::new();
    fs::write(f.0.join("evil\x1b]52;c;secret\x07\n.png"), b"").unwrap();
    let output = f.run(&[]);
    assert!(!output.stdout.contains(&0x1b));
    assert!(!output.stdout.contains(&7));
    assert_eq!(output.stdout.iter().filter(|&&b| b == b'\n').count(), 1);
}
#[test]
fn executable_does_not_need_path_or_python_environment() {
    let f = Fixture::new();
    fs::write(f.0.join("photo.png"), b"").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_lsi"))
        .env_clear()
        .env("PATH", "/nonexistent")
        .current_dir(&f.0)
        .output()
        .unwrap();
    assert!(output.status.success());
    assert_eq!(output.stdout, b"photo.png\n");
}

#[test]
fn directories_first_is_the_default_in_grid_long_and_alias_modes() {
    let f = Fixture::new();
    for name in ["z-folder", "b-folder"] {
        fs::create_dir(f.0.join(name)).unwrap();
    }
    for name in ["a.png", "c.png"] {
        fs::write(f.0.join(name), b"plain output does not decode images").unwrap();
    }
    for flags in [&[][..], &["-lh"]] {
        let output = f.run(flags);
        assert!(output.status.success());
        let names: Vec<_> = String::from_utf8(output.stdout)
            .unwrap()
            .lines()
            .map(|line| line.split_whitespace().last().unwrap().to_owned())
            .collect();
        assert_eq!(names, ["b-folder", "z-folder", "a.png", "c.png"]);
    }
    let alias = f.0.join("lli");
    symlink(env!("CARGO_BIN_EXE_lsi"), &alias).unwrap();
    let output = Command::new(alias)
        .arg("-h")
        .current_dir(&f.0)
        .output()
        .unwrap();
    assert!(output.status.success());
    let names: Vec<_> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| {
            line.split(" -> ")
                .next()
                .unwrap()
                .split_whitespace()
                .last()
                .unwrap()
                .to_owned()
        })
        .collect();
    assert_eq!(names, ["b-folder", "z-folder", "a.png", "c.png", "lli"]);
    assert_eq!(
        f.run(&["--sort=name"]).stdout,
        b"a.png\nb-folder\nc.png\nlli\nz-folder\n"
    );
    assert_eq!(
        f.run(&["--sort=name", "--group-directories-first"]).stdout,
        b"b-folder\nz-folder\na.png\nc.png\nlli\n"
    );
}

#[test]
fn intermediate_symlink_is_not_traversed() {
    let f = Fixture::new();
    fs::create_dir(f.0.join("real")).unwrap();
    fs::write(f.0.join("real/secret.png"), b"secret").unwrap();
    symlink("real", f.0.join("redirect")).unwrap();
    let output = f.run(&["redirect/secret.png"]);
    assert!(!output.status.success(), "must reject symlink ancestors");
    assert!(!String::from_utf8_lossy(&output.stdout).contains("secret"));
}

#[test]
fn argument_diagnostics_cannot_inject_terminal_controls() {
    let f = Fixture::new();
    let output = f.run(&["--sort", "bad\x1b]52;c;secret\x07\nforged-error"]);
    assert_eq!(output.status.code(), Some(2));
    assert!(!output.stderr.contains(&0x1b));
    assert!(!output.stderr.contains(&7));
    let message = String::from_utf8_lossy(&output.stderr);
    assert!(!message.contains("\nforged-error"));
    assert!(message.contains("secret??forged-error"));
    for args in [
        &["--bad\x1b]52;c;secret\x07\nforged-error"][..],
        &["--width", "200\nforged-error\x1b[2J"],
        &["--step=25\nforged-error\x1b[2J"],
    ] {
        let output = f.run(args);
        let message = String::from_utf8_lossy(&output.stderr);
        assert_eq!(output.status.code(), Some(2));
        assert!(!output.stderr.contains(&0x1b));
        assert!(!output.stderr.contains(&7));
        assert!(!message.contains("\nforged-error"), "{message}");
    }
}

#[test]
fn geometry_errors_keep_readable_layout_and_reject_invalid_values() {
    let f = Fixture::new();
    for args in [
        &["--width", "200", "--height", "50"][..],
        &["--width", "-2", "--height", "-8"],
        &["--width=-2", "--height=-8"],
    ] {
        let output = f.run(args);
        let message = String::from_utf8_lossy(&output.stderr);
        assert_eq!(output.status.code(), Some(2));
        assert!(!message.contains("??"), "{message}");
        assert!(message.contains("\n\n"), "{message}");
        assert!(message.contains("For more information, try '--help'."));
        assert!(!output.stderr.contains(&0x1b));
    }
}

#[test]
fn excessive_operands_fail_without_successful_truncation() {
    let f = Fixture::new();
    fs::write(f.0.join("x"), b"").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_lsi"))
        .args(std::iter::repeat_n("x", 20_001))
        .current_dir(&f.0)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("operand limit"));
    assert!(output.stdout.is_empty());
}

#[test]
fn thousands_of_explicit_operands_share_parent_descriptors() {
    let f = Fixture::new();
    fs::write(f.0.join("x"), b"").unwrap();
    let output = Command::new(env!("CARGO_BIN_EXE_lsi"))
        .args(std::iter::repeat_n("x", 2000))
        .current_dir(&f.0)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout.iter().filter(|&&b| b == b'\n').count(), 2000);
}

#[test]
fn excessive_recursion_depth_is_an_explicit_error() {
    let f = Fixture::new();
    let mut path = f.0.clone();
    for _ in 0..66 {
        path.push("nested");
        fs::create_dir(&path).unwrap();
    }
    let output = f.run(&["-R"]);
    assert_eq!(output.status.code(), Some(1));
    assert!(String::from_utf8_lossy(&output.stderr).contains("depth limit"));
}
