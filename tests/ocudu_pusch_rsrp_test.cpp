// Offline regression checks for OCUDU 050a2bb's PUSCH RSRP KPM extension.
// This test calls the real provider and ASN.1 codec; it starts no network or RF service.

#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_asn1_packer.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_impl.h"
#include "lib/e2/e2sm/e2sm_kpm/e2sm_kpm_report_service_impl.h"
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

// F1AP identifiers deliberately differ from sparse DU indices. An identity mapper
// would hide a regression that indexes the metrics vector with the requested ID.
class sparse_ue_id_translator : public odu::f1ap_ue_id_translator
{
public:
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
  const std::map<du_ue_index_t, uint32_t> ids{
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

scheduler_ue_metrics make_measurement(unsigned index, float power)
{
  scheduler_ue_metrics result{};
  result.ue_index      = to_du_ue_index(index);
  result.pci           = 1;
  result.rnti          = static_cast<rnti_t>(0x4600 + index);
  result.pusch_rsrp_db = power;
  result.pusch_snr_db  = 23.75F; // A wrong SNR source must be distinguishable.
  return result;
}

class pusch_rsrp_kpm_test : public ::testing::Test
{
protected:
  pusch_rsrp_kpm_test() : provider(translator)
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

  sparse_ue_id_translator              translator;
  e2sm_kpm_du_meas_provider_impl       provider;
  meas_type_c                         metric;
};

TEST_F(pusch_rsrp_kpm_test, advertises_only_the_custom_ue_metric_and_rejects_other_scopes)
{
  const auto ue_names   = provider.get_supported_metric_names(UE_LEVEL);
  const auto node_names = provider.get_supported_metric_names(E2_NODE_LEVEL);
  EXPECT_NE(std::find(ue_names.begin(), ue_names.end(), metric_name), ue_names.end());
  EXPECT_EQ(std::find(node_names.begin(), node_names.end(), metric_name), node_names.end());
  const auto label = make_no_label()[0].meas_label;
  EXPECT_TRUE(provider.is_metric_supported(metric, label, UE_LEVEL, false));
  EXPECT_FALSE(provider.is_metric_supported(metric, label, E2_NODE_LEVEL, false));
  EXPECT_FALSE(provider.is_metric_supported(metric, label, UE_LEVEL, true));

  report({make_measurement(7, -12.875F)});
  std::vector<meas_record_item_c> output;
  EXPECT_FALSE(collect({}, output));
  EXPECT_TRUE(output.empty());
  EXPECT_FALSE(provider.get_meas_data(metric, make_no_label(), {make_ue(1007)}, cgi_c{}, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
}

TEST_F(pusch_rsrp_kpm_test, preserves_negative_fractional_power_and_zero_in_request_order)
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

TEST_F(pusch_rsrp_kpm_test, missing_ue_nan_and_infinity_produce_no_value_without_shifting_records)
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

TEST_F(pusch_rsrp_kpm_test, empty_or_replaced_snapshot_does_not_reuse_a_previous_power)
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

TEST_F(pusch_rsrp_kpm_test, incompatible_ue_type_returns_no_value_in_place)
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

TEST_F(pusch_rsrp_kpm_test, unsupported_labels_are_rejected_by_admission_and_collection)
{
  report({make_measurement(7, -12.875F)});
  auto labels = make_no_label();
  labels[0].meas_label.five_qi_present = true;
  labels[0].meas_label.five_qi         = 9;
  EXPECT_FALSE(provider.is_metric_supported(metric, labels[0].meas_label, UE_LEVEL, false));
  std::vector<meas_record_item_c> output;
  EXPECT_FALSE(provider.get_meas_data(metric, labels, {make_ue(1007)}, std::nullopt, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
  output.clear();
  EXPECT_FALSE(provider.get_meas_data(metric, {}, {make_ue(1007)}, std::nullopt, output));
  ASSERT_EQ(output.size(), 1U);
  EXPECT_EQ(output[0].type(), meas_record_item_c::types::no_value);
}

e2sm_kpm_action_definition_s make_style4_action(label_info_list_l labels)
{
  e2sm_kpm_action_definition_s action;
  action.ric_style_type = 4;
  auto& format4 = action.action_definition_formats.set_action_definition_format4();
  matching_ue_cond_per_sub_item_s condition;
  condition.test_cond_info.test_type.set_ul_r_srp().value = test_cond_type_c::ul_r_srp_opts::true_value;
  format4.matching_ue_cond_list.push_back(condition);
  format4.sub_info.granul_period = 1000;
  meas_info_item_s info;
  info.meas_type.set_meas_name().from_string(metric_name);
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

TEST_F(pusch_rsrp_kpm_test, actual_style4_admission_rejects_missing_duplicate_and_mixed_labels)
{
  e2sm_kpm_asn1_packer packer(provider);
  e2sm_kpm_impl iface(ocudulog::fetch_basic_logger("TEST"), packer, provider);
  EXPECT_TRUE(iface.action_supported(make_ric_action(make_style4_action(make_no_label()))));

  auto duplicate = make_no_label();
  duplicate.push_back(duplicate[0]);
  EXPECT_FALSE(iface.action_supported(make_ric_action(make_style4_action(duplicate))));
  auto mixed = make_no_label();
  mixed[0].meas_label.five_qi_present = true;
  mixed[0].meas_label.five_qi = 9;
  EXPECT_FALSE(iface.action_supported(make_ric_action(make_style4_action(mixed))));

  // An empty label list violates the ASN.1 minimum length, so test the public
  // admission entry with a handler returning an already decoded definition.
  class decoded_action_handler : public e2sm_kpm_asn1_packer {
  public:
    explicit decoded_action_handler(e2sm_kpm_meas_provider& source) : e2sm_kpm_asn1_packer(source) {}
    e2sm_action_definition handle_packed_e2sm_action_definition(const byte_buffer&) override
    {
      e2sm_action_definition decoded;
      decoded.service_model = e2sm_service_model_t::KPM;
      decoded.action_definition = make_style4_action({});
      return decoded;
    }
  } empty_label_handler(provider);
  e2sm_kpm_impl empty_label_iface(ocudulog::fetch_basic_logger("TEST"), empty_label_handler, provider);
  EXPECT_FALSE(empty_label_iface.action_supported(make_ric_action(make_style4_action(make_no_label()))));
}

TEST_F(pusch_rsrp_kpm_test, real_and_no_value_survive_actual_style4_collection_and_kpm_format3_aper_codec)
{
  report({make_measurement(7, -13.125F), make_measurement(91, 0.0F),
          make_measurement(199, std::numeric_limits<float>::quiet_NaN())});
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
  const auto ric_action = make_ric_action(make_style4_action(make_no_label()));
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
    ASSERT_EQ(item.meas_report.meas_info_list.size(), 1U);
    EXPECT_EQ(item.meas_report.meas_info_list[0].meas_type.meas_name().to_string(), metric_name);
    ASSERT_EQ(item.meas_report.meas_data.size(), 1U);
    ASSERT_EQ(item.meas_report.meas_data[0].meas_record.size(), 1U);
  }
  const auto& power = reports[0].meas_report.meas_data[0].meas_record[0];
  ASSERT_EQ(power.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(power.real().value, -13.125);
  const auto& zero = reports[1].meas_report.meas_data[0].meas_record[0];
  ASSERT_EQ(zero.type(), meas_record_item_c::types::real);
  EXPECT_DOUBLE_EQ(zero.real().value, 0.0);
  EXPECT_EQ(reports[2].meas_report.meas_data[0].meas_record[0].type(), meas_record_item_c::types::no_value);

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

TEST_F(pusch_rsrp_kpm_test, flexric_six_metric_subscription_is_accepted)
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
  ASSERT_EQ(subscription.meas_info_list.size(), 6U);
  const std::vector<std::string> expected{
      "DRB.RlcSduDelayDl", "DRB.UEThpDl", "DRB.UEThpUl", "RRU.PrbTotDl", "RRU.PrbTotUl", metric_name};
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

} // namespace
