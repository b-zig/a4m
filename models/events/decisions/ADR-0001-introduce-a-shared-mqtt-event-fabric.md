---
id: ADR-0001
title: Introduce a shared MQTT event fabric
status: proposed
date: 2026-10-23
affects: [app-mqtt-broker, app-svc-event-streaming, infra-art-mosquitto, compute/infra-docker, home-automation/app-home-assistant, media/app-jellyfin]
---

## Context

Home Assistant integrates with each device and service point to point (polling Jellyfin,
vendor clouds for sensors). Every new integration is another custom connection, and events
cannot be reused by a second consumer.

## Decision

Run one Mosquitto broker as a platform SA (`events`) on the shared Docker VM. Producers
publish to `home/<source>/<event>`; consumers subscribe. Each consuming SA declares its own
use of `events/app-svc-event-streaming` or `events/app-mqtt-broker`.

## Consequences

- New integrations publish once; any number of SAs can subscribe.
- The broker becomes a shared dependency: `python3 -m a4m impact events` lists who relies on it.
- Another container on docker-01, which is already a single point of failure (compute ADR-0001).
