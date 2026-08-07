# Security policy

## Reporting a vulnerability

Do not open a public issue for suspected vulnerabilities. Report the affected
version, impact, reproduction steps, and any proposed mitigation through the
private security-reporting channel configured for the repository.

Until a public contact is configured, repository maintainers should enable
GitHub private vulnerability reporting before publishing this package.

## Supported versions

Security fixes are provided for the latest minor release. Older pre-1.0
versions may receive a patch only when an upgrade is not immediately practical.

## Response targets

These are remediation targets, not guarantees:

| Severity | Initial triage | Target remediation |
|---|---:|---:|
| Critical | 1 business day | 7 days |
| High | 3 business days | 30 days |
| Medium | 10 business days | 90 days |
| Low | Next planned release | Best effort |

A release may be delayed when a coordinated disclosure or upstream dependency
fix is required. Mitigations should be documented when the permanent fix cannot
meet the target.

## Release controls

CI performs dependency auditing, high/critical container scanning, and SPDX
SBOM generation. Production users remain responsible for scanning their final
application image, base image, infrastructure modules, and deployed services.

## Security boundaries

This package supplies application-level controls and integration points. It
does not replace authorization, network isolation, secret rotation, managed
database hardening, backup security, key management, data classification, or
incident response.
