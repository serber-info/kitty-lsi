"""Optional developer QA: capture ONLY isolated Kitty test windows on X11.

Python, Pillow, Kitty remote control, X11 tools and ImageMagick are harness
requirements, never requirements of the executable under test.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    for tool in ("kitty", "kitten", "xdotool", "import"):
        if not shutil.which(tool):
            parser.error(f"missing QA tool: {tool}")
    root = Path(tempfile.mkdtemp(prefix="kitty-lsi-visual-"))
    assets = root / "fixtures"
    assets.mkdir()
    for directory in ("albums", "z-folder"):
        (assets / directory).mkdir()
    colors = [("mountains.png", "#478b9a"), ("sunset.png", "#cc734f"),
              ("forest.png", "#518560"), ("night.png", "#56518a"),
              ("portrait.png", "#99774d"), ("transparent.png", "#368d8e")]
    for index, (name, color) in enumerate(colors):
        size = (220, 340) if index == 4 else (400, 240)
        image = Image.new("RGBA", size, (0, 0, 0, 0) if index == 5 else color)
        draw = ImageDraw.Draw(image)
        draw.ellipse((size[0]//2-35, 25, size[0]//2+35, 95), fill="#ead4a7")
        draw.polygon([(0, size[1]), (size[0]//3, 85), (size[0]*2//3, size[1]),
                      (size[0], size[1]//2), (size[0], size[1])], fill=color if index == 5 else "#203841")
        image.save(assets / name)
    for index in range(24):
        shutil.copyfile(assets / colors[index % len(colors)][0], assets / f"sample-{index:02}.png")
    (assets / "notes.txt").write_text("ordinary document\n")
    (assets / "run").write_text("not executed: icon fixture only\n")
    (assets / "run").chmod(0o755)
    extensions = ("mp4", "mp3", "svg", "tar.gz", "pdf", "xlsx", "pptx", "py", "iso", "json", "unknown")
    for extension in extensions:
        (assets / ("example." + extension)).write_text("icon fixture; never interpreted\n")
    (assets / "file-link").symlink_to("notes.txt")
    (assets / "folder-link").symlink_to("albums", target_is_directory=True)
    (assets / "broken-link").symlink_to("missing")
    os.mkfifo(assets / "pipe")
    endpoint = socket.socket(socket.AF_UNIX)
    endpoint.bind(str(assets / "socket"))
    scenarios = [
        ("extension-icons", 1000, 740, ["-d", "--width", "16", "albums", *["example." + extension for extension in extensions]]),
        ("entry-icons", 1000, 620, ["-d", "--width", "14", "albums", "notes.txt", "run", "file-link", "folder-link", "broken-link", "pipe", "socket", "/dev/null"]),
        ("grid", 1000, 620, ["-d", "--width", "20", "albums", "z-folder", *[name for name, _ in colors]]),
        ("long", 1000, 620, ["-dlnh", "--width", "18", "albums", "z-folder", *[name for name, _ in colors[:2]]]),
        ("scrollback", 1000, 620, ["--width", "20"]),
        ("narrow", 480, 620, ["-dlnh", "--width", "14", "albums", *[name for name, _ in colors[:2]]]),
    ]
    for scenario, width, height, flags in scenarios:
        control_socket = root / (scenario + ".sock")
        title = f"kitty-lsi-qa-{root.name}-{scenario}"
        env = dict(os.environ)
        env.pop("KITTY_LISTEN_ON", None)
        env.pop("TMUX", None)
        command = ["kitty", "--config", "NONE", "--listen-on", "unix:"+str(control_socket),
                   "--class", "kitty-lsi-qa", "--title", title, "--directory", str(assets),
                   "-o", "allow_remote_control=socket-only", "-o", "linux_display_server=x11",
                   "-o", "remember_window_size=no", "-o", "font_size=12",
                   "-o", f"initial_window_width={width}", "-o", f"initial_window_height={height}",
                   "/bin/sh", "-c", '"$@"; status=$?; printf "\\n[exit=%s] $ " "$status"; sleep 120',
                   "qa", str(binary), *flags]
        with (root / (scenario+".log")).open("wb") as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=log)
            try:
                remote = ["kitten", "@", "--to", "unix:"+str(control_socket)]
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f"QA Kitty exited; see {root}")
                    if control_socket.exists():
                        text = subprocess.run([*remote, "get-text"], capture_output=True, text=True)
                        if text.returncode == 0 and "[exit=0]" in text.stdout:
                            break
                    time.sleep(0.1)
                else:
                    raise RuntimeError(f"QA command failed/did not finish; see {root}")
                # Search by a title unique to this process; never capture desktop.
                found = subprocess.check_output(["xdotool", "search", "--onlyvisible", "--name", title], text=True).splitlines()
                if len(found) != 1:
                    raise RuntimeError(f"expected exactly one owned test window: {found}")
                window = found[0]
                subprocess.run(["xdotool", "windowactivate", "--sync", window], check=True)
                time.sleep(1.0)
                if scenario == "scrollback":
                    subprocess.run([*remote, "action", "scroll_home"], check=True, capture_output=True)
                    time.sleep(0.3)
                # Capture only the owned test window after bringing it forward.
                subprocess.run(["import", "-window", window,
                                str(root / (scenario+".png"))], check=True)
                inventory = subprocess.check_output([*remote, "ls"], text=True)
                (root / (scenario+".json")).write_text(inventory)
                all_text = subprocess.check_output([*remote, "get-text", "--extent", "all"], text=True)
                (root / (scenario+".txt")).write_text(all_text)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    print(root)


if __name__ == "__main__":
    main()
