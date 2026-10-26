#include "kpm_broker/kpm_broker.h"
#include <assert.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <poll.h>

typedef struct {
  sm_ag_if_rd_t rd;
  global_e2_node_id_t node;
  uint64_t du,ran;
  meas_report_per_ue_t ue;
  meas_info_format_1_lst_t info[5];
  meas_data_lst_t data;
  meas_record_lst_t records[5];
} input;
static void setup(input *in) {
  memset(in,0,sizeof(*in)); in->du=1; in->ran=UINT64_MAX;
  in->node.type=e2ap_ngran_gNB_DU; in->node.cu_du_id=&in->du;
  in->node.plmn.mcc=1; in->node.plmn.mnc=1; in->node.plmn.mnc_digit_len=2;
  in->node.nb_id.nb_id=411; in->node.nb_id.unused=10;
  in->rd.type=INDICATION_MSG_AGENT_IF_ANS_V0; in->rd.ind.type=KPM_STATS_V3_0;
  in->rd.ind.kpm.ind.hdr.type=FORMAT_1_INDICATION_HEADER;
  in->rd.ind.kpm.ind.msg.type=FORMAT_3_INDICATION_MESSAGE;
  in->rd.ind.kpm.ind.msg.frm_3.ue_meas_report_lst_len=1;
  in->rd.ind.kpm.ind.msg.frm_3.meas_report_per_ue=&in->ue;
  in->ue.ue_meas_report_lst.type=GNB_DU_UE_ID_E2SM;
  in->ue.ue_meas_report_lst.gnb_du.gnb_cu_ue_f1ap=1007;
  in->ue.ue_meas_report_lst.gnb_du.ran_ue_id=&in->ran;
  in->ue.ind_msg_format_1=(kpm_ind_msg_format_1_t){.meas_info_lst_len=5,.meas_info_lst=in->info,.meas_data_lst_len=1,.meas_data_lst=&in->data};
  in->data.meas_record_len=5; in->data.meas_record_lst=in->records;
  for (unsigned k=0;k<5;++k) {
    in->info[k].meas_type.type=NAME_MEAS_TYPE;
    in->info[k].meas_type.name=(byte_array_t){.buf=(uint8_t*)bk_names[k],.len=strlen(bk_names[k])};
    in->records[k].value=k<3 ? REAL_MEAS_VALUE : INTEGER_MEAS_VALUE;
    if (k<3) in->records[k].real_val=k ? 0 : -13.123456789012345;
    else in->records[k].int_val=UINT32_MAX;
  }
}
static void passed(const char *name) { printf("{\"case\":\"%s\",\"status\":\"passed\"}\n",name); }
static void rejected(bk_context *ctx,input *in) {
  uint64_t before=atomic_load(&ctx->malformed); bk_callback(ctx,&in->rd,&in->node);
  bk_row row; assert(!bk_pop(ctx,&row)); assert(atomic_load(&ctx->malformed)==before+1);
}
typedef struct { bk_context *ctx; input *in; } producer_args;
static void *producer(void *arg) {
  producer_args *a=arg;
  for (unsigned i=0;i<10000;++i) bk_callback(a->ctx,&a->in->rd,&a->in->node);
  return NULL;
}
static json_object *receive_line(int fd) {
  char line[BK_FRAME]; size_t n=0;
  do { assert(n<sizeof(line)); assert(recv(fd,line+n,1,0)==1); } while (line[n++]!='\n');
  /* Server frames exceed request bounds in general; these barrier frames fit. */
  json_object *obj=bk_parse(line,n); assert(obj); return obj;
}
static void late_callback_barrier(bk_context *ctx,bk_row *row) {
  int probe=socket(AF_INET,SOCK_STREAM,0); assert(probe>=0);
  struct sockaddr_in address={.sin_family=AF_INET,.sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
  assert(bind(probe,(struct sockaddr*)&address,sizeof(address))==0);
  socklen_t len=sizeof(address); assert(getsockname(probe,(struct sockaddr*)&address,&len)==0); close(probe);
  ctx->cfg.port=ntohs(address.sin_port); ctx->accepting=true; atomic_store(&ctx->sequence,1);
  atomic_store(&ctx->admission_closed,false);
  pthread_t worker; assert(pthread_create(&worker,NULL,bk_server,ctx)==0);
  uint64_t deadline=bk_mono_ms()+2000;
  while (!atomic_load(&ctx->ready) && !atomic_load(&ctx->failed) && bk_mono_ms()<deadline) usleep(1000);
  assert(atomic_load(&ctx->ready));
  int fd=socket(AF_INET,SOCK_STREAM,0); assert(fd>=0);
  struct timeval timeout={.tv_sec=2}; setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));
  assert(connect(fd,(struct sockaddr*)&address,sizeof(address))==0);
  const char registration[]="{\"version\":1,\"type\":\"register\",\"request_id\":\"r\",\"app_id\":\"barrier\",\"filter\":{\"mode\":\"all_du_ues\"}}\n";
  assert(send(fd,registration,sizeof(registration)-1,0)==sizeof(registration)-1);
  json_object *reply=receive_line(fd); assert(!strcmp(bk_string(reply,"status"),"registered"));
  assert(!strcmp(bk_string(reply,"registration_cutoff_report_seq"),"1")); json_object_put(reply);
  /* A callback entered before registration but finished normalization afterward. */
  row->report_seq=1; bk_enqueue_owned(ctx,row);
  const char ping[]="{\"version\":1,\"type\":\"ping\",\"request_id\":\"p\"}\n";
  assert(send(fd,ping,sizeof(ping)-1,0)==sizeof(ping)-1);
  reply=receive_line(fd); assert(!strcmp(bk_string(reply,"type"),"pong")); json_object_put(reply);
  struct pollfd wait={.fd=fd,.events=POLLIN}; assert(poll(&wait,1,80)==0);
  atomic_store(&ctx->sequence,2); row->report_seq=2; bk_enqueue_owned(ctx,row);
  reply=receive_line(fd); assert(!strcmp(bk_string(reply,"report_seq"),"2"));
  assert(!strcmp(bk_string(reply,"delivery_seq"),"1")); json_object_put(reply);
  close(fd); bk_disable(ctx); atomic_store(&ctx->stop,true); bk_wake(ctx);
  assert(pthread_join(worker,NULL)==0);
}
int main(void) {
  bk_config cfg; bk_defaults(&cfg); bk_context *ctx=malloc(sizeof(*ctx)); assert(ctx);
  assert(bk_init(ctx,&cfg,"fixture",NULL)); input in; setup(&in);
  bk_callback(ctx,&in.rd,&in.node); memset(&in,0xa5,sizeof(in)); bk_row row;
  assert(bk_pop(ctx,&row)); assert(!strcmp(row.key.mcc,"001") && !strcmp(row.key.mnc,"01") && row.key.bits==22 && row.key.du==1 && row.key.ue==1007);
  assert(row.ran_ue==UINT64_MAX && row.values[0].real==-13.123456789012345 && row.values[3].integer==UINT32_MAX);
  passed("owned_snapshot_and_precision");
  setup(&in); in.records[0].real_val=NAN; in.records[1].value=END_MEAS_VALUE; in.records[2].value=NO_VALUE_MEAS_VALUE;
  bk_callback(ctx,&in.rd,&in.node); assert(bk_pop(ctx,&row));
  assert(row.values[0].type==BK_REAL && row.values[0].status==BK_INVALID);
  assert(row.values[1].type==BK_UNSUPPORTED && row.values[1].status==BK_INVALID && row.values[2].status==BK_NO_DATA);
  json_object *obj=bk_row_json(ctx,&row); const char *text=json_object_to_json_string(obj); assert(!strstr(text,"NaN")); json_object_put(obj);
  passed("nonfinite_unsupported_and_novalue");
  setup(&in); in.node.cu_du_id=NULL; rejected(ctx,&in);
  setup(&in); in.ue.ue_meas_report_lst.type=GNB_UE_ID_E2SM; rejected(ctx,&in);
  setup(&in); in.info[1]=in.info[0]; rejected(ctx,&in);
  setup(&in); in.info[1].meas_type.type=ID_MEAS_TYPE; rejected(ctx,&in);
  setup(&in); in.data.meas_record_len=4; rejected(ctx,&in);
  setup(&in); in.data.meas_record_lst=NULL; rejected(ctx,&in);
  setup(&in); in.node.nb_id.unused=11; rejected(ctx,&in);
  passed("malformed_mapping_identity_and_pointers");
  setup(&in); for (unsigned i=0;i<300;++i) bk_callback(ctx,&in.rd,&in.node);
  assert(ctx->count==256 && atomic_load(&ctx->dropped)==44);
  unsigned count=0; while (bk_pop(ctx,&row)) ++count; assert(count==256);
  bk_key other=row.key; other.du=2; assert(!bk_key_equal(&row.key,&other)); other=row.key; strcpy(other.mnc,"001"); assert(!bk_key_equal(&row.key,&other));
  passed("bounded_ingress_overflow_and_complete_key");
  atomic_store(&ctx->dropped,0); atomic_store(&ctx->sequence,0);
  pthread_t threads[4]; producer_args args={ctx,&in};
  for (unsigned i=0;i<4;++i) assert(pthread_create(&threads[i],NULL,producer,&args)==0);
  for (unsigned i=0;i<4;++i) assert(pthread_join(threads[i],NULL)==0);
  count=0; while (bk_pop(ctx,&row)) ++count;
  assert(count+atomic_load(&ctx->dropped)==40000 && atomic_load(&ctx->sequence)==40000 && ctx->peak<=256);
  bk_disable(ctx); bk_callback(ctx,&in.rd,&in.node); assert(!bk_pop(ctx,&row));
  passed("concurrent_callback_queue_and_disable");
  late_callback_barrier(ctx,&row);
  passed("callback_finishing_after_registration_cutoff");
  bk_destroy(ctx); free(ctx); return 0;
}
