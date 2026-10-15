# V4.28 Governance CLI Path Confinement

## Scope

The governance verifier, GitHub capture client, signing helper and mandatory milestone runner consume command-line paths. V4.28 makes the path policy explicit so a malformed or mistaken path cannot redirect an audit output onto source, trust, workflow, evidence, key or ledger files.

## Repository-relative CLI paths

- Repository-relative inputs reject absolute paths, Windows drive/UNC paths, `..`, NUL bytes and any existing symlink component.
- Verifier reports, governance captures and milestone audit outputs must be inside `.audit/`.
- The verifier rejects report/event-store collisions and outputs that alias input files, including detected hard links.
- Audit report writes traverse directory file descriptors without following symlinks and use `O_NOFOLLOW`/`O_NONBLOCK` where supported; non-regular destinations are rejected.
- GitHub capture validates its output path before checking GitHub CLI authentication or making API requests. It rejects reserved preflight/governance audit filenames.

## Independent signer

The reviewer's private key and unsigned evidence must remain outside the repository. Their paths may not be symlinks. The signed output must also remain outside the repository and may not overwrite or alias the key or unsigned evidence.

## Limitations

These checks harden local path handling; they do not authenticate the repository host or make an untrusted workstation safe. The actual GitHub capture and hosted workflow still require a connected repository, read permissions and a separately configured independent trust anchor. No production activation is performed.
