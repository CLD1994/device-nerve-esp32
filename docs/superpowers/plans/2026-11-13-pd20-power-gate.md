# 20 V 供电门禁实施计划

> 执行者：按 superpowers:executing-plans 逐项实现并核验。

**目标：** 启动请求20V，稳定确认后开放运动门禁，供电失效锁定并停止输出。
**架构：** cartpower纯核心、I2C/ADC任务与FSM缓存读取分离。main作为组装入口。
**技术：** C11、ESP-IDF、FreeRTOS、宿主gcc与Python测试。
**规格：** [设计](../specs/2026-11-13-pd20-power-gate-design.md)。

## 全局约束
不操作真实硬件；不混入实验文件；中文文档，独立待评审PR。与标定持久化分支分别实现，合并后同时验证两个使能门。保持协议已有正常MODE字段兼容，仅增加POWER原因。

## 审查重点
- 启动过渡的9V不是立即错误，但稳定后9V必须锁定。
- 初始化失败、样本停滞、非有限ADC数据不能默认就绪。
- 超时从请求前开始，截止时刻不能靠第五样本绕过。
- 电机使能/VEL与供电故障并发不能留下使能输出。
- RESET不能消除未恢复电源条件，恢复也不自动使能。

## 任务
- [x] 1. 新建host_tests/cartpower_core_test.c，覆盖上述状态、边界、序列与时间戳；失败后实现components/cartpower/cartpower_core.c与include契约。
- [x] 2. 新建cartpower任务适配、CMake与Kconfig；给初始化失败/读取失败/任务创建失败保留可观测状态；修改main启动组装。
- [x] 3. FSM增加POWER故障与ENABLE门、持续停机；扩展核心与主机解析回归，审查所有READY/FAULT入口。
- [x] 4. 更新hardware/protocol/test指南；运行宿主C/Python回归与diff检查，独立审查；没有ESP-IDF时明确未编译/未上板，不能宣称固件验证通过。

## 验证记录

2026-11-13，云端宿主：17个C测试程序以`-std=c11 -Wall -Wextra -Werror`构建运行通过；
Python工具测试63项通过；`git diff --check`通过。覆盖稳定样本中断、等待锁期间更新采样
导致的时钟竞争、RESET→ENABLE后旧停机快照、供电任务未调度即超时等回归。
独立审查已对电源门和状态/输出互斥复核。

当前环境没有ESP-IDF：正式固件和Unity测试固件目标编译、双核调度、实际20V协商、
掉电与停止距离未验证。

PR #6 合并后，已基于main `166e256`整合：ENABLE同时检查供电验证和已保存行程/本次参考有效性；监督路径保留参考失效停机。补充CAL_PENDING、CONFIRM LEFT后供电失效、RESET后参考失效的组合回归；Python工具65项通过。

融合版本独立复核通过；追加4个标定/采样宿主C程序通过，共21个；其中采样测试使用gnu17，其余按各自文档命令构建。
