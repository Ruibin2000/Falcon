// Offline regression checks for OCUDU 050a2bb's DU RSRP/SNR KPM extension.
// This test calls the real provider and ASN.1 codec; it starts no network or RF service.

#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.h"
#include "lib/scheduler/config/cell_configuration.h"
#include "lib/scheduler/logging/scheduler_metrics_handler.h"
#include "ocudu/scheduler/config/ran_cell_config_helper.h"
#include "ocudu/scheduler/config/scheduler_expert_config_factory.h"
#include "ocudu/scheduler/result/sched_result.h"
#include "ocudu/adt/byte_buffer.h"
#include "ocudu/ocudulog/ocudulog.h"
#include <algorithm>
#include <cstdlib>
#include <fstream>
#include <gtest/gtest.h>
#include <iterator>
#include <limits>
#include <map>

using namespace ocudu;
using namespace asn1::e2sm;

namespace {

constexpr const char* metric_name = "FALCON.PUSCH.RSRP.dBFS";
constexpr const char* snr_metric_name = "FALCON.PUSCH.SNR.dB";

// F1AP identifiers deliberately differ from sparse DU indices. An identity mapper
// would hide a regression that indexes the metrics vector with the requested ID.
class sparse_ue_id_translator : public odu::f1ap_ue_id_translator
{
public:
  void remove_ue(du_ue_index_t index) { ids.erase(index); }

  std::optional<gnb_cu_ue_f1ap_id_t> get_gnb_cu_ue_f1ap_id(const du_ue_index_t& index) const override
  {
    const auto it = ids.find(index);
    if (it == ids.end()) {
      return std::nullopt;
    }
    return int_to_gnb_cu_ue_f1ap_id(it->second);
  }

  std::optional<gnb_cu_ue_f1ap_id_t> get_gnb_cu_ue_f1ap_id(const gnb_du_ue_f1ap_id_t& id) const override
  {
    return get_gnb_cu_ue_f1ap_id(to_du_ue_index(gnb_du_ue_f1ap_id_to_uint(id)));
  }

  gnb_du_ue_f1ap_id_t get_gnb_du_ue_f1ap_id(const du_ue_index_t& index) override
  {
    return int_to_gnb_du_ue_f1ap_id(index);
  }

  gnb_du_ue_f1ap_id_t get_gnb_du_ue_f1ap_id(const gnb_cu_ue_f1ap_id_t& id) override
  {
    return int_to_gnb_du_ue_f1ap_id(get_ue_index(id));
  }

  du_ue_index_t get_ue_index(const gnb_du_ue_f1ap_id_t& id) override
  {
    const auto index = to_du_ue_index(gnb_du_ue_f1ap_id_to_uint(id));
    return ids.count(index) == 0 ? INVALID_DU_UE_INDEX : index;
  }

  du_ue_index_t get_ue_index(const gnb_cu_ue_f1ap_id_t& id) override
  {
    for (const auto& pair : ids) {
      if (pair.second == gnb_cu_ue_f1ap_id_to_uint(id)) {
        return pair.first;
      }
    }
    return INVALID_DU_UE_INDEX;
  }

private:
  std::map<du_ue_index_t, uint32_t> ids{
      {to_du_ue_index(7), 1007}, {to_du_ue_index(91), 2091}, {to_du_ue_index(199), 3199}};
};

ue_id_c make_ue(uint32_t f1ap_id)
{
  ue_id_c ue;
  ue.set_gnb_du_ue_id().gnb_cu_ue_f1ap_id = f1ap_id;
  return ue;
}

label_info_list_l make_no_label()
{
  label_info_item_s item;
  item.meas_label.no_label_present = true;
  item.meas_label.no_label         = meas_label_s::no_label_e_::true_value;
  label_info_list_l result;
  result.push_back(item);
  return result;
}

scheduler_ue_metrics make_measurement(unsigned index, float power, float snr = 23.75F, unsigned samples = 1)
{
  scheduler_ue_metrics result{};
  result.ue_index      = to_du_ue_index(index);
  result.pci           = 1;
  result.rnti          = static_cast<rnti_t>(0x4600 + index);
  result.pusch_rsrp_db = power;
  result.pusch_snr_db  = snr; // The PHY-selected ul_sinr_dB value is reported using the SNR name.
  result.nof_pusch_snr_reports = samples;
  return result;
}

class du_rf_metrics_kpm_test : public ::testing::Test
{
protected:
  du_rf_metrics_kpm_test() : provider(translator)
  {
    metric.set_meas_name().from_string(metric_name);
  }

  static void SetUpTestSuite() { ocudulog::init(); }
  void TearDown() override { ocudulog::flush(); }

  void report(std::initializer_list<scheduler_ue_metrics> measurements)
  {
    scheduler_cell_metrics snapshot{};
    for (const auto& measurement : measurements) {
      snapshot.ue_metrics.push_back(measurement);
    }
    provider.report_metrics(snapshot);
  }

  bool collect(const std::vector<ue_id_c>& ues, std::vector<meas_record_item_c>& output)
  {
    return provider.get_meas_data(metric, make_no_label(), ues, std::nullopt, output);
  }

  bool collect_named(const char* name, const std::vector<ue_id_c>& ues, std::vector<meas_record_item_c>& output)
  {
    meas_type_c selected;
    selected.set_meas_name().from_string(name);
    return provider.get_meas_data(selected, make_no_label(), ues, std::nullopt, output);
  }

  sparse_ue_id_translator              translator;
  e2sm_kpm_du_meas_provider_impl       provider;
  meas_type_c                         metric;
};

TEST_F(du_rf_metrics_kpm_test, advertises_both_rf_metrics_at_ue_level_and_rejects_other_scopes)
{
  const auto ue_names   = provider.get_supported_metric_names(UE_LEVEL);
  const auto node_names = provider.get_supported_metric_names(E2_NODE_LEVEL);
  const auto label = make_no_label()[0].meas_label;
  report({make_measurement(7, -12.875F)});
  for (const char* name : {metric_name, snr_metric_name}) {
    SCOPED_TRACE(name);
    meas_type_c selected;
    selected.set_meas_name().from_string(name);
    EXPECT_NE(std::find(ue_names.begin(), ue_names.end(), name), ue_names.end());
    EXPECT_EQ(std::find(node_names.begin(), node_names.end(), name), node_names.end());
    EXPECT_TRUE(provider.is_metric_supported(selected, label, UE_LEVEL, false));
    EXPECT_FALSE(provider.is_metric_supported(selected, label, E2_NODE_LEVEL, false));
    EXPECT_FALSE(provider.is_metric_supported(selected, label, UE_LEVEL, true));
    std::vector<meas_record_item_c> output;
    EXPECT_FALSE(collect_named(name, {}, output));
    EXPECT_TRUE(output.empty());
    EXPECT_FALSE(provider.get_meas_data(selected, make_no_label(), {make_ue(1007)}, cgi_c{}, output));
    ASSERT_EQ(output.size(), 1U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  }
  for (const char* unsupported : {"RSRP", "RSRQ", "SNR", "SINR", "FALCON.PUSCH.SINR.dB"}) {
    meas_type_c selected;
    selected.set_meas_name().from_string(unsupported);
    EXPECT_EQ(std::find(ue_names.begin(), ue_names.end(), unsupported), ue_names.end());
    EXPECT_EQ(std::find(node_names.begin(), node_names.end(), unsupported), node_names.end());
    EXPECT_FALSE(provider.is_metric_supported(selected, label, UE_LEVEL, false));
    std::vector<meas_record_item_c> output;
    EXPECT_FALSE(collect_named(unsupported, {make_ue(1007)}, output));
    EXPECT_TRUE(output.empty());
  }
}

TEST_F(du_rf_metrics_kpm_test, snr_is_distinct_from_rsrp_and_preserves_sparse_request_order)
{
  report({make_measurement(7, -13.125F, 21.75F), make_measurement(91, -3.5F, -2.875F)});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(2091), make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 2U);
  ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
  ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[0].real().value, -2.875);
  EXPECT_DOUBLE_EQ(output[1].real().value, 21.75);
  output.clear();
  ASSERT_TRUE(collect({make_ue(2091), make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 2U);
  EXPECT_DOUBLE_EQ(output[0].real().value, -3.5);
  EXPECT_DOUBLE_EQ(output[1].real().value, -13.125);
}

TEST_F(du_rf_metrics_kpm_test, snr_zero_is_valid_only_with_a_sample_and_missing_ues_keep_their_positions)
{
  report({make_measurement(7, -13.125F, 0.0F, 3), make_measurement(91, 0.0F, 0.0F, 0)});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(2091), make_ue(9999), make_ue(3199), make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 4U);
  for (unsigned index : {0U, 1U, 2U}) {
    EXPECT_EQ(output[index].type(), meas_record_item_c::types::no_value);
  }
  ASSERT_EQ(output[3].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[3].real().value, 0.0);
  report({make_measurement(7, -13.125F, 21.75F, 0)});
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
}

TEST_F(du_rf_metrics_kpm_test, snr_nan_infinity_wrong_ue_and_replaced_snapshot_produce_no_value)
{
  ue_id_c wrong_type;
  wrong_type.set_gnb_cu_up_ue_id();
  for (float invalid : {std::numeric_limits<float>::quiet_NaN(), std::numeric_limits<float>::infinity(),
                        -std::numeric_limits<float>::infinity()}) {
    report({make_measurement(7, -13.125F, invalid)});
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(snr_metric_name, {wrong_type, make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 2U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
    EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);
  }
  report({make_measurement(7, -13.125F, 21.75F)});
  report({});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  report({make_measurement(91, 0.0F, -0.5F)});
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007), make_ue(2091)}, output));
  ASSERT_EQ(output.size(), 2U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[1].real().value, -0.5);
}

TEST_F(du_rf_metrics_kpm_test, preserves_negative_fractional_power_and_zero_in_request_order)
{
  report({make_measurement(7, -12.875F), make_measurement(91, 0.0F)});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect({make_ue(2091), make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 2U);
  ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
  ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[0].real().value, 0.0);
  EXPECT_DOUBLE_EQ(output[1].real().value, -12.875);
}

TEST_F(du_rf_metrics_kpm_test, missing_ue_nan_and_infinity_produce_no_value_without_shifting_records)
{
  report({make_measurement(7, -0.5F), make_measurement(91, std::numeric_limits<float>::quiet_NaN())});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect({make_ue(2091), make_ue(9999), make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 3U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);
  ASSERT_EQ(output[2].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[2].real().value, -0.5);

  for (float invalid : {std::numeric_limits<float>::infinity(), -std::numeric_limits<float>::infinity()}) {
    report({make_measurement(7, invalid)});
    output.clear();
    ASSERT_TRUE(collect({make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 1U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  }
}

TEST_F(du_rf_metrics_kpm_test, empty_or_replaced_snapshot_does_not_reuse_a_previous_power)
{
  report({make_measurement(7, -18.25F)});
  report({});
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect({make_ue(1007), make_ue(2091)}, output));
  ASSERT_EQ(output.size(), 2U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);

  report({make_measurement(91, -6.25F)});
  output.clear();
  ASSERT_TRUE(collect({make_ue(1007), make_ue(2091)}, output));
  ASSERT_EQ(output.size(), 2U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[1].real().value, -6.25);
}

TEST_F(du_rf_metrics_kpm_test, incompatible_ue_type_returns_no_value_in_place)
{
  report({make_measurement(7, -12.875F)});
  ue_id_c wrong_type;
  wrong_type.set_gnb_cu_up_ue_id();
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect({wrong_type, make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 2U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[1].real().value, -12.875);
}

TEST_F(du_rf_metrics_kpm_test, unsupported_labels_are_rejected_by_admission_and_collection)
{
  report({make_measurement(7, -12.875F)});
  auto labels = make_no_label();
  labels[0].meas_label.five_qi_present = true;
  labels[0].meas_label.five_qi         = 9;
  auto duplicate = make_no_label();
  duplicate.push_back(duplicate[0]);
  for (const char* name : {metric_name, snr_metric_name}) {
    meas_type_c selected;
    selected.set_meas_name().from_string(name);
    EXPECT_FALSE(provider.is_metric_supported(selected, labels[0].meas_label, UE_LEVEL, false));
    for (const auto& invalid : {labels, duplicate, label_info_list_l{}}) {
      std::vector<meas_record_item_c> output;
      EXPECT_FALSE(provider.get_meas_data(selected, invalid, {make_ue(1007), make_ue(2091)}, std::nullopt, output));
      ASSERT_EQ(output.size(), 2U);
      EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
      EXPECT_EQ(output[1].type(), meas_record_item_c::types::no_value);
    }
  }
}

e2sm_kpm_action_definition_s make_style4_action(label_info_list_l labels, const char* name = metric_name)
{
  e2sm_kpm_action_definition_s action;
  action.ric_style_type = 4;
  auto& format4 = action.action_definition_formats.set_action_definition_format4();
  matching_ue_cond_per_sub_item_s condition;
  condition.test_cond_info.test_type.set_ul_r_srp().value = test_cond_type_c::ul_r_srp_opts::true_value;
  format4.matching_ue_cond_list.push_back(condition);
  format4.sub_info.granul_period = 1000;
  meas_info_item_s info;
  info.meas_type.set_meas_name().from_string(name);
  info.label_info_list = labels;
  format4.sub_info.meas_info_list.push_back(info);
  return action;
}

asn1::e2ap::ric_action_to_be_setup_item_s make_ric_action(const e2sm_kpm_action_definition_s& action)
{
  byte_buffer wire;
  asn1::bit_ref writer(wire);
  EXPECT_EQ(action.pack(writer), asn1::OCUDUASN_SUCCESS);
  asn1::e2ap::ric_action_to_be_setup_item_s result;
  result.ric_action_type = asn1::e2ap::ric_action_type_opts::report;
  (void)result.ric_action_definition.resize(wire.length());
  std::copy(wire.begin(), wire.end(), result.ric_action_definition.begin());
  return result;
}

TEST_F(du_rf_metrics_kpm_test, actual_style4_admission_rejects_missing_duplicate_and_mixed_labels)
{
  e2sm_kpm_asn1_packer packer(provider);
  e2sm_kpm_impl iface(ocudulog::fetch_basic_logger("TEST"), packer, provider);
  auto duplicate = make_no_label();
  duplicate.push_back(duplicate[0]);
  auto mixed = make_no_label();
  mixed[0].meas_label.five_qi_present = true;
  mixed[0].meas_label.five_qi = 9;
  for (const char* name : {metric_name, snr_metric_name}) {
    EXPECT_TRUE(iface.action_supported(make_ric_action(make_style4_action(make_no_label(), name))));
    EXPECT_FALSE(iface.action_supported(make_ric_action(make_style4_action(duplicate, name))));
    EXPECT_FALSE(iface.action_supported(make_ric_action(make_style4_action(mixed, name))));
  }
  for (const char* name : {"RSRQ", "SNR", "FALCON.PUSCH.SINR.dB"}) {
    EXPECT_FALSE(iface.action_supported(make_ric_action(make_style4_action(make_no_label(), name))));
  }

  // An empty label list violates the ASN.1 minimum length, so test the public
  // admission entry with a handler returning an already decoded definition.
  class decoded_action_handler : public e2sm_kpm_asn1_packer {
  public:
    decoded_action_handler(e2sm_kpm_meas_provider& source, const char* name_) :
      e2sm_kpm_asn1_packer(source), name(name_) {}
    e2sm_action_definition handle_packed_e2sm_action_definition(const byte_buffer&) override
    {
      e2sm_action_definition decoded;
      decoded.service_model = e2sm_service_model_t::KPM;
      decoded.action_definition = make_style4_action({}, name);
      return decoded;
    }
  private:
    const char* name;
  };
  for (const char* name : {metric_name, snr_metric_name}) {
    decoded_action_handler empty_label_handler(provider, name);
    e2sm_kpm_impl empty_label_iface(ocudulog::fetch_basic_logger("TEST"), empty_label_handler, provider);
    EXPECT_FALSE(empty_label_iface.action_supported(make_ric_action(make_style4_action(make_no_label(), name))));
  }
}

TEST_F(du_rf_metrics_kpm_test, actual_scheduler_crc_samples_export_the_count_average_and_reset_each_window)
{
  class capturing_notifier : public scheduler_cell_metrics_notifier {
  public:
    scheduler_cell_metrics current;
    scheduler_cell_metrics last_report;
    unsigned commits = 0;
    scheduler_cell_metrics& get_next() override
    {
      current = {};
      return current;
    }
    void commit(scheduler_cell_metrics& value) override
    {
      last_report = value;
      ++commits;
    }
    bool is_sched_report_required(slot_point_extended) const override { return true; }
  } notifier;
  const auto expert = config_helpers::make_default_scheduler_expert_config();
  sched_cell_configuration_request_message cell_request{};
  cell_request.cell_index = to_du_cell_index(0);
  cell_request.ran = config_helpers::make_default_ran_cell_config();
  cell_request.si_scheduling.sib1_payload_size = units::bytes{101};
  cell_configuration cell(expert, cell_request);
  cell_metrics_handler scheduler(cell, sched_cell_configuration_request_message::metrics_config{&notifier});
  scheduler.handle_ue_creation(to_du_ue_index(7), to_rnti(0x4607), pci_t{1});
  slot_point_extended slot{subcarrier_spacing::kHz15, 2000};
  sched_result result{};
  result.dl.nof_dl_symbols = 14;
  result.ul.nof_ul_symbols = 14;
  const auto next_report = [&] {
    scheduler.push_result(slot++, result, std::chrono::microseconds{0});
    EXPECT_EQ(notifier.last_report.ue_metrics.size(), 1U);
    provider.report_metrics(notifier.last_report);
  };
  next_report();
  ASSERT_EQ(notifier.commits, 1U);
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 0U);
  EXPECT_FLOAT_EQ(notifier.last_report.ue_metrics[0].pusch_snr_db, 0.0F);
  std::vector<meas_record_item_c> output;
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);

  ul_crc_pdu_indication crc{};
  crc.ue_index = to_du_ue_index(7);
  crc.rnti = to_rnti(0x4607);
  crc.tb_crc_success = true;
  // A CRC without a SNR report must not turn the missing default 0 into a measurement.
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  next_report();
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 0U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].ul_nof_ok, 1U);
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);

  crc.ul_sinr_dB = 0.0F;
  crc.ul_rsrp_dBFS = -13.125F;
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  next_report();
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 1U);
  EXPECT_FLOAT_EQ(notifier.last_report.ue_metrics[0].pusch_snr_db, 0.0F);
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[0].real().value, 0.0);

  for (float value : {21.75F, -1.25F}) {
    crc.ul_sinr_dB = value;
    scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  }
  next_report();
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 2U);
  EXPECT_FLOAT_EQ(notifier.last_report.ue_metrics[0].pusch_snr_db, 10.25F);
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[0].real().value, 10.25);
  output.clear();
  ASSERT_TRUE(collect({make_ue(1007)}, output));
  ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(output[0].real().value, -13.125);

  next_report();
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 0U);
  EXPECT_FLOAT_EQ(notifier.last_report.ue_metrics[0].pusch_snr_db, 0.0F);
  output.clear();
  ASSERT_TRUE(collect_named(snr_metric_name, {make_ue(1007)}, output));
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
}

TEST_F(du_rf_metrics_kpm_test, real_and_no_value_survive_actual_style4_collection_and_kpm_format3_aper_codec)
{
  report({make_measurement(7, -13.125F, 21.75F), make_measurement(91, 0.0F, 0.0F),
          make_measurement(199, -std::numeric_limits<float>::infinity(), 0.0F, 0)});
  // Style 4 currently discovers active UEs from the provider's RLC snapshots.
  for (unsigned index : {7U, 91U, 199U}) {
    rlc_metrics rlc{};
    rlc.ue_index = to_du_ue_index(index);
    rlc.rb_id = rb_id_t(drb_id_t(1));
    rlc.metrics_period = std::chrono::milliseconds(1000);
    provider.report_metrics(rlc);
  }
  e2sm_kpm_asn1_packer packer(provider);
  e2sm_kpm_impl iface(ocudulog::fetch_basic_logger("TEST"), packer, provider);
  auto action = make_style4_action(make_no_label());
  auto snr_info = action.action_definition_formats.action_definition_format4().sub_info.meas_info_list[0];
  snr_info.meas_type.set_meas_name().from_string(snr_metric_name);
  action.action_definition_formats.action_definition_format4().sub_info.meas_info_list.push_back(snr_info);
  const auto ric_action = make_ric_action(action);
  ASSERT_TRUE(iface.action_supported(ric_action));
  auto service = iface.get_e2sm_report_service(ric_action.ric_action_definition);
  ASSERT_NE(service, nullptr);
  ASSERT_TRUE(service->collect_measurements());
  ASSERT_TRUE(service->is_ind_msg_ready());
  const byte_buffer wire = service->get_indication_message();
  ASSERT_FALSE(wire.empty());
  e2sm_kpm_ind_msg_s decoded;
  asn1::cbit_ref reader(wire);
  ASSERT_EQ(decoded.unpack(reader), asn1::OCUDUASN_SUCCESS);
  const auto& reports = decoded.ind_msg_formats.ind_msg_format3().ue_meas_report_list;
  ASSERT_EQ(reports.size(), 3U);
  EXPECT_EQ(reports[0].ue_id.gnb_du_ue_id().gnb_cu_ue_f1ap_id, 1007U);
  EXPECT_EQ(reports[1].ue_id.gnb_du_ue_id().gnb_cu_ue_f1ap_id, 2091U);
  EXPECT_EQ(reports[2].ue_id.gnb_du_ue_id().gnb_cu_ue_f1ap_id, 3199U);
  for (const auto& item : reports) {
    ASSERT_EQ(item.meas_report.meas_info_list.size(), 2U);
    EXPECT_EQ(item.meas_report.meas_info_list[0].meas_type.meas_name().to_string(), metric_name);
    EXPECT_EQ(item.meas_report.meas_info_list[1].meas_type.meas_name().to_string(), snr_metric_name);
    ASSERT_EQ(item.meas_report.meas_data.size(), 1U);
    ASSERT_EQ(item.meas_report.meas_data[0].meas_record.size(), 2U);
  }
  const auto& power = reports[0].meas_report.meas_data[0].meas_record[0];
  ASSERT_EQ(power.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(power.real().value, -13.125);
  const auto& snr = reports[0].meas_report.meas_data[0].meas_record[1];
  ASSERT_EQ(snr.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(snr.real().value, 21.75);
  const auto& zero = reports[1].meas_report.meas_data[0].meas_record[0];
  ASSERT_EQ(zero.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(zero.real().value, 0.0);
  const auto& zero_snr = reports[1].meas_report.meas_data[0].meas_record[1];
  ASSERT_EQ(zero_snr.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(zero_snr.real().value, 0.0);
  EXPECT_EQ(reports[2].meas_report.meas_data[0].meas_record[0].type(), meas_record_item_c::types::no_value);
  EXPECT_EQ(reports[2].meas_report.meas_data[0].meas_record[1].type(), meas_record_item_c::types::no_value);

  // An optional output path lets the separate FlexRIC decoder verify this exact
  // provider-derived APER fixture without introducing any RF dependency.
  if (const char* output_path = std::getenv("FALCON_KPM_WIRE_OUTPUT")) {
    std::ofstream output(output_path, std::ios::binary);
    ASSERT_TRUE(output.good());
    for (uint8_t octet : wire) {
      output.put(static_cast<char>(octet));
    }
    output.close();
    ASSERT_TRUE(output.good());
  }
}

TEST_F(du_rf_metrics_kpm_test, flexric_seven_metric_subscription_is_accepted)
{
  const char* input_path = std::getenv("FALCON_KPM_ACTION_INPUT");
  if (input_path == nullptr) {
    GTEST_SKIP() << "Set FALCON_KPM_ACTION_INPUT to a subscription encoded by the actual FlexRIC xApp builder";
  }
  std::ifstream input(input_path, std::ios::binary);
  ASSERT_TRUE(input.good());
  const std::vector<uint8_t> octets{std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
  ASSERT_FALSE(octets.empty());
  auto wire = byte_buffer::create(octets.begin(), octets.end());
  ASSERT_TRUE(wire.has_value());
  e2sm_kpm_action_definition_s decoded;
  asn1::cbit_ref reader(wire.value());
  ASSERT_EQ(decoded.unpack(reader), asn1::OCUDUASN_SUCCESS);
  ASSERT_EQ(decoded.ric_style_type, 4);
  ASSERT_EQ(decoded.action_definition_formats.type(),
            e2sm_kpm_action_definition_s::action_definition_formats_c_::types::action_definition_format4);
  const auto& subscription = decoded.action_definition_formats.action_definition_format4().sub_info;
  EXPECT_EQ(subscription.granul_period, 1000U);
  ASSERT_EQ(subscription.meas_info_list.size(), 7U);
  const std::vector<std::string> expected{
      "DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl", "RRU.PrbTotDl", "RRU.PrbTotUl", metric_name, snr_metric_name};
  for (size_t index = 0; index < expected.size(); ++index) {
    EXPECT_EQ(subscription.meas_info_list[index].meas_type.meas_name().to_string(), expected[index]);
  }
  asn1::e2ap::ric_action_to_be_setup_item_s ric_action;
  ric_action.ric_action_type = asn1::e2ap::ric_action_type_opts::report;
  (void)ric_action.ric_action_definition.resize(octets.size());
  std::copy(octets.begin(), octets.end(), ric_action.ric_action_definition.begin());
  e2sm_kpm_asn1_packer packer(provider);
  e2sm_kpm_impl iface(ocudulog::fetch_basic_logger("TEST"), packer, provider);
  EXPECT_TRUE(iface.action_supported(ric_action));
}

TEST_F(du_rf_metrics_kpm_test, production_ran_function_description_advertises_rf_only_at_ue_scope)
{
  e2sm_kpm_asn1_packer packer(provider);
  const auto wire = packer.pack_ran_function_description();
  ASSERT_FALSE(wire.empty());
  e2sm_kpm_ran_function_description_s decoded;
  asn1::cbit_ref reader(wire);
  ASSERT_EQ(decoded.unpack(reader), asn1::OCUDUASN_SUCCESS);
  ASSERT_EQ(decoded.ric_report_style_list.size(), 5U);

  std::map<int64_t, unsigned> style_counts;
  for (const auto& style : decoded.ric_report_style_list) {
    ASSERT_GE(style.ric_report_style_type, 1);
    ASSERT_LE(style.ric_report_style_type, 5);
    ++style_counts[style.ric_report_style_type];
    std::vector<std::string> names;
    for (const auto& measurement : style.meas_info_action_list) {
      names.push_back(measurement.meas_name.to_string());
    }
    for (const char* name : {metric_name, snr_metric_name}) {
      EXPECT_EQ(std::count(names.begin(), names.end(), name), style.ric_report_style_type == 1 ? 0 : 1);
    }
    for (const char* name : {"RSRP", "RSRQ", "SNR", "SINR", "FALCON.PUSCH.SINR.dB"}) {
      EXPECT_EQ(std::count(names.begin(), names.end(), name), 0);
    }
    for (const char* name : {"DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl", "RRU.PrbTotDl", "RRU.PrbTotUl"}) {
      EXPECT_EQ(std::count(names.begin(), names.end(), name), 1);
    }
  }
  for (int64_t style = 1; style <= 5; ++style) {
    EXPECT_EQ(style_counts[style], 1U);
  }
}

e2sm_kpm_action_definition_s make_style3_rf_action(const label_info_list_l& labels,
                                                 const char*              name,
                                                 bool                     include_ue_test = true,
                                                 bool                     cell_scope = false)
{
  e2sm_kpm_action_definition_s action;
  action.ric_style_type = 3;
  auto& format3 = action.action_definition_formats.set_action_definition_format3();
  format3.granul_period = 1000;
  format3.cell_global_id_present = cell_scope;
  if (cell_scope) {
    auto& cell = format3.cell_global_id.set_nr_cgi();
    cell.plmn_id.from_string("001001");
    cell.nr_cell_id.from_number(1);
  }
  meas_cond_item_s measurement;
  measurement.meas_type.set_meas_name().from_string(name);
  for (const auto& label : labels) {
    matching_cond_item_s condition;
    condition.matching_cond_choice.set_meas_label() = label.meas_label;
    measurement.matching_cond.push_back(condition);
  }
  if (include_ue_test) {
    matching_cond_item_s condition;
    auto& test = condition.matching_cond_choice.set_test_cond_info();
    test.test_type.set_ul_r_srp().value = test_cond_type_c::ul_r_srp_opts::true_value;
    test.test_expr_present = true;
    test.test_expr = test_cond_expression_opts::greaterthan;
    test.test_value_present = true;
    test.test_value.set_value_int() = 1;
    measurement.matching_cond.push_back(condition);
  }
  format3.meas_cond_list.push_back(measurement);
  return action;
}

TEST_F(du_rf_metrics_kpm_test, actual_style3_admission_enforces_complete_rf_label_and_scope_contract)
{
  e2sm_kpm_asn1_packer packer(provider);
  e2sm_kpm_impl iface(ocudulog::fetch_basic_logger("TEST"), packer, provider);
  auto duplicate = make_no_label();
  duplicate.push_back(duplicate[0]);
  auto mixed = make_no_label();
  mixed[0].meas_label.five_qi_present = true;
  mixed[0].meas_label.five_qi = 9;
  auto expanded = mixed;
  expanded[0].meas_label.no_label_present = false;
  auto missing_no_label = make_no_label();
  missing_no_label[0].meas_label.no_label_present = false;
  auto extension = make_no_label();
  extension[0].meas_label.ext = true;

  // Empty matching lists and a present-but-unset noLabel enum cannot be encoded.
  // Inject only those malformed decoded states through the public admission entry.
  class decoded_style3_action_handler : public e2sm_kpm_asn1_packer {
  public:
    decoded_style3_action_handler(e2sm_kpm_meas_provider& source, const e2sm_kpm_action_definition_s& action_) :
      e2sm_kpm_asn1_packer(source), action(action_) {}
    e2sm_action_definition handle_packed_e2sm_action_definition(const byte_buffer&) override
    {
      e2sm_action_definition decoded;
      decoded.service_model = e2sm_service_model_t::KPM;
      decoded.action_definition = action;
      return decoded;
    }
  private:
    e2sm_kpm_action_definition_s action;
  };

  for (const char* name : {metric_name, snr_metric_name}) {
    SCOPED_TRACE(name);
    EXPECT_TRUE(iface.action_supported(make_ric_action(make_style3_rf_action(make_no_label(), name))));
    EXPECT_TRUE(iface.action_supported(make_ric_action(make_style3_rf_action(make_no_label(), name, false))));
    // A UE-selection test condition does not substitute for the measurement's NO_LABEL.
    EXPECT_FALSE(iface.action_supported(make_ric_action(make_style3_rf_action({}, name))));
    for (const auto& labels : {duplicate, mixed, expanded, missing_no_label, extension}) {
      EXPECT_FALSE(iface.action_supported(make_ric_action(make_style3_rf_action(labels, name))));
    }
    EXPECT_FALSE(iface.action_supported(make_ric_action(make_style3_rf_action(make_no_label(), name, true, true))));

    auto unset_no_label = make_no_label();
    // The ASN.1 enum defines only true_value; nulltype is an invalid decoded state, not a wire FALSE.
    unset_no_label[0].meas_label.no_label = meas_label_s::no_label_opts::nulltype;
    for (const auto& malformed : {make_style3_rf_action({}, name, false),
                                  make_style3_rf_action(unset_no_label, name)}) {
      decoded_style3_action_handler handler(provider, malformed);
      e2sm_kpm_impl decoded_iface(ocudulog::fetch_basic_logger("TEST"), handler, provider);
      asn1::e2ap::ric_action_to_be_setup_item_s action;
      action.ric_action_type = asn1::e2ap::ric_action_type_opts::report;
      EXPECT_FALSE(decoded_iface.action_supported(action));
    }
  }
}

TEST_F(du_rf_metrics_kpm_test, removed_f1ap_mapping_does_not_reuse_retained_rf_snapshot)
{
  report({make_measurement(7, -13.125F, 21.75F), make_measurement(91, -3.5F, -2.875F),
          make_measurement(199, -20.0F, 0.0F)});
  const std::vector<ue_id_c> requested{make_ue(2091), make_ue(1007), make_ue(3199), make_ue(2091)};
  for (const char* name : {metric_name, snr_metric_name}) {
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, requested, output));
    ASSERT_EQ(output.size(), requested.size());
    for (const auto& item : output) {
      ASSERT_EQ(item.type(), meas_record_item_c::types::real);
    }
  }

  // Disconnect the F1AP identity without publishing another scheduler snapshot.
  translator.remove_ue(to_du_ue_index(91));
  for (const char* name : {metric_name, snr_metric_name}) {
    SCOPED_TRACE(name);
    const bool is_snr = std::string(name) == snr_metric_name;
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, requested, output));
    ASSERT_EQ(output.size(), requested.size());
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
    EXPECT_EQ(output[3].type(), meas_record_item_c::types::no_value);
    ASSERT_EQ(output[1].type(), meas_record_item_c::types::real);
    ASSERT_EQ(output[2].type(), meas_record_item_c::types::real);
    EXPECT_DOUBLE_EQ(output[1].real().value, is_snr ? 21.75 : -13.125);
    EXPECT_DOUBLE_EQ(output[2].real().value, is_snr ? 0.0 : -20.0);
  }
}

TEST_F(du_rf_metrics_kpm_test, failed_crc_rf_samples_export_count_mean_and_reset_each_window)
{
  class capturing_notifier : public scheduler_cell_metrics_notifier {
  public:
    scheduler_cell_metrics current;
    scheduler_cell_metrics last_report;
    unsigned commits = 0;
    scheduler_cell_metrics& get_next() override
    {
      current = {};
      return current;
    }
    void commit(scheduler_cell_metrics& value) override
    {
      last_report = value;
      ++commits;
    }
    bool is_sched_report_required(slot_point_extended) const override { return true; }
  } notifier;
  const auto expert = config_helpers::make_default_scheduler_expert_config();
  sched_cell_configuration_request_message cell_request{};
  cell_request.cell_index = to_du_cell_index(0);
  cell_request.ran = config_helpers::make_default_ran_cell_config();
  cell_request.si_scheduling.sib1_payload_size = units::bytes{101};
  cell_configuration cell(expert, cell_request);
  cell_metrics_handler scheduler(cell, sched_cell_configuration_request_message::metrics_config{&notifier});
  scheduler.handle_ue_creation(to_du_ue_index(7), to_rnti(0x4607), pci_t{1});
  slot_point_extended slot{subcarrier_spacing::kHz15, 2000};
  sched_result result{};
  result.dl.nof_dl_symbols = 14;
  result.ul.nof_ul_symbols = 14;
  const auto next_report = [&] {
    scheduler.push_result(slot++, result, std::chrono::microseconds{0});
    provider.report_metrics(notifier.last_report);
  };
  next_report();
  ASSERT_EQ(notifier.commits, 1U);
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);

  ul_crc_pdu_indication crc{};
  crc.ue_index = to_du_ue_index(7);
  crc.rnti = to_rnti(0x4607);
  crc.tb_crc_success = false;
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  next_report();
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].ul_nof_nok, 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 0U);
  for (const char* name : {metric_name, snr_metric_name}) {
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, {make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 1U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  }

  crc.ul_sinr_dB = 21.75F;
  crc.ul_rsrp_dBFS = -13.125F;
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  crc.tb_crc_success = true;
  crc.ul_sinr_dB = -1.25F;
  crc.ul_rsrp_dBFS = -3.5F;
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  next_report();
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);
  const auto& average = notifier.last_report.ue_metrics[0];
  EXPECT_EQ(average.ul_nof_ok, 1U);
  EXPECT_EQ(average.ul_nof_nok, 1U);
  EXPECT_EQ(average.nof_pusch_snr_reports, 2U);
  EXPECT_FLOAT_EQ(average.pusch_snr_db, 10.25F);
  EXPECT_FLOAT_EQ(average.pusch_rsrp_db, -8.3125F);
  for (const char* name : {metric_name, snr_metric_name}) {
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, {make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 1U);
    ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
    EXPECT_DOUBLE_EQ(output[0].real().value, std::string(name) == snr_metric_name ? 10.25 : -8.3125);
  }

  next_report();
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 0U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].ul_nof_ok, 0U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].ul_nof_nok, 0U);
  EXPECT_FLOAT_EQ(notifier.last_report.ue_metrics[0].pusch_snr_db, 0.0F);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].pusch_rsrp_db, -std::numeric_limits<float>::infinity());
  for (const char* name : {metric_name, snr_metric_name}) {
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, {make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 1U);
    EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  }

  crc.tb_crc_success = false;
  crc.ul_sinr_dB = 0.0F;
  crc.ul_rsrp_dBFS = 0.0F;
  scheduler.handle_crc_indication(slot.without_hyper_sfn() - 1, crc, units::bytes{1});
  next_report();
  ASSERT_EQ(notifier.last_report.ue_metrics.size(), 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].nof_pusch_snr_reports, 1U);
  EXPECT_EQ(notifier.last_report.ue_metrics[0].ul_nof_nok, 1U);
  for (const char* name : {metric_name, snr_metric_name}) {
    std::vector<meas_record_item_c> output;
    ASSERT_TRUE(collect_named(name, {make_ue(1007)}, output));
    ASSERT_EQ(output.size(), 1U);
    ASSERT_EQ(output[0].type(), meas_record_item_c::types::real);
    EXPECT_DOUBLE_EQ(output[0].real().value, 0.0);
  }
}

} // namespace
