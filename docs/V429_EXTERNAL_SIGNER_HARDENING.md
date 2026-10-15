# V4.29 — Independent Signer External File Hardening

## Purpose

V4.29 closes a local filesystem gap in the reviewer-side Ed25519 signer. The
V4.28 helpers rejected direct symlinks but did not uniformly reject a symlink
in an ancestor directory; input validation and subsequent path-based reads
were separate operations, and signed output could overwrite an existing file.

## Contract

- Only POSIX environments providing `openat`/directory-fd and `O_NOFOLLOW`
  semantics are accepted for this strict external-file path.
- Reviewer key and unsigned-evidence inputs must be external to the repository,
  have no symlink in any path component, and be regular files.
- The private key is bounded to 1 MiB; unsigned evidence is bounded to 16 MiB.
- The reader opens files through directory file descriptors, applies
  `O_NOFOLLOW` and `O_NONBLOCK`, validates `fstat`, reads in bounded chunks,
  and compares inode, device, size, mtime and ctime after reading.
- The private key must not be group/world accessible.
- Signed evidence output must also be external to the checkout. Parent path
  components are traversed with directory descriptors and no-follow opens.
- Output is created with `O_CREAT|O_EXCL|O_NOFOLLOW`, mode `0600`, and fsync;
  an existing output is never overwritten. A failed partial write is removed
  only if the directory entry still identifies the inode created by this call.
- If secure directory-fd primitives are not supported, the signer fails closed.

## Limits

These are local application-level filesystem controls and synthetic fixtures.
They do not prove the identity of the human reviewer, custody of the key, the
validity of a trust ceremony, the truth of captured GitHub state, or the safety
of every filesystem/host configuration. Those remain external evidence gates.

## Validation

`tests/v429/test_external_file_safety_v429.py` covers traversal, platform paths,
symlinked parent and final components, non-regular and oversized inputs, hard
link/output collisions, exclusive creation, preservation of existing outputs,
and `0600` output permissions. `tests/v429/test_signer_hardening_v429.py` drives
the CLI with fixture keys and evidence and verifies the Ed25519 signature.
