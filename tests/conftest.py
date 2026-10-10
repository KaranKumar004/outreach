import os
import glob
import stat
import hashlib
import pytest

def calculate_sha256(filepath):
    """Compute sha256 checksum of a file."""
    if not os.path.exists(filepath):
        return None
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()

@pytest.fixture(scope="session", autouse=True)
def guard_project_files_integrity():
    """
    Integrity Gate:
    1. Checksums all real project data files (outreach_log*.csv, leads*.csv).
    2. Locks them as read-only via os.chmod(stat.S_IREAD).
    3. Yields for test execution.
    4. Restores write permissions and asserts checksums are completely unchanged.
    """
    target_files = sorted(
        set(
            glob.glob("leads*.csv")
            + glob.glob("outreach_log*.csv")
        )
    )

    initial_hashes = {}
    for fpath in target_files:
        initial_hashes[fpath] = calculate_sha256(fpath)
        # Lock to read-only mode to immediately trap any rogue write attempt
        try:
            os.chmod(fpath, stat.S_IREAD)
        except Exception:
            pass

    yield

    # Teardown: restore permissions and assert no file was modified
    modified_files = []
    for fpath in target_files:
        try:
            os.chmod(fpath, stat.S_IWRITE | stat.S_IREAD)
        except Exception:
            pass
        final_hash = calculate_sha256(fpath)
        if final_hash != initial_hashes[fpath]:
            modified_files.append((fpath, initial_hashes[fpath], final_hash))

    if modified_files:
        details = "\n".join(
            f"  - {f}: initial={ih} vs final={fh}"
            for f, ih, fh in modified_files
        )
        raise AssertionError(
            f"Test isolation violated! The following project files were modified during tests:\n{details}"
        )
