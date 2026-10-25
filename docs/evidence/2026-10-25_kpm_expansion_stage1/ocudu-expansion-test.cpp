// SPDX-FileCopyrightText: Copyright (C) 2021-2026 Software Radio Systems Limited
// SPDX-License-Identifier: BSD-3-Clause-Open-MPI

#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.h"
#include "tests/unittests/e2/common/e2_test_helpers.h"
#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <gtest/gtest.h>
#include <limits>

using namespace ocudu;
using namespace asn1::e2sm;

namespace {

const std::vector<std::string> expanded_names = {
    "DRB.RlcSduDelayDl",
    "DRB.UEThpDl",
    "DRB.UEThpUl",
    "RRU.PrbTotDl",
    "RRU.PrbTotUl",
    "PUSCH.RSRP.dBFS",
    "PUSCH.SNR.dB",
    "CQI",
    "CQI.Samples",
    "DL.MCS",
    "UL.MCS",
    "DL.MCS.Samples",
    "UL.MCS.Samples",
    "UL.PHR.dB",
    "UL.PHR.AgeMs",
    "UL.BSR.Bytes",
    "UL.BSR.AgeMs",
    "DL.Buffer.Bytes",
    "DL.Buffer.AgeMs",
    "DL.MAC.Throughput",
    "UL.MAC.Throughput",
    "DL.HARQ.Ok",
    "DL.HARQ.Nok",
    "UL.CRC.Ok",
    "UL.CRC.Nok",
    "PRB.UsageDl.Percent",
    "PRB.UsageUl.Percent"
};

ue_id_c ue(unsigned id)
{
  ue_id_c result;
  result.set_gnb_du_ue_id().gnb_cu_ue_f1ap_id = id;
  return result;
}

label_info_list_l no_label()
{
  label_info_list_l labels;
  labels.resize(1);
  labels[0].meas_label.no_label_present = true;
  labels[0].meas_label.no_label = meas_label_s::no_label_e_::true_value;
  return labels;
}

scheduler_ue_metrics measurement(unsigned index)
{
  scheduler_ue_metrics result{};
  result.ue_index = to_du_ue_index(index);
  result.cqi_stats.update(10);
  result.cqi_stats.update(11);
  result.cqi_stats.update(11);
  result.dl_mcs = sch_mcs_index{13};
  result.ul_mcs = sch_mcs_index{0};
  result.nof_dl_mcs_reports = 3;
  result.nof_ul_mcs_reports = 1;
  result.dl_nof_ok = 7;
  result.dl_nof_nok = 1;
  result.ul_nof_ok = 3;
  result.ul_nof_nok = 2;
  result.last_phr = -4;
  result.phr_age_ms = 1250.5;
  result.bsr = 25000;
  result.bsr_age_ms = 17.5;
  result.dl_bs = 4096;
  result.dl_buffer_age_ms = 0.0;
  result.dl_brate_kbps = 0.08;
  result.ul_brate_kbps = 1234.56;
  result.tot_pdsch_prbs_used = 19;
  result.tot_pusch_prbs_used = 13;
  result.pusch_rsrp_db = -13.125F;
  result.pusch_snr_db = 21.75F;
  result.nof_pusch_snr_reports = 1;
  return result;
}

class du_kpm_expansion_test : public ::testing::Test
{
protected:
  dummy_f1ap_ue_id_translator translator;
  e2sm_kpm_du_meas_provider_impl provider{translator};

  static void SetUpTestSuite() { ocudulog::init(); }

  void report(std::initializer_list<scheduler_ue_metrics> values, unsigned slots = 10, unsigned prbs = 52)
  {
    scheduler_cell_metrics snapshot{};
    snapshot.nof_prbs = prbs;
    snapshot.nof_dl_slots = snapshot.nof_ul_slots = slots;
    snapshot.ue_metrics = values;
    provider.report_metrics(snapshot);
  }

  std::vector<meas_record_item_c> collect(const std::string& name, const std::vector<ue_id_c>& ids)
  {
    meas_type_c selected;
    selected.set_meas_name().from_string(name);
    std::vector<meas_record_item_c> result;
    EXPECT_TRUE(provider.get_meas_data(selected, no_label(), ids, {}, result));
    return result;
  }
};

TEST_F(du_kpm_expansion_test, sparse_ue_order_counts_signed_power_and_fractional_rates)
{
  auto peer = measurement(7);
  peer.cqi_stats = {};
  peer.cqi_stats.update(2);
  peer.last_phr = 8;
  peer.bsr = 0;
  report({peer, measurement(91)});
  for (const auto& expected : std::vector<std::pair<std::string, uint64_t>>{
           {"CQI", 11}, {"CQI.Samples", 3}, {"DL.MCS", 13}, {"UL.MCS", 0},
           {"DL.MCS.Samples", 3}, {"UL.MCS.Samples", 1}, {"DL.HARQ.Ok", 7},
           {"DL.HARQ.Nok", 1}, {"UL.CRC.Ok", 3}, {"UL.CRC.Nok", 2},
           {"UL.BSR.Bytes", 25000}, {"DL.Buffer.Bytes", 4096}}) {
    SCOPED_TRACE(expected.first);
    auto output = collect(expected.first, {ue(91), ue(199), ue(7)});
    ASSERT_EQ(output.size(), 3U);
    ASSERT_EQ(output[0].type(), meas_record_item_c::types::integer);
    EXPECT_EQ(output[0].integer(), expected.second);
    EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);
  }
  for (const auto& expected : std::vector<std::pair<std::string, double>>{
           {"UL.PHR.dB", -4}, {"UL.PHR.AgeMs", 1250.5}, {"UL.BSR.AgeMs", 17.5},
           {"DL.Buffer.AgeMs", 0}, {"DL.MAC.Throughput", 0.08}, {"UL.MAC.Throughput", 1234.56}}) {
    SCOPED_TRACE(expected.first);
    auto output = collect(expected.first, {ue(91), ue(199), ue(7)});
    ASSERT_EQ(output.size(), 3U);
    ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
    EXPECT_FLOAT_EQ(output[0].real().value, expected.second);
    EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);
  }
  EXPECT_EQ(collect("CQI", {ue(7)})[0].integer(), 2U);
  EXPECT_DOUBLE_EQ(collect("UL.PHR.dB", {ue(7)})[0].real().value, 8.0);
  EXPECT_EQ(collect("UL.BSR.Bytes", {ue(7)})[0].integer(), 0U);
}

TEST_F(du_kpm_expansion_test, absence_zero_reset_and_nonfinite_are_distinct)
{
  scheduler_ue_metrics empty{};
  empty.ue_index = to_du_ue_index(91);
  report({empty});
  for (const char* name : {"CQI", "DL.MCS", "UL.MCS", "UL.PHR.dB", "UL.PHR.AgeMs",
                           "UL.BSR.Bytes", "UL.BSR.AgeMs", "DL.Buffer.Bytes", "DL.Buffer.AgeMs"}) {
    EXPECT_EQ(collect(name, {ue(91)})[0].type(), meas_record_item_c::types::no_value) << name;
  }
  for (const char* name : {"CQI.Samples", "DL.MCS.Samples", "UL.MCS.Samples",
                           "DL.HARQ.Ok", "DL.HARQ.Nok", "UL.CRC.Ok", "UL.CRC.Nok"}) {
    EXPECT_EQ(collect(name, {ue(91)})[0].integer(), 0U) << name;
  }
  auto valid = measurement(91);
  valid.cqi_stats = {};
  valid.cqi_stats.update(0);
  valid.last_phr = 0;
  valid.bsr = valid.dl_bs = 0;
  report({valid});
  EXPECT_EQ(collect("CQI", {ue(91)})[0].integer(), 0U);
  EXPECT_DOUBLE_EQ(collect("UL.PHR.dB", {ue(91)})[0].real().value, 0.0);
  EXPECT_EQ(collect("DL.Buffer.Bytes", {ue(91)})[0].integer(), 0U);
  for (double invalid : {std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()}) {
    valid.dl_brate_kbps = invalid;
    report({valid});
    EXPECT_EQ(collect("DL.MAC.Throughput", {ue(91)})[0].type(), meas_record_item_c::types::no_value);
  }
  report({measurement(7)});
  EXPECT_EQ(collect("CQI", {ue(91)})[0].type(), meas_record_item_c::types::no_value);
}

TEST_F(du_kpm_expansion_test, prb_sparse_indices_multiply_before_division_and_guard_zero_capacity)
{
  report({measurement(91)});
  EXPECT_EQ(collect("RRU.PrbTotDl", {ue(91)})[0].integer(), 3U); // floor(19*100/(10*52)), not 1*100/52.
  EXPECT_EQ(collect("RRU.PrbUsedDl", {ue(91)})[0].integer(), 1U);
  EXPECT_EQ(collect("RRU.PrbTotUl", {ue(91)})[0].integer(), 2U);
  EXPECT_EQ(collect("RRU.PrbUsedUl", {ue(91)})[0].integer(), 1U);
  report({measurement(91)}, 0);
  EXPECT_EQ(collect("RRU.PrbTotDl", {ue(91)})[0].type(), meas_record_item_c::types::no_value);
  report({measurement(91)}, 10, 0);
  EXPECT_EQ(collect("RRU.PrbTotUl", {ue(91)})[0].type(), meas_record_item_c::types::no_value);
}

TEST_F(du_kpm_expansion_test, real_prb_usage_preserves_fractional_sub_percent_and_valid_zero)
{
  auto empty = measurement(7);
  empty.tot_pdsch_prbs_used = empty.tot_pusch_prbs_used = 0;
  report({measurement(91), empty});
  for (const auto& expected : std::vector<std::pair<std::string, double>>{
           {"PRB.UsageDl.Percent", 1900.0 / 520.0}, {"PRB.UsageUl.Percent", 2.5}}) {
    auto values = collect(expected.first, {ue(7), ue(91), ue(199)});
    ASSERT_EQ(values.size(), 3U);
    ASSERT_EQ(values[0].type(), meas_record_item_c::types::real);
    EXPECT_DOUBLE_EQ(values[0].real().value, 0.0);
    ASSERT_EQ(values[1].type(), meas_record_item_c::types::real);
    EXPECT_FLOAT_EQ(values[1].real().value, expected.second);
    EXPECT_EQ(values[2].type(), meas_record_item_c::types::no_value);
  }
  EXPECT_EQ(collect("RRU.PrbTotDl", {ue(91)})[0].integer(), 3U);
  EXPECT_EQ(collect("RRU.PrbTotUl", {ue(91)})[0].integer(), 2U);

  auto small = measurement(91);
  small.tot_pdsch_prbs_used = small.tot_pusch_prbs_used = 1;
  report({small});
  EXPECT_FLOAT_EQ(collect("PRB.UsageDl.Percent", {ue(91)})[0].real().value, 100.0 / 520.0);
  EXPECT_FLOAT_EQ(collect("PRB.UsageUl.Percent", {ue(91)})[0].real().value, 100.0 / 520.0);
  EXPECT_EQ(collect("RRU.PrbTotDl", {ue(91)})[0].integer(), 0U);
  EXPECT_EQ(collect("RRU.PrbTotUl", {ue(91)})[0].integer(), 0U);
}

TEST_F(du_kpm_expansion_test, real_prb_usage_zero_denominator_or_missing_source_is_no_value)
{
  for (const auto& capacity : {std::make_pair(0U, 52U), std::make_pair(10U, 0U)}) {
    report({measurement(91)}, capacity.first, capacity.second);
    for (const char* name : {"PRB.UsageDl.Percent", "PRB.UsageUl.Percent"}) {
      EXPECT_EQ(collect(name, {ue(91)})[0].type(), meas_record_item_c::types::no_value);
    }
  }
  report({});
  for (const char* name : {"PRB.UsageDl.Percent", "PRB.UsageUl.Percent"}) {
    EXPECT_EQ(collect(name, {ue(91)})[0].type(), meas_record_item_c::types::no_value);
  }
}

TEST_F(du_kpm_expansion_test, capability_scope_labels_and_aper_advertisement)
{
  auto names = provider.get_supported_metric_names(UE_LEVEL);
  e2sm_kpm_asn1_packer packer(provider);
  auto encoded = packer.pack_ran_function_description();
  e2sm_kpm_ran_function_description_s description;
  asn1::cbit_ref reader(encoded);
  ASSERT_EQ(description.unpack(reader), asn1::OCUDUASN_SUCCESS);
  for (size_t i = 7; i < expanded_names.size(); ++i) {
    const auto& name = expanded_names[i];
    SCOPED_TRACE(name);
    EXPECT_NE(std::find(names.begin(), names.end(), name), names.end());
    meas_type_c selected;
    selected.set_meas_name().from_string(name);
    EXPECT_TRUE(provider.is_metric_supported(selected, no_label()[0].meas_label, UE_LEVEL, false));
    EXPECT_FALSE(provider.is_metric_supported(selected, no_label()[0].meas_label, E2_NODE_LEVEL, false));
    EXPECT_FALSE(provider.is_metric_supported(selected, no_label()[0].meas_label, UE_LEVEL, true));
    auto labels = no_label();
    labels[0].meas_label.sum_present = true;
    std::vector<meas_record_item_c> output;
    EXPECT_FALSE(provider.get_meas_data(selected, labels, {ue(91)}, {}, output));
    ASSERT_EQ(output.size(), 1U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
    for (const auto& style : description.ric_report_style_list) {
      const auto found = std::count_if(style.meas_info_action_list.begin(), style.meas_info_action_list.end(),
                                      [&name](const auto& info) { return info.meas_name.to_string() == name; });
      EXPECT_EQ(found, style.ric_report_style_type >= 2 ? 1 : 0);
    }
  }
}

TEST_F(du_kpm_expansion_test, expanded_100ms_aper_fixture_preserves_types_and_sparse_ues)
{
  report({measurement(91), measurement(7)});
  for (unsigned id : {91U, 7U}) {
    rlc_metrics rlc{};
    rlc.ue_index = to_du_ue_index(id);
    rlc.rb_id = rb_id_t(drb_id_t(1));
    rlc.metrics_period = std::chrono::milliseconds(100);
    rlc.rx.num_sdus = rlc.rx.num_pdus = 1;
    rlc.rx.num_sdu_bytes = rlc.rx.num_pdu_bytes = 1000;
    rlc.rx.mode_specific = rlc_am_rx_metrics{};
    rlc.tx.tx_high.num_sdus = 1;
    rlc.tx.tx_low.num_of_pulled_sdus = 1;
    rlc.tx.tx_low.sum_sdu_latency_us = 100;
    rlc.tx.tx_low.mode_specific = rlc_am_tx_metrics_lower{};
    provider.report_metrics(rlc);
  }
  auto large = measurement(7);
  large.bsr = std::numeric_limits<uint32_t>::max();
  report({measurement(91), large});
  e2sm_kpm_action_definition_s action;
  action.ric_style_type = 4;
  auto& format = action.action_definition_formats.set_action_definition_format4();
  matching_ue_cond_per_sub_item_s condition;
  condition.test_cond_info.test_type.set_ul_r_srp().value = test_cond_type_c::ul_r_srp_opts::true_value;
  format.matching_ue_cond_list.push_back(condition);
  format.sub_info.granul_period = 100;
  for (const auto& name : expanded_names) {
    meas_info_item_s info;
    info.meas_type.set_meas_name().from_string(name);
    info.label_info_list = no_label();
    format.sub_info.meas_info_list.push_back(info);
  }
  e2sm_kpm_report_service_style4 service(action, provider);
  ASSERT_TRUE(service.collect_measurements());
  ASSERT_TRUE(service.is_ind_msg_ready());
  byte_buffer encoded = service.get_indication_message();
  e2sm_kpm_ind_msg_s decoded;
  asn1::cbit_ref reader(encoded);
  ASSERT_EQ(decoded.unpack(reader), asn1::OCUDUASN_SUCCESS);
  const auto& rows = decoded.ind_msg_formats.ind_msg_format3().ue_meas_report_list;
  ASSERT_EQ(rows.size(), 2U);
  for (const auto& row : rows) {
    EXPECT_EQ(row.meas_report.granul_period, 100U);
    ASSERT_EQ(row.meas_report.meas_data[0].meas_record.size(), expanded_names.size());
  }
  auto header_bytes = service.get_indication_header();
  auto indication = generate_e2_ind_msg(header_bytes, encoded);
  byte_buffer full_pdu;
  asn1::bit_ref e2_writer(full_pdu);
  ASSERT_EQ(indication.pdu.pack(e2_writer), asn1::OCUDUASN_SUCCESS);
  EXPECT_LT(full_pdu.length(), 9100U);
  if (const char* directory = std::getenv("FALCON_IDENTITY_FIXTURE_DIR")) {
    std::ofstream size(std::string(directory) + "/du_expanded_size.txt");
    size << "Synthetic two-UE KPM payload bytes: " << encoded.length()
         << "\nSynthetic full E2AP indication bytes: " << full_pdu.length() << "\n";
  }
  if (const char* directory = std::getenv("FALCON_IDENTITY_FIXTURE_DIR")) {
    std::ofstream file(std::string(directory) + "/du_expanded_message.asn", std::ios::binary);
    for (auto byte : encoded) file.put(static_cast<char>(byte));
    ASSERT_TRUE(file.good());
    e2sm_kpm_ind_hdr_s header;
    header.ind_hdr_formats.ind_hdr_format1().collet_start_time.from_number(2208988900ULL << 32);
    byte_buffer hdr;
    asn1::bit_ref hdr_writer(hdr);
    ASSERT_EQ(header.pack(hdr_writer), asn1::OCUDUASN_SUCCESS);
    std::ofstream output(std::string(directory) + "/du_expanded_header.asn", std::ios::binary);
    for (auto byte : hdr) output.put(static_cast<char>(byte));
    ASSERT_TRUE(output.good());
  }
}

} // namespace
