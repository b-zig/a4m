---
id: ADR-0001
title: Move off-site backups from Backblaze B2 to a Hetzner Storage Box
status: accepted
date: 2026-10-23
affects: [app-offsite-b2, app-offsite-hetzner, app-backup, enterprise/bus-req-backup]
---

## Context

Off-site snapshots go to Backblaze B2 (S3 API, US region, priced per GB and per download).
Restores of the full photo library are slow and cost egress.

## Decision

Copy restic snapshots to a Hetzner Storage Box (EU, flat monthly price, SFTP). Keep B2
until two full restore tests from Hetzner have succeeded, then retire it.

## Consequences

- Predictable cost; data stays in the EU (enterprise/bus-drv-privacy).
- One more credential to manage; the restore runbook changes.
- Once B2 is retired: delete `app-offsite-b2` and its Flow, and set the Hetzner items to `state: existing`.
