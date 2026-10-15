# Configuration Precedence Matrix

| Precedence | Class | Authority | Production rule |
|---:|---|---|---|
| 50 | SAFETY_OVERRIDE | hard safety control | cannot be weakened by lower precedence |
| 40 | RUNTIME | explicitly scoped runtime control | audited, TTL where applicable |
| 30 | ENVIRONMENT | environment variable | provenance captured |
| 20 | CONFIG_FILE | versioned configuration | immutable by version |
| 10 | DEFAULT | code default | baseline only |

Equal-precedence conflicting values produce CONFIG_CONFLICT and block live decisions.
