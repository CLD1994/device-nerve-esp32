# 固件结构与数据所有权

本文说明当前主线的组件边界，替代历史实施规格中的架构说明，不包含新的开发计划。具体命令见[协议](../protocol.md)，接线与供电见[硬件](../hardware.md)，采样口径见[编码器采样](../encoder-sampling.md)。接口与配置的最终依据是同版本源码。

## 组装与数据流

[main/app_main.c](../../main/app_main.c) 是正式固件的组装入口：先由 `bsp_early_init()` 禁用电机，再初始化参数和 BSP；分别创建小车、摆角的 MT6835 实例，绑定解释层；创建 TMC2209 电机实例并绑定直线轴；启动异步供电验证、协议、状态机和遥测。测试固件由 `test/` 单独组装，不编入正式启动流程。

```text
BSP 注入总线/引脚
  ├─ MT6835 帧读取 → magnetic_encoder 实例快照
  │                    ├─ cartpos：小车位置、速度与参考
  │                    └─ poleang：摆角、角速度与角度标定
  └─ TMC2209 + step_engine → motor：steps 域
                               ↑
                    cartaxis：机械单位换算
                               ↑
UART 协议 → cartfsm：命令、模式与监督 ← cartpower 缓存
                ↓                         ↑
      telemetry：状态与可选事件        低频 I2C/ADC 任务
```

当前台位是两个 MT6835 实例，各自使用独立 SPI 主机；AS5600 驱动仍可作为实现存在，但不是当前 `app_main` 的小车编码器。协议使用 UART0、TMC 使用 UART2、日志默认使用原生 USB。具体引脚、波特率和配置入口统一见硬件文档，不在此另设一份参数表。

## 原生单位与解释层

| 层 | 职责与权威来源 | 不应混入的语义 |
|---|---|---|
| 器件帧驱动 | [MT6835 帧层](../../components/mt6835/mt6835_hw.c)与[协议参考](mt6835.md)负责 SPI、帧和 CRC；TMC 帧层负责 UART 寄存器事务 | 小车标定、轨道长度、运动策略 |
| 编码器类别 | [magnetic_encoder.h](../../components/magnetic_encoder/include/magnetic_encoder.h)：句柄和操作表分发，单圈/累计 counts、时间戳、序列、有效性与速度窗 | mm、µrad 与机械零点 |
| 编码器解释 | [cartpos](../../components/cartpos/include/cartpos.h)与[poleang](../../components/poleang/include/poleang.h)：物理单位、方向、参考和角度变换 | 芯片总线配置、STEP 生成 |
| 电机类别 | [motor.h](../../components/motor/include/motor.h)：steps 域接口，TMC 驱动与步进引擎组合实现 | 轨道机械比例、摆杆物理状态 |
| 直线轴解释 | [cartaxis](../../components/cartaxis/cartaxis.c)：mm/µm 与 steps 换算、X_INV、细分重定基 | 将软件 STEP 位置冒充真实运动 |
| 业务监督 | [cartfsm](../../components/cartfsm/cartfsm.c)：模式、命令门、标定与运动监督 | 在高频路径进行诊断文本格式化或额外 SPI/I2C 读取 |

类别实例通过句柄区分。编码器采样的 `valid` 只表示曾有成功值，不等于当前新鲜；`last_attempt_ok`、时间戳、连续性序列、速度有效性必须按消费场景一起解释。完整判据见采样文档。软件累计 STEP 与编码器位置是不同来源，二者差值不是物理脉冲或机械失步的直接证据。

## 参数和换算的单一权威

- `settings` 保存底层设备/机械设置；`cartparams` 的注册表是业务参数名与索引的权威。不同参数的持久化和生效规则以[标定指南](../calibration.md)及协议为准，不把一次实验读回当默认配置。
- `cartaxis` 使用**已写入芯片的细分档**计算 steps/mm，而非盲目使用先提交的设置值。静止时更新细分并重定基；运动中先挂起、待停稳应用；写失败保持旧档及换算，避免软件坐标跳变。
- 电流设置由组装点订阅并转交电机接口。请求电流、寄存器写入成功、真实相电流和扭矩不是同一份证据。
- 引脚归 BSP；驱动通过配置注入外设信息。历史规格中的具体单例 API、AS5600 组装和采样频率不能覆盖现行实现。

## 监督与可选诊断

[cartpower](../../components/cartpower/cartpower.c) 的低频任务处理 I2C/ADC，纯核心判断有效性，状态机读取缓存，避免把供电总线事务放进运动监督。供电验证不等于硬件耐压或停止距离认证；完整状态和恢复约束见硬件文档。

STEP_LOSS 的**判定、事件、轨迹和处置**分别配置，默认值以 [cartfsm/Kconfig](../../components/cartfsm/Kconfig) 为准：

- 连续增长窗口是可选判定，不等于取消误差检测；关闭时沿用立即阈值判定。
- 事件通知不要求开启轨迹；轨迹诊断保存软件快照，停稳后读取，不证明驱动脚或真实机械运动。
- observe-only 显式放弃由固件因 STEP_LOSS 停车，保留该时刻控制目标并由上位机处置；并不取消供电、编码器失效、软限位和命令看门狗。
- 事件没有 ACK 或重放保证，不可当作可靠停机通道。正式配置和诊断配置不能混为一谈。

事件与轨迹的字段、开关组合、读取前提见[丢步诊断](../step-loss-diagnostic.md)。任何采样率、监督周期、命令频率及硬件脉冲频率都属于不同层，不因其中一项配置而自动相等。

## 验证边界

当前验证方法见[测试指南](../../test/README.md)。历史重构的构建、宿主测试与未验证项保存在[实施验证归档](../archive/implementation-validation.md)，原始台架报告见归档。旧提交上的编译通过、宿主模拟和用户现场运行分别回答不同问题，不能互相替代，也不能用于宣称当前提交全部硬件验收通过。
