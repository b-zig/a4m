---
id: ADR-0001
title: Use Proxmox VE for virtualisation
status: accepted
date: 2026-10-23
affects: [tech-pve-01, tech-proxmox-ve, tech-svc-vm-hosting, enterprise/mot-asm-single-host]
---

## Context

The home lab needs to run several isolated workloads (Docker host, Home Assistant OS,
Pi-hole) on a single mini PC, with snapshots and easy restore.

## Decision

Run Proxmox VE 8 on the host. Workloads run as KVM VMs (docker-01, haos) or LXC
containers (pihole).

## Consequences

- Snapshots and backups of whole guests become trivial.
- The single host is a single point of failure (enterprise/mot-asm-single-host); a second node
  would be needed for HA. That is out of scope for the home lab but relevant for the office.
