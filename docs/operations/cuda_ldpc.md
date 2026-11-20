# CUDA Uplink PUSCH and LDPC

This optional candidate runs CUDA uplink processing on **both DU1 and DU2**
on the DGX Spark GB10. The existing CPU CU, FlexRIC, xApp and broker remain
the control and telemetry path. Normal startup without `--cuda` selects the
existing CPU DUs.

The deployed OCUDU checkout has no CUDA LDPC switch. The candidate uses the
upstream [CUDA acceleration integration](https://gitlab.com/ocudu/work_groups/wg1_hw_accel/cuda_accelerated_ocudu),
pinned to `4df349bf66abad4047537aa519331ed79da91567`, with the retained Falcon
identity/KPM changes and a Clang compatibility fix in
[`cuda_ldpc_integration.patch`](../../patches/ocudu/cuda_ldpc_integration.patch).
The isolated build does not replace `build-integrated` or install a driver.

## Scope

The selected upstream path combines GPU PUSCH demodulation/equalization,
rate recovery and LDPC decoding. It is **not an LDPC-only YAML switch**.
Keeping the soft bits on the GPU avoids an additional CPU/GPU round trip.
The [upstream decoder contribution](https://gitlab.com/ocudu/ocudu/-/merge_requests/1566)
alone contains kernels; its live PUSCH caller is a separate part of the
integration.

The [uplink overlay](../../configs/ocudu/cuda_uplink.yml) requires PUSCH
acceleration on GPU 0. PDSCH, PRACH, SRS and SDR lower-PHY transforms are
explicitly kept on their CPU paths. The candidate preserves the CPU route
for unsupported PUSCH cases and HARQ retransmissions; enabling CUDA does not
mean every transport block executes only on the GPU. Resident failed first
transmissions must export their soft bits for the CPU HARQ-combining path.

The newer upstream FAPI carries optional floating-point RF measurements rather
than the older fixed-point encoding. Metric names and missing-value meaning
are retained, but RF measurement precision can differ from the deployed CPU
build. Producer tests cover missing measurements, real zeros, both SINR signs
and failed-CRC forwarding through the production translators.

The overlay does not specify frequency, bandwidth, sample rate, TDD pattern,
gain, cell identity or USB serial. It inherits the current deployed YAML:
DU1 20 MHz / 23.04 MS/s / TX 70 / RX 25 and DU2 40 MHz / 46.08 MS/s /
TX 60 / RX 35. Keep the same radio configuration when comparing CPU and CUDA.

## Build and offline validation

Spark currently has CUDA toolkit 13.0 and an available GB10 GPU. The build
targets CUDA architecture `121`. Run as the normal user; no RAN processes
are started by this command:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 -B scripts/cuda_ldpc/build.py
```

Default locations:

- Source: `/tmp/falcon-ocudu-cuda-upstream` (recreated from the pinned revision
  if removed after reboot).
- Build: `/home/nyu/ocudu/build-cuda-upstream`.
- Test logs: `build-cuda-upstream/falcon-validation/`.
- Acceptance manifest: `build-cuda-upstream/falcon-cuda-validation.json`.

The builder refuses to reset an existing checkout at an unexpected revision.
It applies the pinned patch, compiles the DU and tests at low CPU priority,
then runs GPU LDPC tests, HARQ soft-bit tests, the retained E2/KPM tests and
scheduler/FAPI producer tests.
Generated 1-layer, 1-RX-port PUSCH comparisons cover 51 and 106 PRBs, with
100 measured iterations each, 20 warmup iterations and an explicit
resident-GPU requirement. The comparisons use GB10 high-capacity CPU groups
5–9 and 15–19 to avoid migration between different core types.
The comparisons also run concurrently in two independent GPU processes,
matching the two-DU context-sharing arrangement without opening the radios.
It also parses both deployed DU configurations with the overlay without
opening either radio. A successful manifest binds the tested DU binary and
overlay hashes. Missing, failed or stale validation prevents `--cuda` startup.

To repeat validation of an already compiled candidate:

```bash
python3 -B scripts/cuda_ldpc/build.py --validate-only
```

Offline decoding correctness and kernel latency do not establish an OTA
uplink throughput improvement. The upstream Spark measurements show that
small, single-layer workloads can have higher GPU latency than CPU latency;
see the [architecture and measurements](https://arxiv.org/abs/2608.04338).

## Recorded offline result: November 2, 2026

The candidate passed 714 LDPC cases (510 intentionally inapplicable parameter
cases skipped), 11 HARQ/code-block cases, 32 E2/KPM cases and 26 scheduler/FAPI
producer cases. The launcher has 33 passing offline configuration/process/PTY tests.
All four PUSCH comparisons decoded
100/100 transport blocks on both CPU and GPU, with zero payload mismatches
and resident GPU processing confirmed for every measured GPU iteration.

The timing comparison used 30-kHz SCS, one layer, one RX port, MCS 20 from
the qam64 table, 30-dB synthetic SINR, 20 warmup iterations and the fixed CPU
groups above. CPU and GPU routes came from the same Release candidate build.
These are preliminary mean processing latencies, not OTA throughput results.

| Workload | CPU mean (microseconds) | CUDA mean (microseconds) |
| --- | ---: | ---: |
| DU1 shape, 51 PRBs, alone | 196.9 | 339.0 |
| DU2 shape, 106 PRBs, alone | 209.7 | 250.6 |
| DU1 shape, both GPU processes active | 194.2 | 535.8 |
| DU2 shape, both GPU processes active | 224.3 | 241.8 |

CUDA was slower for these current 1-layer profiles, especially DU1 when both
processes shared the GPU. No uplink performance improvement is established.
Keep normal CPU startup as the baseline; `--cuda` is an explicit experimental
option for the requested two-DU trial. Reproduction logs and hashes are in
the local validation directory and manifest above.

## Start both DUs with CUDA uplink

Finish the current CPU run normally with Ctrl+C before starting a new run.
From the Spark terminal:

```bash
cd /home/nyu/Desktop/Falcon_repo/Falcon
python3 -B scripts/spark_auto.py --check --cuda
sudo python3 -B scripts/spark_auto.py --cuda
```

Each DU must print `CUDA_PUSCH_READY device=0 resident_ldpc=true` before its
`[READY]` stage. Its native initialization message is required, in addition
to the normal E2/F1 checks. `status` shows `uplink=cuda_ready` for both DUs.
This indicates successful backend initialization, not a per-packet GPU-usage
counter. MPTCP registers with the same xApp broker and uses the same report
contract. Gain commands still control DU2 only.

Stop with Ctrl+C or `stop`, as in the [auto startup guide](../spark_auto.md).
To return to the existing CPU DUs, start again without `--cuda`:

```bash
sudo python3 -B scripts/spark_auto.py
```

## Live acceptance

Compare CPU and CUDA runs with the same gains, RF path, TDD pattern, UE
placement, traffic direction/duration and MPTCP workload. Retain per-link
uplink throughput, retransmissions/CRC failures, DU processing latency,
late/underflow warnings, GPU activity and the 100-ms KPM cadence. Include
simultaneous traffic on both DUs to exercise shared-GPU contention and HARQ
recovery. Keep test evidence local under the experiment archive policy.

The earlier DU1 `LIBUSB_TRANSFER_ERROR` is a separate USB transport fault.
CUDA decoding does not repair USB disconnects or missing radio samples.
