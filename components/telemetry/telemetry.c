/*
 * telemetry — 500 Hz STATE 流实现
 */

#include "telemetry.h"

#include <math.h>
#include <stdio.h>
#include <inttypes.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "telemetry_timing.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"

#include "cartpos.h"
#include "poleang.h"
#include "cartproto.h"
#include "cartfsm.h"

static const char *TAG = "telemetry";

#define TELEMETRY_TASK_PRIO   2
#define TELEMETRY_TASK_CORE   1
#define TELEMETRY_TASK_STACK  3072

static void telemetry_task(void *arg)
{
    (void)arg;

    TickType_t last_wake = xTaskGetTickCount();
    char buf[128];
    telemetry_validity_t gate = {0};

    ESP_LOGI(TAG, "STATE 流任务已启动：%d Hz，优先级 %d，CPU%d",
             TELEMETRY_RATE_HZ, TELEMETRY_TASK_PRIO, TELEMETRY_TASK_CORE);

    bool wdt_ok = (esp_task_wdt_add(NULL) == ESP_OK);
    if (!wdt_ok) {
        ESP_LOGW(TAG, "任务看门狗订阅失败——组帧任务不受监控");
    }

    for (;;) {
        /* The supervisor only enqueues; UART formatting is off its control path. */
        cartfsm_step_loss_notice_t notice;
        if (cartfsm_take_step_loss_notice(&notice)) {
            int event_n = snprintf(buf, sizeof(buf),
                "EVENT STEP_LOSS %" PRIu32 " %" PRIu32 " %" PRId64 "\n",
                notice.event_id, notice.run_id, notice.device_us);
            if (event_n > 0 && event_n < (int)sizeof(buf))
                cartproto_send_raw(buf, event_n);
        }
        cartpos_measurement_t cart = {0};
        poleang_measurement_t pole = {0};
        bool cart_valid = cartpos_get_measurement(&cart);
        bool pole_valid = poleang_get_measurement(&pole);
        int n = telemetry_format_measurement(buf, sizeof(buf), &gate, esp_timer_get_time(),
            cart_valid, pole_valid, cart.x_um, pole.theta_urad, cart.vx_mm_s, pole.vth_mrad_s);
        if (n > 0) {
            cartproto_send_raw(buf, n);
        } else if (n < 0) {
            ESP_LOGE(TAG, "组帧失败（n=%d）——帧被丢弃", n);
        }

        if (wdt_ok) {
            esp_task_wdt_reset();
        }
        vTaskDelayUntil(&last_wake, TELEMETRY_PERIOD_TICKS);
    }
}

esp_err_t telemetry_start(void)
{
    BaseType_t ok = xTaskCreatePinnedToCore(telemetry_task, "telemetry",
                                            TELEMETRY_TASK_STACK, NULL,
                                            TELEMETRY_TASK_PRIO, NULL,
                                            TELEMETRY_TASK_CORE);
    if (ok != pdPASS) {
        ESP_LOGE(TAG, "创建组帧任务失败");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
