# V4.24 Recovery/Lineage Note

The build runtime contained the complete `trading_platform_v4_18.tar.gz` archive and V4.22/V4.23 release reports, but did **not** contain `trading_platform_v4_23.tar.gz` or the corresponding V4.22/V4.23 source worktrees. The V4.23 report files describe the prior design (milestone preflight, controlled runner and GitHub Actions contract) but are not a substitute for the missing source archive.

Accordingly, this is a **V4.24 recovery build** reconstructed from the last code archive actually present (V4.18) with the documented V4.22/V4.23 preflight/runner contracts reimplemented and the V4.24 remote-governance evidence verifier added. It is not represented as a byte-for-byte continuation of an unavailable V4.23 repository. The original V4.23 report's 1,164-test result is historical and is not claimed for this recovered worktree.

Measured results in `V424_VERIFICATION_REPORT.md` apply only to the actual source tree and final archive produced by this recovery build. To establish canonical lineage from the previous claimed release, merge or rebase these changes onto the original V4.23 source archive when it is available, then rerun the controlled pipeline and rebuild all hashes.
