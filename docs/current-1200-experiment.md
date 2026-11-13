# 1200 mA RMS 请求实验（非持久、无自动运动）

用户授权现场短时提高运行请求至1200mA，保持400mA保持请求，接受超过电机0.9A铭牌相关损坏风险。此代码不证明温升/电机耐受，不添加自动运动、自动使能或温控保证。

设置来自settings（NVS cart/p3或默认800），不是sdkconfig电流选项。**仅settings为800/400且CONFIG_TMC2209_RSENSE约0.11Ω**时，在初始化TMC前将传入的run请求改1200，hold原样。其他配置绝不覆盖并打印警告。NVS、默认值、标定、速度/加速度均不修改。bsp_early_init已经设置EN高；后续状态机仍上电DISABLED。

修正同一硬件VSENSE的换算：先由run选择VSENSE，run和hold必须使用同一量程计算，初始化和set_current两条路径均修正。1200/400、0.11Ω下VSENSE=0，IRUN=21，IHOLD=6；名义量化约1215/387mA。800/400和850/400仍为VSENSE1，分别CS25/12和27/12。公共单电流自动换算函数不代表成对电流可分别选档。

烧录后核对日志：

```text
1200mA实验：settings run=800 hold=400；本次初始化请求run=1200 hold=400 mA；NVS不变，电机保持禁用
实验请求量化：VSENSE=0 IRUN_CS=21 IHOLD_CS=6，名义约1215/387mA；不是芯片写入确认或实际电流测量
initialized: microstep=8, run=1200mA, hold=400mA, VSENSE=0
```

保持DISABLED再执行 `python tools/tmc_readonly.py --port COM11 --baud 460800`：核对CHOPCONF bit17为0、GCONF模式正确。IHOLD_IRUN只写不可读；IFCNT增量仅说明写帧受理，不单独证明电流值。CS_ACTUAL静止读数不能证明运行电流。驱动写失败不等于已验证回滚，本次不扩大事务层；上述日志仅证明软件请求，不是硬件生效证据。

显式修改settings电流后，已有回调按该配置请求，不再沿用启动覆盖。重启这份实验固件仍按条件应用。回退不含覆盖的固件恢复原settings请求，无需清空NVS。本实现没有短时自动倒计时；不能把固件配置称为自动限时运行，运动必须另外显式发起和停止。

关键离线测试（无设备）：

```sh
cc -std=c11 -Wall -Wextra -Werror -fsanitize=undefined -Ihost_tests/tmc_current_stubs -Ihost_tests/power_stubs -Ihost_tests/step_engine_stubs -Ihost_tests/stub -Icomponents/tmc2209/include host_tests/tmc_current_test.c -lm -o /tmp/tmc-current-test
/tmp/tmc-current-test
```
