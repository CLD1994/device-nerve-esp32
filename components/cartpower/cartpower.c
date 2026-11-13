#include "cartpower.h"
#include "cartpower_core.h"
#include "bsp.h"
#include "ch224q.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
#include <limits.h>

static const char *TAG="cartpower";
static portMUX_TYPE s_lock=portMUX_INITIALIZER_UNLOCKED;
static cp_core_t s_core={.state=CP_FAILED,.reason=CP_INIT};
static bool s_started;
static ch224q_handle_t s_pd;

static const char *reason_name(cp_reason_t r)
{
    switch(r) {
    case CP_NONE: return "NONE";
    case CP_INIT: return "INIT";
    case CP_REQUEST: return "REQUEST";
    case CP_READ: return "READ";
    case CP_ADC: return "ADC";
    case CP_TIMEOUT: return "TIMEOUT";
    case CP_PD: return "PD";
    case CP_VOLTAGE: return "VOLTAGE";
    case CP_STALE: return "STALE";
    default: return "UNKNOWN";
    }
}
static void fail(cp_reason_t reason)
{
    portENTER_CRITICAL(&s_lock);
    cp_fail(&s_core,reason);
    portEXIT_CRITICAL(&s_lock);
    ESP_LOGE(TAG,"20V验证失败: %s；禁止使能，排查后重启",reason_name(reason));
}

bool cartpower_ready(void)
{
    portENTER_CRITICAL(&s_lock);
    /* 时钟与缓存同锁读取，不能用等锁前的旧时间判新样本来自未来。 */
    bool ready=cp_allowed(&s_core,esp_timer_get_time());
    portEXIT_CRITICAL(&s_lock);
    return ready;
}

static void power_task(void *arg)
{
    (void)arg;
    /* 若任务尚未调度就已超时，不在已失败状态继续请求高压。 */
    int64_t started=esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    (void)cp_allowed(&s_core,started);
    bool waiting=s_core.state==CP_WAITING;
    portEXIT_CRITICAL(&s_lock);
    if (!waiting) { vTaskDelete(NULL); return; }
    /* cp_init时间已在请求前记录。写成功不表示实际电压已到20V。 */
    esp_err_t err=ch224q_set_voltage(s_pd,CH224Q_VSEL_20V);
    if(err!=ESP_OK) { fail(CP_REQUEST); vTaskDelete(NULL); return; }
    ESP_LOGI(TAG,"已请求20V，等待PD与VBUS连续验证；电机保持禁用");
    for(;;) {
        int64_t sampled_at=esp_timer_get_time();
        ch224q_status_t st={0};
        err=ch224q_get_status(s_pd,&st);
        float volts=bsp_vbus_read_volt();
        int mv=-1;
        if(isfinite(volts) && volts>=0 && volts<(float)INT_MAX/1000.0f)
            mv=(int)lroundf(volts*1000.0f);
        int64_t now=esp_timer_get_time();
        portENTER_CRITICAL(&s_lock);
        cp_state_t old=s_core.state;
        cp_sample(&s_core,now,sampled_at,err==ESP_OK,st.pd,mv);
        cp_state_t state=s_core.state;
        cp_reason_t reason=s_core.reason;
        portEXIT_CRITICAL(&s_lock);
        if(state!=old || state==CP_FAILED) {
            ESP_LOGI(TAG,"20V状态=%s VBUS_MV=%d PD=%d 原因=%s",
                     state==CP_VERIFIED?"VERIFIED":"FAILED",mv,st.pd,reason_name(reason));
        }
        if(state==CP_FAILED) { vTaskDelete(NULL); return; }
        vTaskDelay(pdMS_TO_TICKS(CONFIG_CARTPOWER_SAMPLE_MS));
    }
}

esp_err_t cartpower_start(i2c_master_bus_handle_t bus)
{
    if(s_started) return ESP_ERR_INVALID_STATE;
    s_started=true; /* 失败也不在同次启动重试 */
    if(CONFIG_CARTPOWER_TIMEOUT_MS <= CONFIG_CARTPOWER_SETTLE_MS +
       (CONFIG_CARTPOWER_STABLE_SAMPLES-1)*CONFIG_CARTPOWER_SAMPLE_MS ||
       CONFIG_CARTPOWER_FRESH_MS < 2*CONFIG_CARTPOWER_SAMPLE_MS+100) {
        ESP_LOGE(TAG,"供电验证时间配置不满足稳定窗口/新鲜期限约束");
        return ESP_ERR_INVALID_ARG;
    }
    ch224q_config_t cfg={.bus=bus,.dev_addr=CONFIG_CH224Q_I2C_ADDR};
    esp_err_t err=ch224q_init(&cfg,&s_pd);
    if(err!=ESP_OK) { fail(CP_INIT); return err; }
    const cp_timing_t timing={
        .settle_us=(int64_t)CONFIG_CARTPOWER_SETTLE_MS*1000,
        .timeout_us=(int64_t)CONFIG_CARTPOWER_TIMEOUT_MS*1000,
        .sample_us=(int64_t)CONFIG_CARTPOWER_SAMPLE_MS*1000,
        .stable_required=CONFIG_CARTPOWER_STABLE_SAMPLES,
        .fresh_us=(int64_t)CONFIG_CARTPOWER_FRESH_MS*1000,
    };
    int64_t now=esp_timer_get_time();
    portENTER_CRITICAL(&s_lock);
    cp_init(&s_core,&timing,now);
    portEXIT_CRITICAL(&s_lock);
    if(xTaskCreate(power_task,"cartpower",3072,NULL,3,NULL)!=pdPASS) {
        fail(CP_INIT); return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
