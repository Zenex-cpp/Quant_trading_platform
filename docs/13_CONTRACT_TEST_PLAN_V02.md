# V0.2 Contract Test Plan

Critical automated tests introduced:
- UNKNOWN position blocks new risk;
- reservation cannot be double-consumed;
- risk degradation is monotone non-increasing;
- state transition replay is side-effect free;
- equal-precedence config conflict blocks;
- duplicate fill does not double count;
- failed assumptions return METHOD_NOT_APPLICABLE.

These are implementation tests, not independent VERIFIED evidence.
