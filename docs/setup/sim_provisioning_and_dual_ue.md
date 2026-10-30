# Open Cells SIM Provisioning and Dual UE Preparation

Provisioning record: **2026-10-07**; deployment context updated **2026-10-29**.
This record combines SIM personalization, local Milenage tests and Quectel
readouts with reproduction instructions. At the original October 7 checkpoint,
the two new cards had not completed end-to-end registration or PDU validation.

Both subscriber paths subsequently passed registration and IPv4 traffic in the
dated dual-UE reports. The [current radio design](../dual_link_radio_design.md)
assigns SIM `...101` to the intended DU1 3660-MHz / 20-MHz path and SIM `...102`
to the intended DU2 3600-MHz n78 interface / 40-MHz path. Link 2 is designed
for 9250-MHz OTA through Pi-Radio. On October 29 the operator confirmed both
UE connections in the direct test without converters. SIM credentials and
PLMN do not themselves enforce cell selection; verify the actual serving cell.

The existing single-link baseline used IMSI **`001010000000001`**. Its registration, IPv4 session, initial application traffic, and later FlexRIC measurements remain historical evidence for that subscriber; they do not establish registration of the new `...101` and `...102` cards. Preserve that baseline and its [configuration record](../project_progress_and_configuration.md#configuration-records).

The commands labeled **tested** below reproduce the reported operations. Acquisition, credential-handling, and device-selection helpers labeled **new convenience commands** were assembled for this guide and were not part of the reported hardware tests.

## SIM assignments

Both cards now use MCC `001`, two-digit MNC `01`, and PLMN `00101`. Preserve leading zeros in IMSI, ICCID, MSISDN, and PLMN fields.

| Field | SIM / UE1 | SIM / UE2 |
|---|---|---|
| Physical Open Cells card | `OC011830` | `OC011831` |
| ICCID, unchanged by personalization | `89860061100000000830` | `89860061100000000831` |
| Original IMSI | `208920100001830` | `208920100001831` |
| Final IMSI | `001010000000101` | `001010000000102` |
| Original PLMN | `20892` | `20892` |
| Final PLMN | `00101` | `00101` |
| Original MSISDN | `00000830` | `00000831` |
| Final MSISDN | `00000101` | `00000102` |
| Original SPN | `OpenCells830` | `OpenCells831` |
| Final SPN | `OpenCells101` | `OpenCells102` |
| Independent authentication pair | `K1` / `OPc1` | `K2` / `OPc2` |
| Protected local credential file | `~/sim_du1_credentials.txt` | `~/sim_du2_credentials.txt` |
| Tool's post-authentication HSS SQN reference | `96` | `96` |
| Intended physical path | Quectel #1 → DU1 | Quectel #2 → DU2 |

The topology uses two independent UEs/subscribers and modems on one laptop,
DU1 and DU2, a shared CU and Open5GS/UPF. Separate WWAN/IP paths support the
MPTCP application. These were future validation tasks at the original October 7
provisioning checkpoint; later dual-UE and MPTCP experiments are linked from
the current radio design above.

**Sharing PLMN `00101` does not enforce IMSI-to-DU assignment.** `...101 → DU1` and `...102 → DU2` are intended mappings that require validated cell selection and observed attachment to the correct cells. SIM2 also worked in the original modem, demonstrating that its credentials are not bound to one modem's IMEI.

## Install the PCSC environment

The tested reader was an **ACS ACR39U**, USB `072f:b100`. The following package installation and checks were tested:

If the first `apt update` stalls on an Ubuntu mirror, follow [HTTPS recovery](#recover-ubuntu-apt-access-over-https) before installing packages. A clean laptop may need its source URIs corrected before it can install `curl`; the source-editing step does not require `curl`.

```bash
sudo apt update
sudo apt install -y pcscd pcsc-tools libccid libpcsclite-dev
lsusb
systemctl status pcscd --no-pager
pcsc_scan
```

The reader appeared as `072f:b100 Advanced Card Systems, Ltd ACR39U`. `pcscd` was `active (running)`, and `pcsc_scan` reported `Card state: Card inserted` with this ATR:

```text
3B 9F 95 80 1F C7 80 31 A0 73 B6 A1 00 67 CF 32 11 B2 52 C6 79 F3
```

The ATR database labeled it `open5gs (Telecommunication)`. That is a heuristic card-identification hint, not evidence that an Open5GS subscriber record exists. Stop `pcsc_scan` with `Ctrl+C` before using the programming utility.

On a clean laptop, the following are **new convenience commands** for build/download prerequisites and starting an inactive daemon:

```bash
sudo apt install -y build-essential git curl ca-certificates openssl
sudo systemctl start pcscd
```

### Recover Ubuntu APT access over HTTPS

During the reported setup, HTTP connections to `http://archive.ubuntu.com` and `http://us.archive.ubuntu.com` timed out. This tested check reached the Ubuntu archive over HTTPS and returned HTTP 200:

```bash
curl -4 -I --max-time 10 https://archive.ubuntu.com/ubuntu/
```

The enabled Ubuntu source entries were changed to `https://archive.ubuntu.com/ubuntu/` and `https://security.ubuntu.com/ubuntu/`, after which `sudo apt update` completed normally. Inspect the actual enabled entries in `/etc/apt/sources.list` or `/etc/apt/sources.list.d/`; preserve their suites, components, and signing configuration when changing the Ubuntu archive URIs. The source-file layout depends on the Ubuntu installation. This was an HTTP network/path failure, not an ACR39U or `pcscd` failure.

## Build the UICC programming utility

The original Open Cells download endpoint had an expired TLS certificate during setup. The code was obtained instead from [UICC-GUI-Sim-Programmer](https://github.com/DanieleRiccobene/UICC-GUI-Sim-Programmer). The working directory was `~/UICC-GUI-Sim-Programmer/uicc_v3.3`, containing `aes.h`, `milenage.h`, `program_uicc.c`, `uicc.h`, the Makefile, and the programming binaries. A source commit for that tested checkout was not provided.

For a fresh checkout, these are **new convenience acquisition commands**. Record the retrieved commit rather than inventing a pin:

```bash
cd "$HOME"
git clone https://github.com/DanieleRiccobene/UICC-GUI-Sim-Programmer.git
cd "$HOME/UICC-GUI-Sim-Programmer"
git rev-parse HEAD
```

The following local rebuild was **tested**:

```bash
cd "$HOME/UICC-GUI-Sim-Programmer/uicc_v3.3"
rm -f program_uicc_pcsc
make program_uicc_pcsc
```

The tested Makefile invocation was:

```bash
g++ --std=c++11 -g3 -DPCSC \
  -I. -I/usr/include/PCSC -Wall program_uicc.c \
  -L/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  -lccid -o program_uicc_pcsc
```

The first launch failed with `libccid.so: cannot open shared object file`. On the tested Ubuntu installation, the library was `/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux/libccid.so`. The successful commands below therefore use `sudo env LD_LIBRARY_PATH=...`; a different installation must confirm its actual driver-library path first.

## Provision and authenticate the cards

### Read the inserted card before writing

Insert one identified card in the ACR39U and perform this **tested read-only check**:

```bash
cd "$HOME/UICC-GUI-Sim-Programmer/uicc_v3.3"
sudo env LD_LIBRARY_PATH=/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  ./program_uicc_pcsc --port usb:072f/b100
```

`usb:072f/b100` is the tested PC/SC port syntax for this reader's VID/PID. For this initial read, omit `--adm`, `--imsi`, `--key`, `--opc`, and other personalization options. The message `No ADM code of 8 figures, can't program the UICC` is expected when no programming credentials are supplied. Both cards were readable and returned the original identifiers in the assignment table.

### Generate and retain independent authentication credentials

For a **fresh or deliberate re-personalization**, the tested generation operations were `umask 077` and a separate `openssl rand -hex 16` call for each value. This **new convenience guard** refuses generation when either protected file already exists:

```bash
generate_new_sim_credentials() {
  local sim_credentials_dir="${1:-$HOME}"
  [[ -d "$sim_credentials_dir" &&
     ! -e "$sim_credentials_dir/sim_du1_credentials.txt" && ! -L "$sim_credentials_dir/sim_du1_credentials.txt" &&
     ! -e "$sim_credentials_dir/sim_du2_credentials.txt" && ! -L "$sim_credentials_dir/sim_du2_credentials.txt" ]] || return 1
  umask 077
  K1=$(openssl rand -hex 16) || return 1
  OPC1=$(openssl rand -hex 16) || return 1
  K2=$(openssl rand -hex 16) || return 1
  OPC2=$(openssl rand -hex 16) || return 1
}
generate_new_sim_credentials || printf 'Generation stopped; preserve existing files and resolve the cause before continuing.\n'
```

Each value is 128 bits represented by 32 hexadecimal characters. Generate each pair independently; do not reuse UE1's pair for UE2. `OPC1` and `OPC2` here are shell variable names for the values passed to `--opc`, not OP inputs.

**For the already provisioned cards, retain their existing protected files and matching values. Do not regenerate credentials merely to read a card or repeat registration preparation.** Generation does not update a programmed card or the core by itself.

The local files contain public identifiers and secret `K`/`OPC` fields. This **new convenience saving block** provides that structure without printing the secrets and refuses to overwrite an existing file. Run it only after generating a new pair for new personalization; if it fails, stop and resolve the existing-file situation before proceeding:

```bash
save_new_sim_credentials() {
  local sim_credentials_dir="${1:-$HOME}"
  [[ "${K1:-}" =~ ^[[:xdigit:]]{32}$ && "${OPC1:-}" =~ ^[[:xdigit:]]{32}$ &&
     "${K2:-}" =~ ^[[:xdigit:]]{32}$ && "${OPC2:-}" =~ ^[[:xdigit:]]{32}$ ]] || return 1
  [[ "$K1" != "$K2" && "$OPC1" != "$OPC2" ]] || return 1
  [[ -d "$sim_credentials_dir" &&
     ! -e "$sim_credentials_dir/sim_du1_credentials.txt" && ! -L "$sim_credentials_dir/sim_du1_credentials.txt" &&
     ! -e "$sim_credentials_dir/sim_du2_credentials.txt" && ! -L "$sim_credentials_dir/sim_du2_credentials.txt" ]] || return 1
  (
    umask 077
    set -o noclobber
    printf 'SIM=OC011830\nICCID=89860061100000000830\nIMSI=001010000000101\nMCC=001\nMNC=01\nK=%s\nOPC=%s\n' \
      "$K1" "$OPC1" > "$sim_credentials_dir/sim_du1_credentials.txt" &&
    printf 'SIM=OC011831\nICCID=89860061100000000831\nIMSI=001010000000102\nMCC=001\nMNC=01\nK=%s\nOPC=%s\n' \
      "$K2" "$OPC2" > "$sim_credentials_dir/sim_du2_credentials.txt" &&
    chmod 600 "$sim_credentials_dir/sim_du1_credentials.txt" "$sim_credentials_dir/sim_du2_credentials.txt"
  )
}
save_new_sim_credentials
```

The reported credential files were retained as `~/sim_du1_credentials.txt` and `~/sim_du2_credentials.txt`, with permission **600**. These paths refer to the provisioning host's home directory; they are not automatically present on Spark. Subscriber administration must use the matching files through the protected local operator workflow. Keep them outside the repository, never paste their contents or real K/OPc values into documentation or shared logs, and do not enable shell tracing while using them. The repository excludes copies/backups matching `sim_du*_credentials.txt*`; keep all other credential copies outside Git as well. IMSI, ICCID, and the controlled-testbed assignments may be recorded; they cannot reconstruct K or OPc.

The two write commands below are for fresh or deliberate re-personalization only. For the completed cards, reuse their existing matching protected files and perform read-only identification; do not repeat the write/authentication sequence merely to check the cards.

If variables were lost and the saved pair is needed for deliberate re-personalization or protected subscriber administration, this **new convenience loader** parses the expected local file without executing it. It requires an owned regular file with mode 600, the matching IMSI, and exactly one valid K/OPC pair. It prints no credentials. Do not use `source` or `eval` on a credential file:

```bash
load_saved_sim_credentials() {
  local sim_index="$1" sim_credentials_dir="${2:-$HOME}"
  local sim_file expected_imsi field value file_imsi="" file_key="" file_opc=""
  local imsi_count=0 key_count=0 opc_count=0
  case "$sim_index" in
    1) unset K1 OPC1; expected_imsi=001010000000101 ;;
    2) unset K2 OPC2; expected_imsi=001010000000102 ;;
    *) return 1 ;;
  esac
  sim_file="$sim_credentials_dir/sim_du${sim_index}_credentials.txt"
  [[ -f "$sim_file" && ! -L "$sim_file" &&
     "$(stat -c '%a' "$sim_file")" = 600 &&
     "$(stat -c '%u' "$sim_file")" = "$(id -u)" ]] || return 1
  while IFS='=' read -r field value || [[ -n "$field" ]]; do
    case "$field" in
      IMSI) file_imsi="$value"; imsi_count=$((imsi_count + 1)) ;;
      K) file_key="$value"; key_count=$((key_count + 1)) ;;
      OPC) file_opc="$value"; opc_count=$((opc_count + 1)) ;;
    esac
  done < "$sim_file"
  [[ "$imsi_count" -eq 1 && "$key_count" -eq 1 && "$opc_count" -eq 1 &&
     "$file_imsi" = "$expected_imsi" &&
     "$file_key" =~ ^[[:xdigit:]]{32}$ && "$file_opc" =~ ^[[:xdigit:]]{32}$ ]] || return 1
  case "$sim_index" in
    1) printf -v K1 '%s' "$file_key"; printf -v OPC1 '%s' "$file_opc" ;;
    2) printf -v K2 '%s' "$file_key"; printf -v OPC2 '%s' "$file_opc" ;;
  esac
}
unset K1 OPC1 K2 OPC2
if ! load_saved_sim_credentials 1 || ! load_saved_sim_credentials 2; then
  printf 'STOP: Matching protected credentials are unavailable or invalid; do not continue to a write.\n' >&2
fi
```

These helpers default to the provisioning host's home directory. Their optional directory argument supports isolated offline checks; it does not transfer credentials to Spark. Stop after any loader or validation failure.

### Tested write: SIM1 / OC011830

Confirm that the currently inserted physical card is `OC011830`, and that `K1`/`OPC1` contain its saved pair. The full write and authentication command inside this **new convenience guard** was **tested**. The guard prevents a write if the directory or 32-hex pair is missing or invalid:

```bash
if cd "$HOME/UICC-GUI-Sim-Programmer/uicc_v3.3" &&
   [[ "${K1:-}" =~ ^[[:xdigit:]]{32}$ && "${OPC1:-}" =~ ^[[:xdigit:]]{32}$ ]]; then
  sudo env LD_LIBRARY_PATH=/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  ./program_uicc_pcsc \
  --port usb:072f/b100 \
  --adm 12345678 \
  --iccid 89860061100000000830 \
  --imsi 001010000000101 \
  --MNCsize 2 \
  --isdn 00000101 \
  --acc 0001 \
  --key "$K1" \
  --opc "$OPC1" \
  --spn OpenCells101 \
  --authenticate
else
  printf 'STOP: Check the utility directory and matching 32-hex K1/OPC1 before writing SIM1.\n' >&2
fi
```

The reported V5 Open Cells cards accepted the eight-digit ADM value `12345678` for personalization. This is specific to the tested cards; it is neither PIN1 nor PIN2 and is not a generic ADM code for other USIMs.

### Tested write: SIM2 / OC011831

Insert and identify `OC011831`, then use its own saved pair in `K2`/`OPC2`. The full command inside this **new convenience guard** was **tested**:

```bash
if cd "$HOME/UICC-GUI-Sim-Programmer/uicc_v3.3" &&
   [[ "${K2:-}" =~ ^[[:xdigit:]]{32}$ && "${OPC2:-}" =~ ^[[:xdigit:]]{32}$ ]]; then
  sudo env LD_LIBRARY_PATH=/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  ./program_uicc_pcsc \
  --port usb:072f/b100 \
  --adm 12345678 \
  --iccid 89860061100000000831 \
  --imsi 001010000000102 \
  --MNCsize 2 \
  --isdn 00000102 \
  --acc 0001 \
  --key "$K2" \
  --opc "$OPC2" \
  --spn OpenCells102 \
  --authenticate
else
  printf 'STOP: Check the utility directory and matching 32-hex K2/OPC2 before writing SIM2.\n' >&2
fi
```

Post-write output matched each card's final IMSI, MSISDN, and SPN. Both cards returned `0x00f1107c` for the PLMN selector, Operator Control PLMN selector, and Home PLMN selector. Both authentication tests printed:

```text
Succeeded to authentify with SQN: 64
set HSS SQN value as: 96
```

This establishes successful personalization and local Milenage authentication using each newly written K/OPc pair. It does not establish radio registration or core authentication. Retain the tool's `96` recommendation as the post-test core SQN reference and verify its interpretation and representation before subscriber provisioning. Avoid unnecessary repeated `--authenticate` operations: authentication advances the card's SQN, so a previously recorded core reference can become stale.

### What the binding means

K and OPc are not calculated from IMSI or ICCID. Passing `--key "$K1" --opc "$OPC1"` while `OC011830` is inserted writes that pair into that physical card alongside IMSI `001010000000101`; SIM2's command creates the corresponding `...102 ↔ K2/OPc2 ↔ OC011831` association. The core must use the same pair for the matching IMSI. The SIM-to-modem/DU assignment is separate from this authentication binding.

Ordinary SIM readouts cannot recover K/OPc after personalization. If the protected credential files are lost, re-personalization with a new pair and matching core updates may be required; IMSI and ICCID alone are insufficient.

## Verify the cards through Quectel

Both cards were verified through Quectel `RM500QGL_VH`. SIM2 was first checked in the original modem, then again in a **second physical modem**:

| Observation | Quectel #1 | Quectel #2 |
|---|---|---|
| Previously observed IMEI / equipment ID | `863305041978437` | `863305041980706` |
| Card checks reported | SIM1 and initial SIM2 verification | SIM2 verification |
| Intended final card | `OC011830` / `...101` | `OC011831` / `...102` |
| Recorded port/interface example | Rediscover actual values | `cdc-wdm2` / `wwan0` in that session |

The differing IMEIs establish two physical modems. ModemManager numbers, SIM paths, QMI/AT ports, and WWAN names can change after power cycles and when both modems are connected. The second modem's observed `wwan0` is not an allocation plan for two simultaneous interfaces.

Use the [UE quick-command selection functions](../single_ue/ue_laptop_quick_commands.md#1-install-tools-and-select-the-modem) and choose the intended device when multiple RM500Q units are listed. For dual-modem work, also verify the selected unit's equipment identifier against the table. The reported one-modem shortcut selected the first `Modem/...` entry; do not carry that shortcut into a two-modem setup.

After `MODEM` identifies the intended device, the following SIM and proxy-QMI query pattern was **tested**:

```bash
mmcli -L
mmcli -m "$MODEM"
SIM_PATH=$(mmcli -m "$MODEM" -K | sed -n 's/^modem\.generic\.sim *: *//p')
SIM_ID=${SIM_PATH##*/}
mmcli -i "$SIM_ID"
QMI=$(mmcli -m "$MODEM" -K | sed -n 's/^modem\.generic\.primary-port *: *//p')
sudo qmicli -p -d "/dev/$QMI" --uim-get-card-status
```

Confirm the primary port is the actual QMI port before the `qmicli` call; keep proxy mode `-p` alongside ModemManager. Selecting and checking the two devices' equipment identifiers is a **new convenience workflow** for the intended dual-modem setup; two simultaneous private sessions have not been demonstrated.

| Quectel SIM readout | SIM1 | SIM2 |
|---|---|---|
| Active | `yes` | `yes` |
| IMSI | `001010000000101` | `001010000000102` |
| ICCID | `89860061100000000830` | `89860061100000000831` |
| Operator ID | `00101` | `00101` |
| Operator name | `OpenCells101` | `OpenCells102` |
| Preferred networks | `00101 (lte, 5gnr)` | `00101 (lte, 5gnr)` |
| Modem own number | `00000101` | `00000102` |

Both low-level readouts reported `Card state: present`, `Application type: usim`, `Application state: ready`, `Personalization state: ready`, and `PIN1 state: disabled`. SIM1's PIN2 state was `enabled-not-verified`. PIN2 is separate from ADM and PIN1; that state did not prevent the successful card access and is not a reason to alter PIN2 for ordinary private-network registration preparation.

### Safe SIM swap

Do not hot-swap the cards in an operating modem. Follow this procedure for the intended device:

1. Stop that UE's traffic and release any active PDU/interface configuration using the [UE shutdown procedure](../single_ue/ue_laptop_quick_commands.md#6-shut-down-the-ue).
2. Disable the selected modem with `sudo mmcli -m "$MODEM" --disable`.
3. Physically power off or disconnect the RMU500EK/Quectel unit before removing and inserting the card.
4. Reapply power, run `mmcli -L`, and rediscover the intended modem, SIM, QMI/AT port, and WWAN interface. Confirm its IMEI and inserted IMSI before continuing.

A reported reconnect sequence changed modem numbers from `Modem/5` to `Modem/6`, and another physical modem appeared as `Modem/7`. These are historical examples, not commands or fixed assignments.

## Prepare Open5GS subscribers

At the original October 7 checkpoint, the two new subscribers had not
completed end-to-end registration. For a fresh installation, provision or
verify each through the project's administrative workflow after checking
the installed schema and SQN handling:

| Subscriber | IMSI | Authentication source | Post-test SQN reference |
|---|---|---|---|
| UE1 | `001010000000101` | `~/sim_du1_credentials.txt`, matching `K1`/`OPc1` | Tool recommended `96` |
| UE2 | `001010000000102` | `~/sim_du2_credentials.txt`, matching `K2`/`OPc2` | Tool recommended `96` |

Do not exchange the pairs between subscribers, and do not overwrite the working `001010000000001` subscriber. The existing baseline uses PLMN `00101`, SST 1, DNN `internet`, and subscriber session type **1 / IPv4**; consult the [Open5GS configuration record](../project_progress_and_configuration.md#open5gs-identity-sessions-and-interfaces) when preparing the new subscribers.

Version-specific upstream evidence: Open5GS **v2.8.0** defines `security.sqn` as Mongoose `Schema.Types.Long` in its [subscriber model](https://github.com/open5gs/open5gs/blob/v2.8.0/webui/server/models/subscriber.js), and its [subscription DB code](https://github.com/open5gs/open5gs/blob/v2.8.0/lib/dbi/subscription.c) reads BSON int64 and writes `BCON_INT64`. SQN is therefore not a K-like hexadecimal secret string in those upstream paths. The installed administrative UI/API, local database representation, and correct handling of the tool's `96` reference still need verification before provisioning.

## Validate two UE paths

The reproduction sequence below originated at the October 7 checkpoint.
Use the current dual-UE handbooks for deployed values and commands:

1. Create or confirm the exact two subscribers with their matching saved pairs and verified SQN representation. Preserve the single-link baseline subscriber separately.
2. Prepare and validate CU + DU1 + DU2 configuration and both B210 RF paths
   using the [current profiles](../dual_link_radio_design.md). Keep radio
   serials, PCI, SSB and DU identities distinct; do not reuse DU1's settings for DU2.
3. Select the intended cell for each physical modem and verify actual `...101 → DU1` and `...102 → DU2` attachment. A common PLMN alone cannot prove this mapping.
4. For each selected modem, require successful registration, the private
   operator identity, `5gnr` access technology and attached packet service.
   Create and verify an IPv4 PDU session with UE1 DNN `internet` or UE2
   DNN `internet2`, using dynamically discovered modem/bearer identifiers.
5. Discover both actual WWAN interfaces and allocated IP parameters. Apply each bearer configuration to its own interface, retain management Wi-Fi, and verify independent private data paths; do not assume historical interface names or UE addresses.
6. Measure each path separately, then validate concurrent traffic and expose the two IP paths to MPTCP. Record direction, duration, throughput, errors, and routing before asserting transport aggregation.
7. Extend FlexRIC/xApp observation to the actual per-DU/per-UE paths, then evaluate MPTCP path steering. Existing single-DU KPM reception does not establish dual-DU telemetry or proactive steering.

The reported newer modem with SIM2 was `state: searching`, `registration: searching`, and `packet service state: detached`. Its signal-quality indication was approximately **88%**. The successful SIM readouts establish a usable USIM application; neither searching/detached nor 88% proves private-cell detection or registration. A completed RAN/core registration will validate the combined IMSI, K, OPc, SQN, PLMN, RAN, and subscriber configuration.

## Troubleshooting and lessons learned

| Observation | Established meaning and next action |
|---|---|
| APT HTTP archive requests time out; HTTPS returns 200 | Repair the Ubuntu archive transport entries; do not diagnose a reader/PCSC failure from this network symptom. |
| Original download endpoint has an expired certificate | The reported workaround was the GitHub source; record its commit and retain TLS verification. |
| `libccid.so` cannot be found | The tested driver-library path required `sudo env LD_LIBRARY_PATH=...`; confirm the local path before changing the loader configuration. |
| Read-only UICC command prints the missing-ADM message | Expected without `--adm`; verify card identifiers before a deliberate write. |
| ATR lookup says `open5gs` | A database identification hint, not subscriber provisioning evidence. |
| Both Milenage tests succeed at printed SQN `64`, tool recommends `96` | Local card authentication passed; retain that reference, verify core representation, and avoid needless authentication repeats. |
| Card is present, USIM ready, personalization ready, PIN1 disabled | Card access and personalization are working; continue with RAN/core registration checks rather than repeating the write. |
| PIN2 is enabled but not verified | Separate from ADM/PIN1; it did not block the reported card checks and was left unchanged. |
| New SIM shows searching/detached and 88% signal | Registration remains unverified; scanning may include surrounding commercial signals. |
| One modem/session has a different carrier profile | Record the difference; investigate only if correct private-cell RF/settings and matching subscriber data still do not yield registration. |
| Device indexes or WWAN names change after swapping | Power off before a swap and rediscover by physical equipment identity and current SIM rather than selecting the first listed modem. |

The newer Quectel session showed carrier configuration `Volte_OpenMkt-Commercial-CMCC`, while another earlier configuration/session showed `ROW_Commercial`. This difference is a future investigation item, not an established cause of registration failure. No carrier-profile change was reported or is required by the successful UICC checks. Investigate it only after the private cell is running, band/frequency/cell selection is correct, and the exact Open5GS subscriber credentials and SQN handling are verified.

The October 7 work completed two readable Open Cells cards, the ACR39U/PCSC
environment, the rebuilt utility, independent protected authentication pairs,
both personalization/Milenage tests, Quectel readouts and SIM2 verification in
the second modem. Registration, dual PDU/WWAN paths, concurrent traffic and
MPTCP were follow-up tasks at that checkpoint; later reports record their
results. The current radio design above distinguishes direct connection,
sustained-traffic evidence and the still-unvalidated converted OTA path.
