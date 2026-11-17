# GPIO39：FAULT MT6835 示波器触发

`CONFIG_CARTFSM_MT6835_FAULT_TRIGGER` 默认关闭。启用后，启动时 GPIO39 配置为 3.3 V 推挽输出并拉低；固件首次真正接受进入 `FAULT MT6835` 的状态转换时置高，保持到重启。ENABLE、DISABLE、RESET 和故障恢复都不清除高锁存。不需要先出现有效窗口，也不再针对单次读帧失败触发。

输出在原有保护减速请求提交之后，串口 MODE 故障行通常还要等停车完成才发送。因此示波器沿不是 SPI 错误位时刻，不是第一帧失败时刻，也不是最终停稳时刻。置位只调用一次 `gpio_set_level`，不打印、不等待、不改原停车流程。GPIO 初始化失败会使固件初始化失败，不宣称触发可用。

## MT6835 故障的实际含义

当前监督任务仅在 READY 时检查这条故障路径：

1. 先处理供电问题；
2. 再检查小车编码器健康、位置参考和已保存轨道范围，失败归为 `AS5600`（即使当前小车实际也是 MT6835，这仍是现有协议名称）；
3. 然后检查摆杆编码器健康，失败才进入 `MT6835`。

摆杆读帧连续失败 10 次会使编码器健康标志变为 false；成功读取会恢复健康。目标 2 kHz 下，连续十次读取名义约占 5 ms（从第一次失败到第十次约 4.5 ms），之后由目标 1 kHz 监督任务观察并接受 FAULT。跳采、SPI 耗时、调度、锁竞争都会增加时间，不能据此承诺硬实时上界。如果监督观察前已恢复健康，也可能没有接受此故障。单帧失败、只有速度窗口无效、DISABLED 下失败、小车故障、POWER 或 STEP_LOSS 都不触发 GPIO39。

## 构建和接线

仅在已更新的 `diagnostic/changqing-tmc-runtime-status` 分支中执行：

```sh
idf.py menuconfig
```

在 `Component config → cartfsm` 下启用 `GPIO39: latch accepted FAULT MT6835`。旧的 `MAGNETIC_ENCODER_POLE_FAILURE_TRIGGER` 已删除，不再有效，必须确认新选项。保留现场其他配置，包括摆杆 SPI DMA、电流与串口。

```sh
grep -n 'CONFIG_CARTFSM_MT6835_FAULT_TRIGGER' sdkconfig
idf.py build
idf.py -p /dev/ttyACM1 flash
```

检查输出为 `CONFIG_CARTFSM_MT6835_FAULT_TRIGGER=y`，烧录端口以实际设备为准。烧录重启会清低并重新允许一次触发。这里的命令供操作者执行，工具不会自动烧录。

GPIO39 接高阻示波器通道并共地，上升沿触发（例如约 1.5 V），预触发长度覆盖失败前 SPI 波形。不要向 GPIO39 加外部电压。编译会检查 BSP 主要外设及自定义控制台的 GPIO39 冲突，仍需操作者确认板外接线。默认关闭不会配置 GPIO39，复位后的电平取决于芯片与外部电路，不能把高低读数当作已启用证明。

主机测试和目标构建不证明物理电平、触发延迟或故障根因；这些留待现场验证。
