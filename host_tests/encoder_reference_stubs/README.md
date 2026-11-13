# 编码器快照和参考点单元测试替身

这些头文件只用于 `magnetic_encoder_sample_test.c` 和
`cartpos_reference_test.c`，不进入固件构建。测试使用可控单调时钟、
单线程临界区和不启动硬件任务的 FreeRTOS 替身；不能验证目标平台锁、
调度、SPI/I²C 时序或真实电机停止状态。

从仓库根目录运行：

```bash
cc -std=gnu17 -Wall -Wextra -Werror \
  -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
  -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
  host_tests/magnetic_encoder_sample_test.c \
  components/magnetic_encoder/magnetic_encoder_tracker.c \
  components/magnetic_encoder/magnetic_encoder_core.c -lm \
  -o /tmp/magnetic_encoder_sample_test
/tmp/magnetic_encoder_sample_test

cc -std=gnu17 -Wall -Wextra -Werror \
  -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
  -Icomponents/cartpos/include -Icomponents/magnetic_encoder/include \
  -Icomponents/settings/include host_tests/cartpos_reference_test.c \
  components/cartpos/cartpos.c -lm -o /tmp/cartpos_reference_test
/tmp/cartpos_reference_test
```

第一个测试直接编入采样骨架，以可控成功/失败帧推进快照，覆盖首读失败、
位置与时间同拍、健康位恢复、失败序列和 20 ms 连续性边界。
第二个测试通过类别接口替身验证稳定捕获、过期/无效样本、观测中断、
失败与采样空窗、比例变更、整数定基和失效锁存。参考点捕获不驱动电机，
调用方仍必须保证整个操作处于 DISABLED。
