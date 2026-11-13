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
  -Icomponents/settings/include -Icomponents/cartparams/include \
  host_tests/cartpos_reference_test.c \
  components/cartpos/cartpos.c -lm -o /tmp/cartpos_reference_test
/tmp/cartpos_reference_test
```

第一个测试直接编入采样骨架，以可控成功/失败帧推进快照，覆盖首读失败、
位置与时间同拍、健康位恢复、失败序列和 20 ms 连续性边界。
第二个测试通过类别接口替身验证稳定捕获、过期/无效样本、观测中断、
失败与采样空窗、比例变更、整数定基和失效锁存。参考点捕获不驱动电机，
调用方仍必须保证整个操作处于 DISABLED。

真实时间速度窗还有独立纯函数测试：

```bash
cc -std=c17 -Wall -Wextra -Werror -Icomponents/magnetic_encoder \
  host_tests/magnetic_encoder_timed_velocity_test.c \
  components/magnetic_encoder/magnetic_encoder_core.c -lm \
  -o /tmp/magnetic_encoder_timed_velocity_test
/tmp/magnetic_encoder_timed_velocity_test
```

速度窗在1 kHz下保留17个成功样本，2 kHz实验下保留33个，均为名义约16 ms平滑；分母使用读帧完成时间差，
因此实际跨度可能不等于 16 ms。快照的 `velocity_valid` 区分有效零速与
未满窗、读取失败、时间不连续、过期、数值溢出。任一次读取失败清空
窗口；恢复后需要按当前采样配置重新积累17或33个成功样本。大于连续性阈值的间隔或
非递增时间同样清窗，并由当前合法时间样本重新播种。时间非负且
相邻间隔等于连续性阈值仍允许位置连续性判定；速度额外要求整个配置窗口（17或33点）的实际跨度≤32 ms。
总跨度超过32ms时返回无效但继续滚动，直到整窗符合门限再恢复。
此实验门限并非硬件最优值，也不证明多圈位置未发生混叠。

`velocity_counts_per_s` 标量接口保留最后有效缓存且不带有效性，不能
用于安全或停稳判断。使用快照的消费者必须检查 `velocity_valid`；
两传感器各有自己的采样时刻，不能把它们视为同步采样。此处测试
不验证遥测消费者的协议迁移、硬件采样精度或实际加速度。


小车实例按参数注册表允许的最高速度、每转行程和编码器分辨率计算连续性
时间预算，允许位移最多四分之一圈；当前 40 mm/rev 和 2000 mm/s 对应
5 ms。此数值是保守工程策略，不是设备测得的极限，也不能证明外力导致
的超速不存在。超过预算或时钟不递增时，不对跨空窗角度应用最短角差，
而是保持累计基准、以新角度继续相对累计，并增加连续性序列。

小车位置解释只接受开机基准或最近成功参考确认时的连续性序列。即使
速度窗口已经重新有效，丢失整圈可信性的绝对位置也不会自动恢复；需要
保持 DISABLED、重新手动定位并执行既有参考确认流程。NVS 中的行程长度
不会补回丢失的圈数。采样快照单测覆盖 1250 mm/s、17 ms 空窗的半圈歧义；
参考单测覆盖故障后持续无效、重新定位恢复和旧测量跨越新参考提交的交错。

2 kHz实验的纯调度/统计单测与33点速度窗、启动失败清理单测：

```bash
cc -std=c17 -Wall -Wextra -Werror \
  -DCONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ=1 \
  -Icomponents/magnetic_encoder host_tests/magnetic_encoder_sampling_test.c \
  -o /tmp/magnetic_encoder_sampling_test
/tmp/magnetic_encoder_sampling_test

cc -std=gnu17 -Wall -Wextra -Werror -fsanitize=undefined \
  -DCONFIG_MAGNETIC_ENCODER_EXPERIMENT_2KHZ=1 \
  -DCONFIG_MAGNETIC_ENCODER_SAMPLING_STATS=1 \
  -Ihost_tests/encoder_reference_stubs -Ihost_tests/stub \
  -Icomponents/magnetic_encoder -Icomponents/magnetic_encoder/include \
  host_tests/magnetic_encoder_2khz_test.c \
  components/magnetic_encoder/magnetic_encoder_tracker.c \
  components/magnetic_encoder/magnetic_encoder_core.c -lm \
  -o /tmp/magnetic_encoder_2khz_test
/tmp/magnetic_encoder_2khz_test
```

定时器/RTOS替身不执行真实任务调度；生命周期用例同步运行任务入口到
等待通知处，再注入定时器启动失败，核对没有任务看门狗订阅泄漏。
这不替代ESP-IDF构建或真机2 kHz与CPU负载测量。
