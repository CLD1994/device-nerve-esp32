/*
 * Step Engine — GPTimer ISR 速度模式实现
 *
 * 模型（vel_ramp 纯函数，契约级）：每发出一步后更新速度再排下一拍。
 * 目标由任务上下文（cartfsm）写入，ISR 读取；64 位目标写入与 ISR
 * 读取经 s_spinlock 互斥（跨核），避免 32 位总线上撕裂读。
 *
 * 定时器：1 MHz、one-shot alarm。计数自由运行，alarm 目标按
 * 「上一次报警值 + dt」相对排布，带延迟保护下限；超过
 * MAX_ALARM_US 的间隔拆成链式等待。静止起步（vel_target 发现
 * 定时器停止）用冻结计数种子法排第一拍（dt0，换向时含 DIR setup）。
 *
 * STEP 脉冲：HIGH → 1 µs → LOW。DIR 换向先置 DIR，第一拍 dt 加
 * 2 µs setup（不在 ISR 里忙等，由定时时间保证建立时间）。
 *
 * 位置计数：DIR 高 = 正。32 位对齐写，任务上下文原子读。
 */

#include "step_engine.h"
#include "vel_ramp.h"

#include <string.h>

#include "esp_log.h"
#include "driver/gpio.h"
#include "driver/gptimer.h"
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
#include "driver/pulse_cnt.h"
#include "esp_timer.h"
#endif
#include "esp_rom_sys.h"
#include "esp_cpu.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "step_engine";

/* ================================================================
 * 配置常量
 * ================================================================ */

#define TIMER_RESOLUTION_HZ  1000000  /* 1 MHz → 1 µs/tick */

/* 单次 alarm 上限（µs），超过走链式等待 */
#define MAX_ALARM_US      60000

/* ISR 入口锁存的计数与下一 alarm 目标之间的最小余量（µs） */
#define ALARM_GUARD_US    5

/* 上电默认加速度（steps/s²）；cartfsm 启动后按注册表覆盖 */
#define DEFAULT_ACCEL     4000

/* ================================================================
 * 内部状态
 * ================================================================ */

/* GPIO 引脚 */
static int s_step_gpio = -1;
static int s_dir_gpio  = -1;

/* 最近一次输出的 DIR 电平（换向 setup 检测用） */
static bool s_last_out_dir = false;

/* ---- 速度模式状态 ----
 * 任务写 / ISR 读：s_target_q16、s_target_dir、s_accel、s_decel、
 * s_wdt_us、s_last_kick_us（经 s_spinlock）。
 * ISR 单写：s_v_q16、s_dir、s_stopped、s_chain_remaining_us
 * （vel_target 的静止启动路径也在持锁下写，此时定时器停止、
 * 无 ISR 并发）。 */
static volatile uint64_t s_target_q16 = 0;   /* 目标速率幅值 */
static volatile bool     s_target_dir = true;
static uint64_t s_v_q16 = 0;                 /* 最近一步速率幅值 */
static bool     s_dir = false;               /* 当前运动方向 */
static uint32_t s_accel = DEFAULT_ACCEL;     /* steps/s² */
static uint32_t s_decel = DEFAULT_ACCEL;
static uint32_t s_wdt_us = 0;                /* 0 = 看门狗关闭 */
static volatile uint64_t s_last_kick_us = 0; /* 最近喂狗时刻（µs 域） */
/* 上电以来的饱和诊断计数，受 s_spinlock 保护。
 * expired 统计判定次数，不是独立看门狗事件数。 */
static uint32_t s_wdt_stale_time_count;
static uint32_t s_wdt_expired_count;

/* 位置计数（带符号累计） */
static volatile int32_t s_position = 0;

/* 停止标志（ISR 首先检查） */
static volatile bool s_stopped = true;

/* 定时器 */
static gptimer_handle_t s_timer = NULL;
static volatile bool s_timer_running = false;

/* 链式等待剩余（µs） */
static uint32_t s_chain_remaining_us = 0;

/* alarm 排布基准（每次报警 ISR 刷新） */
static uint64_t s_cb_alarm_base = 0;
static uint64_t s_cb_guard_floor = 0;

/* 自旋锁：任务上下文函数与 ISR 的互斥 */
static portMUX_TYPE s_spinlock = portMUX_INITIALIZER_UNLOCKED;

static bool s_initialized = false;

#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
/* 只观察现有输出；不改变 STEP/DIR/EN 输出模式或运动控制。PCNT 原点
 * 独立于软件位置重定基，使用相邻采样差值比较，不比较绝对位置。 */
#define DIAG_EN_GPIO 21
#define PCNT_DIAG_LIMIT 30000
#define PCNT_DIAG_LIFETIME_US (3600LL * 1000000)
static pcnt_unit_handle_t s_pcnt_unit;
static pcnt_channel_handle_t s_pcnt_channel;
static esp_err_t s_pcnt_init_error = ESP_ERR_INVALID_STATE;
static esp_err_t s_en_read_error = ESP_ERR_INVALID_STATE;
static bool s_pcnt_overflow_invalid;
static bool s_pcnt_started;
static int64_t s_pcnt_start_us;

static void step_diag_init(void)
{
    /* input_enable 保留已有 output_enable；禁止 gpio_config 重配输出。 */
    s_en_read_error = gpio_input_enable((gpio_num_t)DIAG_EN_GPIO);
    pcnt_unit_config_t unit_cfg = {
        .low_limit = -PCNT_DIAG_LIMIT,
        .high_limit = PCNT_DIAG_LIMIT,
        .flags = { .accum_count = true },
    };
    pcnt_chan_config_t channel_cfg = {
        .edge_gpio_num = s_step_gpio,
        .level_gpio_num = s_dir_gpio,
    };
    bool enabled = false;
    esp_err_t err = pcnt_new_unit(&unit_cfg, &s_pcnt_unit);
    if (err != ESP_OK) goto failed;
    err = pcnt_new_channel(s_pcnt_unit, &channel_cfg, &s_pcnt_channel);
    if (err != ESP_OK) goto failed;
    /* 上升沿 +1，下降沿不计；DIR 高保持，低反向。不开毛刺滤波。 */
    err = pcnt_channel_set_edge_action(s_pcnt_channel,
                                      PCNT_CHANNEL_EDGE_ACTION_INCREASE,
                                      PCNT_CHANNEL_EDGE_ACTION_HOLD);
    if (err != ESP_OK) goto failed;
    err = pcnt_channel_set_level_action(s_pcnt_channel,
                                       PCNT_CHANNEL_LEVEL_ACTION_KEEP,
                                       PCNT_CHANNEL_LEVEL_ACTION_INVERSE);
    if (err != ESP_OK) goto failed;
    err = pcnt_unit_add_watch_point(s_pcnt_unit, -PCNT_DIAG_LIMIT);
    if (err != ESP_OK) goto failed;
    err = pcnt_unit_add_watch_point(s_pcnt_unit, PCNT_DIAG_LIMIT);
    if (err != ESP_OK) goto failed;
    err = pcnt_unit_clear_count(s_pcnt_unit);
    if (err != ESP_OK) goto failed;
    err = pcnt_unit_enable(s_pcnt_unit);
    if (err != ESP_OK) goto failed;
    enabled = true;
    s_pcnt_start_us = esp_timer_get_time();
    err = pcnt_unit_start(s_pcnt_unit);
    if (err != ESP_OK) goto failed;
    s_pcnt_started = true;
    s_pcnt_init_error = ESP_OK;
    return;
failed:
    s_pcnt_init_error = err;
    if (enabled) (void)pcnt_unit_disable(s_pcnt_unit);
    if (s_pcnt_channel) {
        (void)pcnt_del_channel(s_pcnt_channel);
        s_pcnt_channel = NULL;
    }
    if (s_pcnt_unit) {
        (void)pcnt_del_unit(s_pcnt_unit);
        s_pcnt_unit = NULL;
    }
    ESP_LOGW(TAG, "PCNT 诊断初始化失败: %d，运动控制保持原行为", (int)err);
}

/* 由监督任务采样。PCNT 读取与软件计数、编码器并非同时采样；时间括号
 * 只包围本次 PCNT/EN 读取，不证明电机驱动器端的波形或机械运动。 */
static void step_diag_read(step_engine_diag_t *out)
{
    out->pcnt_begin_us = esp_timer_get_time();
    out->pcnt_init_error = s_pcnt_init_error;
    out->pcnt_read_error = ESP_ERR_INVALID_STATE;
    out->pcnt_count = 0;
    out->pcnt_valid = false;
    out->en_read_error = s_en_read_error;
    out->en_level = s_en_read_error == ESP_OK
                  ? gpio_get_level((gpio_num_t)DIAG_EN_GPIO) : -1;
    /* 按最高 50 kHz 连续单向输入，一小时最多 1.8 亿脉冲，远小于
     * int32 上限。寿命到期即永久失效，不允许回绕后的值重新变有效。
     * 这依赖既有输入频率上限；外部任意高频/长时间停止采样不在证明内。 */
    if (s_pcnt_init_error == ESP_OK && !s_pcnt_overflow_invalid) {
        int64_t age = out->pcnt_begin_us - s_pcnt_start_us;
        if (age < 0 || age >= PCNT_DIAG_LIFETIME_US) {
            s_pcnt_overflow_invalid = true;
        } else {
            int count = 0;
            out->pcnt_read_error = pcnt_unit_get_count(s_pcnt_unit, &count);
            if (out->pcnt_read_error == ESP_OK) {
                out->pcnt_count = count;
                if (count >= INT32_MAX / 2 || count <= -(INT32_MAX / 2))
                    s_pcnt_overflow_invalid = true;
                else
                    out->pcnt_valid = true;
            }
        }
    }
    if (s_pcnt_overflow_invalid && s_pcnt_started) {
        esp_err_t err = pcnt_unit_stop(s_pcnt_unit);
        if (err == ESP_OK) s_pcnt_started = false;
        else out->pcnt_read_error = err;
    }
    out->pcnt_overflow_invalid = s_pcnt_overflow_invalid;
    out->pcnt_end_us = esp_timer_get_time();
}
#endif


/* ================================================================
 * 自测钩子（仅 CONFIG_STEP_ENGINE_TEST_HOOKS=y）
 * ================================================================ */

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
static uint32_t *s_sample_buf = NULL;
static int       s_sample_max = 0;
static volatile int *s_sample_count = NULL;
static uint32_t  s_last_alarm_ccount = 0;

static volatile uint32_t s_max_isr_cycles = 0;
/* 分段计时（诊断 ISR 主体耗时归因）：脉冲 / 递推 / 排下一拍 */
static volatile uint32_t s_max_cyc_pulse = 0;
static volatile uint32_t s_max_cyc_ramp = 0;
static volatile uint32_t s_max_cyc_alarm = 0;
/* 分段累计与计数：求均值（典型耗时决定可持续步频上限，
 * 最大值只反映离群值——缓存未命中/跨核竞争） */
static volatile uint64_t s_sum_cyc_pulse = 0;
static volatile uint64_t s_sum_cyc_ramp = 0;
static volatile uint64_t s_sum_cyc_alarm = 0;
static volatile uint32_t s_isr_pulse_count = 0;
#endif /* CONFIG_STEP_ENGINE_TEST_HOOKS */

/* ================================================================
 * 辅助：方向输出
 * ================================================================ */

static inline void set_dir_physical(bool logical_dir)
{
    gpio_set_level((gpio_num_t)s_dir_gpio, logical_dir ? 1 : 0);
    s_last_out_dir = logical_dir;
}

/* ================================================================
 * alarm 排布（ISR 与静止启动路径共用）
 * ================================================================ */

/* 在 (base + dt) 排一次性 alarm，绝不早于 floor。纯寄存器排布，
 * 不碰链式状态。 */
static void arm_alarm(uint64_t base, uint64_t floor, uint32_t dt_us)
{
    uint64_t target = base + dt_us;
    if (target < floor) {
        target = floor;
    }

    gptimer_alarm_config_t alarm_cfg = {
        .alarm_count = target,
        .flags = { .auto_reload_on_alarm = false },
    };
    gptimer_set_alarm_action(s_timer, &alarm_cfg);
    gptimer_start(s_timer);  /* 已在运行则为空操作 */
    s_timer_running = true;
}

/* 相对刚触发的报警排下一拍；超过 MAX_ALARM_US 拆链。 */
static void isr_set_alarm(uint32_t dt_us)
{
    if (dt_us > MAX_ALARM_US) {
        s_chain_remaining_us = dt_us - MAX_ALARM_US;
        arm_alarm(s_cb_alarm_base, s_cb_guard_floor, MAX_ALARM_US);
    } else {
        s_chain_remaining_us = 0;
        arm_alarm(s_cb_alarm_base, s_cb_guard_floor, dt_us);
    }
}

/* ================================================================
 * GPTimer alarm ISR
 * ================================================================ */

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
/* 分段计时更新（ISR 发步出口调用一次；max 段与 sum 段口径同旧：
 * total=now-start，pulse=pulse_end-start，ramp=ramp_end-pulse_end，
 * alarm=now-ramp_end）。 */
static inline void record_isr_timings(uint32_t start, uint32_t pulse_end,
                                      uint32_t ramp_end, uint32_t now)
{
    uint32_t total = now - start;
    if (total > s_max_isr_cycles) {
        s_max_isr_cycles = total;
    }
    uint32_t pulse = pulse_end - start;
    if (pulse > s_max_cyc_pulse) {
        s_max_cyc_pulse = pulse;
    }
    uint32_t ramp = ramp_end - pulse_end;
    if (ramp > s_max_cyc_ramp) {
        s_max_cyc_ramp = ramp;
    }
    uint32_t alarm = now - ramp_end;
    if (alarm > s_max_cyc_alarm) {
        s_max_cyc_alarm = alarm;
    }
    s_sum_cyc_pulse += pulse;
    s_sum_cyc_ramp += ramp;
    s_sum_cyc_alarm += alarm;
    s_isr_pulse_count++;
}
#endif /* CONFIG_STEP_ENGINE_TEST_HOOKS */

static bool gptimer_alarm_cb(gptimer_handle_t timer,
                             const gptimer_alarm_event_data_t *edata,
                             void *user_ctx)
{
    (void)timer;
    (void)user_ctx;

    s_cb_alarm_base = edata->alarm_value;
    s_cb_guard_floor = edata->count_value + ALARM_GUARD_US;

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
    uint32_t isr_start_ccount = esp_cpu_get_cycle_count();
#endif

    /* 停止标志最优先 */
    if (s_stopped) {
        gptimer_stop(s_timer);
        s_timer_running = false;
        return false;
    }

    /* 链式等待：本次 alarm 不发步，续排下一块（不发步不进分段统计，
     * 只更新整段最大值，口径同旧） */
    if (s_chain_remaining_us > 0) {
        uint32_t chunk = (s_chain_remaining_us > MAX_ALARM_US)
                       ? MAX_ALARM_US : s_chain_remaining_us;
        s_chain_remaining_us -= chunk;
        arm_alarm(s_cb_alarm_base, s_cb_guard_floor, chunk);
#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
        uint32_t cend = esp_cpu_get_cycle_count();
        if (cend - isr_start_ccount > s_max_isr_cycles) {
            s_max_isr_cycles = cend - isr_start_ccount;
        }
#endif
        return false;
    }

    /* ---- 发 STEP 脉冲 ---- */
    gpio_set_level((gpio_num_t)s_step_gpio, 1);
    esp_rom_delay_us(1);
    gpio_set_level((gpio_num_t)s_step_gpio, 0);

    /* 位置计数（DIR 高 = 正） */
    if (s_dir) {
        s_position++;
    } else {
        s_position--;
    }

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
    if (s_sample_buf && s_sample_count && *s_sample_count < s_sample_max) {
        uint32_t now = esp_cpu_get_cycle_count();
        if (s_last_alarm_ccount != 0) {
            s_sample_buf[*s_sample_count] = (now - s_last_alarm_ccount) / 240;
            (*s_sample_count)++;
        }
        s_last_alarm_ccount = now;
    }
    uint32_t cyc_pulse_end = esp_cpu_get_cycle_count();
#endif

    /* ---- 递推下一拍（持锁读共享目标，防 64 位撕裂读） ---- */
    uint64_t nv;
    uint32_t dt;
    bool     dchg;
    bool     moving;

    portENTER_CRITICAL_ISR(&s_spinlock);
    /* edata 在取得本锁之前已捕获，其间接受的新目标可能带来更新的喂狗
     * 时间戳。禁止无符号相减下溢产生假超时；本次判定把更新的喂狗
     * 时间戳按经过时间为零处理。 */
    bool wdt_stale_time = (s_wdt_us > 0)
                       && (edata->count_value < s_last_kick_us);
    bool wdt_expired = (s_wdt_us > 0) && !wdt_stale_time
                    && (edata->count_value - s_last_kick_us > s_wdt_us);
    if (wdt_stale_time && s_wdt_stale_time_count != UINT32_MAX)
        ++s_wdt_stale_time_count;
    if (wdt_expired && s_wdt_expired_count != UINT32_MAX)
        ++s_wdt_expired_count;
    moving = vel_ramp_next(s_v_q16, s_dir, s_target_q16, s_target_dir,
                           s_accel, s_decel, wdt_expired,
                           &nv, &dt, &dchg);
    if (dchg) {
        s_dir = !s_dir;
        set_dir_physical(s_dir);
        dt += 2;   /* DIR setup 2 µs，并入第一拍间隔 */
    }
    s_v_q16 = nv;
    if (!moving) {
        /* 停表标志并入持锁段：与 vel_target 的静止启动判定互斥，
         * 避免「目标非零但引擎自停」的竞态窗口 */
        s_stopped = true;
    }
    portEXIT_CRITICAL_ISR(&s_spinlock);

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
    uint32_t cyc_ramp_end = esp_cpu_get_cycle_count();
#endif

    if (!moving) {
        /* 到零速且无换向目标：停表（模式语义由 cartfsm 负责） */
        gptimer_stop(s_timer);
        s_timer_running = false;
#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
        record_isr_timings(isr_start_ccount, cyc_pulse_end,
                           cyc_ramp_end, esp_cpu_get_cycle_count());
#endif
        return false;
    }

    isr_set_alarm(dt);

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS
    record_isr_timings(isr_start_ccount, cyc_pulse_end,
                       cyc_ramp_end, esp_cpu_get_cycle_count());
#endif

    return false;
}

/* ================================================================
 * 公开 API
 * ================================================================ */

esp_err_t step_engine_init(int step_gpio, int dir_gpio)
{
    if (s_initialized) {
        ESP_LOGW(TAG, "step_engine 已初始化，跳过");
        return ESP_OK;
    }

    s_step_gpio = step_gpio;
    s_dir_gpio  = dir_gpio;

    s_target_q16 = 0;
    s_target_dir = true;
    s_v_q16 = 0;
    s_dir = false;
    s_accel = DEFAULT_ACCEL;
    s_decel = DEFAULT_ACCEL;
    s_wdt_us = 0;
    s_last_kick_us = 0;
    s_wdt_stale_time_count = 0;
    s_wdt_expired_count = 0;
    s_position = 0;
    s_stopped = true;
    s_timer_running = false;
    s_chain_remaining_us = 0;

    gptimer_config_t timer_cfg = {
        .clk_src = GPTIMER_CLK_SRC_DEFAULT,
        .direction = GPTIMER_COUNT_UP,
        .resolution_hz = TIMER_RESOLUTION_HZ,
    };
    esp_err_t err = gptimer_new_timer(&timer_cfg, &s_timer);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "gptimer_new_timer 失败：%s", esp_err_to_name(err));
        return err;
    }

    gptimer_event_callbacks_t cbs = {
        .on_alarm = gptimer_alarm_cb,
    };
    err = gptimer_register_event_callbacks(s_timer, &cbs, NULL);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "gptimer_register_event_callbacks 失败：%s", esp_err_to_name(err));
        return err;
    }

    err = gptimer_enable(s_timer);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "gptimer_enable 失败：%s", esp_err_to_name(err));
        return err;
    }

    ESP_LOGI(TAG, "step engine 已初始化（STEP=GPIO%d，DIR=GPIO%d，定时器 1MHz）",
             step_gpio, dir_gpio);

#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    step_diag_init();
#endif
    s_initialized = true;
    return ESP_OK;
}

void step_engine_vel_set_accel(uint32_t accel_steps_s2)
{
    portENTER_CRITICAL(&s_spinlock);
    s_accel = accel_steps_s2 ? accel_steps_s2 : 1;
    portEXIT_CRITICAL(&s_spinlock);
}

void step_engine_vel_set_decel(uint32_t decel_steps_s2)
{
    portENTER_CRITICAL(&s_spinlock);
    s_decel = decel_steps_s2 ? decel_steps_s2 : 1;
    portEXIT_CRITICAL(&s_spinlock);
}

void step_engine_vel_set_wdt_us(uint32_t wdt_us)
{
    portENTER_CRITICAL(&s_spinlock);
    s_wdt_us = wdt_us;
    portEXIT_CRITICAL(&s_spinlock);
}

void step_engine_vel_target(int64_t v_q16)
{
    const int64_t limit_q16 = (int64_t)STEP_ENGINE_MAX_TARGET_HZ * VEL_RAMP_Q16_ONE;
    if (v_q16 > limit_q16) v_q16 = limit_q16;
    if (v_q16 < -limit_q16) v_q16 = -limit_q16;
    uint64_t mag;
    bool dir;

    if (v_q16 < 0) {
        mag = (uint64_t)(-(v_q16 + 1)) + 1;
        dir = false;
    } else {
        mag = (uint64_t)v_q16;
        dir = true;
    }

    portENTER_CRITICAL(&s_spinlock);

    /* 喂狗：时间戳取定时器原始计数（µs 域，自由运行） */
    uint64_t now = 0;
    gptimer_get_raw_count(s_timer, &now);
    s_last_kick_us = now;

    s_target_q16 = mag;
    s_target_dir = dir;

    if (s_stopped && mag > 0) {
        /* 静止启动：冻结计数种子法排第一拍（此时定时器停止，
         * 原始计数读数即精确基准；无 ISR 并发）。ISR 的停表
         * （gptimer_stop）与本次排布可能交错：释放锁后复查
         * s_stopped，若被 ISR 置回真则重排一次。 */
        for (int retry = 0; retry < 3 && s_stopped; retry++) {
            uint64_t nv;
            uint32_t dt;
            bool     dchg;

            (void)vel_ramp_next(0, s_dir, mag, dir, s_accel, s_decel, false,
                                &nv, &dt, &dchg);
            if (dchg) {
                s_dir = !s_dir;
                set_dir_physical(s_dir);
                dt += 2;   /* DIR setup 并入第一拍 */
            }
            s_v_q16 = nv;
            s_stopped = false;

            uint64_t base = 0;
            gptimer_get_raw_count(s_timer, &base);
            s_cb_alarm_base = base;
            s_cb_guard_floor = base + ALARM_GUARD_US;
            isr_set_alarm(dt);
        }
    }

    portEXIT_CRITICAL(&s_spinlock);
}

void step_engine_vel_halt(void)
{
    portENTER_CRITICAL(&s_spinlock);
    s_target_q16 = 0;
    portEXIT_CRITICAL(&s_spinlock);
}

int64_t step_engine_vel_now_q16(void)
{
    /* 持锁快照：64 位 s_v_q16 在 32 位总线上无锁读可撕裂出假零，
     * 会令 FAULT 停机次序提前关 EN */
    portENTER_CRITICAL(&s_spinlock);
    bool stopped = s_stopped;
    uint64_t v = s_v_q16;
    bool dir = s_dir;
    portEXIT_CRITICAL(&s_spinlock);

    if (stopped || v == 0) {
        return 0;
    }
    return dir ? (int64_t)v : -(int64_t)v;
}

void step_engine_stop(void)
{
    portENTER_CRITICAL(&s_spinlock);

    s_stopped = true;
    s_target_q16 = 0;
    s_v_q16 = 0;

    if (s_timer != NULL && s_timer_running) {
        gptimer_stop(s_timer);
        s_timer_running = false;
    }

    s_chain_remaining_us = 0;

    portEXIT_CRITICAL(&s_spinlock);
}

bool step_engine_try_stop_at_rest(void)
{
    portENTER_CRITICAL(&s_spinlock);
    /* 精确Q16判零与清目标同锁，不能把小于1 step/s的残速舍入为零。
     * 调用方串行化目标提交；自然停稳的ISR已同锁发布零速/停止标志。 */
    if (s_v_q16 != 0) {
        portEXIT_CRITICAL(&s_spinlock);
        return false;
    }
    s_stopped = true;
    s_target_q16 = 0;
    if (s_timer != NULL && s_timer_running) {
        gptimer_stop(s_timer);
        s_timer_running = false;
    }
    s_chain_remaining_us = 0;
    portEXIT_CRITICAL(&s_spinlock);
    return true;
}

void step_engine_diag_snapshot(step_engine_diag_t *out)
{
    if (out == NULL) return;
    portENTER_CRITICAL(&s_spinlock);
    out->v_q16 = s_dir ? (int64_t)s_v_q16 : -(int64_t)s_v_q16;
    out->target_q16 = s_target_dir ? (int64_t)s_target_q16 : -(int64_t)s_target_q16;
    out->position_steps = s_position;
    out->stopped = s_stopped;
    out->timer_running = s_timer_running;
    out->wdt_stale_time_count = s_wdt_stale_time_count;
    out->wdt_expired_count = s_wdt_expired_count;
    portEXIT_CRITICAL(&s_spinlock);
#ifdef CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS
    step_diag_read(out);
#else
    out->pcnt_count = 0;
    out->pcnt_valid = false;
    out->pcnt_init_error = ESP_ERR_NOT_SUPPORTED;
    out->pcnt_read_error = ESP_ERR_NOT_SUPPORTED;
    out->pcnt_overflow_invalid = false;
    out->pcnt_begin_us = out->pcnt_end_us = 0;
    out->en_level = -1;
    out->en_read_error = ESP_ERR_NOT_SUPPORTED;
#endif
}

int32_t step_engine_position_steps(void)
{
    return s_position;
}

void step_engine_set_position(int32_t steps)
{
    /* 调用约定：引擎停止时调用（回零完成路径），无 ISR 竞争；
     * 32 位对齐写本身原子 */
    s_position = steps;
}

/* ================================================================
 * 自测钩子
 * ================================================================ */

#ifdef CONFIG_STEP_ENGINE_TEST_HOOKS

void step_selftest_start_sampling(uint32_t *buf, int max, volatile int *count)
{
    portENTER_CRITICAL(&s_spinlock);
    s_sample_buf = buf;
    s_sample_max = max;
    s_sample_count = count;
    *count = 0;
    s_last_alarm_ccount = 0;
    portEXIT_CRITICAL(&s_spinlock);
}

void step_selftest_stop_sampling(void)
{
    portENTER_CRITICAL(&s_spinlock);
    s_sample_buf = NULL;
    s_sample_count = NULL;
    portEXIT_CRITICAL(&s_spinlock);
}

uint32_t step_selftest_max_isr_cycles(void)
{
    return s_max_isr_cycles;
}

uint32_t step_selftest_max_cycles_pulse(void)
{
    return s_max_cyc_pulse;
}

uint32_t step_selftest_max_cycles_ramp(void)
{
    return s_max_cyc_ramp;
}

uint32_t step_selftest_max_cycles_alarm(void)
{
    return s_max_cyc_alarm;
}

uint32_t step_selftest_avg_cycles_pulse(void)
{
    return s_isr_pulse_count ? (uint32_t)(s_sum_cyc_pulse / s_isr_pulse_count) : 0;
}

uint32_t step_selftest_avg_cycles_ramp(void)
{
    return s_isr_pulse_count ? (uint32_t)(s_sum_cyc_ramp / s_isr_pulse_count) : 0;
}

uint32_t step_selftest_avg_cycles_alarm(void)
{
    return s_isr_pulse_count ? (uint32_t)(s_sum_cyc_alarm / s_isr_pulse_count) : 0;
}

void step_selftest_reset_isr_cycles(void)
{
    s_max_isr_cycles = 0;
    s_max_cyc_pulse = 0;
    s_max_cyc_ramp = 0;
    s_max_cyc_alarm = 0;
    s_sum_cyc_pulse = 0;
    s_sum_cyc_ramp = 0;
    s_sum_cyc_alarm = 0;
    s_isr_pulse_count = 0;
}

#endif /* CONFIG_STEP_ENGINE_TEST_HOOKS */
