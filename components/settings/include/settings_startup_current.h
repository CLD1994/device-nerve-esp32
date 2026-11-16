#pragma once
#include "settings.h"

/**
 * 仅启动组装阶段，在 settings_init 后、设备及订阅初始化前调用。
 * enabled=false 无副作用；开启时仅修改运行电流请求并持久保存，保持电流不变。
 * 返回值仅证明 settings/NVS 处理结果，不证明芯片接收或真实相电流。
 */
settings_status_t settings_apply_startup_run_current(bool enabled, int target_ma);
