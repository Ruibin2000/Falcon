/* Decode an OCUDU-generated two-metric fixture and exercise the real monitor.
 * This harness remains offline: no RIC, radio, or SDK subscription is started.
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

typedef struct {
  char* output;
  char* errors;
} callback_output_t;

static char* read_capture(FILE* stream)
{
  require(fseek(stream, 0, SEEK_END) == 0, "seek captured callback output");
  long length = ftell(stream);
  require(length >= 0 && length < 1024 * 1024, "bounded callback output");
  rewind(stream);
  char* text = calloc((size_t)length + 1, 1);
  require(text != NULL, "allocate captured callback output");
  require(fread(text, 1, (size_t)length, stream) == (size_t)length, "read callback output");
  return text;
}

static callback_output_t capture_callback(sm_ag_if_rd_t const* rd, global_e2_node_id_t const* node)
{
  require(fflush(stdout) == 0 && fflush(stderr) == 0, "flush before callback capture");
  FILE* output = tmpfile();
  FILE* errors = tmpfile();
  require(output != NULL && errors != NULL, "open callback capture files");
  int saved_stdout = dup(STDOUT_FILENO);
  int saved_stderr = dup(STDERR_FILENO);
  require(saved_stdout >= 0 && saved_stderr >= 0, "save callback output descriptors");
  int redirect_output = dup2(fileno(output), STDOUT_FILENO);
  int redirect_errors = dup2(fileno(errors), STDERR_FILENO);
  if (redirect_output < 0 || redirect_errors < 0) {
    (void)dup2(saved_stdout, STDOUT_FILENO);
    (void)dup2(saved_stderr, STDERR_FILENO);
    require(false, "redirect callback output descriptors");
  }
  sm_cb_kpm(rd, node);
  int flush_output = fflush(stdout);
  int flush_errors = fflush(stderr);
  int restore_output = dup2(saved_stdout, STDOUT_FILENO);
  int restore_errors = dup2(saved_stderr, STDERR_FILENO);
  int close_output = close(saved_stdout);
  int close_errors = close(saved_stderr);
  require(flush_output == 0 && flush_errors == 0 && restore_output >= 0 && restore_errors >= 0 &&
            close_output == 0 && close_errors == 0,
          "restore and close callback output descriptors");
  callback_output_t captured = {.output = read_capture(output), .errors = read_capture(errors)};
  require(fclose(output) == 0 && fclose(errors) == 0, "close callback capture files");
  return captured;
}

static void free_callback_output(callback_output_t* captured)
{
  free(captured->output);
  free(captured->errors);
}

/* Match complete space-delimited fields so identity and metric checks cannot
 * accidentally accept a prefix, another UE, or a neighboring trace line. */
static bool has_field(const char* line, const char* field)
{
  size_t length = strlen(field);
  for (const char* match = strstr(line, field); match != NULL; match = strstr(match + 1, field)) {
    if ((match == line || match[-1] == ' ') &&
        (match[length] == ' ' || match[length] == '\0'))
      return true;
  }
  return false;
}

static char* find_rf_trace(const char* output, const char* metric, uint32_t ue_id)
{
  char metric_field[80];
  char ue_field[64];
  require(snprintf(metric_field, sizeof(metric_field), "metric=%s", metric) > 0, "format metric field");
  require(snprintf(ue_field, sizeof(ue_field), "ue_f1ap_id=%" PRIu32, ue_id) > 0, "format UE field");
  const char* cursor = output;
  while (*cursor != '\0') {
    const char* end = strchr(cursor, '\n');
    size_t length = end != NULL ? (size_t)(end - cursor) : strlen(cursor);
    char* line = calloc(length + 1, 1);
    require(line != NULL, "allocate trace line");
    memcpy(line, cursor, length);
    if (strncmp(line, "RF_TRACE ", strlen("RF_TRACE ")) == 0 &&
        has_field(line, metric_field) && has_field(line, ue_field))
      return line;
    free(line);
    if (end == NULL)
      break;
    cursor = end + 1;
  }
  require(false, "find RF trace for the requested metric and UE");
  return NULL;
}

static void require_trace_fields(const char* line, const char* record_type, const char* value,
                                 const char* unit, const char* reason)
{
  char field[96];
  snprintf(field, sizeof(field), "record_type=%s", record_type);
  require(has_field(line, field), "trace preserves the measurement record type");
  snprintf(field, sizeof(field), "value=%s", value);
  require(has_field(line, field), "trace preserves the measurement value or n/a");
  snprintf(field, sizeof(field), "unit=%s", unit);
  require(has_field(line, field), "trace includes the correct RF unit");
  if (reason != NULL) {
    snprintf(field, sizeof(field), "reason=%s", reason);
    require(has_field(line, field), "trace explains an invalid RF value");
  } else {
    require(strstr(line, "reason=") == NULL, "valid/noValue trace has no error reason");
  }
}

static void require_diagnostic(sm_ag_if_rd_t const* rd, global_e2_node_id_t const* node,
                               const char* diagnostic)
{
  callback_output_t captured = capture_callback(rd, node);
  require(strstr(captured.errors, diagnostic) != NULL, "malformed callback has an explicit diagnostic");
  free_callback_output(&captured);
}

static void check_subscription_capacity(void)
{
  size_t capacity = 99;
  require(get_subscription_capacity(2, 3, &capacity) && capacity == 6,
          "multiple matching configurations have one handle per node/configuration pair");
  require(get_subscription_capacity(0, SIZE_MAX, &capacity) && capacity == 0,
          "zero nodes need no handles");
  require(get_subscription_capacity(SIZE_MAX, 0, &capacity) && capacity == 0,
          "zero configurations need no handles");
  capacity = 99;
  require(!get_subscription_capacity(SIZE_MAX, 2, &capacity) && capacity == 0,
          "node/configuration multiplication overflow is rejected");
  capacity = 99;
  require(!get_subscription_capacity(SIZE_MAX / sizeof(sm_ans_xapp_t) + 1, 1, &capacity) && capacity == 0,
          "subscription handle allocation-byte overflow is rejected");
  puts("PASS: bounded multi-configuration subscription capacity without SDK calls");
}

static void check_trace_contract(sm_ag_if_rd_t* rd, global_e2_node_id_t* node)
{
  static const char* names[] = {"FALCON.PUSCH.RSRP.dBFS", "FALCON.PUSCH.SNR.dB"};
  static const char* units[] = {"dBFS", "dB"};
  const char* previous = getenv("FALCON_KPM_RF_TRACE");
  char* saved_environment = previous != NULL ? strdup(previous) : NULL;
  require(previous == NULL || saved_environment != NULL, "save trace environment");
  const char* disabled[] = {NULL, "0", "true", "01", "1 "};
  for (size_t i = 0; i < sizeof(disabled) / sizeof(disabled[0]); ++i) {
    require(disabled[i] != NULL ? setenv("FALCON_KPM_RF_TRACE", disabled[i], 1) == 0
                               : unsetenv("FALCON_KPM_RF_TRACE") == 0,
            "set disabled trace mode");
    callback_output_t captured = capture_callback(rd, node);
    require(strstr(captured.output, "RF_TRACE ") == NULL, "trace requires the exact opt-in value 1");
    require(strstr(captured.output, "FALCON.PUSCH.RSRP.dBFS = -13.12 dBFS") != NULL &&
            strstr(captured.output, "FALCON.PUSCH.SNR.dB = 21.75 dB") != NULL,
            "default human-readable RF output retains two-decimal formatting");
    free_callback_output(&captured);
  }
  require(setenv("FALCON_KPM_RF_TRACE", "1", 1) == 0, "enable exact trace opt-in");
  callback_output_t captured = capture_callback(rd, node);
  for (size_t metric = 0; metric < 2; ++metric) {
    char* line = find_rf_trace(captured.output, names[metric], 1007);
    char field[96];
    require(has_field(line, "plmn=001-01") && has_field(line, "mnc_digits=2") &&
              has_field(line, "node_id=411") && has_field(line, "node_id_unused=0") &&
              has_field(line, "cu_du_id=1") && has_field(line, "sample_idx=0") &&
              has_field(line, "incomplete=false"),
            "trace includes complete node/DU/UE/report-row context");
    snprintf(field, sizeof(field), "node_type=%d", node->type);
    require(has_field(line, field), "trace includes actual node type");
    snprintf(field, sizeof(field), "header_time_us=%" PRIu64,
             rd->ind.kpm.ind.hdr.kpm_ric_ind_hdr_format_1.collectStartTime);
    require(has_field(line, field), "trace preserves header time rather than inventing measurement time");
    require_trace_fields(line, "REAL", metric == 0 ? "-13.125" : "21.75", units[metric], NULL);
    free(line);
    line = find_rf_trace(captured.output, names[metric], 2091);
    require_trace_fields(line, "REAL", "0", units[metric], NULL);
    free(line);
    line = find_rf_trace(captured.output, names[metric], 3199);
    require_trace_fields(line, "noValue", "n/a", units[metric], NULL);
    free(line);
  }
  require(strstr(captured.output, "RSRQ = n/a source=xapp-capability-status reason=unavailable_in_du") != NULL,
          "RSRQ remains an explicit local capability notice");
  puts("CASE: exact opt-in full-precision cross-codec fixture traces");
  fputs(captured.output, stdout);
  free_callback_output(&captured);

  kpm_ind_msg_format_1_t* first = &rd->ind.kpm.ind.msg.frm_3.meas_report_per_ue[0].ind_msg_format_1;
  for (size_t metric = 0; metric < 2; ++metric) {
    meas_record_lst_t* record = &first->meas_data_lst[0].meas_record_lst[metric];
    meas_record_lst_t saved_record = *record;
    const double precise[] = {-13.123456789012345, 0.12345678901234566, -0.0};
    for (size_t i = 0; i < sizeof(precise) / sizeof(precise[0]); ++i) {
      record->value = REAL_MEAS_VALUE;
      record->real_val = precise[i];
      captured = capture_callback(rd, node);
      char* line = find_rf_trace(captured.output, names[metric], 1007);
      const char* value = strstr(line, " value=");
      require(value != NULL, "trace has numeric value field");
      char* end = NULL;
      double decoded = strtod(value + strlen(" value="), &end);
      require(end != NULL && (*end == ' ' || *end == '\0') && decoded == precise[i] &&
                (signbit(decoded) != 0) == (signbit(precise[i]) != 0),
              "full-precision RF trace round-trips binary double including negative zero");
      printf("CASE: verified %s precise REAL %zu\n%s\n", names[metric], i, line);
      free(line);
      free_callback_output(&captured);
    }
    const double nonfinite[] = {NAN, INFINITY, -INFINITY};
    for (size_t i = 0; i < sizeof(nonfinite) / sizeof(nonfinite[0]); ++i) {
      record->value = REAL_MEAS_VALUE;
      record->real_val = nonfinite[i];
      captured = capture_callback(rd, node);
      char* line = find_rf_trace(captured.output, names[metric], 1007);
      require_trace_fields(line, "REAL", "n/a", units[metric], "non_finite_REAL");
      printf("CASE: verified %s non-finite REAL %zu\n%s\n", names[metric], i, line);
      free(line);
      free_callback_output(&captured);
    }
    record->value = INTEGER_MEAS_VALUE;
    record->int_val = 23;
    captured = capture_callback(rd, node);
    char* line = find_rf_trace(captured.output, names[metric], 1007);
    require_trace_fields(line, "INTEGER", "n/a", units[metric], "expected_REAL");
    printf("CASE: verified %s rejected INTEGER\n%s\n", names[metric], line);
    free(line);
    free_callback_output(&captured);
    record->value = END_MEAS_VALUE;
    captured = capture_callback(rd, node);
    line = find_rf_trace(captured.output, names[metric], 1007);
    require_trace_fields(line, "unsupported", "n/a", units[metric], "unsupported_value_type");
    printf("CASE: verified %s unsupported value type\n%s\n", names[metric], line);
    free(line);
    free_callback_output(&captured);
    *record = saved_record;
  }

  global_e2_node_id_t saved_node = *node;
  node->plmn.mnc_digit_len = 3;
  node->nb_id.unused = 10;
  node->cu_du_id = NULL;
  enum_value_e incomplete = TRUE_ENUM_VALUE;
  enum_value_e* saved_flag = first->meas_data_lst[0].incomplete_flag;
  first->meas_data_lst[0].incomplete_flag = &incomplete;
  captured = capture_callback(rd, node);
  char* line = find_rf_trace(captured.output, names[0], 1007);
  require(has_field(line, "plmn=001-001") && has_field(line, "mnc_digits=3") &&
            has_field(line, "node_id_unused=10") && has_field(line, "cu_du_id=n/a") &&
            has_field(line, "incomplete=true"),
          "trace distinguishes MNC width, node bit width, absent DU ID, and incomplete reports");
  free(line);
  free_callback_output(&captured);
  first->meas_data_lst[0].incomplete_flag = saved_flag;
  *node = saved_node;
  require(saved_environment != NULL ? setenv("FALCON_KPM_RF_TRACE", saved_environment, 1) == 0
                                   : unsetenv("FALCON_KPM_RF_TRACE") == 0,
          "restore original trace environment");
  free(saved_environment);
  puts("PASS: exact opt-in RF trace, full identity, REAL precision/zero, noValue, and invalid values");
}

static void check_malformed_callbacks(sm_ag_if_rd_t* rd, global_e2_node_id_t* node)
{
  require_diagnostic(NULL, node, "ignoring unexpected KPM callback type");
  require_diagnostic(rd, NULL, "ignoring unexpected KPM callback type");
  sm_ag_if_rd_t saved_rd = *rd;
  rd->type = -1;
  require_diagnostic(rd, node, "ignoring unexpected KPM callback type");
  *rd = saved_rd;
  rd->ind.type = -1;
  require_diagnostic(rd, node, "ignoring unexpected KPM callback type");
  *rd = saved_rd;
  rd->ind.kpm.ind.hdr.type = -1;
  require_diagnostic(rd, node, "ignoring unsupported KPM header format");
  *rd = saved_rd;
  rd->ind.kpm.ind.msg.type = -1;
  require_diagnostic(rd, node, "ignoring unsupported KPM message format");
  *rd = saved_rd;

  global_e2_node_id_t saved_node = *node;
  node->plmn.mcc = 1000;
  require_diagnostic(rd, node, "ignoring invalid KPM node PLMN");
  *node = saved_node;
  node->plmn.mnc_digit_len = 1;
  require_diagnostic(rd, node, "ignoring invalid KPM node PLMN");
  *node = saved_node;
  node->plmn.mnc = 100;
  require_diagnostic(rd, node, "ignoring invalid KPM node PLMN");
  *node = saved_node;

  kpm_ind_msg_format_3_t* message = &rd->ind.kpm.ind.msg.frm_3;
  kpm_ind_msg_format_3_t saved_message = *message;
  const size_t invalid_lengths[] = {0, 65536};
  for (size_t i = 0; i < sizeof(invalid_lengths) / sizeof(invalid_lengths[0]); ++i) {
    message->ue_meas_report_lst_len = invalid_lengths[i];
    require_diagnostic(rd, node, "ignoring invalid KPM UE report list");
    *message = saved_message;
  }
  message->meas_report_per_ue = NULL;
  require_diagnostic(rd, node, "ignoring invalid KPM UE report list");
  *message = saved_message;

  meas_report_per_ue_t* ue = &message->meas_report_per_ue[0];
  ue_id_e2sm_t saved_ue = ue->ue_meas_report_lst;
  ue->ue_meas_report_lst.type = -1;
  require_diagnostic(rd, node, "skipping unsupported KPM UE ID type");
  ue->ue_meas_report_lst = saved_ue;
  ue->ue_meas_report_lst = (ue_id_e2sm_t){0};
  ue->ue_meas_report_lst.type = GNB_UE_ID_E2SM;
  ue->ue_meas_report_lst.gnb.gnb_cu_ue_f1ap_lst_len = 1;
  require_diagnostic(rd, node, "skipping invalid gNB UE F1AP ID list");
  uint32_t f1ap_id = 1007;
  ue->ue_meas_report_lst.gnb.gnb_cu_ue_f1ap_lst = &f1ap_id;
  ue->ue_meas_report_lst.gnb.gnb_cu_ue_f1ap_lst_len = 5;
  require_diagnostic(rd, node, "skipping invalid gNB UE F1AP ID list");
  ue->ue_meas_report_lst = saved_ue;

  kpm_ind_msg_format_1_t* first = &ue->ind_msg_format_1;
  kpm_ind_msg_format_1_t saved_first = *first;
  for (size_t i = 0; i < sizeof(invalid_lengths) / sizeof(invalid_lengths[0]); ++i) {
    first->meas_data_lst_len = invalid_lengths[i];
    require_diagnostic(rd, node, "skipping invalid KPM measurement lists");
    *first = saved_first;
    first->meas_info_lst_len = invalid_lengths[i];
    require_diagnostic(rd, node, invalid_lengths[i] == 0
                                  ? "skipping KPM row with mismatched name/value counts"
                                  : "skipping invalid KPM measurement lists");
    *first = saved_first;
  }
  first->meas_data_lst = NULL;
  require_diagnostic(rd, node, "skipping invalid KPM measurement lists");
  *first = saved_first;
  first->meas_info_lst = NULL;
  require_diagnostic(rd, node, "skipping invalid KPM measurement lists");
  *first = saved_first;
  first->meas_info_lst_len = 1;
  require_diagnostic(rd, node, "skipping KPM row with mismatched name/value counts");
  *first = saved_first;

  meas_data_lst_t* row = &first->meas_data_lst[0];
  meas_data_lst_t saved_row = *row;
  for (size_t i = 0; i < sizeof(invalid_lengths) / sizeof(invalid_lengths[0]); ++i) {
    row->meas_record_len = invalid_lengths[i];
    require_diagnostic(rd, node, "skipping invalid KPM measurement records");
    *row = saved_row;
  }
  row->meas_record_lst = NULL;
  require_diagnostic(rd, node, "skipping invalid KPM measurement records");
  *row = saved_row;

  meas_type_t* name = &first->meas_info_lst[0].meas_type;
  meas_type_t saved_name = *name;
  name->type = END_MEAS_TYPE;
  require_diagnostic(rd, node, "skipping unnamed KPM measurement type");
  *name = saved_name;
  name->name.buf = NULL;
  require_diagnostic(rd, node, "skipping invalid KPM measurement name");
  *name = saved_name;
  name->name.len = 0;
  require_diagnostic(rd, node, "skipping invalid KPM measurement name");
  *name = saved_name;
  name->name.len = 151;
  require_diagnostic(rd, node, "skipping invalid KPM measurement name");
  *name = saved_name;
  uint8_t embedded_nul[] = "FALCON.PUSCH.SNR.dB\0suffix";
  name->name.buf = embedded_nul;
  name->name.len = sizeof(embedded_nul) - 1;
  meas_record_lst_t* record = &row->meas_record_lst[0];
  meas_record_lst_t saved_record = *record;
  record->value = INTEGER_MEAS_VALUE;
  record->int_val = 23;
  callback_output_t captured = capture_callback(rd, node);
  require(strstr(captured.errors, "skipping invalid KPM measurement name") != NULL &&
            strstr(captured.output, "FALCON.PUSCH.SNR.dB = 23") == NULL,
          "embedded NUL cannot disguise a numeric INTEGER as a known RF metric");
  free_callback_output(&captured);
  *name = saved_name;
  *record = saved_record;
  puts("PASS: malformed callback/list/name/type guards preserve decoded ownership");
}

static void check_format1_callbacks(sm_ag_if_rd_t const* rd, global_e2_node_id_t const* node)
{
  /* The local report aliases decoded rows; restore pointed-to fields and never
   * free the shallow copy, whose storage remains owned by the original report. */
  kpm_ind_msg_format_1_t original = rd->ind.kpm.ind.msg.frm_3.meas_report_per_ue[0].ind_msg_format_1;
  sm_ag_if_rd_t report = *rd;
  report.ind.kpm.ind.msg.type = FORMAT_1_INDICATION_MESSAGE;
  report.ind.kpm.ind.msg.frm_1 = original;
  kpm_ind_msg_format_1_t* first = &report.ind.kpm.ind.msg.frm_1;
  callback_output_t captured = capture_callback(&report, node);
  require(captured.errors[0] == '\0' &&
            strstr(captured.output, "meas record REAL_MEAS_VALUE value -13.125000") != NULL &&
            strstr(captured.output, "meas record REAL_MEAS_VALUE value 21.750000") != NULL,
          "valid Format 1 keeps the existing raw REAL output");
  free_callback_output(&captured);

  first->meas_info_lst_len = 0;
  first->meas_info_lst = NULL;
  captured = capture_callback(&report, node);
  require(captured.errors[0] == '\0' &&
            strstr(captured.output, "meas record REAL_MEAS_VALUE value -13.125000") != NULL,
          "Format 1 raw output permits omitted optional measurement names");
  free_callback_output(&captured);
  *first = original;

  meas_data_lst_t* row = &first->meas_data_lst[0];
  meas_data_lst_t saved_row = *row;
  meas_record_lst_t* record = &row->meas_record_lst[0];
  meas_record_lst_t saved_record = *record;
  record->value = INTEGER_MEAS_VALUE;
  record->int_val = 23;
  captured = capture_callback(&report, node);
  require(strstr(captured.output, "meas record INTEGER_MEAS_VALUE value 23") != NULL,
          "Format 1 preserves the generic raw INTEGER output");
  free_callback_output(&captured);
  record->value = NO_VALUE_MEAS_VALUE;
  captured = capture_callback(&report, node);
  require(strstr(captured.output, "meas record NO_VALUE_MEAS_VALUE value") != NULL,
          "Format 1 preserves the generic raw noValue output");
  free_callback_output(&captured);
  *record = saved_record;

  const size_t invalid_lengths[] = {0, 65536};
  for (size_t i = 0; i < sizeof(invalid_lengths) / sizeof(invalid_lengths[0]); ++i) {
    first->meas_data_lst_len = invalid_lengths[i];
    require_diagnostic(&report, node, "skipping invalid KPM measurement lists");
    *first = original;
    row->meas_record_len = invalid_lengths[i];
    require_diagnostic(&report, node, "skipping invalid KPM measurement records");
    *row = saved_row;
  }
  first->meas_data_lst = NULL;
  require_diagnostic(&report, node, "skipping invalid KPM measurement lists");
  *first = original;
  first->meas_info_lst_len = 65536;
  require_diagnostic(&report, node, "skipping invalid KPM measurement lists");
  *first = original;
  first->meas_info_lst = NULL;
  require_diagnostic(&report, node, "skipping invalid KPM measurement lists");
  *first = original;
  row->meas_record_lst = NULL;
  require_diagnostic(&report, node, "skipping invalid KPM measurement records");
  *row = saved_row;
  puts("PASS: Format 1 raw-output compatibility and malformed list/record guards");
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
  require(subscription.act_len == 7, "existing five metrics plus RSRP and SNR");
  require(strcmp(subscription.actions[5].name, "FALCON.PUSCH.RSRP.dBFS") == 0, "RSRP is subscribed");
  require(strcmp(subscription.actions[6].name, "FALCON.PUSCH.SNR.dB") == 0, "SNR is subscribed");
  for (int32_t i = 0; i < subscription.act_len; ++i) {
    require(strcmp(subscription.actions[i].name, "RSRQ") != 0 &&
            strcmp(subscription.actions[i].name, "SINR") != 0 &&
            strcmp(subscription.actions[i].name, "FALCON.PUSCH.SINR.dB") != 0,
            "no unavailable RSRQ or separately named SINR subscription");
  }
  require(!config.db_params.enable, "database disabled for NONE_XAPP build");
  kpm_act_def_t action = gen_kpm_act_def(subscription, FORMAT_4_ACTION_DEFINITION, (uint32_t)subscription.time);
  byte_array_t encoded_action = kpm_enc_action_def_asn(&action);
  FILE* action_file = fopen(argv[3], "wb");
  require(action_file != NULL, "open encoded subscription output");
  require(fwrite(encoded_action.buf, 1, encoded_action.len, action_file) == encoded_action.len,
          "write actual FlexRIC seven-metric subscription");
  require(fclose(action_file) == 0, "close subscription output");
  free_byte_array(encoded_action);
  free_kpm_action_def(&action);
  free_fr_args(&config);
  puts("PASS: real config parser and xApp builder encode seven-metric Format 4 subscription");

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
  static const double expected_values[2][2] = {{-13.125, 21.75}, {0.0, 0.0}};
  static const char* expected_names[] = {"FALCON.PUSCH.RSRP.dBFS", "FALCON.PUSCH.SNR.dB"};
  for (size_t i = 0; i < 3; ++i) {
    meas_report_per_ue_t* ue = &msg->meas_report_per_ue[i];
    require(ue->ue_meas_report_lst.type == GNB_DU_UE_ID_E2SM, "gNB-DU UE ID");
    require(ue->ue_meas_report_lst.gnb_du.gnb_cu_ue_f1ap == expected_ids[i], "F1AP UE identity");
    kpm_ind_msg_format_1_t* row = &ue->ind_msg_format_1;
    require(row->meas_info_lst_len == 2 && row->meas_data_lst_len == 1, "two metrics and one window per UE");
    require(row->meas_data_lst[0].meas_record_len == 2, "two RF records per UE");
    for (size_t j = 0; j < 2; ++j) {
      require(row->meas_info_lst[j].meas_type.type == NAME_MEAS_TYPE, "named measurement");
      require(row->meas_info_lst[j].meas_type.name.len == strlen(expected_names[j]) &&
              memcmp(row->meas_info_lst[j].meas_type.name.buf, expected_names[j], strlen(expected_names[j])) == 0,
              "RF metric name survives the wire");
      meas_record_lst_t* value = &row->meas_data_lst[0].meas_record_lst[j];
      if (i < 2) {
        require(value->value == REAL_MEAS_VALUE, "REAL preserves negative, fractional, and zero RF measurements");
        require(value->real_val == expected_values[i][j], "RSRP and SNR remain distinct across codecs");
      } else {
        require(value->value == NO_VALUE_MEAS_VALUE, "absent measurement remains noValue");
      }
    }
  }

  /* The header is synthetic; the measurement payload comes from the DU codec. */
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
  for (size_t j = 0; j < 2; ++j) {
    meas_record_lst_t* value = &first->meas_data_lst[0].meas_record_lst[j];
    meas_record_lst_t saved_value = *value;
    printf("CASE: reject %s encoded as INTEGER\n", expected_names[j]);
    value->value = INTEGER_MEAS_VALUE;
    value->int_val = 23;
    sm_cb_kpm(&rd, &node);
    *value = saved_value;
    printf("CASE: reject %s non-finite REAL\n", expected_names[j]);
    value->real_val = NAN;
    sm_cb_kpm(&rd, &node);
    *value = saved_value;
  }

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

  /* Restore the fixture context before isolated monitor-only negative cases. */
  du_id = 1;
  check_subscription_capacity();
  check_trace_contract(&rd, &node);
  check_malformed_callbacks(&rd, &node);
  check_format1_callbacks(&rd, &node);

  sm_cb_kpm(NULL, &node);
  request_stop(SIGTERM);
  require(stop_requested == 1, "stop handler sets a flag for main-thread cleanup");
  free_kpm_ind_msg(&rd.ind.kpm.ind.msg);
  pthread_mutex_destroy(&mtx);
  puts("PASS: OCUDU to FlexRIC RF REAL/noValue payload and patched xApp callback");
  return EXIT_SUCCESS;
}
