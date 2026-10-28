---
id: ADR-0001
title: Add Jellyfin as the family media server
status: proposed
date: 2026-10-23
affects: [app-jellyfin, infra-art-jellyfin, compute/infra-docker, nextcloud/data-files]
---

## Context

Family videos sit in Nextcloud but are awkward to watch on the TV. Streaming services do not
cover home videos, and the data should stay at home (enterprise/bus-drv-privacy).

## Decision

Run Jellyfin as a container on the shared Docker VM (compute platform), reading the media
folders of the Nextcloud data read-only.

## Consequences

- One more container on docker-01, which is already a single point of failure.
- Transcoding load on the Proxmox host; hardware transcoding needs GPU passthrough.
