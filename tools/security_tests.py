import argparse
import fcntl
import json
import os
import pathlib
import pty
import resource
import selectors
import shutil
import signal
import struct
import subprocess
import tempfile
import termios
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(
    description="Isolated CLI security regression tests; never remove results automatically"
)
parser.add_argument("--binary", type=pathlib.Path, required=True)
parser.add_argument("--out", type=pathlib.Path)
opts = parser.parse_args()
R = opts.out if opts.out else pathlib.Path(tempfile.mkdtemp(prefix="lsi-security-"))
if opts.out:
    R.mkdir(parents=True, exist_ok=False)
os.chmod(R, 0o700)
B = opts.binary.resolve(strict=True)
BWRAP = shutil.which("bwrap")
if not BWRAP:
    raise SystemExit("bwrap is required; adversarial tests not executed")
print("Results retained:", R, flush=True)
# Trusted probe is compiled locally, never downloaded/executed as a script.
libc = list((ROOT / "rust/target/x86_64-unknown-linux-musl/release/deps").glob("liblibc-*.rlib"))
if not libc:
    raise SystemExit("Build the musl release before testing")
subprocess.run(
    [
        "rustc",
        str(ROOT / "tools/security_probe.rs"),
        "-o",
        str(R / "probe"),
        "--target",
        "x86_64-unknown-linux-musl",
        "-C",
        "linker=rust-lld",
        "-C",
        "target-feature=+crt-static",
        "-O",
        "--extern",
        "libc=" + str(libc[0]),
    ],
    check=True,
)
D = R / "fixtures"
D.mkdir(exist_ok=True)
RESULTS = []


def nproc():
    n = 0
    for p in pathlib.Path("/proc").glob("[0-9]*/status"):
        try:
            s = p.read_text()
            if int(s.split("Uid:")[1].split()[0]) == os.getuid():
                n += int(s.split("Threads:")[1].split()[0])
        except (OSError, ValueError, IndexError):
            pass
    return n + 48


N = nproc()


def command(args, data=D, rw=False):
    return [
        BWRAP,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--cap-drop",
        "ALL",
        "--ro-bind",
        str(B),
        "/lsi",
        "--symlink",
        "/lsi",
        "/lli",
        "--ro-bind",
        str(R / "probe"),
        "/probe",
        "--bind" if rw else "--ro-bind",
        str(data),
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
        "PATH",
        "/no-programs",
        "--setenv",
        "TERM",
        "xterm-kitty",
        "--setenv",
        "TZ",
        "UTC",
        "--chdir",
        "/images",
        "/probe",
        "supervise",
        *args,
    ]


def run(name, args, tty=False, wall=12, cpu=8, aslimit=1280 * 1024**2, data=D, rw=False):
    def limits():
        os.setsid()
        for r, v in [
            (resource.RLIMIT_AS, aslimit),
            (resource.RLIMIT_CPU, cpu),
            (resource.RLIMIT_NPROC, N),
            (resource.RLIMIT_NOFILE, 128),
            (resource.RLIMIT_FSIZE, 16 * 1024**2),
            (resource.RLIMIT_CORE, 0),
        ]:
            resource.setrlimit(r, (v, v))

    master = slave = None
    if tty:
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 800, 480))
    start = time.monotonic()
    p = subprocess.Popen(
        command(args, data, rw),
        stdin=subprocess.DEVNULL,
        stdout=slave if tty else subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=limits,
    )
    if slave is not None:
        os.close(slave)
    sel = selectors.DefaultSelector()
    outs = {}
    streams = {}
    for fd, label in [
        (master if tty else p.stdout.fileno(), "stdout"),
        (p.stderr.fileno(), "stderr"),
    ]:
        os.set_blocking(fd, False)
        sel.register(fd, selectors.EVENT_READ, label)
        outs[label] = bytearray()
        streams[fd] = label
    killed = None
    while sel.get_map():
        if time.monotonic() - start > wall and killed is None:
            killed = "wall"
            os.killpg(p.pid, signal.SIGKILL)
        for key, _ in sel.select(0.05):
            try:
                chunk = os.read(key.fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                sel.unregister(key.fd)
                continue
            outs[key.data] += chunk
            if sum(map(len, outs.values())) > 8 * 1024**2 and killed is None:
                killed = "output"
                os.killpg(p.pid, signal.SIGKILL)
    _, status, usage = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    if master is not None:
        os.close(master)
    row = {
        "name": name,
        "argv": args if len(args) < 50 else [args[0], f"<{len(args) - 1} operands>"],
        "exit": p.returncode,
        "wall_s": round(time.monotonic() - start, 4),
        "cpu_s": round(usage.ru_utime + usage.ru_stime, 4),
        "maxrss_kib": usage.ru_maxrss,
        "killed": killed,
        "stdout_bytes": len(outs["stdout"]),
        "stderr": outs["stderr"].decode(errors="replace"),
        "limits": {
            "address_space_bytes": aslimit,
            "cpu_seconds": cpu,
            "nproc": N,
            "wall_seconds": wall,
        },
    }
    for label, value in outs.items():
        (R / (name + "." + label)).write_bytes(value)
    import re

    metric = re.search(rb"METRIC (\{[^\n]+\})", outs["stderr"])
    if metric:
        row.update(json.loads(metric[1]))
        row["metric_scope"] = (
            "direct supervisor wait4; maximum RSS is not concurrent process-tree sum"
        )
    RESULTS.append(row)
    (R / "results.json").write_text(json.dumps(RESULTS, indent=2))
    print(json.dumps(row), flush=True)
    return row, bytes(outs["stdout"])


def main():
    probe, out = run("isolation", ["/probe"])
    assert probe["exit"] == 0 and b"PASS isolation" in out
    net = os.readlink("/proc/self/ns/net")
    pid = os.readlink("/proc/self/ns/pid")
    assert ("net=" + net).encode() not in out and ("pid=" + pid).encode() not in out
    assert b"CapEff:\t0000000000000000" in out
    cpu, _ = run("cpu-limit", ["/probe", "cpu"], cpu=1, wall=5)
    assert cpu["exit"] in [-9, 137] and cpu["cpu_s"] >= 0.8
    wall, _ = run("wall-limit", ["/probe", "wall"], wall=1)
    assert wall["killed"] == "wall"
    (R / "ISOLATION-PASSED").write_text(
        "Filesystem/HOME/network namespaces, zero effective capabilities, AS/NPROC/CPU/wall limits verified.\n"
    )
    from PIL import Image

    formats = [
        ("png", "PNG"),
        ("jpg", "JPEG"),
        ("gif", "GIF"),
        ("webp", "WEBP"),
        ("bmp", "BMP"),
        ("tiff", "TIFF"),
        ("ico", "ICO"),
        ("avif", "AVIF"),
    ]
    for ext, fmt in formats:
        Image.new("RGB", (64, 64), "red").save(D / ("valid." + ext), format=fmt)
    (D / "z-folder").mkdir(exist_ok=True)
    (D / "a-folder").mkdir(exist_ok=True)
    for ext, _fmt in formats:
        row, out = run("valid-" + ext, ["/lsi", "-1", "valid." + ext], tty=True)
        assert row["exit"] == 0 and b"a=T,f=100" in out
    row, out = run("valid-lli", ["/lli", "-lh"])
    assert row["exit"] == 0 and out.index(b"a-folder") < out.index(b"valid")
    row, out = run("valid-grid", ["/lsi"], tty=True)
    assert row["exit"] == 0 and b"a=T,f=100" in out
    # No malformed file is created or run until the isolation marker and benign tests succeeded.
    import random
    import zlib

    def chunk(k, v):
        return struct.pack(">I", len(v)) + k + v + struct.pack(">I", zlib.crc32(k + v))

    (D / "empty.png").write_bytes(b"")
    (D / "truncated.jpg").write_bytes((D / "valid.jpg").read_bytes()[:30])
    (D / "wrong.jpg").write_bytes((D / "valid.png").read_bytes())
    (D / "huge.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8000, 6000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", b"")
        + chunk(b"IEND", b"")
    )
    (D / "extreme.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 0xFFFFFFFF, 0xFFFFFFFF, 16, 6, 0, 0, 0))
        + chunk(b"IDAT", b"")
        + chunk(b"IEND", b"")
    )
    (D / "metadata.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"iCCP", b"x\0\0" + zlib.compress(b"x" * 1000000))
        + chunk(b"IDAT", zlib.compress(b"\0\xff\0\0"))
        + chunk(b"IEND", b"")
    )
    for name in [
        "empty.png",
        "truncated.jpg",
        "huge.png",
        "extreme.png",
        "metadata.png",
        "wrong.jpg",
    ]:
        row, out = run("adversarial-" + name, ["/lsi", "-1", name, "valid.png"], tty=True)
        assert row["exit"] in [0, 1] and b"valid.png" in out and b"a=T,f=100" in out
    for ext, _ in formats:
        raw = (D / ("valid." + ext)).read_bytes()
        rng = random.Random(1776)
        for index in range(6):
            damaged = bytearray(raw if index >= 3 else raw[: max(1, len(raw) * (index + 1) // 4)])
            if index >= 3:
                for _ in range(min(12, len(damaged))):
                    damaged[rng.randrange(len(damaged))] ^= rng.randrange(1, 256)
            name = f"mutated-{ext}-{index}.{ext}"
            (D / name).write_bytes(damaged)
            row, out = run(f"mutation-{ext}-{index}", ["/lsi", "-1", name, "valid.png"], tty=True)
            assert row["exit"] in [0, 1] and b"valid.png" in out
    many = R / "many"
    many.mkdir(exist_ok=True)
    for i in range(21000):
        (many / f"{i:05d}.png").touch(exist_ok=True)
    row, out = run("entry-limit", ["/lsi"], data=many)
    assert row["exit"] == 1 and "entry limit" in row["stderr"]
    ten = R / "ten-thousand"
    ten.mkdir()
    for i in range(10000):
        (ten / f"{i:05d}.png").touch()
    row, out = run("entry-10000", ["/lsi"], data=ten)
    assert row["exit"] == 0 and len(out.splitlines()) == 10000
    row, out = run("closed-stdout", ["/probe", "closed-stdout"], data=ten)
    assert row["exit"] == 0 and b"PASS closed stdout" in out
    (D / "redirect").symlink_to("z-folder", target_is_directory=True)
    row, out = run("symlink-ancestor", ["/lsi", "redirect/secret.png"])
    assert row["exit"] == 1
    for name in ["evil\x1b]52;c;secret\x07.png", "bidi\u202e.png", "日本語-ñ.png"]:
        (D / name).write_bytes((D / "valid.png").read_bytes())
    row, out = run("control-names", ["/lsi", "--no-images"])
    assert row["exit"] == 0 and b"\x1b" not in out and b"\x07" not in out
    row, out = run("directory-replacement-race", ["/probe", "race"], rw=True, wall=30, cpu=15)
    assert row["exit"] == 0 and b"leaks=0" in out
    # A valid high-expansion image under a deliberately reduced inherited limit
    # must fail only its worker, then still render the next small valid image.
    scanline = b"\0" + b"\0" * (4000 * 3)
    compressor = zlib.compressobj()
    compressed = b"".join(compressor.compress(scanline) for _ in range(3000)) + compressor.flush()
    (D / "memory-budget.png").write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 4000, 3000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", compressed)
        + chunk(b"IEND", b"")
    )
    row, out = run(
        "worker-memory-recovery",
        ["/lsi", "-1", "memory-budget.png", "valid.png"],
        tty=True,
        aslimit=32 * 1024**2,
    )
    assert row["exit"] == 1 and b"valid.png" in out and b"a=T,f=100" in out
    denied = D / "denied"
    denied.mkdir()
    denied.chmod(0)
    try:
        row, out = run("inaccessible-directory", ["/lsi", "denied"])
        assert row["exit"] == 1 and "Permission denied" in row["stderr"]
    finally:
        denied.chmod(0o700)
    os.mkfifo(D / "pipe.png")
    row, out = run("fifo-and-links", ["/lsi", "pipe.png", "redirect"])
    assert row["exit"] == 0 and b"pipe.png" in out
    (R / "COMPLETED").write_text("All assertions passed.\n")


if __name__ == "__main__":
    main()
