# Software Installation, Drivers, and OCUDU Environment

Deployment context, October 30: use the [current two-link design](../../project_design_and_progress.md)
and paired Spark/Laptop handbooks for DU1 3660 MHz / 20 MHz and DU2
3600-MHz logical n78 interface / 40 MHz with its current 9250-MHz Pi-Radio
OTA path and tuned TX 60 / RX 10. The October 29 direct-radio connections
remain historical. The software-build
records below retain their original dates and single-link preparation scope;
their pending dual-UE statements describe those checkpoints.

Updated: 2026-10-12. This document records software dependencies, device drivers and builds for DGX Spark and the UE laptop. The OCUDU/Open5GS baseline comes from the 2026-10-05 deployment; section 8 records the FlexRIC build and installation completed on 2026-10-07. Section 7.4 adds the completed Open Cells PC/SC provisioning environment and Quectel card checks for the two new UE SIMs.

For experiment startup, modem registration, PDU sessions, traffic, and shutdown, use the [Full Reproduction Runbook](../legacy_single_ue.md). Executable CU/DU and core configuration values are recorded in [Project Progress](../../project_design_and_progress.md#configuration-ownership); registration and data-session failures are in the [2026-10-05 debug record](../../experiments/records/bringup/2026-10-05_sa_bringup.md).

## 1. Software baseline and host constraints

| Component | Recorded working environment |
|---|---|
| Spark | NVIDIA DGX Spark / GB10, Ubuntu 24.04.5 LTS, aarch64 / arm64 |
| Kernel | NVIDIA `7.0.0-1019-nvidia`, PREEMPT_DYNAMIC |
| System compiler | GCC/G++ 13.3, default compiler selection retained |
| OCUDU compiler | Clang/Clang++ 18.1.3, C++17 |
| Build system | CMake 3.28.3, Make; Release build |
| OCUDU | `release_26_04`, commit `050a2bb`, checkout `/home/nyu/ocudu` |
| FlexRIC | `br-flexric`, pinned `73650812`, checkout `/home/nyu/flexric`, GCC 13.3 Debug build in `build-ocudu` |
| Radio software | Ubuntu UHD 4.6.0.0, `libuhd-dev` and `uhd-host` |
| Core software | Open5GS arm64 packages `2.8.0~noble5` |
| Database | MongoDB 7, Docker image `mongo:7.0-jammy`, arm64 |
| Container runtime | Installed Docker CE package `5:29.6.2-1~ubuntu.24.04~noble` |
| Modem tools inspected on Spark | ModemManager 1.23.4, libqmi-utils 1.35.2, minicom 2.9 |
| UE laptop | Ubuntu/Linux with USB serial and QMI kernel drivers; its kernel/version must be checked independently |

Retain the NVIDIA kernel and system compiler defaults. Select Clang for OCUDU through CMake, rather than changing compiler alternatives. FlexRIC/C xApp use GCC selected per build; Python/CUDA remains a separate future AI stage. Installing a generic kernel, PREEMPT_RT, CUDA toolkit, or NVIDIA driver replacement is not part of this deployment.

`[SPARK]` Record the host and toolchain before installation:

```bash
uname -m
uname -r
cat /etc/os-release
dpkg --print-architecture
lscpu
free -h
gcc --version
g++ --version
cmake --version
```

The package architecture is `arm64`; compiler/host output uses `aarch64`. Package repositories and container tags may advance. Compare installed versions against this table and retain the exact version output when reproducing on another host.

## 2. Install the Spark development dependencies

`[SPARK]` On a new host:

```bash
sudo apt update
sudo apt install -y build-essential clang-18 cmake make git pkg-config \
  ca-certificates curl software-properties-common usbutils \
  libuhd-dev uhd-host libmbedtls-dev libsctp-dev \
  libyaml-cpp-dev libfftw3-dev libgtest-dev
```

| Package | Role in this deployment |
|---|---|
| `clang-18` | Recorded OCUDU C/C++ compiler |
| `cmake`, `make`, `git`, `pkg-config` | Source checkout, build configuration, compilation and dependency discovery |
| `libuhd-dev` | UHD headers and link library for the radio implementation |
| `uhd-host` | UHD utilities, device-image downloader and USB access rules |
| `libmbedtls-dev` | Cryptographic library used by OCUDU |
| `libsctp-dev` | SCTP development support for N2 and F1-C |
| `libyaml-cpp-dev` | YAML configuration parser |
| `libfftw3-dev` | FFTW, including the single-precision FFT library found by CMake |
| `libgtest-dev` | Build dependency when `BUILD_TESTING=ON` |
| `usbutils` | USB enumeration and negotiated-speed inspection |

`[SPARK]` Inspect installed versions:

```bash
clang-18 --version
clang++-18 --version
pkg-config --modversion uhd
dpkg-query -W clang-18 cmake libuhd-dev uhd-host \
  libmbedtls-dev libsctp-dev libyaml-cpp-dev libfftw3-dev libgtest-dev
```

The working build does not require ZeroMQ, DPDK, LibNUMA, Intel MKL, or an ARM performance library. In the inspected cache, `ENABLE_ZEROMQ=ON` was the default, but `ZEROMQ_FOUND=FALSE`; the radio implementation uses UHD. Do not interpret an optional-library discovery warning as a missing B210 driver.

## 3. UHD, B210 images, and USB access

### 3.1 Driver and library layout

The B210 software path is OCUDU → UHD → libusb/Linux USB → B210. The recorded setup uses distribution UHD packages and their device images. No separate vendor kernel-module build was recorded. The Ubuntu package installation is documented in the [UHD 4.6 binary installation guide](https://files.ettus.com/manual_archive/v4.6.0.0/html/page_install.html).

`[SPARK]` Download device images for the installed UHD version:

```bash
uhd_config_info --version
sudo uhd_images_downloader
dpkg -L uhd-host | grep -Ei 'udev|images|uhd_images_downloader'
```

Keep UHD headers, runtime library, utilities, and images from a consistent installation. If both `/usr` distribution packages and a `/usr/local` source installation exist, inspect library resolution before changing the system library path.

### 3.2 udev rules and access failures

The inspected package installs `/usr/lib/udev/rules.d/60-uhd-host.rules`. Its B200-series entries include USB VID/PID `2500:0020`, `2500:0021`, and `2500:0022`, with `MODE:="0666"`. These are existing package rules, not proposed new permissions.

`[SPARK]`

```bash
dpkg -L uhd-host | grep -i udev
grep -nE '2500|0020|0021|0022|MODE' /usr/lib/udev/rules.d/60-uhd-host.rules
lsusb
lsusb -t
```

If package rules were just installed or intentionally changed, reload them and reconnect the stopped radio:

`[SPARK]`

```bash
sudo udevadm control --reload-rules
```

Device-access failures encountered during environment inspection must be separated from actual driver failure. Compare access in a normal host terminal with privileged access, inspect the enumerated USB device and package rules, and account for any execution sandbox's USB restrictions. Do not rewrite udev rules solely because a sandbox cannot open libusb devices.

### 3.3 Hardware detection and USB speed

Stop DU before any UHD discovery or probe. For another B210, replace the recorded serial with the detected device's serial.

`[SPARK]`

```bash
uhd_find_devices
uhd_usrp_probe --args="type=b200,serial=3271233"
lsusb -t
```

Expected evidence is B210 serial `3271233`, USB 3 / `5000M`, and successful register loopback tests. This testbed's working DU transport is USB 3. A `480M` path warrants inspection of the cable, hub and host port. The [B2x0 hardware manual](https://files.ettus.com/manual/page_usrp_b200.html) documents the device's USB and image requirements.

The earlier 30.72 MS/s, 20-second RX benchmark passed without drops, overruns, sequence errors or timeouts. This is historical USB/UHD evidence; the NR configuration uses 23.04 MS/s. Benchmarking and RF startup belong to the operational procedure.

## 4. OCUDU source and build environment

### 4.1 Source checkout

`[SPARK]` Clone only when the working checkout does not already exist:

```bash
cd /home/nyu
git clone --branch release_26_04 --depth 1 https://gitlab.com/ocudu/ocudu.git
cd /home/nyu/ocudu
git log -1 --oneline
git describe --tags --always
```

The recorded revision is `050a2bb` / `release_26_04`. Adapt `/home/nyu` for another account. Preserve an existing checkout and its local CU/DU configuration when inspecting or rebuilding the working host.

### 4.2 Configure and compile

`[SPARK]` Configure a new build directory with the recorded compiler and build type:

```bash
cd /home/nyu/ocudu
cmake -S . -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_C_COMPILER=clang-18 \
  -DCMAKE_CXX_COMPILER=clang++-18 \
  -DENABLE_UHD=ON \
  -DBUILD_TESTING=ON
cmake --build build --target ocu -j 8
cmake --build build --target odu_split_8 -j 8
```

If `build` was configured with another compiler, use a separate directory such as `build-clang18` and adjust the later paths. Reusing a CMake cache from a different compiler can obscure dependency and compiler changes. The system GCC/G++ selection remains unchanged.

| Item | Inspected working value |
|---|---|
| C++ language standard | C++17, declared in the OCUDU source |
| C compiler / C++ compiler | `/usr/bin/clang-18` / `/usr/bin/clang++-18` |
| `CMAKE_BUILD_TYPE` | `Release` |
| `BUILD_TESTING` | `ON`; this enables test compilation, not automatic test execution |
| `ENABLE_UHD` | `ON`; UHD headers/library found under `/usr` |
| FFTW | Single-precision `libfftw3f.so` under `/usr/lib/aarch64-linux-gnu` |
| ZeroMQ | Default option ON, library not found; unused by this deployment |
| LibNUMA / DPDK | Disabled in the recorded build |

`release_26_04` does not use the `DU_SPLIT_TYPE` CMake variable. Its DU build target is **`odu_split_8`**, while the executable filename is **`odu`**. An unused-variable warning from `DU_SPLIT_TYPE` is addressed by using the supported targets, not by changing the radio driver.

### 4.3 Build artifacts and library resolution

`[SPARK]`

```bash
cd /home/nyu/ocudu
ls -l build/apps/cu/ocu build/apps/du_split_8/odu
grep -E '^(CMAKE_BUILD_TYPE|CMAKE_C_COMPILER|CMAKE_CXX_COMPILER|ENABLE_UHD|BUILD_TESTING|UHD_INCLUDE_DIRS|UHD_LIBRARIES|ZEROMQ_FOUND):' build/CMakeCache.txt
ldd build/apps/du_split_8/odu | grep -E 'uhd|usb|sctp|yaml|not found'
```

Acceptance requires both executable files and no unresolved runtime libraries. The earlier monolithic `gnb_split_8` build and `band_helper_test` were successful historical checks. They are not installation requirements for operating the split CU/DU deployment.

Runtime configuration uses `/home/nyu/ocudu/configs/cu.yml`, `configs/du1_b210_n78_3660mhz.yml` and `configs/du2_b210_n78_40mhz.yml`. Use [the configuration record](../../project_design_and_progress.md#configuration-ownership) when preparing those files. INFO log levels, RF gain, PLMN, and session type are deployment settings rather than compiler or device-driver fixes.

## 5. Docker and the MongoDB compatibility workaround

### 5.1 Container runtime

The working Spark has Docker CE and `containerd.io`. Inspect an existing installation before considering another package provider:

`[SPARK]`

```bash
docker --version
dpkg-query -W docker-ce docker-ce-cli containerd.io
sudo docker info
```

For a new Ubuntu host with no existing Docker installation, the following repository setup follows the [official Docker Ubuntu installation procedure](https://docs.docker.com/engine/install/ubuntu/). Check that the new host has no conflicting Docker/containerd packages before using it.

`[SPARK]`

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && printf '%s' "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

This installs the repository's available version; it does not pin Docker to the recorded package version. Docker administration commands use sudo in this documentation.

### 5.2 Native MongoDB failure and selected replacement

Native MongoDB 8 failed on the recorded Spark/NVIDIA-kernel environment. The retained workaround is MongoDB 7 in an arm64 Docker container. The available record does not isolate the failure sufficiently to claim that every MongoDB 8 installation fails on every NVIDIA kernel.

`[SPARK]` If the failed native service exists, retain its disabled state:

```bash
sudo systemctl disable --now mongod
sudo systemctl reset-failed mongod
```

`[SPARK]` Inspect the existing container first; pull the image for a new installation:

```bash
sudo docker ps -a --filter name=open5gs-mongo
sudo docker pull mongo:7.0-jammy
sudo docker image inspect mongo:7.0-jammy --format '{{.Architecture}} {{.Os}}'
```

Require `arm64 linux`. Only when `open5gs-mongo` does not already exist:

`[SPARK]`

```bash
sudo docker run -d \
  --name open5gs-mongo \
  -p 127.0.0.1:27017:27017 \
  -v open5gs-mongo-data:/data/db \
  mongo:7.0-jammy
sudo docker exec open5gs-mongo mongosh --quiet --eval 'db.adminCommand({ping: 1})'
```

Require `{ ok: 1 }`. Preserve an existing container and `open5gs-mongo-data`; do not replace them to repair an unrelated subscriber or registration problem. SIM credentials remain in the local administrative workflow, outside Git.

## 6. Open5GS packages and installed environment

The deployment uses Ubuntu arm64 binary packages, rather than a local Open5GS source build. The [Open5GS quickstart](https://open5gs.org/open5gs/docs/guide/01-quickstart/) describes its Ubuntu package installation and systemd integration.

`[SPARK]` On a new host:

```bash
sudo add-apt-repository ppa:open5gs/latest
sudo apt update
sudo apt install --no-install-recommends open5gs
dpkg-query -W open5gs
```

The recorded version is `2.8.0~noble5`; the PPA may now provide a different version. Package installation can start systemd services. Use the full runbook to select the required SA services and to stop installed optional/legacy functions.

| Installed location | Purpose |
|---|---|
| `/etc/open5gs/*.yaml` | Core network-function configuration |
| `/usr/bin/open5gs-*` | Packaged network-function executables |
| `/usr/lib/systemd/system/open5gs-*.service` | Service definitions |
| `/etc/systemd/network/99-open5gs.netdev` | Persistent `ogstun_1` TUN definition after the October 23 migration |
| `/etc/systemd/network/99-open5gs.network` | `ogstun_1` addressing, routes and MTU |
| `/etc/systemd/network/99-open5gs-ue2.netdev` | Persistent `ogstun_2` TUN definition |
| `/etc/systemd/network/99-open5gs-ue2.network` | `ogstun_2` addressing and MTU |

`[SPARK]`

```bash
ls /etc/open5gs
systemctl cat open5gs-amfd open5gs-smfd open5gs-upfd
cat /etc/systemd/network/99-open5gs.netdev /etc/systemd/network/99-open5gs.network
cat /etc/systemd/network/99-open5gs-ue2.netdev /etc/systemd/network/99-open5gs-ue2.network
```

After the applied October 23 [TUN split](../networking.md), the original
`.netdev` defines `Name=ogstun_1`, `Kind=tun`, and its `.network` configures UE1
IPv4, original IPv6, routes and `MTUBytes=1400`. The additional UE2 pair defines
`ogstun_2 / 10.46.0.1/16`, also MTU 1400. UPF session entries select the matching
device. The UPF service requests `systemd-networkd`; cold-boot reproduction
is a [supplemental experiment](../../experiments/supplemental_experiments.md),
excluded from current Dual UE acceptance and merging. Verify these host-specific
files before another deployment.

PLMN alignment across NRF/AMF, the subscriber database, and IPv4 session selection are covered in the configuration record and runbook. WebUI is an optional administration component; an existing WebUI installation is not evidence that all runtime SA functions are ready.

The earlier working subscriber is IMSI `001010000000001`. The newly programmed Open Cells cards use `001010000000101` and `001010000000102`; adding their matching subscriber records is the next required core setup step, not a completed installation result. Use the respective protected `~/sim_du1_credentials.txt` and `~/sim_du2_credentials.txt` files for K/OPc, with SST 1, DNN `internet`, and IPv4 session type 1. The programming test suggested SQN 96 for each card; verify the installed Open5GS administration interface and database representation before setting it. See [Open5GS subscriber preparation](sim_provisioning_and_dual_ue.md#prepare-open5gs-subscribers). Preserve the existing subscriber and MongoDB volume.

## 7. UE laptop software and Quectel drivers

### 7.1 Install userspace tools

`[LAPTOP]`

```bash
uname -r
cat /etc/os-release
sudo apt update
sudo apt install -y modemmanager libqmi-utils minicom iproute2 iperf3 usbutils
sudo systemctl enable --now ModemManager
mmcli --version
qmicli --version
minicom --version
```

ModemManager manages the modem and bearers, libqmi-utils supplies QMI queries, and minicom provides an interactive AT terminal. These tools supplement the laptop's kernel drivers; their installation alone does not ensure that every USB interface binds correctly.

### 7.2 Kernel driver responsibilities

| Linux driver | Interface/function in the recorded QMI setup |
|---|---|
| `option` | USB serial ports, including AT-capable `ttyUSB*` ports |
| `qmi_wwan` | Modem network interface, historically `wwan0` |
| `cdc_wdm` | QMI control device, exposed as `/dev/cdc-wdm*` |

These roles are implemented by the upstream [USB serial option driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/usb/serial/option.c) and [QMI WWAN driver](https://raw.githubusercontent.com/torvalds/linux/master/drivers/net/usb/qmi_wwan.c). The working experiment used these drivers; no custom Quectel kernel patch was recorded.

`[LAPTOP]` Connect the RMU500EK/RM500Q and inspect enumeration:

```bash
lsusb
lsusb -t
ls -l /dev/ttyUSB* /dev/cdc-wdm* 2>/dev/null || true
ip -br link | grep -E 'wwan|rmnet' || true
mmcli -L
modinfo option
modinfo qmi_wwan
modinfo cdc_wdm
sudo journalctl -k --since '5 minutes ago' --no-pager | grep -Ei 'usb|quectel|ttyUSB|qmi|cdc.wdm|disconnect'
```

Expected device ID is `2c7c:0800` for the recorded USB composition. Historical AT ports were ttyUSB2/ttyUSB3, QMI was cdc-wdm2, and the network port was wwan0. Discover actual ports on each laptop. ModemManager reports known roles but may omit working AT ports; an existing ttyUSB can still respond to AT. With two modems, match each candidate's sysfs USB parent against the identity-selected modem's physical device, never the first ttyUSB number. ModemManager's [Device property](https://github.com/linux-mobile-broadband/ModemManager/blob/main/introspection/org.freedesktop.ModemManager1.Modem.xml) identifies the modem's physical device, and [mmcli's output fields](https://github.com/linux-mobile-broadband/ModemManager/blob/main/cli/mmcli-output.c) expose it as `modem.generic.device`. A diagnostic/GNSS/ignored ttyUSB is not automatically an AT-capable port.

[UE step 2](../legacy_single_ue.md#11-configure-rm500q-nr-sa-and-lock-the-private-cell) uses `sudo minicom -D /dev/ttyUSB2 -b 115200` for the current setup. Type `AT` and require a real `OK` before configuring the modem. Keep ModemManager running. Missing `(at)` output alone requires no reboot or firmware/USB-composition change. After USB reconnection, repeat identity selection and check actual port numbering.

If a module is available but not loaded, load it and reconnect the modem:

`[LAPTOP]`

```bash
sudo modprobe option
sudo modprobe qmi_wwan
sudo modprobe cdc_wdm
```

If `modinfo` reports a missing module, inspect that laptop's matching kernel-module packages and kernel configuration first. A module being present does not prove that its USB ID/interface matching supports the selected modem composition. Inspect `lsusb -t` and kernel messages before installing vendor drivers, changing USB composition, or adding device IDs manually.

### 7.3 Firmware and access issues encountered

The tested firmware is `RM500QGLABR13A03M4G`. Older `AT+QCFG="nwscanmode"` / `AT+QCFG="band"` commands returned ERROR; the working preference commands use `QNWPREFCFG`. This was a firmware-command difference, not proof of a Linux driver fault. The full runbook contains the tested NR/SA configuration sequence.

Repeated USB disconnects require inspection of cables, power, enumeration and modem state. The record did not isolate a universal cause or establish a required autosuspend change. After a modem reboot, rediscover IDs and ports. QMI queries alongside ModemManager use proxy mode (`qmicli -p`), and concurrent programs must not hold the same AT port.

### 7.4 Open Cells SIM provisioning environment

The ACS ACR39U reader (`072f:b100`) was recognized by Ubuntu and accessed both full USIM applications through PC/SC and libccid. The tested PC/SC packages were installed with:

`[PROVISIONING LAPTOP]`

```bash
sudo apt install -y pcscd pcsc-tools libccid libpcsclite-dev
systemctl status pcscd --no-pager
lsusb
pcsc_scan
```

`pcscd` was active; `pcsc_scan` reported `Card inserted` and ATR `3B 9F 95 80 1F C7 80 31 A0 73 B6 A1 00 67 CF 32 11 B2 52 C6 79 F3`. The ATR database label `open5gs (Telecommunication)` is an identification hint, not proof that an Open5GS subscriber exists. The clean-Ubuntu prerequisite list, reader checks, original card values and full procedure are in [Open Cells SIM Provisioning and Dual UE Preparation](sim_provisioning_and_dual_ue.md).

During setup, HTTP port 80 requests to Ubuntu archive mirrors timed out while `curl -4 -I --max-time 10 https://archive.ubuntu.com/ubuntu/` returned HTTP 200. Changing the Ubuntu archive/security source URIs to `https://archive.ubuntu.com/ubuntu/` and `https://security.ubuntu.com/ubuntu/` allowed `sudo apt update` to finish. This was a network-path issue, not a reader or PC/SC failure.

The original Open Cells download endpoint had an expired TLS certificate during setup. The source was obtained from [UICC GUI Sim Programmer](https://github.com/DanieleRiccobene/UICC-GUI-Sim-Programmer), whose repository includes the Open Cells CLI and PC/SC build target. The tested directory was `~/UICC-GUI-Sim-Programmer/uicc_v3.3`; the CLI was rebuilt locally:

```bash
cd ~/UICC-GUI-Sim-Programmer/uicc_v3.3
rm -f program_uicc_pcsc
make program_uicc_pcsc
```

The recorded Makefile command was:

```bash
g++ --std=c++11 -g3 -DPCSC \
  -I. -I/usr/include/PCSC -Wall program_uicc.c \
  -L/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  -lccid -o program_uicc_pcsc
```

The executable initially could not resolve `libccid.so`. Commands succeeded with the reader port `usb:072f/b100` and a per-command library path; the initial card read uses no programming or authentication arguments:

```bash
sudo env LD_LIBRARY_PATH=/lib/pcsc/drivers/ifd-ccid.bundle/Contents/Linux \
  ./program_uicc_pcsc --port usb:072f/b100
```

Both cards were subsequently personalized for PLMN `00101`: `OC011830` as IMSI `001010000000101`, and `OC011831` as `001010000000102`. Independently generated K/OPc pairs were stored in the respective protected home-directory files with mode 600. Both Milenage tests succeeded at SQN 64 and suggested core SQN 96. Both cards were verified through Quectel RM500QGL; SIM2 also passed in a second physical modem. These checks establish SIM provisioning and ready USIM applications. The two new SIMs have not yet passed end-to-end registration/PDU setup with the target RAN/Core.

The newer modem's `searching`/`detached` state and approximately 88% signal quality do not establish private-cell registration. Its `Volte_OpenMkt-Commercial-CMCC` carrier profile differs from a prior `ROW_Commercial` session; leave profiles unchanged during the completed UICC checks and investigate only if registration still fails after RAN, band/cell and subscriber settings are verified. See [Quectel verification and safe SIM swaps](sim_provisioning_and_dual_ue.md#verify-the-cards-through-quectel).

## 8 FlexRIC installation on Spark

FlexRIC is a separate Near-RT RIC project connected to OCUDU over E2. The tested revision is **`736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`** on `br-flexric`. Its standard KPM ASN.1 codec supports the tested Format 4 subscription and OCUDU Format 3 report encoding. The earlier pinned `1a3903a7` failed live subscription with OCUDU `050a2bb`; do not use that revision for this procedure. The [dated record](../../experiments/records/bringup/2026-10-07_flexric_bringup.md) distinguishes offline codec tests, successful live subscription and actual UE report reception.

### 8a Dependencies

`[SPARK]`

```bash
sudo apt update
sudo apt install -y build-essential cmake libsctp-dev pkg-config \
  cmake-curses-gui libconfig-dev libconfig++-dev
```

On 2026-10-07, the missing packages installed were `cmake-curses-gui` 3.28.3 and the two libconfig development packages 1.5. GCC 13.3, CMake 3.28.3, SCTP, SWIG 4.2 and Python 3.12 development files were already present. The C-only build below disables multilanguage support, so no Python xApp or database service is needed.

### 8b Source and build

For a new checkout only:

```bash
cd /home/nyu
git clone --branch br-flexric https://gitlab.eurecom.fr/mosaic5g/flexric.git
```

For the existing checkout, retain local changes and use its fetched history. Configure a separate build directory:

```bash
cd /home/nyu/flexric
git switch --detach 736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8
git log -1 --format='%h %s'

cmake -S . -B build-ocudu \
  -DCMAKE_C_COMPILER=gcc \
  -DCMAKE_BUILD_TYPE=Debug \
  -DE2AP_VERSION=E2AP_V3 \
  -DKPM_VERSION=KPM_V3_00 \
  -DXAPP_DB=NONE_XAPP \
  -DXAPP_MULTILANGUAGE=OFF

cmake --build build-ocudu -j 8
sudo cmake --install build-ocudu
```

Stop any running RIC/xApp before replacing their installed binaries/libraries. The correct KPM option for this revision is `KPM_V3_00`; the old revision used `KPM_V3`. Leave the old `build` directory out of these commands. Configuration should report E2AP v3, KPM v3.00, `NONE_XAPP` and multilanguage OFF. The reported build completed despite executable-stack linker warnings.

### 8c Installed files and artifact confirmation

The install prefix is `/usr/local`, with `CMAKE_INSTALL_LIBDIR=lib`:

| Artifact | Installed path |
|---|---|
| RIC | `/usr/local/bin/flexric/ric/nearRT-RIC` |
| C xApp | `/usr/local/bin/flexric/xApp/c/xapp_oran_moni` |
| KPM codec | `/usr/local/lib/flexric/libkpm_sm.so` |
| RIC config | `/usr/local/etc/flexric/ric.conf` |
| xApp config | `/usr/local/etc/flexric/xapp_oran_sm.conf` |

Both configs use `SM_DIR = "/usr/local/lib/flexric/"`. RIC listens on localhost SCTP E2 `36421` and E42 `36422`. Confirm the installed codec matches this build:

```bash
cd /home/nyu/flexric
sha256sum \
  build-ocudu/src/sm/kpm_sm/kpm_sm_v03.00/libkpm_sm.so \
  /usr/local/lib/flexric/libkpm_sm.so
```

Require identical hashes for the pair, not a fixed hash across builds. The runtime DU overlay and startup sequence are in [runbook stage 9](../legacy_single_ue.md#9-confirm-rf-and-start-the-du).

## 9 Installation and environment issue log

| Issue or observation | Evidence/status | Recorded resolution or next diagnostic |
|---|---|---|
| B210 access denied during environment inspection | Host permissions and execution restrictions must be distinguished | Inspect packaged udev rules; compare normal/privileged host access and sandbox restrictions |
| B210 connected through a 480M path | USB transport does not match the working baseline | Inspect cable/hub/port and establish USB 3 / 5000M |
| Compiler choice | Clang 18 successfully produced the current OCUDU binaries | Set per-build CMake compiler paths; retain default GCC |
| `DU_SPLIT_TYPE` unused | Variable is not used by `release_26_04` | Build targets `ocu` and `odu_split_8` |
| ZeroMQ library not found | Inspected build still supports the UHD radio implementation | No ZeroMQ dependency required for this B210 deployment |
| Native MongoDB 8 failed | Observed on this Spark; complete failure mechanism not preserved | Retain MongoDB 7 arm64 Docker workaround |
| RM500Q ports renamed after reconnect/reboot | Port numbers and modem IDs changed | Rediscover ports and their roles rather than reuse historical paths |
| Older Quectel preference commands returned ERROR | Tested firmware accepted QNWPREFCFG instead | Use the recorded firmware-compatible commands in the runbook |
| RAN scheduling warnings / recurring RF errors | Runtime privilege/performance issue after successful installation | Recorded performance script and privileged launch; sustained stability remains open |
| KPM Format 4 decode failure and RIC assertion | Old `1a3903a7` compiled a modified KPM ASN.1 codec | Install `73650812` from `build-ocudu` with `KPM_V3_00`; live subscription/deletion then passed |
| xApp exits after about 10 seconds | Expected behavior of the `73650812` C monitor example | Look for successful subscription, deletion response and `Test xApp run SUCCESSFULLY` |
| Huge negative KPM indication latency | Timestamp word-order and NTP/Unix conversion problems | [Repair built/tested/installed](../../experiments/records/bringup/2026-10-07_flexric_latency_fix.md); actual UE `2` produced 12 report ages of 499–717 microseconds with normal exit |
| Ubuntu archive HTTP requests timed out | HTTPS archive request returned HTTP 200 | Changed the relevant archive/security source URIs to HTTPS; APT update completed |
| Original Open Cells download had an expired TLS certificate | Source acquired from the GitHub repository | Rebuilt the local `uicc_v3.3` PC/SC CLI; preserve certificate verification |
| `program_uicc_pcsc` cannot load `libccid.so` | Library existed under the PC/SC driver bundle | Pass its directory through `sudo env LD_LIBRARY_PATH=...` for this command |
| `No ADM code of 8 figures, can't program the UICC` during initial read | No write/authentication arguments supplied; identities readable | Expected read-only message; add write arguments only for deliberate provisioning |
| Ready USIM but modem searching/detached | Both cards passed programming authentication and Quectel UICC checks | Provision matching core subscribers and validate target-cell registration; signal quality alone is insufficient |
| Quectel carrier configuration differs | Newer unit showed `Volte_OpenMkt-Commercial-CMCC`; prior session showed `ROW_Commercial` | Future registration diagnostic after cell settings and subscribers are correct; no profile change performed |

A successful build or driver probe does not establish SA registration or a usable PDU session. The 2026-10-05 NRF PLMN, subscriber, IPv4v6 and WWAN issues are documented separately in the dated debug record.

## 10 Installation completion record

- [ ] Spark OS, kernel, architecture and compiler versions recorded.
- [ ] UHD packages and matching images present; stopped-radio probe detects B210 over USB 3.
- [ ] OCUDU revision, compiler and CMake options recorded; CU/DU binaries exist with resolved libraries.
- [ ] Docker available; existing MongoDB 7 container/volume retained or created on a new host.
- [ ] Open5GS package version, service files and persistent TUN configuration inspected.
- [ ] UE laptop detects the modem's AT, QMI and network interfaces with the expected drivers.
- [ ] FlexRIC revision/options recorded; installed KPM library matches `build-ocudu` and configs reference the installed service directory.

The completed SIM setup adds the ACR39U/PC/SC environment, local PC/SC utility build, two independently provisioned and authenticated cards, and Quectel USIM verification. For reproduction, also verify credential-file mode 600 and the card-to-IMSI assignment using the [SIM guide](sim_provisioning_and_dual_ue.md#sim-assignments). The new `...101`/`...102` Open5GS subscriber records, local SQN handling, two UE registrations, DU2 operation, two PDU/WWAN paths and MPTCP remain next steps.

Continue with the [Full Reproduction Runbook](../legacy_single_ue.md) or the [Spark](../legacy_single_ue.md#1-baseline-and-physical-connections) and [UE laptop](../legacy_single_ue.md#10-prepare-a-new-ubuntulinux-laptop) quick commands. Actual UE KPM reception passed on 2026-10-07. The timestamp display repair is applied, built, installed and verified with actual UE reports. Precise timestamp/delay accuracy, synchronized application/KPM characterization, AI/CUDA development and MPTCP application tooling remain future work.
