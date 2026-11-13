# TMC2209 最小只读诊断（实验）

保持 `DISABLED`，Windows 运行：

```powershell
python tools/tmc_readonly.py --port COM11 --baud 460800
```

只发送 `TMC?`。READY、FAULT（即使已停稳）均拒绝；不会自动禁用、配置、写寄存器、使能或运动。禁用状态下持有既有 ENABLE/output 互斥门禁完成 UART 读取，释放后输出。不要在实时采样或运动路径调用。应答校验 CRC、0x05同步字节、0xff主机地址、匹配的寄存器和完整请求回声。

协议逐行 `TMC1 NAME VALID RAW BEGIN_US END_US`，结束 `TMC1 END`。VALID=0时RAW=0只是占位，工具转换为null，不可作为有效值解码。五项独立读取，非原子/非同步；时标是软件UART调用包络。查询的是当前静止配置/状态，不能回溯STEP_LOSS瞬间。没有自动重试或为验证写入重写配置。

- GCONF (0x00)：bit0 I_SCALE_ANALOG、bit1 INTERNAL_RSENSE 应与设计相符（当前均0）；bit2 EN_SPREADCYCLE、bit6 PDN_DISABLE、bit7 MSTEP_REG_SELECT。当前设计期望0xc4。
- CHOPCONF (0x6c)：MRES bits24..27，0..8分别为256..1细分；其他值无效。bit28 INTPOL不改变外部STEP细分，bit29 DEDGE、bit17 VSENSE、bits0..3 TOFF也需核对。
- IFCNT (0x02)：低8位写帧受理计数，模256回绕。单次读值不能证明过去具体写入；即使观察到增量也只能证明写帧受理，不能单独证明电流值。
- IOIN (0x06)：包含芯片版本与当前引脚状态。
- DRV_STATUS (0x6f)：温度/短路/静止等状态与CS_ACTUAL。禁用/保持状态不能证明运行时电流。

`IHOLD_IRUN`只写不可读，不请求此寄存器。软件期望800/400mA不等于读回或测得相电流。现场已确认Rsense=0.11Ω；电流换算仍需结合VSENSE、模式及实际测量。低层写接口目前未增设IFCNT事务验证，本改动不把软件“已生效”日志升级为芯片验证结论。

工具不调用flush；接收期限从write返回后计，不保证整个程序硬时限。UART读取可能阻塞，门禁只在禁用态允许，因此不会在运行态阻挡运动停机监督。尚需真机确认响应兼容性；无真机成功承诺。
