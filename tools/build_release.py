#!/usr/bin/env python3
"""Build deterministic local candidate archives and .deb; never publishes.
Development tooling only. Runtime is the single supplied ELF executable.
"""

import argparse
import gzip
import hashlib
import io
import json
import pathlib
import re
import subprocess
import tarfile
import tomllib

from check_elf import check as check_elf

ROOT = pathlib.Path(__file__).resolve().parents[1]
ALLOW = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "MPL-2.0",
    "Unicode-3.0",
    "Zlib",
    "0BSD",
    "CC0-1.0",
    "Unlicense",
}


def tar_bytes(files, epoch):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as tar:
        parents = set()
        for name, _, _, _ in files:
            parent = pathlib.PurePosixPath(name).parent
            while str(parent) != ".":
                parents.add(str(parent))
                parent = parent.parent
        for name in sorted(parents):
            info = tarfile.TarInfo(name + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mtime = epoch
            tar.addfile(info)
        for name, data, mode, link in sorted(files):
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            info.mode = mode
            info.mtime = epoch
            if link:
                info.type = tarfile.SYMTYPE
                info.linkname = link
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return gzip.compress(out.getvalue(), mtime=epoch)


def ar(members):
    out = bytearray(b"!<arch>\n")
    for name, data in members:
        header = f"{name + '/':<16}{0:<12}{0:<6}{0:<6}{'100644':<8}{len(data):<10}`\n".encode(
            "ascii"
        )
        assert len(header) == 60
        out += header + data
        if len(data) % 2:
            out += b"\n"
    return bytes(out)


def licenses():
    meta = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--locked",
                "--offline",
                "--filter-platform",
                "x86_64-unknown-linux-musl",
                "--format-version",
                "1",
            ],
            cwd=ROOT / "rust",
        )
    )
    files = []
    notices = [
        "# Third-party dependencies\n\nExact locked Linux x86-64 build graph, including build tools.\n"
    ]
    summary = []
    for package in sorted(meta["packages"], key=lambda p: p["name"]):
        if package["name"] == "kitty-lsi":
            continue
        expression = package.get("license") or ""
        ids = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9.-]*", expression)) - {"AND", "OR", "WITH"}
        if not ids or not ids <= ALLOW:
            raise SystemExit(f"Unreviewed SPDX expression: {package['name']}: {expression}")
        base = pathlib.Path(package["manifest_path"]).parent
        prefix = f"licenses/{package['name']}-{package['version']}"
        texts = [
            p
            for p in base.iterdir()
            if p.is_file()
            and p.name.upper().startswith(
                ("LICENSE", "COPYING", "COPYRIGHT", "NOTICE", "UNLICENSE")
            )
        ]
        if not texts:
            fallback = ROOT / "packaging/licenses" / f"{package['name']}-{package['version']}"
            texts = list(fallback.glob("LICENSE*"))
        if not texts:
            raise SystemExit(f"No license text: {package['name']}; review before distribution")
        for p in texts:
            files.append((prefix + "/" + p.name, p.read_bytes(), 0o644, ""))
        notices.append(f"- {package['name']} {package['version']}: {expression}\n")
        summary.append(
            {
                "name": package["name"],
                "version": package["version"],
                "license": expression,
                "source": package["source"],
            }
        )
        if "MPL-2.0" in ids:
            # Ship the exact covered source, not merely a moving upstream URL.
            for p in sorted(base.rglob("*")):
                if p.is_file() and not any(
                    x.startswith(".cargo") or x == ".git" for x in p.relative_to(base).parts
                ):
                    files.append(
                        (
                            "mpl-source/"
                            + package["name"]
                            + "-"
                            + package["version"]
                            + "/"
                            + str(p.relative_to(base)),
                            p.read_bytes(),
                            0o644,
                            "",
                        )
                    )
    files.append(("THIRD_PARTY.md", "".join(notices).encode(), 0o644, ""))
    files.append(("dependencies.json", json.dumps(summary, indent=2).encode(), 0o644, ""))
    return files


def runtime_licenses():
    # Cargo metadata does not inventory statically linked std/musl/libunwind.
    sysroot = pathlib.Path(
        subprocess.check_output(["rustc", "--print", "sysroot"], text=True).strip()
    )
    docs = sysroot / "share/doc/rust"
    selected = [docs / "COPYRIGHT-library.html"]
    selected += [
        docs / "licenses" / name
        for name in [
            "Apache-2.0.txt",
            "MIT.txt",
            "BSD-2-Clause.txt",
            "ISC.txt",
            "NCSA.txt",
            "LLVM-exception.txt",
            "Unicode-3.0.txt",
        ]
    ]
    files = []
    for path in selected:
        if not path.is_file():
            raise SystemExit("Missing Rust runtime notice: " + str(path))
        files.append(("licenses/rust-runtime/" + path.name, path.read_bytes(), 0o644, ""))
    for group in ["musl-1.2.5", "llvm-libunwind"]:
        for path in sorted((ROOT / "packaging/licenses" / group).iterdir()):
            if path.is_file():
                files.append(("licenses/" + group + "/" + path.name, path.read_bytes(), 0o644, ""))
    files.append(
        (
            "RUNTIME-NOTICES.md",
            b"Rust 1.98.0 standard library: MIT OR Apache-2.0; dependencies retain their licenses.\n"
            b"musl 1.2.5 with Rust vendor patches: see licenses/musl-1.2.5/COPYRIGHT.\n"
            b"LLVM libunwind: Apache-2.0 WITH LLVM-exception AND NCSA; see its exact source LICENSE.\n"
            b"Rust standard-library complete notices and relevant license texts are included.\n",
            0o644,
            "",
        )
    )
    return files


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--binary", type=pathlib.Path, required=True)
    p.add_argument("--out", type=pathlib.Path, required=True)
    p.add_argument("--repository", help="actual owner/repo, only when known")
    p.add_argument("--revision", default="UNCOMMITTED")
    p.add_argument("--maintainer", help="real Debian maintainer Name <email>")
    p.add_argument(
        "--release",
        action="store_true",
        help="require complete public-release metadata; does not publish",
    )
    p.add_argument("--epoch", type=int, default=0)
    a = p.parse_args()
    if a.repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", a.repository):
        p.error("repository must be owner/repo")
    if a.revision != "UNCOMMITTED" and not re.fullmatch(r"[0-9a-f]{40}", a.revision):
        p.error("revision must be a full commit SHA")
    if a.repository and a.revision == "UNCOMMITTED":
        p.error("public URL metadata requires a real source commit")
    if a.maintainer and (not re.fullmatch(r"[^<>\r\n]+ <[^<>@\s]+@[^<>@\s]+>", a.maintainer)):
        p.error("maintainer must be Name <email>")
    if a.release and (not a.repository or a.revision == "UNCOMMITTED" or not a.maintainer):
        p.error("release requires repository, source commit and real maintainer contact")
    if a.release:
        owner, repository = a.repository.lower().split("/")
        if owner in {"owner", "local-validation"} or repository in {"repository", "not-published"}:
            p.error("release refuses a placeholder repository")
        contact = a.maintainer.rsplit("<", 1)[1].rstrip(">").lower()
        domain = contact.rsplit("@", 1)[1]
        if (
            a.maintainer.lower().startswith("unconfigured ")
            or "." not in domain
            or domain.endswith((".invalid", ".test", ".localhost", ".example"))
            or any(
                domain == d or domain.endswith("." + d)
                for d in ("example.com", "example.net", "example.org")
            )
        ):
            p.error("release refuses a reserved or placeholder maintainer contact")
        compiler = subprocess.check_output(["rustc", "--version", "--verbose"], text=True)
        if "commit-hash: 88d9e12ae178fab0fb5cc050a94da85685d449ea" not in compiler:
            p.error(
                "native runtime notices must be re-audited for this Rust toolchain before release"
            )
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        if (
            head != a.revision
            or subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        ):
            p.error("release requires matching clean source checkout")
    try:
        check_elf(a.binary)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        p.error(f"ELF verification failed: {error}")
    binary = a.binary.resolve(strict=True).read_bytes()
    a.out.mkdir(parents=True, exist_ok=False)
    version = tomllib.loads((ROOT / "rust/Cargo.toml").read_text())["package"]["version"]
    build_inputs = {}
    for path in sorted(
        [
            *ROOT.glob("rust/src/*.rs"),
            ROOT / "rust/Cargo.toml",
            ROOT / "rust/Cargo.lock",
            ROOT / "rust/.cargo/config.toml",
            ROOT / "tools/build_static.sh",
        ]
    ):
        build_inputs[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    provenance = json.dumps(
        {
            "version": version,
            "revision": a.revision,
            "candidate": not a.release,
            "binary_sha256": hashlib.sha256(binary).hexdigest(),
            "target": "x86_64-unknown-linux-musl",
            "build_inputs": build_inputs,
            "source_date_epoch": a.epoch,
            "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        },
        indent=2,
    ).encode()
    common = (
        [
            ("lsi", binary, 0o755, ""),
            ("lli", b"", 0o777, "lsi"),
            ("LICENSE", (ROOT / "LICENSE").read_bytes(), 0o644, ""),
            ("SECURITY.md", (ROOT / "SECURITY.md").read_bytes(), 0o644, ""),
            ("README.md", (ROOT / "README.md").read_bytes(), 0o644, ""),
            ("PROVENANCE.json", provenance, 0o644, ""),
        ]
        + licenses()
        + runtime_licenses()
    )
    archive = a.out / f"lsi-{version}-linux-x86_64.tar.gz"
    archive.write_bytes(tar_bytes(common, a.epoch))
    debfiles = []
    for name, data, mode, link in common:
        if name == "lli":
            continue  # Global lli belongs to LLVM; packages install lsi only.
        target = (
            "usr/bin/" + name
            if name in {"lsi", "lli"}
            else "usr/share/doc/lsi/" + ("copyright" if name == "LICENSE" else name)
        )
        debfiles.append((target, data, mode, link))
    control = f"Package: lsi\nVersion: {version}\nSection: utils\nPriority: optional\nArchitecture: amd64\nMaintainer: {a.maintainer or 'UNCONFIGURED <noreply@example.invalid>'}\nInstalled-Size: {sum(len(d) for _, d, _, _ in debfiles) // 1024 + 1}\nDescription: image thumbnail listing in Kitty-compatible terminals\n Standalone Rust executable; use lsi -l for long listings.\n"
    if a.repository:
        control += f"Homepage: https://github.com/{a.repository}\n"
    deb = a.out / f"lsi_{version}_amd64.deb"
    deb.write_bytes(
        ar(
            [
                ("debian-binary", b"2.0\n"),
                ("control.tar.gz", tar_bytes([("control", control.encode(), 0o644, "")], a.epoch)),
                ("data.tar.gz", tar_bytes(debfiles, a.epoch)),
            ]
        )
    )
    (a.out / "PROVENANCE.json").write_bytes(provenance)
    # Concrete AUR metadata only when provenance and destination are real.
    if a.repository:
        sha = hashlib.sha256(archive.read_bytes()).hexdigest()
        for name in ["PKGBUILD", ".SRCINFO"]:
            text = (
                (ROOT / "packaging/aur" / f"{name}.in")
                .read_text()
                .replace("@VERSION@", version)
                .replace("@REPOSITORY@", a.repository)
                .replace("@SHA256@", sha)
            )
            aur = a.out / "lsi-bin"
            aur.mkdir(exist_ok=True)
            (aur / name).write_text(text)
    else:
        (a.out / "AUR-NOT-RENDERED.txt").write_text(
            "No public repository/commit configured. Templates are not publishable packages.\n"
        )
    sums = []
    for path in sorted(a.out.iterdir()):
        if path.is_file():
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n")
    (a.out / "SHA256SUMS").write_text("".join(sums))
    print(a.out)


if __name__ == "__main__":
    main()
