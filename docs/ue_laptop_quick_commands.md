# UE Laptop Quick Commands

Updated: 2026-10-12. Run these steps in order in **one Bash terminal per UE on the laptop** and keep that UE's variables in its terminal. Continue only after each step succeeds. For full instructions, see [Runbook stages 10–14](full_reproduction_runbook.md#10-prepare-a-new-ubuntulinux-laptop); start Spark using [Spark Quick Commands](spark_quick_commands.md).

For the DU1 migration to **3660 MHz**, use the recorded **PCI 1 / SSB 643680 / SCS 30 kHz / n78** lock in step 2 after comparing it with the current DU startup cell line. This tuple comes from the operator-provided 2026-10-12 startup summary. Historical 3750-MHz traffic/KPM results below do not establish acceptance at the new carrier. The matching subscriber must be prepared for the SIM actually installed; using the new SIM1 requires its own core record.

The 2026-10-05 session verified single-UE registration, IPv4 connectivity, and an initial 10-second TCP uplink. The 2026-10-07 session verified five DU KPM measurements from a real UE. After the timestamp repair, the latest run received 12 reports for UE ID `7`, with `report_age_us` of **591–796 µs**, and the xApp exited normally. The ping and 30-second uplink/downlink commands below are further acceptance checks, not results demonstrated in this session.

## 0 Select the SIM and subscriber plan

Open Cells SIM provisioning, Milenage authentication, and Quectel USIM-readiness checks are complete for both cards. The new IMSIs have **not yet registered with the RAN/Open5GS**. The earlier single-link baseline used IMSI `001010000000001`; its traffic/KPM evidence does not establish registration of the new cards.

| Intended UE / DU | Card | IMSI | Observed modem IMEI |
| --- | --- | --- | --- |
| UE1 / DU1 | OC011830 | `001010000000101` | `863305041978437` |
| UE2 / DU2 | OC011831 | `001010000000102` | `863305041980706` |

Before connecting either new UE, prepare its matching Open5GS subscriber using the protected `~/sim_du1_credentials.txt` or `~/sim_du2_credentials.txt`, SST 1, DNN `internet`, and IPv4 session type 1. K/OPc must remain private. The utility recommended SQN reference `96` after its authentication test; verify the installed core's representation and current SQN before using it. See [SIM assignments](sim_provisioning_and_dual_ue.md#sim-assignments), [subscriber preparation](sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers), and [dual-path validation](sim_provisioning_and_dual_ue.md#validate-two-ue-paths).

Do not select a second modem in a terminal retaining the first UE's bearer/WWAN variables. Separate terminals protect variables, but share the laptop's routing tables. The single-link route recipe below does **not** implement two simultaneous IP paths or MPTCP.

## 1 Install tools and select the modem

Install these tools on a new laptop; skip this if they are already installed:

```bash
sudo apt update
sudo apt install -y modemmanager libqmi-utils minicom iproute2 iperf3 usbutils psmisc
sudo systemctl enable --now ModemManager
```

Connect the RM500Q-GL, test USIM, antennas, data USB, and auxiliary power to the RMU500EK. Verified firmware: `RM500QGLABR13A03M4G`. If ports are missing, see [Driver checks](software_installation_and_drivers.md#72-kernel-driver-responsibilities).

Define these functions once in each UE terminal. The following identity-selection wrapper is a reproduction procedure; the reported session tested the underlying `mmcli` commands. Select by the intended IMEI or device identifier, not the first modem path:

```bash
mm_value() {
  awk -F ':' -v key="$1" '
    { field=$1; gsub(/^[ \t]+|[ \t]+$/, "", field) }
    field==key { sub(/^[^:]*:[ \t]*/, ""); sub(/[ \t]+$/, ""); print; exit }
  '
}

select_rm500q() {
  local listing path details model identity imei
  local -a candidates=() matched=()
  if [ -n "${BEARER:-}" ] || [ -n "${WWAN_IF:-}" ]; then
    printf 'This terminal retains a UE bearer/WWAN; finish cleanup and use a fresh UE terminal.\n'
    return 1
  fi
  MODEM=""
  listing=$(mmcli -L) || return 1
  mapfile -t candidates < <(printf '%s\n' "$listing" |
    awk '/RM500Q/ { print }' | grep -oE '/org/freedesktop/ModemManager1/Modem/[0-9]+')
  if [ ${#candidates[@]} -eq 0 ]; then
    printf 'No RM500Q found; check USB and drivers before retrying.\n'; return 1
  fi
  read -r -p 'Expected RM500Q IMEI or device identifier: ' EXPECTED_MODEM_ID
  [ -n "$EXPECTED_MODEM_ID" ] || return 1
  for path in "${candidates[@]}"; do
    details=$(mmcli -m "$path" -K) || return 1
    model=$(printf '%s\n' "$details" | mm_value modem.generic.model)
    identity=$(printf '%s\n' "$details" | mm_value modem.generic.device-identifier)
    imei=$(printf '%s\n' "$details" | mm_value modem.generic.equipment-identifier)
    printf 'candidate=%s imei=%s identity=%s\n' "$path" "$imei" "$identity"
    if [[ "$model" = *RM500Q* && -n "$identity" && "$identity" != -- ]] &&
       [[ "$EXPECTED_MODEM_ID" = "$imei" || "$EXPECTED_MODEM_ID" = "$identity" ]]; then
      matched+=("$path")
    fi
  done
  if [ ${#matched[@]} -ne 1 ]; then
    printf 'Expected identity matched %s modems; stop and inspect.\n' "${#matched[@]}"; return 1
  fi
  MODEM=${matched[0]}
  MODEM_KV=$(mmcli -m "$MODEM" -K) || { MODEM=""; return 1; }
  MODEM_IDENTITY=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.device-identifier)
  imei=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.equipment-identifier)
  if [[ "$EXPECTED_MODEM_ID" != "$imei" && "$EXPECTED_MODEM_ID" != "$MODEM_IDENTITY" ]]; then
    MODEM=""; printf 'Device identity changed; stop here.\n'; return 1
  fi
  printf 'modem=%s imei=%s firmware=%s\n' "$MODEM" "$imei" \
    "$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.revision)"
}
select_rm500q
```

If the modem is disabled, run `sudo mmcli -m "$MODEM" --enable`. Rediscover modem, SIM, and bearer IDs instead of reusing historical numbers.

### 1a Read the inserted SIM and USIM state

Use the selected modem's actual SIM path and `(qmi)` port. This wrapper is a read-only reproduction procedure, not an additional test result:

```bash
MODEM_KV=$(mmcli -m "$MODEM" -K)
SIM_PATH=$(printf '%s\n' "$MODEM_KV" | mm_value modem.generic.sim)
if [[ "$SIM_PATH" =~ ^/org/freedesktop/ModemManager1/SIM/[0-9]+$ ]] && \
   SIM_KV=$(mmcli -i "$SIM_PATH" -K); then
  printf 'SIM active=%s IMSI=%s ICCID=%s operator=%s name=%s\n' \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.active)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.imsi)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.iccid)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.operator-code)" \
    "$(printf '%s\n' "$SIM_KV" | mm_value sim.properties.operator-name)"
else
  printf 'No valid SIM readout for the selected modem; stop here.\n'
fi
mapfile -t QMI_PORTS < <(printf '%s\n' "$MODEM_KV" |
  grep -oE 'cdc-wdm[0-9]+ \(qmi\)' | awk '{print $1}' | sort -u)
if [ ${#QMI_PORTS[@]} -eq 1 ]; then
  QMI_PORT=${QMI_PORTS[0]}
  if QMI_STATUS=$(sudo qmicli -p -d "/dev/$QMI_PORT" --uim-get-card-status); then
    printf '%s\n' "$QMI_STATUS" | awk '/Card state:|Application type:|Application state:|Personalization state:|PIN1 state:|PIN2 state:/ {print}'
  else
    printf 'USIM query failed; stop and inspect.\n'
  fi
else
  printf 'Expected one QMI port on this modem; found %s. Stop and inspect.\n' "${#QMI_PORTS[@]}"
fi
```

Match IMSI/ICCID to the intended card before continuing. Require card present, application `usim`, application/personalization ready, and PIN1 disabled. PIN2 `enabled-not-verified` did not prevent the reported checks and does not currently require modification. SIM readiness is not network registration: `searching / detached`, even with signal quality around 88%, is not evidence of private PLMN `00101` attachment. See [Quectel verification](sim_provisioning_and_dual_ue.md#verify-the-cards-through-quectel).

For a SIM swap: finish traffic and bearer cleanup, disable the selected modem with `sudo mmcli -m "$MODEM" --disable`, physically power off/disconnect the RMU, swap the card, and reconnect power. Open a fresh UE terminal and rediscover identity, modem/SIM IDs, and ports. Do not hot-swap or reuse a cached modem number.

## 2 Configure NR SA and lock the private cell

The lock in this stage is **DU1 only**. DU2's radio and final settings remain pending; do not reuse this lock as a DU2 template. An IMSI does not select a DU automatically. Check that the current startup cell line in [Spark step 5](spark_quick_commands.md#5-start-du-with-e2-enabled) matches carrier `644000` / 3660 MHz, PCI `1`, and SSB `643680`. After a carrier migration, replace the old lock even if the modem still displays registration. Skip configuration only when the readback and serving cell already match the current DU.

SSB `643680` is deterministic for the current cell configuration and derivation logic; restarting DU or reconnecting UE does not select a random SSB. Recheck it after changing the carrier, band, bandwidth, SCS, SSB/CORESET parameters, or OCUDU version. If startup differs from the recorded tuple, update the lock from the actual output before using it.

ModemManager can omit working AT ports. On the reported Alienware m15-R6, the selected RM500Q exposed ttyUSB0–3 in Linux while ModemManager listed only an ignored ttyUSB0, GPS ttyUSB1, QMI and network ports; manual AT communication still worked. That observation does not assign fixed tty numbers to UE1 or UE2.

Use the modem already selected in step 1. The block below lists only this modem's ttyUSB ports by matching their sysfs USB parent, skips GPS/QCDM/ignored ports, and prefers any ports explicitly marked `(at)`. You choose a displayed port; a candidate is not proof of an AT response. It checks existing serial locks and process ownership before opening minicom. `fuser` is supplied by Ubuntu's `psmisc` package.

Copy and run the block in the same UE Bash terminal:

```bash
open_rm500q_at() {
  local details identity imei usb tty parent port chosen owners status
  local -a ports=() preferred=()
  AT_PORT=""
  [[ -n "${MODEM:-}" && -n "${MODEM_IDENTITY:-}" && -n "${EXPECTED_MODEM_ID:-}" ]] || return 1
  details=$(mmcli -m "$MODEM" -K) || return 1
  identity=$(printf '%s\n' "$details" | mm_value modem.generic.device-identifier)
  imei=$(printf '%s\n' "$details" | mm_value modem.generic.equipment-identifier)
  if [[ "$identity" != "$MODEM_IDENTITY" || ( "$EXPECTED_MODEM_ID" != "$identity" && "$EXPECTED_MODEM_ID" != "$imei" ) ]]; then
    printf 'Modem changed; rerun select_rm500q.\n'; return 1
  fi
  usb=$(readlink -e "$(printf '%s\n' "$details" | mm_value modem.generic.device)") || return 1
  [[ -f "$usb/idVendor" ]] || { printf 'Cannot confirm USB parent; stop here.\n'; return 1; }
  printf 'Selected modem: %s\nIMEI: %s\nUSB parent: %s\n' "$MODEM" "$imei" "$usb"
  for tty in /sys/class/tty/ttyUSB*; do
    parent=$(readlink -e "$tty/device") || continue
    while [[ "$parent" != / && ! -f "$parent/idVendor" ]]; do parent=${parent%/*}; done
    [[ "$parent" = "$usb" ]] || continue
    port=/dev/${tty##*/}
    [[ -c "$port" ]] || continue
    if printf '%s\n' "$details" | grep -Eq "(${tty##*/}[[:space:]]*\((gps|qcdm|ignored)\)|ignored-ports[^:]*:.*\b${tty##*/}\b)"; then
      printf 'Skip %s (GPS/QCDM/ignored).\n' "$port"; continue
    fi
    ports+=("$port")
    if printf '%s\n' "$details" | grep -Eq "${tty##*/}[[:space:]]*\(at\)"; then preferred+=("$port"); fi
  done
  if [ ${#preferred[@]} -gt 0 ]; then ports=("${preferred[@]}"); fi
  [ ${#ports[@]} -gt 0 ] || { printf 'No eligible port on this modem; inspect enumeration.\n'; return 1; }
  printf 'Candidate ports (AT response not yet checked):\n'; printf '  %s\n' "${ports[@]}"
  read -r -p 'Enter one candidate, including /dev/: ' chosen
  [[ " ${ports[*]} " = *" $chosen "* && -c "$chosen" ]] || { printf 'Choose a displayed port.\n'; return 1; }
  if [[ -e "/run/lock/LCK..${chosen##*/}" || -L "/run/lock/LCK..${chosen##*/}" ]]; then
    printf 'Serial lock exists; close your own session before retrying.\n'; return 1
  fi
  command -v fuser >/dev/null || { printf 'Install psmisc for fuser before continuing.\n'; return 1; }
  if owners=$(sudo fuser -- "$chosen" 2>&1); then
    printf 'Port is in use; stop here: %s\n' "$owners"; return 1
  else
    status=$?
    [[ "$status" -eq 1 && -z "$owners" ]] || { printf 'Cannot check port ownership: %s\n' "$owners"; return 1; }
  fi
  AT_PORT=$chosen
  sudo minicom -o -D "$AT_PORT" -b 115200
}
open_rm500q_at
```

In minicom, type **`AT`** first and require a real **`OK`** before continuing. If no response arrives within a few seconds, exit with `Ctrl+A`, then `Q`, rerun `open_rm500q_at`, and choose another candidate. Do not infer AT capability from tty numbering or change modem configuration to test a port.

Keep ModemManager running. Missing `(at)` entries alone require no reboot or `AT+CFUN`. After USB reconnection, rerun `select_rm500q` and rediscover ports. Open one AT session at a time; `minicom -o` skips initialization and lock-file checks, so keep the ownership checks above and coordinate access. The check does not reserve the port until minicom opens it. Explicitly GPS/QCDM/ignored ports need separate evidence of AT capability before manual use.

Enter these commands in minicom, **not in Bash**. Each configuration write must return `OK`:

```text
AT
AT+QNWPREFCFG="mode_pref",NR5G
AT+QNWPREFCFG="mode_pref"
AT+QNWPREFCFG="nr5g_disable_mode",2
AT+QNWPREFCFG="nr5g_disable_mode"
AT+QNWPREFCFG="nr5g_band"
AT+QNWLOCK="common/5g",1,643680,30,78
AT+QNWLOCK="common/5g"
AT+QENG="servingcell"
AT+C5GREG?
```

Confirm that the band selection includes 78, the readback matches `PCI=1 / SSB=643680 / SCS=30 / n78` and the current DU startup, the serving cell is `NR5G-SA / 001,01 / TAC 7` on the intended DU1 cell, and registration reports `+C5GREG: 0,1`. `NOCONN` can indicate an idle, camped state; use C5GREG to confirm registration. **Historical SSB `649632` applies to the old 3750-MHz setup. Neither it nor the new carrier ARFCN `644000` is the new SSB lock value.** If the new lock write fails, stop and inspect firmware/AT responses before proceeding to the bearer steps.

On this tested firmware, disable mode `2` disables NSA. Exit minicom with `Ctrl+A`, then `X`. Close duplicate AT sessions and leave ModemManager running.

Use the optional reboot command `AT+CFUN=1,1` only when needed. After USB enumeration, run `select_rm500q` again, rediscover the AT port, and reapply or check the preferences and cell lock above. **Do not reboot the modem after the final cell lock.**

## 3 Check registration and connect IPv4

Show only the registration fields:

```bash
mmcli -m "$MODEM" -K | awk -F ':' '
  /modem\.generic\.(state|access-technologies)(\.value\[[0-9]+\])?[[:space:]]*:/ ||
  /modem\.3gpp\.(operator-code|registration-state|packet-service-state)[[:space:]]*:/ {print}
'
```

Require `5gnr / 00101 / home / attached`, with state registered or connected. Then create an **IPv4** PDU session for `internet`:

```bash
sudo mmcli -m "$MODEM" --simple-connect="apn=internet,ip-type=ipv4"
```

If this fails, stop and see the [PDU/IPv4v6 troubleshooting record](troubleshooting/2026-10-05_sa_bringup.md#10-pdu-root-cause-ipv4v6-rejected-by-ocudu). The subscriber on Spark must use session type `1`. The EPS initial bearer may still display IPv4v6; that display does not need changing.

## 4 Find the active bearer and configure dedicated WWAN

Find the **connected + internet** bearer belonging to the selected modem, rather than using the EPS initial bearer. Stop if several bearers match; do not guess an ID:

```bash
BEARER=""
matches=()
discovery_ok=yes
if MODEM_KV=$(mmcli -m "$MODEM" -K); then
  for path in $(printf '%s\n' "$MODEM_KV" |
    grep -oE '/org/freedesktop/ModemManager1/Bearer/[0-9]+' | sort -u); do
    details=$(mmcli -b "$path" -K) || { discovery_ok=no; break; }
    connected=$(printf '%s\n' "$details" | mm_value bearer.status.connected)
    apn=$(printf '%s\n' "$details" | mm_value bearer.properties.apn)
    if [ "$connected" = yes ] && [ "$apn" = internet ]; then matches+=("$path"); fi
  done
else
  discovery_ok=no
fi
if [ "$discovery_ok" = yes ] && [ ${#matches[@]} -eq 1 ] && \
   BEARER_KV=$(mmcli -b "${matches[0]}" -K); then
  BEARER=${matches[0]}
  UE_CONNECTED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.connected)
  UE_SUSPENDED=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.suspended)
  WWAN_IF=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.status.interface)
  UE_IP=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.address)
  UE_PREFIX=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.prefix)
  UE_MTU=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.mtu)
  UE_METHOD=$(printf '%s\n' "$BEARER_KV" | mm_value bearer.ipv4-config.method)
  printf 'bearer=%s connected=%s suspended=%s if=%s IPv4=%s/%s mtu=%s method=%s\n' \
    "$BEARER" "$UE_CONNECTED" "$UE_SUSPENDED" "$WWAN_IF" "$UE_IP" "$UE_PREFIX" "$UE_MTU" "$UE_METHOD"
else
  printf 'No unique usable bearer found (discovery=%s, matches=%s); stop and inspect.\n' "$discovery_ok" "${#matches[@]}"
fi
```

Require `connected=yes / suspended=no / static`. Historical values were `wwan0 / 10.45.0.2/30 / MTU 1400`; configure the interface using the values just read. ModemManager supplies the IP parameters, but the host interface still needs configuration.

These commands apply only to a dedicated QMI WWAN interface. If a NetworkManager cellular profile is active, first resolve which component owns WWAN configuration; retain management Wi-Fi and NetworkManager. The script refuses changes when the interface carries a default route, the SSH management path, or another IPv4 address.

```bash
configure_wwan() {
  local current_ips mgmt_dev driver host_devs
  [[ -n "$BEARER" && "$UE_CONNECTED" = yes && "$UE_SUSPENDED" = no && "$UE_METHOD" = static ]] || return 1
  [[ "$UE_IP" =~ ^10\.45\.([0-9]{1,3})\.([0-9]{1,3})$ ]] || return 1
  (( 10#${BASH_REMATCH[1]} <= 255 && 10#${BASH_REMATCH[2]} <= 255 )) || return 1
  [[ "$UE_IP" != 10.45.0.1 && "$UE_PREFIX" =~ ^[0-9]+$ && "$UE_MTU" =~ ^[0-9]+$ ]] || return 1
  (( UE_PREFIX >= 1 && UE_PREFIX <= 32 && UE_MTU >= 576 && UE_MTU <= 65535 )) || return 1
  [[ "$WWAN_IF" =~ ^(wwan|wwp|rmnet)[[:alnum:]_.-]*$ ]] || return 1
  ip link show dev "$WWAN_IF" >/dev/null || return 1
  driver=$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")
  [[ "$driver" = qmi_wwan ]] || return 1
  printf '%s\n' "$MODEM_KV" | grep -Fq "$WWAN_IF (net)" || return 1
  [[ -z "$(ip -4 route show default dev "$WWAN_IF")" &&
     -z "$(ip -6 route show default dev "$WWAN_IF")" ]] || return 1
  if [ -n "$SSH_CONNECTION" ]; then
    mgmt_dev=$(ip route get "${SSH_CONNECTION%% *}" | awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}')
    [[ -n "$mgmt_dev" && "$mgmt_dev" != "$WWAN_IF" ]] || return 1
  fi
  current_ips=$(ip -o -4 addr show dev "$WWAN_IF" | awk '{print $4}')
  [[ -z "$current_ips" || "$current_ips" = "$UE_IP/$UE_PREFIX" ]] || return 1
  host_devs=$(ip -4 route show exact 10.45.0.1/32 |
    awk '{for(i=1;i<NF;i++) if($i=="dev") print $(i+1)}' | sort -u)
  if [[ -n "$host_devs" && "$host_devs" != "$WWAN_IF" ]]; then
    printf 'The private host route belongs to another interface; dual-path routing must be planned first.\n'
    return 1
  fi
  sudo ip link set dev "$WWAN_IF" mtu "$UE_MTU" up &&
  sudo ip -4 addr replace "$UE_IP/$UE_PREFIX" dev "$WWAN_IF" noprefixroute &&
  sudo ip -4 route replace 10.45.0.1/32 dev "$WWAN_IF" src "$UE_IP"
}
if configure_wwan; then
  ip -4 route get 10.45.0.1 from "$UE_IP"
  ip -4 route show default
else
  printf 'WWAN configuration is incomplete; check the bearer, dedicated interface, and management routes before testing.\n'
fi
```

This guarded route-ownership check is a reproduction procedure. It refuses to replace another interface's active private path. The route to `10.45.0.1` must use `$WWAN_IF` and `$UE_IP`, with the Wi-Fi default route retained. This adds only a private host route; it does not add a default route, NAT, or MASQUERADE.

## 5 Check ping, traffic, and KPM

Show the ping summary while keeping errors visible:

```bash
ping -q -I "$WWAN_IF" -c 5 10.45.0.1
```

Require `0% packet loss`. Give Spark the actual `UE_IP` from the bearer summary for a reverse ping. Start `iperf3 -s -B 10.45.0.1` on Spark first.

Run these **one at a time**, keeping the final sender/receiver summaries:

```bash
# Uplink: UE -> Spark, 30 seconds (not yet verified)
iperf3 -c 10.45.0.1 -B "${UE_IP:?Use the terminal where WWAN was configured}" -t 30 -i 0

# Downlink: Spark -> UE, 30 seconds (not yet verified)
iperf3 -c 10.45.0.1 -B "${UE_IP:?Use the terminal where WWAN was configured}" -R -t 30 -i 0
```

The repaired KPM library and monitor are installed and verified to match the new build. Keep **CU, DU, and FlexRIC** running on Spark; the existing iperf server can stay running. Start the 30-second uplink above in the UE terminal where WWAN was configured, then **immediately run the newly installed `xapp_oran_moni` for about 10 seconds on Spark**. See [Spark verification after installation](spark_quick_commands.md#7a-verify-reports-after-the-timestamp-repair). Require `report_age_us`, a UE ID, KPM values, and a normal exit.

The earlier 2026-10-07 run received measurements for UE ID `14`. After the repair, UE ID `2` and the later UE ID `7` each produced **12 reports**, with `report_age_us` ranges of **499–717 µs** and **591–796 µs**, respectively. Subscription, deletion, and xApp exit all succeeded. An intermediate collection window subscribed successfully but received no UE reports. If the result is `NO_UE`, first confirm registration and that UE traffic covers the collection window. `report_age_us` is report age, not application RTT. Fresh ping results, 30-second application uplink/downlink throughput, reporting-period accuracy, and sustained stability remain unverified. Record direction, summary rates, retransmissions, and growth in Spark RF errors on both sides.

For SIM or registration problems, use the actual `(qmi)` port with `qmicli -p`; see [Runbook stage 10](full_reproduction_runbook.md#10-prepare-a-new-ubuntulinux-laptop). Use proxy mode alongside ModemManager rather than competing for a direct QMI session.

## 6 Shut down the UE

Stop traffic with `Ctrl+C` first. Use the variables saved in the same terminal and verify the same modem, then **disconnect the PDU session before removing only this run's manual IP address and host route**. Do not reselect the first modem or flush the entire interface.

```bash
cleanup_ue() {
  local current_identity current_modem_kv driver
  [[ -n "$MODEM" && -n "$MODEM_IDENTITY" && -n "$WWAN_IF" && -n "$UE_IP" && -n "$UE_PREFIX" ]] || return 1
  current_modem_kv=$(mmcli -m "$MODEM" -K) || return 1
  current_identity=$(printf '%s\n' "$current_modem_kv" | mm_value modem.generic.device-identifier)
  [[ "$current_identity" = "$MODEM_IDENTITY" ]] || return 1
  printf '%s\n' "$current_modem_kv" | grep -Fq "$WWAN_IF (net)" || return 1
  sudo mmcli -m "$MODEM" --simple-disconnect || return 1
  driver=$(basename "$(readlink -f "/sys/class/net/$WWAN_IF/device/driver")")
  [[ "$driver" = qmi_wwan ]] || return 1
  if ip -4 route show exact 10.45.0.1/32 dev "$WWAN_IF" | grep -Fq "src $UE_IP"; then
    sudo ip -4 route del 10.45.0.1/32 dev "$WWAN_IF" src "$UE_IP" || return 1
  fi
  if ip -o -4 addr show dev "$WWAN_IF" | awk '{print $4}' | grep -Fxq "$UE_IP/$UE_PREFIX"; then
    sudo ip -4 addr del "$UE_IP/$UE_PREFIX" dev "$WWAN_IF" || return 1
  fi
  printf 'PDU disconnected; the manual address and route for this run are removed.\n'
  ip -br -4 addr show dev "$WWAN_IF"
}
cleanup_ue || printf 'Cleanup is incomplete; check the same modem and interface and any command errors. Do not guess an interface or flush it.\n'
```

If variables were lost or the modem rebooted, reconfirm the original device, interface, and this run's address before cleanup; do not run commands with stale variables. After disconnection and cleanup, optionally run `sudo mmcli -m "$MODEM" --disable`, then unplug the RMU. Shut Spark down using [Spark Quick Commands](spark_quick_commands.md).
