/* Fresh APER fixtures using the actual FlexRIC KPM v3 encoder. No SDK/RIC. */
#include "sm/kpm_sm/kpm_sm_v03.00/enc/kpm_enc_asn.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

static const char *names[]={"DRB.RlcSduDelayDl","DRB.UEThpDl","DRB.UEThpUl","RRU.PrbTotDl","RRU.PrbTotUl"};
static void write_bytes(const char *dir,const char *name,byte_array_t bytes) {
  char path[4096]; assert(snprintf(path,sizeof(path),"%s/%s",dir,name)<(int)sizeof(path));
  FILE *f=fopen(path,"wx"); assert(f); assert(fwrite(bytes.buf,1,bytes.len,f)==bytes.len);
  assert(fclose(f)==0); free_byte_array(bytes);
}
static void generate(const char *dir,const char *file,unsigned mode) {
  kpm_ind_msg_t msg={.type=FORMAT_3_INDICATION_MESSAGE};
  msg.frm_3.ue_meas_report_lst_len=2;
  msg.frm_3.meas_report_per_ue=calloc(2,sizeof(meas_report_per_ue_t)); assert(msg.frm_3.meas_report_per_ue);
  for (unsigned u=0;u<2;++u) {
    meas_report_per_ue_t *ue=&msg.frm_3.meas_report_per_ue[u];
    ue->ue_meas_report_lst.type=GNB_DU_UE_ID_E2SM;
    ue->ue_meas_report_lst.gnb_du.gnb_cu_ue_f1ap=u ? 2091 : 1007;
    ue->ue_meas_report_lst.gnb_du.ran_ue_id=calloc(1,sizeof(uint64_t)); assert(ue->ue_meas_report_lst.gnb_du.ran_ue_id);
    *ue->ue_meas_report_lst.gnb_du.ran_ue_id=UINT64_MAX-u;
    kpm_ind_msg_format_1_t *rows=&ue->ind_msg_format_1;
    rows->meas_info_lst_len=mode==2 ? 4 : 5;
    rows->meas_info_lst=calloc(rows->meas_info_lst_len,sizeof(meas_info_format_1_lst_t)); assert(rows->meas_info_lst);
    rows->meas_data_lst_len=2; rows->meas_data_lst=calloc(2,sizeof(meas_data_lst_t)); assert(rows->meas_data_lst);
    for (unsigned k=0;k<rows->meas_info_lst_len;++k) {
      meas_info_format_1_lst_t *info=&rows->meas_info_lst[k];
      info->meas_type.type=NAME_MEAS_TYPE;
      info->meas_type.name=cp_str_to_ba(names[mode==1 ? 4-k : (mode==3 && k==1 ? 0 : k)]);
      if (mode==4) { free_byte_array(info->meas_type.name); info->meas_type.type=ID_MEAS_TYPE; info->meas_type.id=20+k; }
      info->label_info_lst_len=1; info->label_info_lst=calloc(1,sizeof(label_info_lst_t)); assert(info->label_info_lst);
      info->label_info_lst->noLabel=calloc(1,sizeof(enum_value_e)); assert(info->label_info_lst->noLabel);
      *info->label_info_lst->noLabel=TRUE_ENUM_VALUE;
    }
    for (unsigned r=0;r<2;++r) {
      meas_data_lst_t *row=&rows->meas_data_lst[r];
      row->meas_record_len=rows->meas_info_lst_len-(mode==5 ? 1 : 0);
      row->meas_record_lst=calloc(row->meas_record_len,sizeof(meas_record_lst_t)); assert(row->meas_record_lst);
      if (mode==2 && !r) { row->incomplete_flag=calloc(1,sizeof(enum_value_e)); assert(row->incomplete_flag); *row->incomplete_flag=TRUE_ENUM_VALUE; }
      for (unsigned k=0;k<row->meas_record_len;++k) {
        unsigned metric=mode==1 ? 4-k : k; meas_record_lst_t *v=&row->meas_record_lst[k];
        if (mode==2 && !r) v->value=NO_VALUE_MEAS_VALUE;
        else if (metric<3) { v->value=REAL_MEAS_VALUE; v->real_val=r ? 0.0 : (metric==0 ? -13.123456789012345 : 1280.1234567890123)+u*100+mode*10; }
        else { v->value=INTEGER_MEAS_VALUE; v->int_val=r ? 0 : (metric==4 ? UINT32_MAX : 12+u+mode); }
      }
    }
  }
  write_bytes(dir,file,kpm_enc_ind_msg_asn(&msg)); free_kpm_ind_msg(&msg);
}
int main(int argc,char **argv) {
  if (argc!=2) { fprintf(stderr,"Usage: %s NEW_DIRECTORY\n",argv[0]); return 2; }
  assert(mkdir(argv[1],0700)==0);
  kpm_ind_hdr_t hdr={.type=FORMAT_1_INDICATION_HEADER};
  hdr.kpm_ric_ind_hdr_format_1.collectStartTime=UINT64_C(1791745200000000);
  write_bytes(argv[1],"header.aper",kpm_enc_ind_hdr_asn(&hdr));
  const char *files[]={"normal.aper","reordered.aper","states.aper","duplicate.aper","ids.aper","mismatch.aper"};
  for (unsigned i=0;i<6;++i) generate(argv[1],files[i],i);
  char path[4096]; assert(snprintf(path,sizeof(path),"%s/manifest.json",argv[1])<(int)sizeof(path));
  FILE *f=fopen(path,"wx"); assert(f);
  fputs("{\"version\":1,\"profile\":\"base5\",\"cases\":[",f);
  for (unsigned i=0;i<7;++i) {
    fprintf(f,"%s{\"header\":\"header.aper\",\"message\":\"%s\",\"link\":{\"node\":{\"mcc\":\"001\",\"mnc\":\"01\","
      "\"node_type\":\"ngran_gNB_DU\",\"gnb_id\":\"411\",\"gnb_id_bits\":22,\"du_id\":\"%u\"},"
      "\"ue\":{\"id_type\":\"gnb_du\",\"gnb_cu_ue_f1ap_id\":\"1007\"}}}",i ? "," : "",files[i==6 ? 0 : i],i==6 ? 2 : 1);
  }
  fputs("]}\n",f); assert(fclose(f)==0); puts("Generated six fresh KPM APER messages and two DU identities"); return 0;
}
