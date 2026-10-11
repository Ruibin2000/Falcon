/* Decode a real OCUDU-generated KPM fixture and exercise the patched monitor.
 * FALCON_XAPP_SOURCE names the staged xapp_oran_moni.c. No RIC or RF is started.
 */
#ifndef FALCON_XAPP_SOURCE
#error "Define FALCON_XAPP_SOURCE as the staged xapp_oran_moni.c path"
#endif

#define main falcon_original_xapp_main
#include FALCON_XAPP_SOURCE
#undef main

#include "sm/kpm_sm/kpm_sm_v03.00/dec/kpm_dec_asn.h"
#include "sm/kpm_sm/kpm_sm_v03.00/enc/kpm_enc_asn.h"

static void require(bool condition, const char* description)
{
  if (!condition) {
    fprintf(stderr, "FAIL: %s\n", description);
    exit(EXIT_FAILURE);
  }
}

int main(int argc, char** argv)
{
  require(argc == 4, "provide indication fixture, monitor config, and output action paths");
  char* config_argv[] = {argv[0], "-c", argv[2]};
  fr_args_t config = init_fr_args(3, config_argv);
  require(config.sub_oran_sm_len == 1, "one DU-only subscription");
  sub_oran_sm_t subscription = config.sub_oran_sm[0];
  require(strcmp(subscription.ran_type, "ngran_gNB_DU") == 0, "DU subscription type");
  require(subscription.time == 1000 && subscription.format == 4, "1000 ms Format 4");
  require(subscription.act_len == 6, "existing five metrics plus RSRP");
  require(strcmp(subscription.actions[5].name, "FALCON.PUSCH.RSRP.dBFS") == 0, "new metric is subscribed");
  require(!config.db_params.enable, "database disabled for NONE_XAPP build");
  kpm_act_def_t action = gen_kpm_act_def(subscription, FORMAT_4_ACTION_DEFINITION, (uint32_t)subscription.time);
  byte_array_t encoded_action = kpm_enc_action_def_asn(&action);
  FILE* action_file = fopen(argv[3], "wb");
  require(action_file != NULL, "open encoded subscription output");
  require(fwrite(encoded_action.buf, 1, encoded_action.len, action_file) == encoded_action.len,
          "write actual FlexRIC six-metric subscription");
  require(fclose(action_file) == 0, "close subscription output");
  free_byte_array(encoded_action);
  free_kpm_action_def(&action);
  free_fr_args(&config);
  puts("PASS: real config parser and xApp builder encode six-metric Format 4 subscription");

  FILE* fixture = fopen(argv[1], "rb");
  require(fixture != NULL, "open the fixture");
  require(fseek(fixture, 0, SEEK_END) == 0, "seek fixture");
  long size = ftell(fixture);
  require(size > 0 && size <= 65536, "bounded fixture size");
  rewind(fixture);
  uint8_t* bytes = malloc((size_t)size);
  require(bytes != NULL, "allocate fixture bytes");
  require(fread(bytes, 1, (size_t)size, fixture) == (size_t)size, "read fixture");
  fclose(fixture);

  sm_ag_if_rd_t rd = {0};
  rd.type = INDICATION_MSG_AGENT_IF_ANS_V0;
  rd.ind.type = KPM_STATS_V3_0;
  rd.ind.kpm.ind.msg = kpm_dec_ind_msg_asn((size_t)size, bytes);
  free(bytes);
  require(rd.ind.kpm.ind.msg.type == FORMAT_3_INDICATION_MESSAGE, "Format 3 decoding");
  kpm_ind_msg_format_3_t* msg = &rd.ind.kpm.ind.msg.frm_3;
  require(msg->ue_meas_report_lst_len == 3, "three distinct UE reports");

  static const uint32_t expected_ids[] = {1007, 2091, 3199};
  static const double expected_power[] = {-13.125, 0.0};
  static const char expected_name[] = "FALCON.PUSCH.RSRP.dBFS";
  for (size_t i = 0; i < 3; ++i) {
    meas_report_per_ue_t* ue = &msg->meas_report_per_ue[i];
    require(ue->ue_meas_report_lst.type == GNB_DU_UE_ID_E2SM, "gNB-DU UE ID");
    require(ue->ue_meas_report_lst.gnb_du.gnb_cu_ue_f1ap == expected_ids[i], "F1AP UE identity");
    kpm_ind_msg_format_1_t* row = &ue->ind_msg_format_1;
    require(row->meas_info_lst_len == 1 && row->meas_data_lst_len == 1, "one metric and window per UE");
    require(row->meas_info_lst[0].meas_type.type == NAME_MEAS_TYPE, "named measurement");
    require(row->meas_info_lst[0].meas_type.name.len == sizeof(expected_name) - 1 &&
            memcmp(row->meas_info_lst[0].meas_type.name.buf, expected_name, sizeof(expected_name) - 1) == 0,
            "custom metric name survives the wire");
    require(row->meas_data_lst[0].meas_record_len == 1, "one record per UE");
    meas_record_lst_t* value = &row->meas_data_lst[0].meas_record_lst[0];
    if (i < 2) {
      require(value->value == REAL_MEAS_VALUE, "REAL preserves negative and zero power");
      require(value->real_val == expected_power[i], "fractional power survives cross-codec decoding");
    } else {
      require(value->value == NO_VALUE_MEAS_VALUE, "absent measurement remains noValue");
    }
  }

  /* The header is synthetic. This check concerns measurement payloads only. */
  rd.ind.kpm.ind.hdr.type = FORMAT_1_INDICATION_HEADER;
  rd.ind.kpm.ind.hdr.kpm_ric_ind_hdr_format_1.collectStartTime = (uint64_t)time_now_us();
  uint64_t du_id = 1;
  global_e2_node_id_t node = {0};
  node.type = e2ap_ngran_gNB_DU;
  node.plmn.mcc = 1;
  node.plmn.mnc = 1;
  node.plmn.mnc_digit_len = 2;
  node.nb_id.nb_id = 411;
  node.cu_du_id = &du_id;
  puts("CASE: valid cross-codec payload");
  sm_cb_kpm(&rd, &node);

  kpm_ind_msg_format_1_t* first = &msg->meas_report_per_ue[0].ind_msg_format_1;
  meas_record_lst_t* first_value = &first->meas_data_lst[0].meas_record_lst[0];
  meas_record_lst_t saved_value = *first_value;
  puts("CASE: reject RSRP encoded as INTEGER");
  first_value->value = INTEGER_MEAS_VALUE;
  first_value->int_val = 23;
  sm_cb_kpm(&rd, &node);
  *first_value = saved_value;

  puts("CASE: reject non-finite REAL");
  first_value->real_val = NAN;
  sm_cb_kpm(&rd, &node);
  *first_value = saved_value;

  puts("CASE: missing measurement-name mapping");
  size_t saved_names = first->meas_info_lst_len;
  first->meas_info_lst_len = 0;
  sm_cb_kpm(&rd, &node);
  first->meas_info_lst_len = saved_names;

  puts("CASE: incomplete report and second DU context");
  enum_value_e incomplete = TRUE_ENUM_VALUE;
  enum_value_e* saved_flag = first->meas_data_lst[0].incomplete_flag;
  first->meas_data_lst[0].incomplete_flag = &incomplete;
  du_id = 2;
  sm_cb_kpm(&rd, &node);
  first->meas_data_lst[0].incomplete_flag = saved_flag;

  sm_cb_kpm(NULL, &node);
  request_stop(SIGTERM);
  require(stop_requested == 1, "stop handler sets a flag for main-thread cleanup");
  free_kpm_ind_msg(&rd.ind.kpm.ind.msg);
  pthread_mutex_destroy(&mtx);
  puts("PASS: OCUDU to FlexRIC REAL/noValue payload and patched xApp callback");
  return EXIT_SUCCESS;
}
