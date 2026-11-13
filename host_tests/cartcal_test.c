/* 纯内存 NVS 替身，不访问设备或真实存储。 */
#include "cartcal.h"
#include "settings.h"
#include "nvs.h"
#include <assert.h>
#include <math.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
static unsigned char stored[64], pending[64];
static size_t stored_n, pending_n;
static int open_err, get_err, set_err, commit_err, closed, commits;
bool settings_is_valid(int idx, float v) { assert(idx == SET_MM_PER_REV); return isfinite(v) && v > 0 && v <= 500; }
esp_err_t nvs_open(const char *name,int mode,nvs_handle_t *h) { assert(!strcmp(name,"cartcal")); (void)mode; if(open_err)return open_err; *h=1;return ESP_OK; }
esp_err_t nvs_get_blob(nvs_handle_t h,const char *key,void *p,size_t *n) { assert(h==1&&!strcmp(key,"record")); if(get_err)return get_err; if(!stored_n)return ESP_ERR_NVS_NOT_FOUND; if(p){assert(*n>=stored_n);memcpy(p,stored,stored_n);} *n=stored_n;return ESP_OK; }
esp_err_t nvs_set_blob(nvs_handle_t h,const char *key,const void *p,size_t n) { assert(h==1&&!strcmp(key,"record")); if(set_err)return set_err; assert(n<=sizeof pending);memcpy(pending,p,n);pending_n=n;return ESP_OK; }
esp_err_t nvs_commit(nvs_handle_t h) { assert(h==1);commits++;if(commit_err)return commit_err;memcpy(stored,pending,pending_n);stored_n=pending_n;return ESP_OK; }
void nvs_close(nvs_handle_t h){assert(h==1);closed++;}
static void repair_crc(void){uint32_t c=UINT32_MAX;for(size_t j=0;j<24;j++){c^=stored[j];for(unsigned i=0;i<8;i++)c=(c>>1)^(0xedb88320u&(0u-(c&1u)));}c=~c;for(unsigned i=0;i<4;i++)stored[24+i]=(unsigned char)(c>>(8*i));}
static void unchanged(int expected){cartcal_record_t out={123,456,0,40},before=out;assert(cartcal_load(&out)==expected);assert(!memcmp(&before,&out,sizeof out));}
int main(void){
 cartcal_record_t r={853436,2159697,1,40},out;
 unchanged(ESP_ERR_NVS_NOT_FOUND);
 assert(cartcal_save(&r)==ESP_OK);assert(cartcal_load(&out)==ESP_OK);
 assert(out.length_um==r.length_um&&out.pole_zero_urad==r.pole_zero_urad&&out.pole_inv==1&&out.mm_per_rev==40);
 unsigned char valid[64];memcpy(valid,stored,stored_n);size_t len=stored_n;
 stored[9]^=1;unchanged(ESP_ERR_INVALID_STATE);memcpy(stored,valid,len);
 stored[4]=2;repair_crc();unchanged(ESP_ERR_INVALID_STATE);memcpy(stored,valid,len);
 stored[16]=2;repair_crc();unchanged(ESP_ERR_INVALID_STATE);memcpy(stored,valid,len);
 stored[8]=1;stored[9]=stored[10]=stored[11]=0;repair_crc();unchanged(ESP_ERR_INVALID_STATE);memcpy(stored,valid,len);
 stored_n=len-1;unchanged(ESP_ERR_INVALID_STATE);stored_n=len;
 open_err=-40;int c=closed;unchanged(-40);assert(cartcal_save(&r)==-40&&closed==c);open_err=0;
 get_err=-41;c=closed;unchanged(-41);assert(closed==c+1);get_err=0;
 set_err=-42;c=closed;int k=commits;assert(cartcal_save(&r)==-42&&closed==c+1&&commits==k);set_err=0;
 commit_err=-43;r.length_um=0;c=closed;assert(cartcal_save(&r)==-43&&closed==c+1);commit_err=0;
 assert(cartcal_load(&out)==ESP_OK&&out.length_um==853436);
 assert(cartcal_save(&r)==ESP_OK);assert(cartcal_load(&out)==ESP_OK&&out.length_um==0);
 r.length_um=99999;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);r.length_um=1000001;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);r.length_um=100000;
 r.pole_inv=2;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);r.pole_inv=1;r.pole_zero_urad=3141593;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);r.pole_zero_urad=0;
 r.mm_per_rev=NAN;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);r.mm_per_rev=0;assert(cartcal_save(&r)==ESP_ERR_INVALID_STATE);
 assert(cartcal_load(NULL)==ESP_ERR_INVALID_ARG);assert(cartcal_save(NULL)==ESP_ERR_INVALID_ARG);
 puts("cartcal tests passed");return 0;
}
