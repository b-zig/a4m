---
id: ADR-0001
title: Run Nextcloud as Docker containers on a dedicated VM
status: accepted
date: 2026-10-23
affects: [app-nextcloud, app-nextcloud-web, app-nextcloud-db, app-nextcloud-cache, compute/infra-vm-docker, compute/infra-docker]
---

## Context

Nextcloud needs PHP, a database and a cache. Installing them on the host makes upgrades
risky and couples them to the OS.

## Decision

Run the official images (nextcloud:29-apache, mariadb:11, redis:7) with Docker Compose on
VM docker-01. User files live on the NAS via NFS.

## Consequences

- Upgrades are image bumps; rollback is a VM snapshot.
- NAS availability now affects Nextcloud (compute/infra-svc-nfs).
