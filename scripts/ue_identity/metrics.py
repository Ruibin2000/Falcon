"""Metric contracts for the preserved baselines and the first DU expansion."""

BASE_FIVE = (
    "DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl", "RRU.PrbTotDl", "RRU.PrbTotUl",
)
SEVEN = BASE_FIVE + ("PUSCH.RSRP.dBFS", "PUSCH.SNR.dB")
# Types describe E2 measurement records, before application-derived values.
STAGE1 = {
    "CQI": ("index", "integer"),
    "CQI.Samples": ("samples", "integer"),
    "DL.MCS": ("index", "integer"),
    "UL.MCS": ("index", "integer"),
    "DL.MCS.Samples": ("samples", "integer"),
    "UL.MCS.Samples": ("samples", "integer"),
    "UL.PHR.dB": ("dB", "real"),
    "UL.PHR.AgeMs": ("ms", "real"),
    "UL.BSR.Bytes": ("bytes", "integer"),
    "UL.BSR.AgeMs": ("ms", "real"),
    "DL.Buffer.Bytes": ("bytes", "integer"),
    "DL.Buffer.AgeMs": ("ms", "real"),
    "DL.MAC.Throughput": ("kbit/s", "real"),
    "UL.MAC.Throughput": ("kbit/s", "real"),
    "DL.HARQ.Ok": ("count", "integer"),
    "DL.HARQ.Nok": ("count", "integer"),
    "UL.CRC.Ok": ("count", "integer"),
    "UL.CRC.Nok": ("count", "integer"),
    "PRB.UsageDl.Percent": ("%", "real"),
    "PRB.UsageUl.Percent": ("%", "real"),
}
EXPANDED = SEVEN + tuple(STAGE1)

UNITS = {
    "DRB.RlcSduDelayDl": "0.1 ms", "DRB.UEThpDl": "kbit/s", "DRB.UEThpUl": "kbit/s",
    "RRU.PrbTotDl": "%", "RRU.PrbTotUl": "%", "FALCON.UE.RRCState": "enum",
    "PUSCH.RSRP.dBFS": "dBFS", "PUSCH.SNR.dB": "dB",
    **{name: contract[0] for name, contract in STAGE1.items()},
}


def derive_failure_ratios(metrics):
    """Keep xApp calculations separate from the unmodified E2 measurement row."""
    result = {}
    for name, ok, nok in (
        ("DL.HARQ.FailureRatio", "DL.HARQ.Ok", "DL.HARQ.Nok"),
        ("UL.CRC.FailureRatio", "UL.CRC.Ok", "UL.CRC.Nok"),
    ):
        if ok not in metrics and nok not in metrics:
            continue
        counts = [metrics.get(key, {}) for key in (ok, nok)]
        valid = all(item.get("type") == "integer" and type(item.get("value")) is int
                    and 0 <= item["value"] <= (1 << 32) - 1 for item in counts)
        total = sum(item["value"] for item in counts) if valid else 0
        value = 100.0 * counts[1]["value"] / total if total else None
        result[name] = {"type": "real" if value is not None else "no_value",
                        "value": value, "unit": "%", "derived_from": [ok, nok]}
    return result
