# Spark dual-TUN migration archive — 2026-10-23

This directory preserves 15 files byte-for-byte from the prepared bundle
`/tmp/falcon-dual-tun-c8f9f749`. The operator successfully applied it on
`spark-7c40`, creating `ogstun_1 / 10.45.0.1/16` and
`ogstun_2 / 10.46.0.1/16`, both with MTU 1400.

See the [migration and rollback guide](../../../../docs/networking/dual_ue_tun_split.md)
and [retained evidence](../../../../docs/evidence/2026-10-23_dual_tun_split/manifest.json).

| Artifact | Purpose |
| --- | --- |
| `apply.sh` | Captured migration and automatic rollback attempt on failure |
| `rollback.sh` | Restores the shared-`ogstun` state with both IPv4 addresses |
| `guard.py` | Checks files, TUN ownership, routes, services and baseline routing |
| `original/` | Pre-migration UPF, unchanged SMF and original networkd files |
| `prepared/` | Five deployed UPF/networkd configuration files |
| `manifest.json`, `source.json` | Intended layout and configuration hashes |
| `baseline.json` | Pre-migration management default route and IPv4 policy rules |
| `archive.sha256` | SHA-256 values for the 15 preserved files; excludes this README |

Run `sha256sum -c archive.sha256` from this directory to check the snapshot.
The deployed backup is `/var/backups/falcon-dual-tun-c8f9f749`.

This bundle is specific to the captured host/configuration and is already
applied. Do not rerun `apply.sh` on the current Spark. Live rollback, automatic
failure recovery, post-split UE traffic and cold-boot validation remain untested.
