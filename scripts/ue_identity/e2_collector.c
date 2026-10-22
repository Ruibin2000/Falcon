/*
 * Licensed to the OpenAirInterface (OAI) Software Alliance under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The OpenAirInterface Software Alliance licenses this file to You under
 * the OAI Public License, Version 1.1  (the "License"); you may not use this file
 * except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *      http://www.openairinterface.org/?page_id=698
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *-------------------------------------------------------------------------------
 * For more information about the OpenAirInterface (OAI) Software Alliance:
 *      contact@openairinterface.org
 */


#define _GNU_SOURCE
#include "xApp/e42_xapp_api.h"
#include "xApp/plugin_ric.h"
#include "util/time_now_us.h"
#include "util/e2ap_ngran_types.h"
#include "sm/kpm_sm/kpm_sm_id_wrapper.h"
#include "sm/sm_ric.h"
#include <dlfcn.h>
#include <assert.h>
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <unistd.h>

// Only owned serialized records cross the callback boundary. Slow output never
// holds the callback mutex; the queue has fixed item and byte capacities.
static pthread_mutex_t queue_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t queue_ready = PTHREAD_COND_INITIALIZER;
static char* queue_items[16];
static size_t queue_sizes[16], head, count, queued_bytes;
static uint64_t dropped;
static bool drain_stop;
static FILE* events;
static volatile sig_atomic_t stopping;

static void stop_handler(int sig) { (void)sig; stopping = 1; }

static void json_bytes(FILE* out, const uint8_t* bytes, size_t len)
{
  fputc('"', out);
  for (size_t i = 0; i < len; ++i) {
    unsigned char c = bytes[i];
    if (c == '"' || c == '\\') fprintf(out, "\\%c", c);
    else if (c < 32 || c >= 127) fprintf(out, "\\u%04x", c);
    else fputc(c, out);
  }
  fputc('"', out);
}

static void json_node(FILE* out, const global_e2_node_id_t* node)
{
  fprintf(out, "{\"mcc\":\"%03u\",\"mnc\":\"%0*u\",\"gnb_id\":\"%u\","
               "\"gnb_padding\":%u,\"node_type\":\"%s\",\"du_id\":",
          node->plmn.mcc, node->plmn.mnc_digit_len, node->plmn.mnc,
          node->nb_id.nb_id, node->nb_id.unused, get_e2ap_ngran_name(node->type));
  if (node->type == e2ap_ngran_gNB_DU && node->cu_du_id)
    fprintf(out, "\"%" PRIu64 "\"", *node->cu_du_id);
  else fputs("null", out);
  fputc('}', out);
}

static void json_ue(FILE* out, const ue_id_e2sm_t* ue)
{
  if (ue->type == GNB_DU_UE_ID_E2SM) {
    fprintf(out, "{\"id_type\":\"gnb_du\",\"gnb_cu_ue_f1ap_id\":\"%u\"}", ue->gnb_du.gnb_cu_ue_f1ap);
  } else if (ue->type == GNB_UE_ID_E2SM) {
    const gnb_e2sm_t* id = &ue->gnb;
    fprintf(out, "{\"id_type\":\"gnb\",\"amf_ue_ngap_id\":\"%" PRIu64 "\","
                 "\"guami\":{\"mcc\":\"%03u\",\"mnc\":\"%0*u\",\"amf_region_id\":%u,"
                 "\"amf_set_id\":%u,\"amf_pointer\":%u},\"f1ap_ids\":[",
            id->amf_ue_ngap_id, id->guami.plmn_id.mcc, id->guami.plmn_id.mnc_digit_len,
            id->guami.plmn_id.mnc, id->guami.amf_region_id, id->guami.amf_set_id, id->guami.amf_ptr);
    for (size_t i = 0; i < id->gnb_cu_ue_f1ap_lst_len; ++i) {
      if (i) fputc(',', out);
      fprintf(out, "\"%u\"", id->gnb_cu_ue_f1ap_lst[i]);
    }
    fputs("]}", out);
  } else fputs("{\"id_type\":\"unsupported\"}", out);
}

static bool bounded_report(const kpm_ind_data_t* kpm)
{
  size_t budget = 1024;
  if (kpm->msg.type != FORMAT_3_INDICATION_MESSAGE) return false;
  const kpm_ind_msg_format_3_t* msg = &kpm->msg.frm_3;
  if (msg->ue_meas_report_lst_len > 256) return false;
  for (size_t i = 0; i < msg->ue_meas_report_lst_len; ++i) {
    const ue_id_e2sm_t* ue = &msg->meas_report_per_ue[i].ue_meas_report_lst;
    if (ue->type == GNB_UE_ID_E2SM && ue->gnb.gnb_cu_ue_f1ap_lst_len > 4) return false;
    const kpm_ind_msg_format_1_t* rows = &msg->meas_report_per_ue[i].ind_msg_format_1;
    if (rows->meas_info_lst_len > 32 || rows->meas_data_lst_len > 16) return false;
    for (size_t j = 0; j < rows->meas_info_lst_len; ++j) {
      if (rows->meas_info_lst[j].meas_type.type == NAME_MEAS_TYPE &&
          rows->meas_info_lst[j].meas_type.name.len > 256) return false;
      budget += rows->meas_data_lst_len * (128 +
          (rows->meas_info_lst[j].meas_type.type == NAME_MEAS_TYPE ?
           6 * rows->meas_info_lst[j].meas_type.name.len : 32));
    }
    budget += rows->meas_data_lst_len * 2048;
    if (budget > 2 * 1024 * 1024) return false;
    for (size_t j = 0; j < rows->meas_data_lst_len; ++j) {
      if (rows->meas_data_lst[j].meas_record_len != rows->meas_info_lst_len) return false;
    }
  }
  return true;
}

static char* serialize_report(const kpm_ind_data_t* kpm, const global_e2_node_id_t* node,
                              int64_t callback_us, size_t* length)
{
  char* bytes = NULL;
  FILE* out = open_memstream(&bytes, length);
  if (!out) return NULL;
  fputs("{\"kind\":\"kpm_report\",\"node\":", out);
  json_node(out, node);
  fprintf(out, ",\"header_time_us\":\"%" PRIu64 "\",\"callback_at_us\":\"%" PRId64 "\","
               "\"ingress_dropped_total\":\"%" PRIu64 "\",\"rows\":[",
          kpm->hdr.kpm_ric_ind_hdr_format_1.collectStartTime, callback_us, dropped);
  const kpm_ind_msg_format_3_t* msg = &kpm->msg.frm_3;
  bool first = true;
  for (size_t i = 0; i < msg->ue_meas_report_lst_len; ++i) {
    const kpm_ind_msg_format_1_t* rows = &msg->meas_report_per_ue[i].ind_msg_format_1;
    for (size_t j = 0; j < rows->meas_data_lst_len; ++j) {
      if (!first) fputc(',', out);
      first = false;
      fputs("{\"ue\":", out);
      json_ue(out, &msg->meas_report_per_ue[i].ue_meas_report_lst);
      fprintf(out, ",\"sample_idx\":%zu,\"incomplete\":%s,\"granularity_ms\":", j,
              rows->meas_data_lst[j].incomplete_flag ?
              (*rows->meas_data_lst[j].incomplete_flag == TRUE_ENUM_VALUE ? "true" : "false") : "null");
      if (rows->gran_period_ms) fprintf(out, "%u", *rows->gran_period_ms);
      else fputs("null", out);
      fputs(",\"metrics\":{", out);
      for (size_t z = 0; z < rows->meas_info_lst_len; ++z) {
        if (z) fputc(',', out);
        const meas_type_t* type = &rows->meas_info_lst[z].meas_type;
        if (type->type == NAME_MEAS_TYPE) json_bytes(out, type->name.buf, type->name.len);
        else fprintf(out, "\"metric_id_%u\"", type->id);
        const meas_record_lst_t* value = &rows->meas_data_lst[j].meas_record_lst[z];
        if (value->value == INTEGER_MEAS_VALUE)
          fprintf(out, ":{\"type\":\"integer\",\"value\":%d}", value->int_val);
        else if (value->value == REAL_MEAS_VALUE && isfinite(value->real_val))
          fprintf(out, ":{\"type\":\"real\",\"value\":%.17g}", value->real_val);
        else fputs(":{\"type\":\"no_value\",\"value\":null}", out);
      }
      fputs("}}", out);
    }
  }
  fputs("]}\n", out);
  fclose(out);
  return bytes;
}

static void callback(sm_ag_if_rd_t const* rd, global_e2_node_id_t const* node)
{
  if (!rd || rd->type != INDICATION_MSG_AGENT_IF_ANS_V0 || rd->ind.type != KPM_STATS_V3_0) return;
  pthread_mutex_lock(&queue_mutex);
  const kpm_ind_data_t* kpm = &rd->ind.kpm.ind;
  if (!bounded_report(kpm) || count == 16) { ++dropped; pthread_mutex_unlock(&queue_mutex); return; }
  size_t length = 0;
  char* bytes = serialize_report(kpm, node, time_now_us(), &length);
  if (!bytes || length > 4 * 1024 * 1024 || queued_bytes + length > 4 * 1024 * 1024) {
    free(bytes); ++dropped;
  } else {
    size_t tail = (head + count) % 16;
    queue_items[tail] = bytes; queue_sizes[tail] = length;
    queued_bytes += length; ++count; pthread_cond_signal(&queue_ready);
  }
  pthread_mutex_unlock(&queue_mutex);
}

static void* writer(void* unused)
{
  (void)unused;
  for (;;) {
    pthread_mutex_lock(&queue_mutex);
    while (!count && !drain_stop) pthread_cond_wait(&queue_ready, &queue_mutex);
    if (!count && drain_stop) { pthread_mutex_unlock(&queue_mutex); break; }
    char* bytes = queue_items[head]; size_t length = queue_sizes[head];
    head = (head + 1) % 16; --count; queued_bytes -= length;
    pthread_mutex_unlock(&queue_mutex);
    if (fwrite(bytes, 1, length, events) != length || fflush(events)) stopping = 1;
    free(bytes);
  }
  return NULL;
}

static
kpm_event_trigger_def_t gen_kpm_ev_trig(uint64_t period)
{
  kpm_event_trigger_def_t dst = {0};

  dst.type = FORMAT_1_RIC_EVENT_TRIGGER;
  dst.kpm_ric_event_trigger_format_1.report_period_ms = period;

  return dst;
}

static
meas_info_format_1_lst_t gen_meas_info_format_1_lst(const act_name_id_t act)
{
  meas_info_format_1_lst_t dst = {0};

  // use id
  if (!strcasecmp(act.name, "null")) {
    dst.meas_type.type = ID_MEAS_TYPE;
    dst.meas_type.id = act.id;
  } else { // use name
    dst.meas_type.type = NAME_MEAS_TYPE;
    // ETSI TS 128 552
    dst.meas_type.name = cp_str_to_ba(act.name);
  }

  dst.label_info_lst_len = 1;
  dst.label_info_lst = calloc(1, sizeof(label_info_lst_t));
  assert(dst.label_info_lst != NULL && "Memory exhausted");

  // No Label
  dst.label_info_lst[0].noLabel = calloc(1, sizeof(enum_value_e));
  assert(dst.label_info_lst[0].noLabel != NULL && "Memory exhausted");
  *dst.label_info_lst[0].noLabel = TRUE_ENUM_VALUE;

  return dst;
}

static
kpm_act_def_format_1_t gen_kpm_act_def_frmt_1(const sub_oran_sm_t sub_sm, uint32_t period_ms)
{
  kpm_act_def_format_1_t dst = {0};

  dst.gran_period_ms = period_ms;

  dst.meas_info_lst_len = sub_sm.act_len;
  dst.meas_info_lst = calloc(dst.meas_info_lst_len, sizeof(meas_info_format_1_lst_t));
  assert(dst.meas_info_lst != NULL && "Memory exhausted");

  for(size_t i = 0; i < dst.meas_info_lst_len; i++) {
    dst.meas_info_lst[i] = gen_meas_info_format_1_lst(sub_sm.actions[i]);
  }

  return dst;
}

static
kpm_act_def_format_4_t gen_kpm_act_def_frmt_4(const sub_oran_sm_t sub_sm, uint32_t period_ms)
{
  kpm_act_def_format_4_t dst = {0};

  // [1, 32768]
  dst.matching_cond_lst_len = 1;

  dst.matching_cond_lst = calloc(dst.matching_cond_lst_len, sizeof(matching_condition_format_4_lst_t));
  assert(dst.matching_cond_lst != NULL && "Memory exhausted");

  test_info_lst_t* test_info_lst = &dst.matching_cond_lst[0].test_info_lst;
  test_info_lst->test_cond_type = S_NSSAI_TEST_COND_TYPE;
  test_info_lst->S_NSSAI = TRUE_TEST_COND_TYPE;

  test_cond_e* test_cond = calloc(1, sizeof(test_cond_e));
  assert(test_cond != NULL && "Memory exhausted");
  *test_cond = EQUAL_TEST_COND;
  test_info_lst->test_cond = test_cond;

  test_cond_value_t* test_cond_value = calloc(1, sizeof(test_cond_value_t));
  assert(test_cond_value != NULL && "Memory exhausted");
  test_cond_value->type = INTEGER_TEST_COND_VALUE;
  test_cond_value->int_value = calloc(1, sizeof(int64_t));
  assert(test_cond_value->int_value != NULL && "Memory exhausted");
  *test_cond_value->int_value = 1;
  test_info_lst->test_cond_value = test_cond_value;

  // Action definition Format 1
  dst.action_def_format_1 = gen_kpm_act_def_frmt_1(sub_sm, period_ms);  // 8.2.1.2.1

  return dst;
}

static
kpm_act_def_t gen_kpm_act_def(const sub_oran_sm_t sub_sm, format_action_def_e act_frm, uint32_t period_ms)
{
  kpm_act_def_t dst = {0};

  if (act_frm == FORMAT_1_ACTION_DEFINITION) {
    dst.type = FORMAT_1_ACTION_DEFINITION;
    dst.frm_1 = gen_kpm_act_def_frmt_1(sub_sm, period_ms);
  } else if (act_frm == FORMAT_4_ACTION_DEFINITION) {
    dst.type = FORMAT_4_ACTION_DEFINITION;
    dst.frm_4 = gen_kpm_act_def_frmt_4(sub_sm, period_ms);
  } else {
    assert(0!=0 && "not support action definition type");
  }

  return dst;
}



static uint8_t* fixture_bytes(const char* path, size_t* length)
{
  FILE* file = fopen(path, "rb");
  if (!file) return NULL;
  uint8_t* bytes = malloc(2 * 1024 * 1024 + 1);
  if (!bytes) { fclose(file); return NULL; }
  *length = fread(bytes, 1, 2 * 1024 * 1024 + 1, file);
  bool valid = !ferror(file) && *length > 0 && *length <= 2 * 1024 * 1024;
  fclose(file);
  if (!valid) { free(bytes); return NULL; }
  return bytes;
}

static int decode_fixture(const char* hdr, const char* msg, const char* plugin)
{
  // Use the same installed-model interface as FlexRIC, not an OCUDU decoder.
  sm_ind_data_t raw = {0};
  raw.ind_hdr = fixture_bytes(hdr, &raw.len_hdr);
  raw.ind_msg = fixture_bytes(msg, &raw.len_msg);
  if (!raw.ind_hdr || !raw.ind_msg) { free(raw.ind_hdr); free(raw.ind_msg); return 2; }
  void* library = dlopen(plugin, RTLD_NOW);
  if (!library) { fprintf(stderr, "%s\n", dlerror()); free(raw.ind_hdr); free(raw.ind_msg); return 2; }
  sm_ric_t* (*make)(void) = dlsym(library, "make_kpm_sm_ric");
  if (!make) { dlclose(library); free(raw.ind_hdr); free(raw.ind_msg); return 2; }
  sm_ric_t* model = make();
  sm_ag_if_rd_ind_t decoded = model->proc.on_indication(model, &raw);
  global_e2_node_id_t node = {0};
  node.type = e2ap_ngran_gNB;
  node.plmn.mcc = 1; node.plmn.mnc = 1; node.plmn.mnc_digit_len = 2;
  node.nb_id.nb_id = 411;
  size_t length = 0;
  char* output = bounded_report(&decoded.kpm.ind) ? serialize_report(&decoded.kpm.ind, &node, 100000001, &length) : NULL;
  bool success = output != NULL;
  if (output) { fwrite(output, 1, length, stdout); free(output); }
  model->alloc.free_ind_data(&decoded);
  model->free_sm(model);
  free(raw.ind_hdr); free(raw.ind_msg); dlclose(library);
  return success ? 0 : 1;
}

int main(int argc, char** argv)
{
  setvbuf(stdout, NULL, _IOLBF, 0);
  if (argc == 3 && !strcmp(argv[1], "--check-config")) {
    char* arguments[] = {argv[0], "-c", argv[2]};
    fr_args_t config = init_fr_args(3, arguments);
    plugin_ric_t plugins;
    init_plugin_ric(&plugins, config.libs_dir);
    bool success = sm_plugin_ric(&plugins, SM_KPM_ID) != NULL;
    free_plugin_ric(&plugins);
    free_fr_args(&config);
    return success ? 0 : 1;
  }
  if (argc == 5 && !strcmp(argv[1], "--decode-fixture")) return decode_fixture(argv[2], argv[3], argv[4]);
  const char* fd = getenv("FALCON_IDENTITY_FD");
  if (!fd) { fprintf(stderr, "Run through xapp_ue_identity.py (missing event descriptor)\n"); return 2; }
  char* end = NULL;
  long descriptor = strtol(fd, &end, 10);
  if (*fd == '\0' || *end || descriptor < 3 || descriptor > 65535) return 2;
  events = fdopen((int)descriptor, "w");
  if (!events) return 2;
  unsigned long seconds = 60;
  const char* duration = getenv("FALCON_KPM_SECONDS");
  if (duration) {
    seconds = strtoul(duration, &end, 10);
    if (!*duration || *end || seconds < 1 || seconds > 3600) return 2;
  }
  signal(SIGINT, stop_handler); signal(SIGTERM, stop_handler); signal(SIGPIPE, SIG_IGN);
  pthread_t thread;
  if (pthread_create(&thread, NULL, writer, NULL)) return 2;
  fr_args_t args = init_fr_args(argc, argv);
  init_xapp_api(&args);
  sleep(1);
  e2_node_arr_xapp_t nodes = e2_nodes_xapp_api();
  sm_ans_xapp_t* handles = calloc(nodes.len ? nodes.len : 1, sizeof(*handles));
  assert(handles);
  size_t subscriptions = 0;
  for (size_t i = 0; i < nodes.len && !stopping; ++i) {
    bool subscribed = false;
    for (int j = 0; j < args.sub_oran_sm_len; ++j) {
      const sub_oran_sm_t spec = args.sub_oran_sm[j];
      if (strcasecmp(spec.name, "kpm") || strcasecmp(spec.ran_type, get_e2ap_ngran_name(nodes.n[i].id.type))) continue;
      if (subscribed || spec.format != 4) { stopping = 1; break; }
      kpm_sub_data_t sub = {0};
      sub.ev_trg_def = gen_kpm_ev_trig(spec.time);
      sub.sz_ad = 1;
      sub.ad = calloc(1, sizeof(*sub.ad)); assert(sub.ad);
      sub.ad[0] = gen_kpm_act_def(spec, FORMAT_4_ACTION_DEFINITION, spec.time);
      sm_ans_xapp_t answer = report_sm_xapp_api(&nodes.n[i].id, SM_KPM_ID, &sub, callback);
      free_kpm_sub_data(&sub);
      if (!answer.success) { fprintf(stderr, "CU/DU KPM subscription rejected\n"); stopping = 1; break; }
      handles[subscriptions++] = answer;
      subscribed = true;
    }
  }
  fprintf(stderr, "identity collector: %zu KPM subscriptions, duration=%lu\n", subscriptions, seconds);
  for (unsigned long tick = 0; tick < seconds * 10 && !stopping; ++tick) usleep(100000);
  for (size_t i = 0; i < subscriptions; ++i) { rm_report_sm_xapp_api(handles[i].u.handle); usleep(100000); }
  free(handles); free_e2_node_arr_xapp(&nodes);
  while (!try_stop_xapp_api()) usleep(1000);
  free_fr_args(&args);
  pthread_mutex_lock(&queue_mutex); drain_stop = true; pthread_cond_signal(&queue_ready); pthread_mutex_unlock(&queue_mutex);
  pthread_join(thread, NULL);
  fclose(events);
  return subscriptions ? 0 : 1;
}
