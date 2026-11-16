"""Build and package the Linux x86-64 port from a local European cartridge."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
UPSTREAM = BUILD / "upstream"
EXTRACTED = ROOT / "extracted"
GENERATED = ROOT / "generated" / "kirby-eur"
CLOCKWORK = "3047d9e990be4ac2c84174cb570dfec569c882e9"
XBYAK = "df112862583c2d327c1d9782fd28f53aa675f11d"
FONT = "f470e0c9d341db73b8a24880295d2eab4cd81660"
LANGUAGES = {"en": 1, "fr": 2, "de": 3, "es": 5, "it": 4}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download(name, url, sha256):
    path = UPSTREAM / name
    if path.is_file():
        if digest(path) != sha256:
            raise ValueError(f"SHA-256 mismatch for {path}")
        return path
    print(f"Downloading {name}", flush=True)
    with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
        candidate = Path(work) / name
        with urllib.request.urlopen(url, timeout=90) as response, candidate.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(candidate) != sha256:
            raise ValueError(f"SHA-256 mismatch for {name}")
        candidate.replace(path)
    return path


def github_zip(name, repo, commit, directory, sha256):
    archive = download(name, f"https://codeload.github.com/{repo}/zip/{commit}", sha256)
    target = UPSTREAM / directory
    if not target.is_dir():
        with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
            with zipfile.ZipFile(archive) as source:
                source.extractall(work)
            (Path(work) / f"{repo.split('/')[-1]}-{commit}").replace(target)
    return target


def release_tar(name, repo, tag, directory, sha256, strip=0):
    archive = download(name, f"https://github.com/{repo}/releases/download/{tag}/{name}", sha256)
    target = UPSTREAM / directory
    if not target.is_dir():
        with tempfile.TemporaryDirectory(dir=UPSTREAM) as work:
            staged = Path(work) / directory
            staged.mkdir()
            subprocess.run(["tar", "-xf", archive, "-C", staged, f"--strip-components={strip}"], check=True)
            staged.replace(target)


def prepare_dependencies():
    UPSTREAM.mkdir(parents=True, exist_ok=True)
    clockwork = github_zip("clockwork-pinned.zip", "watchmakerers/clockwork", CLOCKWORK, "clockwork-master",
                          "7923e82994e3a06f7aa17dfdb2a6e25a608e3495227baf1a0fdbcc32dfbe1ded")
    github_zip("xbyak-pinned.zip", "herumi/xbyak", XBYAK, f"xbyak-{XBYAK}",
               "b0e8d74a5813d4c4d2baa550b889b7f7c2696e471dfb8de1554ce47f7e52d7f8")
    release_tar("SDL3-3.4.0.tar.gz", "libsdl-org/SDL", "release-3.4.0", "SDL3-3.4.0-linux",
                "082cbf5f429e0d80820f68dc2b507a94d4cc1b4e70817b119bbb8ec6a69584b8", strip=1)
    release_tar("linux_dxc_2025_07_14.x86_64.tar.gz", "microsoft/DirectXShaderCompiler", "v1.8.2505.1",
                "dxc-linux-1.8.2505.1", "f2213da1fc99dc8778c8823078e16ba97c7f80f86a1d4520ab1adf4b462bc48c")
    return clockwork


def python(script, *args, cwd=ROOT):
    subprocess.run([sys.executable, script, *args], cwd=cwd, check=True)


def prepare_system_resources():
    source = github_zip("system-archives-pinned.zip", "B3n30/citra_system_archives", FONT,
                        f"citra_system_archives-{FONT}",
                        "2f2072de4026462e786bc0e6040238a6fde356325041cabc4d66f9432f75e3db")
    mii = EXTRACTED / "mii.romfs"
    if not mii.is_file():
        python("mii.py", "-c", "custom", mii, cwd=source / "mii")
    target = EXTRACTED / "shared-font.bcfnt"
    if not target.is_file():
        font = source / "shared_font"
        python("create_png.py", cwd=font)
        for glyph in (font / "reserved_unicode_chars").glob("*.png"):
            shutil.copyfile(glyph, font / glyph.name)
        python("bcfnt.py", "-c", "-y", "-f", "code.bcfnt", cwd=font)
        shutil.copyfile(font / "code.bcfnt", target)


def prepare_game(args, clockwork):
    workspace = BUILD / "linux-tools"
    workspace.mkdir(exist_ok=True)
    for name in ("Cargo.toml", "Cargo.lock"):
        shutil.copy2(clockwork / name, workspace / name)
    for name in ("ctrx", "recomp"):
        shutil.copytree(clockwork / "tools" / name, workspace / "tools" / name, dirs_exist_ok=True)
    python("tools/prepare_recompiler.py", clockwork / "tools/recomp/src", workspace / "tools/recomp/src")
    subprocess.run(["cargo", "build", "--locked", "--release", "--target-dir", workspace / "target"],
                   cwd=workspace, check=True)
    tools = workspace / "target" / "release"

    EXTRACTED.mkdir(exist_ok=True)
    cxi = EXTRACTED / "KIRBY-EUR.cxi"
    with tempfile.TemporaryDirectory(dir=EXTRACTED) as work:
        candidate = cxi
        if args.cartridge.resolve() != cxi:
            candidate = Path(work) / cxi.name
            if args.cartridge.suffix.lower() == ".cxi":
                shutil.copyfile(args.cartridge, candidate)
            else:
                options = ["--key-file", args.key_file.resolve()] if args.key_file else []
                python("tools/cartridge.py", args.cartridge.resolve(), "--extract", candidate, *options)
        python("tools/verify_extraction.py", candidate)
        code = Path(work) / "code"
        subprocess.run([tools / "ctrx", "--code-only", candidate, code], check=True)
        if digest(code / "code.bin") != "e3acd2fd3e6dc8edde61a6f5bab0eed7df1daeeb02fd3c10e44ac466e477567b":
            raise ValueError("The cartridge does not match the supported European game revision")
        if candidate != cxi:
            candidate.replace(cxi)
        GENERATED.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=GENERATED.parent) as output:
            subprocess.run([tools / "recomp", "emit", code, output], check=True)
            generated = {file.name: file for file in Path(output).iterdir()}
            for name, file in generated.items():
                existing = GENERATED / name
                if not existing.is_file() or digest(file) != digest(existing):
                    file.replace(existing)
            for file in GENERATED.glob("*.c"):
                if file.name not in generated:
                    file.unlink()


def package(build, language):
    dist = ROOT / "dist" / "linux-x64"
    licenses = dist / "licenses"
    licenses.mkdir(parents=True, exist_ok=True)
    shutil.copy2(build / "KirbyTripleDeluxe", dist)
    shutil.copy2(EXTRACTED / "shared-font.bcfnt", dist)
    shutil.copy2(EXTRACTED / "mii.romfs", dist)
    shutil.copyfile(ROOT / "LICENSE", licenses / "Clockwork.txt")
    shutil.copyfile(UPSTREAM / "SDL3-3.4.0-linux/LICENSE.txt", licenses / "SDL.txt")
    shutil.copyfile(UPSTREAM / f"xbyak-{XBYAK}/COPYRIGHT", licenses / "Xbyak.txt")
    shutil.copyfile(UPSTREAM / f"citra_system_archives-{FONT}/license.txt", licenses / "SystemArchives.txt")

    if language is not None:
        settings = dist / "userdata" / "settings.ini"
        settings.parent.mkdir(exist_ok=True)
        lines = settings.read_text(encoding="utf-8").splitlines() if settings.is_file() else []
        lines = [line for line in lines if not line.startswith("language=")]
        lines.append(f"language={LANGUAGES[language]}")
        with tempfile.TemporaryDirectory(dir=settings.parent) as work:
            staged = Path(work) / settings.name
            staged.write_text("\n".join(lines) + "\n", encoding="utf-8")
            staged.replace(settings)
        print(f"Game language: {language}")
    print(f"Run {dist / 'KirbyTripleDeluxe'}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cartridge", type=Path, required=True)
    parser.add_argument("--language", choices=LANGUAGES)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    if not args.cartridge.is_file():
        parser.error(f"cartridge file not found: {args.cartridge}")
    try:
        clockwork = prepare_dependencies()
        prepare_game(args, clockwork)
        prepare_system_resources()
        build = BUILD / "linux-Release"
        subprocess.run(["cmake", "-S", ROOT, "-B", build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release"], check=True)
        jobs = os.environ.get("CMAKE_BUILD_PARALLEL_LEVEL") or "4"
        subprocess.run(["cmake", "--build", build, "--parallel", jobs], check=True)
        subprocess.run(["ctest", "--test-dir", build, "--output-on-failure", "--no-tests=error"], check=True)
        package(build, args.language)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"error: {error}\n")


if __name__ == "__main__":
    main()
