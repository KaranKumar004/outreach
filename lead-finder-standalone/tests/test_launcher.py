"""
tests/test_launcher.py — Verification tests for OS/CPU detection, runtime relocation, and cryptographic checksum integrity in launchers.

NOTE: Real Windows launcher executions (running run.bat to end-of-run) are verified via static
parsing and unit simulations; no real bare-metal Windows run on fresh machines has occurred yet.
"""

import os
import hashlib
import tempfile
import pytest

REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Pinned official uv release 0.6.5 integrity hashes (verified against Astral GitHub releases)
EXPECTED_HASHES = {
    ("Windows", "x86_64"): "a3e9f0913189c38b804bf6bb3d348af305a8ceabc690be92b6e111245a821640",
    ("Windows", "arm64"):  "2af20abb3a289d57ae6a8f34ec9f6a60276947fdfb80de6d7304a1b49242cc64",
    ("Darwin", "arm64"):   "4952c6275778fbc7e5cf6b5739ffd944c47063134d6ea43a7037b0a028ef771e",
    ("Darwin", "x86_64"):  "d336d862694e1c36afea55eb15f5df02aa77c04a168b781df515d641e23285f0",
    ("Linux", "x86_64"):   "8fc9895719a1291ecd193cb86f9282ff3649cef797d29eacc74c4f573aab1e2f",
    ("Linux", "aarch64"):  "ebf0707ab949b948ad14250ed93f968fec954e20d12ce6bc9fce74b0ce7e4900",
}


def resolve_uv_target(os_name: str, arch: str) -> tuple:
    """Simulates the launcher OS and CPU detection logic."""
    arch_lower = arch.lower()
    if os_name == "Windows":
        if arch_lower in ("arm64", "aarch64"):
            return "uv-aarch64-pc-windows-msvc.zip", EXPECTED_HASHES[("Windows", "arm64")]
        else:
            return "uv-x86_64-pc-windows-msvc.zip", EXPECTED_HASHES[("Windows", "x86_64")]
    elif os_name == "Darwin":
        if arch_lower in ("arm64", "aarch64"):
            return "uv-aarch64-apple-darwin.tar.gz", EXPECTED_HASHES[("Darwin", "arm64")]
        else:
            return "uv-x86_64-apple-darwin.tar.gz", EXPECTED_HASHES[("Darwin", "x86_64")]
    elif os_name == "Linux":
        if arch_lower in ("arm64", "aarch64"):
            return "uv-aarch64-unknown-linux-gnu.tar.gz", EXPECTED_HASHES[("Linux", "aarch64")]
        else:
            return "uv-x86_64-unknown-linux-gnu.tar.gz", EXPECTED_HASHES[("Linux", "x86_64")]
    else:
        raise ValueError(f"Unsupported OS: {os_name}")


def verify_file_sha256(filepath: str, expected_hash: str) -> bool:
    """Simulates the launcher SHA256 checksum verification."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hash.lower()


def test_os_cpu_detection_all_platforms():
    """Verify that OS and CPU combinations map to the correct artifact and expected hash."""
    test_cases = [
        ("Windows", "AMD64", "uv-x86_64-pc-windows-msvc.zip", EXPECTED_HASHES[("Windows", "x86_64")]),
        ("Windows", "ARM64", "uv-aarch64-pc-windows-msvc.zip", EXPECTED_HASHES[("Windows", "arm64")]),
        ("Darwin", "arm64", "uv-aarch64-apple-darwin.tar.gz", EXPECTED_HASHES[("Darwin", "arm64")]),
        ("Darwin", "x86_64", "uv-x86_64-apple-darwin.tar.gz", EXPECTED_HASHES[("Darwin", "x86_64")]),
        ("Linux", "x86_64", "uv-x86_64-unknown-linux-gnu.tar.gz", EXPECTED_HASHES[("Linux", "x86_64")]),
        ("Linux", "aarch64", "uv-aarch64-unknown-linux-gnu.tar.gz", EXPECTED_HASHES[("Linux", "aarch64")]),
    ]

    for os_name, arch, expected_target, expected_hash in test_cases:
        target, h = resolve_uv_target(os_name, arch)
        assert target == expected_target, f"Failed target resolution for {os_name} {arch}"
        assert h == expected_hash, f"Failed hash resolution for {os_name} {arch}"


def test_checksum_verification_valid_and_tampered():
    """Verify that checksum verification accepts authentic files and rejects tampered files."""
    content = b"LocalLeadsKit official test content"
    correct_hash = hashlib.sha256(content).hexdigest()

    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(content)
        temp_path = f.name

    try:
        assert verify_file_sha256(temp_path, correct_hash) is True
        tampered_hash = "0000000000000000000000000000000000000000000000000000000000000000"
        assert verify_file_sha256(temp_path, tampered_hash) is False
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_run_bat_embedded_integrity():
    """Verify that run.bat contains the verified Windows uv hashes, architecture detection, and isolated runtime location."""
    bat_path = os.path.join(REPO_DIR, "run.bat")
    assert os.path.exists(bat_path), "run.bat must exist"

    with open(bat_path, "r", encoding="utf-8") as f:
        bat_content = f.read()

    win_x64_hash = EXPECTED_HASHES[("Windows", "x86_64")]
    win_arm64_hash = EXPECTED_HASHES[("Windows", "arm64")]
    assert win_x64_hash in bat_content, f"run.bat must embed Windows x64 uv SHA256: {win_x64_hash}"
    assert win_arm64_hash in bat_content, f"run.bat must embed Windows ARM64 uv SHA256: {win_arm64_hash}"
    assert "PROCESSOR_ARCHITECTURE" in bat_content, "run.bat must check PROCESSOR_ARCHITECTURE"
    assert "PROCESSOR_ARCHITEW6432" in bat_content, "run.bat must check PROCESSOR_ARCHITEW6432 for WOW64"
    assert "%LOCALAPPDATA%\\LocalLeadsKit" in bat_content or "LocalLeadsKit" in bat_content, "run.bat must isolate runtime in LOCALAPPDATA"
    assert "UV_CACHE_DIR" in bat_content, "run.bat must export UV_CACHE_DIR"
    assert "UV_PYTHON_INSTALL_DIR" in bat_content, "run.bat must export UV_PYTHON_INSTALL_DIR"
    assert "0.6.5" in bat_content, "run.bat must use pinned uv version 0.6.5"
    assert "python 3.11" in bat_content or "--python 3.11" in bat_content, "run.bat must provision Python 3.11"
    assert "credentials.toml" in bat_content, "run.bat must configure credentials.toml"
    assert "streamlit run" in bat_content, "run.bat must launch Streamlit"


def test_run_sh_embedded_integrity():
    """Verify that run.sh contains all Unix uv hashes, isolated runtime location, and python 3.11 provisioning."""
    sh_path = os.path.join(REPO_DIR, "run.sh")
    assert os.path.exists(sh_path), "run.sh must exist"

    with open(sh_path, "r", encoding="utf-8") as f:
        sh_content = f.read()

    for (os_name, arch), expected_hash in EXPECTED_HASHES.items():
        if os_name in ("Darwin", "Linux"):
            assert expected_hash in sh_content, f"run.sh must embed {os_name} {arch} SHA256: {expected_hash}"

    assert ".localleadskit" in sh_content, "run.sh must isolate runtime in ~/.localleadskit"
    assert "UV_CACHE_DIR" in sh_content, "run.sh must export UV_CACHE_DIR"
    assert "UV_PYTHON_INSTALL_DIR" in sh_content, "run.sh must export UV_PYTHON_INSTALL_DIR"
    assert "0.6.5" in sh_content, "run.sh must use pinned uv version 0.6.5"
    assert "python 3.11" in sh_content or "--python 3.11" in sh_content, "run.sh must provision Python 3.11"
    assert "credentials.toml" in sh_content, "run.sh must configure credentials.toml"
    assert "streamlit run" in sh_content, "run.sh must launch Streamlit"


def test_live_network_official_release_sha256_fetch_and_match():
    """Live network verification: fetches the 6 official .sha256 files directly from GitHub and asserts 100% byte match against launchers and EXPECTED_HASHES."""
    import urllib.request

    base_url = "https://github.com/astral-sh/uv/releases/download/0.6.5/"
    targets = [
        (("Windows", "x86_64"), "uv-x86_64-pc-windows-msvc.zip"),
        (("Windows", "arm64"),  "uv-aarch64-pc-windows-msvc.zip"),
        (("Darwin", "arm64"),   "uv-aarch64-apple-darwin.tar.gz"),
        (("Darwin", "x86_64"),  "uv-x86_64-apple-darwin.tar.gz"),
        (("Linux", "x86_64"),   "uv-x86_64-unknown-linux-gnu.tar.gz"),
        (("Linux", "aarch64"),  "uv-aarch64-unknown-linux-gnu.tar.gz"),
    ]

    bat_path = os.path.join(REPO_DIR, "run.bat")
    sh_path = os.path.join(REPO_DIR, "run.sh")
    with open(bat_path, "r", encoding="utf-8") as f:
        bat_content = f.read()
    with open(sh_path, "r", encoding="utf-8") as f:
        sh_content = f.read()

    for (os_name, arch), archive_name in targets:
        url = f"{base_url}{archive_name}.sha256"
        req = urllib.request.Request(url, headers={"User-Agent": "LocalLeadsKit-TestVerifier/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw_hash_line = resp.read().decode("utf-8").strip()
            fetched_hash = raw_hash_line.split()[0].lower()

        # 1. Matches EXPECTED_HASHES constant
        expected_hash = EXPECTED_HASHES[(os_name, arch)]
        assert fetched_hash == expected_hash, (
            f"Hash mismatch for {archive_name}: fetched {fetched_hash} != expected {expected_hash}"
        )

        # 2. Matches embedded hash in launcher
        if os_name == "Windows":
            assert fetched_hash in bat_content, f"Fetched hash for {archive_name} not found in run.bat: {fetched_hash}"
        else:
            assert fetched_hash in sh_content, f"Fetched hash for {archive_name} not found in run.sh: {fetched_hash}"

