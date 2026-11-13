# TMC2209 最小只读诊断

保持 `DISABLED`，Windows 运行：

```powershell
python tools/tmc_readonly.py --port COM11 --baud 460800
```

只发送 `TMC?`。READY、FAULT（即使已停稳）均拒绝；不会自动禁用、配置、写寄存器、使能或运动。禁用状态下持有使能与输出互斥锁完成 UART 读取，释放后输出。不要在实时采样或运动路径调用。应答校验 CRC、0x05同步字节、0xff主机地址、匹配的寄存器和完整请求回声。

协议逐行 `TMC1 NAME VALID RAW BEGIN_US END_US`，结束 `TMC1 END`。VALID=0时RAW=0只是占位，工具转换为null，不可作为有效值解码。五项独立读取，非原子/非同步；时标是软件UART调用包络。查询的是当前静止配置/状态，不能回溯STEP_LOSS瞬间。没有自动重试或为验证写入重写配置。

- GCONF (0x00)：bit0 I_SCALE_ANALOG、bit1 INTERNAL_RSENSE 应与设计相符（当前均0）；bit2 EN_SPREADCYCLE、bit6 PDN_DISABLE、bit7 MSTEP_REG_SELECT。当前设计期望0xc4。
- CHOPCONF (0x6c)：MRES bits24..27，0..8分别为256..1细分；其他值无效。bit28 INTPOL不改变外部STEP细分，bit29 DEDGE、bit17 VSENSE、bits0..3 TOFF也需核对。
- IFCNT (0x02)：低8位写帧受理计数，模256回绕。单次读值不能证明过去具体写入；即使观察到增量也只能证明写帧受理，不能单独证明电流值。
- IOIN (0x06)：包含芯片版本与当前引脚状态。
- DRV_STATUS (0x6f)：温度/短路/静止等状态与CS_ACTUAL。禁用/保持状态不能证明运行时电流。

`IHOLD_IRUN`只写不可读，不请求此寄存器。软件请求电流不等于读回或测得相电流。现场已确认Rsense=0.11Ω；电流换算仍需结合VSENSE、模式及实际测量。写接口不通过 IFCNT 验证事务，因此初始化成功日志不能替代芯片读回验证。

工具不调用flush；接收期限从write返回后计，不保证整个程序硬时限。UART读取可能阻塞，门禁只在禁用态允许，因此不会在运行态阻挡运动停机监督。静止查询不能用于判定运动中的故障原因。

## 默认电流与保存值

默认运行电流为 1500 mA RMS，保持电流为 400 mA RMS；权威定义见
[settings 参数表](../components/settings/settings.c)。启动先读取 NVS `cart` 中的保存值，
缺失或非法值按 settings 规则回落默认。有效的旧 800/400 mA 保存值继续生效，
升级不会通过条件判断自动改写它，也不擦除标定。显式修改使用 `settings_set(SET_RUN_MA, ...)`
及其既有持久化路径；串口 `CONFIG` 的运动参数表不包含运行电流，不要把 `ACC_MAX` 当作电流设置。

运行与保持电流共用同一个 VSENSE，保持电流必须按运行电流选择的量程编码。
在 Rsense=0.11 Ω 时，1500/400 mA 请求对应 VSENSE=0、IRUN=26、IHOLD=6，
理想换算约为 1492/387 mA。这是量化请求，不是实际相电流测量，日志也不证明写入成功。

当前电机铭牌额定 0.9 A/相，默认 1.5 A 是针对本设备选择的超额定实验设置；
已有短时运动记录不能证明长期温升、寿命或所有负载下稳定。更换电机、驱动板或采样
电阻后需重新核对电流与散热。默认仍上电禁用，不自动运动。

## 宿主检查

```bash
bash host_tests/test_tmc.sh
```

测试通过 UART、时钟、寄存器和任务边界注入替身，以独立编译的生产模块验证公开接口。
覆盖电流量程与编码、禁用态查询、运行态拒绝，以及 UART 短帧、回声不符、发送超时、
错误响应身份和 CRC。失败读回必须保留调用者原有输出值。它们只验证软件行为，
不证明 ESP-IDF 目标编译、实际电流或热稳定。settings 默认值断言位于组件 Unity 测试，
需目标测试镜像单独执行。
