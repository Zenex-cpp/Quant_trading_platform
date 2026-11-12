# V4.29 M25 Public Historical Data Import

**Status:** `TESTED`; infrastructure routing proof remains open. Binance Vision data is restricted to non-commercial historical research by the terms reviewed for this change.

## Change

Added an opt-in CLI command for daily USD-M Futures kline archives. It uses only HTTPS GET requests to the exact public archive host, disables ambient proxy configuration and redirects, bounds response and decompressed sizes, verifies the sibling SHA-256 checksum, validates the ZIP member and 12-column kline rows, and audits timestamp order, numeric values, OHLCV invariants, duplicates and daily candle coverage.

Each successful import writes a new content-addressed snapshot containing the original ZIPs, checksum sidecars, normalized UTC CSV and a manifest with archive URLs/hashes, dataset contract, coverage, quality results and terms URL. A reservation and atomic directory rename prevent an existing snapshot from being replaced. Missing archives and invalid data stop the import; incomplete candle coverage is marked `WARNING`.

Output paths inside the source repository are rejected so license-restricted market data cannot be added to the code checkout accidentally.

The command requires `--confirm-noncommercial-research`. The evidence manifest records that the source is for non-commercial historical research only. The source terms reviewed on 2026-11-11 say commercial use is excluded and prohibit live proprietary/commercial trading and paid signal distribution. This importer does not authorize these datasets for the platform's intended live/commercial trading path. Use a source with appropriate commercial licensing for that path.

## M25 boundary

The declarative network policy adds a separate `PUBLIC_MARKET_DATA` zone limited to `data.binance.vision`. Research remains deny-all. The public-data zone denies the configured Testnet and Production exchange hosts. The downloader additionally pins archive path construction to the USD-M daily kline tree and does not implement account, order, or exchange REST API methods.

The V391 policy and the importer are application controls. They do not prove that OS firewalls, VPC rules, container NetworkPolicy, DNS or routing tables enforce isolation. Therefore M25 remains `TESTED`, not `VERIFIED`, until infrastructure evidence is supplied and independently reviewed.

## M25 application-policy hardening — package 3.61.23

The zone decision now requires an exact allowlisted hostname, HTTPS or WSS, the default TLS port (443), and a URL without embedded username/password. Malformed ports, malformed endpoint inputs and invalid zone values fail closed. This prevents an application caller from treating an alternate service on a listed hostname as the same approved endpoint. The public-data importer still independently restricts its HTTPS transport to port 443, rejects redirects and disables proxies.

Focused tests cover default and explicit port 443, nonstandard HTTPS/WSS ports, embedded userinfo, malformed ports and invalid inputs. They use synthetic endpoint strings only and open no socket. These changes improve application policy checks but do not establish DNS/IP pinning, host firewall, VPC/container rules, or actual route separation; M25 remains `TESTED` pending independently reviewed infrastructure evidence.

The focused market-data, network-segmentation, M25 matrix/workflow and release-integrity regression passed **61 tests** on Windows/Python 3.14.7. No public archive was downloaded and no exchange endpoint was contacted.

The mandatory Windows/Python 3.14.7 V4.29 runner on package `3.61.23` passed with **1,343 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. `.audit/V429_M25_ENDPOINTS_FINAL_20261112.json` recorded `READY_FOR_MILESTONE`, `allowed=true`, `pipeline_status=PASS`, no blocking reasons, M18/M21/M25 in the impacted set and 165 input hashes. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.

## Verification

Automated tests use locally constructed ZIP fixtures and an injected fake transport. They perform no socket connections and download no market dataset. Coverage includes checksum mismatch, unsafe ZIP paths, malformed rows, bounded date ranges, immutable output collision, term acknowledgement, host allowlist, proxy/redirect configuration, CLI behavior and M25 zone isolation.

Focused importer, segmentation, workflow-contract, compliance-matrix and release-integrity regressions: **43 passed**. Full Windows/Python 3.14.7 V4.29 runner: **1,255 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. M25 was included in the impacted set; preflight returned `READY_FOR_MILESTONE`, `allowed=true`, with no blocking reasons.

No Binance market data was downloaded. No proprietary dataset or trading-edge evidence was created, and no order or production deployment was activated. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.
