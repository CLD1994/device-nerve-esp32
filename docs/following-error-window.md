# 实验性跟随误差窗口判定

编码器位置 E 与实际已发 STEP 软件累计位置 C 的差 e=E−C 是跟随误差，不是电机物理丢步的直接证明。C 仅在 ENABLE 时与 E 对齐，运行中不重置。编码器健康检查、真实位置软限位以及原有 FAULT 减速停车路径不变。

## 行为

默认关闭实验模式，保持原来的 `|e| > STEP_LOSS_UM` 单拍停车。开启后：

- 每拍 `|e| >= HARD_UM` 立即进入 STEP_LOSS；与软门限独立。
- 非重叠观察窗口比较首尾 `|e|`，每窗向外增长达到 GROWTH_UM 才累计一次；不增长、回落或增长不足则清连续计数。
- 连续增长达到 WINDOWS 且当前 `|e| > STEP_LOSS_UM` 时停车。监督调度延后时，增长门限按实际窗长同比增加。
- 一次偏差跳到 3.3 mm 后保持稳定，在默认 6 mm 硬限内不会因持续偏置本身停车；持续缓慢偏离即使未满足增长条件，仍会触发硬限。窗口内先增后减可能被端点比较抵消，但硬限每拍仍检查。
- 每次 ENABLE 建立新观察窗口。RESET 不清除已经锁存的故障诊断。

## 启用与参数

在 `idf.py menuconfig` 的 `Component config → cartfsm - 模式机` 中启用窗口判定。项目配置为：

```text
CONFIG_CARTFSM_FOLLOWING_ERROR_WINDOW=y
CONFIG_CARTFSM_FOLLOWING_ERROR_HARD_UM=6000
CONFIG_CARTFSM_FOLLOWING_ERROR_WINDOW_MS=50
CONFIG_CARTFSM_FOLLOWING_ERROR_GROWTH_UM=1000
CONFIG_CARTFSM_FOLLOWING_ERROR_WINDOWS=2
CONFIG_CARTFSM_STEP_LOSS_DIAGNOSTICS=y
```

运行时 `STEP_LOSS_UM` 仍是总偏差软门限；建议本次保留 3000。若软门限不小于硬限，软路径会被硬限覆盖。连续窗口判定默认至少约 100 ms，窗口相位可能延长；高速堵转主要依靠硬限。有限偏差若形成过程跨两个窗口且每窗增长达标，仍可能触发软停车。上述数值是现场联调起点，不是已验证安全值，也不保证不会发生碰撞或失稳。6 mm 是触发时误差，不包含随后减速行程。固件不做速度闭环补偿；容忍有限误差不代表机械执行恢复正常。时间窗方法不补偿采样年龄，也不能区分传动打滑、比例误差与电机失步。

执行 `idf.py build` 后由操作者烧录。保持有人监督，先无外力运行，再逐步增加扰动。不要仅因本次没有故障就断言机械问题已解决。回退只需关闭窗口选项并重新构建烧录。

## 诊断

使用同分支 `tools/step_loss_capture.py`，兼容 VERSION 1，新增 VERSION 2：TRIGGER=1 表示原始累计硬限，2 表示连续增长，3 表示传统单拍。HARD_UM 为硬限；GROWTH_UM、WINDOW_US 为最近完成窗口的实际增长及长度；GROWING_WINDOWS 为连续增长数。硬限可发生于窗口中间，因此这些窗口字段不代表硬限触发瞬间。旧脚本不支持 VERSION 2，需一并更新。

## 验证边界

2026-11-15：在 Linux 主机编译执行纯 C 判定断言并核对 Python 新旧诊断解析；未做目标 ESP-IDF 构建、未操作设备，也未验证现场停止距离或稳定性。没有新增测试套件。
