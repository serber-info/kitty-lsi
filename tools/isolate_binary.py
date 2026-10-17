#!/usr/bin/python3
import os
import pathlib
import resource
import shutil
import sys

binary = str(
    pathlib.Path(
        os.environ.get(
            "LSI_REAL_BINARY",
            pathlib.Path(__file__).resolve().parents[1]
            / "rust/target/x86_64-unknown-linux-musl/release/lsi",
        )
    ).resolve(strict=True)
)
cwd = os.getcwd()
args = [a.replace(cwd, "/images") if a.startswith(cwd + "/") else a for a in sys.argv[1:]]
count = 0
for p in pathlib.Path("/proc").glob("[0-9]*/status"):
    try:
        s = p.read_text()
        if int(s.split("Uid:")[1].split()[0]) == os.getuid():
            count += int(s.split("Threads:")[1].split()[0])
    except (OSError, ValueError, IndexError):
        pass
for r, v in [
    (resource.RLIMIT_AS, 1280 * 1024**2),
    (resource.RLIMIT_CPU, 10),
    (resource.RLIMIT_NPROC, count + 48),
    (resource.RLIMIT_CORE, 0),
    (resource.RLIMIT_NOFILE, 128),
]:
    resource.setrlimit(r, (v, v))
bwrap = shutil.which("bwrap")
if not bwrap:
    raise SystemExit("bwrap required; refusing unsandboxed execution")
cmd = [
    bwrap,
    "--unshare-all",
    "--die-with-parent",
    "--new-session",
    "--cap-drop",
    "ALL",
    "--ro-bind",
    binary,
    "/lsi",
    "--symlink",
    "/lsi",
    "/lli",
    "--ro-bind",
    cwd,
    "/images",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "--size",
    "16777216",
    "--tmpfs",
    "/tmp",
    "--dir",
    "/home",
    "--dir",
    "/home/test",
    "--clearenv",
    "--setenv",
    "HOME",
    "/home/test",
    "--setenv",
    "TERM",
    "xterm-kitty",
    "--setenv",
    "PATH",
    "/no-programs",
    "--setenv",
    "TZ",
    "UTC",
    "--chdir",
    "/images",
    "/lli" if pathlib.Path(sys.argv[0]).name == "lli" else "/lsi",
    *args,
]
os.execv(cmd[0], cmd)
