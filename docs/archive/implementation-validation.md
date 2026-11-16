# 历史实施验证记录
以下为旧实施计划中的验证回填摘录，不是当前版本的测试结果，也不表示曾标记待上板的项目已验收。旧方案包含已淘汰的 AS5600 组装、频率和接口，不能作为当前操作指南。现行结构见[架构](../reference/architecture.md)，当前测试入口见[测试指南](../../test/README.md)。
原计划和规格不再保留整篇实现配方；固定提交链接保留可复查原文。这里只留独有验证、评审修正与限制，不自动恢复任何历史待办。

---
## 2026-10-13-biz-layer-fixes

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-10-13-biz-layer-fixes.md)

## 附录 C：验证记录（执行时回填）

| 任务 | 主工程 | 测试工程 | 宿主 | 上板 | 提交 |
|---|---|---|---|---|---|
| Task 1 | complete | cartpole-test.bin | — | flowtest 回归随 Task 2 待上板 | 96ad4b1 |
| Task 2 | complete | complete | cartfsm_core 79/79 | 3c 红绿 + flowtest 全量待上板 | 905cf93 |
| Task 3 | complete | complete | — | flowtest 回归 + ENABLE 后首步核对待上板 | 113d16c |
| Task 4 | complete | complete | 六组 228/228（含 find 8 条先红后绿） | flowtest CONFIG 路径待上板 | b01dfa3 |
| Task 5 | complete | complete | vel_ramp 48/48 | [step_engine] 计时对照待上板 | 8c1bfe1 |
| Task 6 | complete | complete | — | [bringup] 寄存器核对待上板 | 754a416 |
| Task 7 | complete | complete | 六组 228/228（parse 57 为等价锚） | — | b5141cf |
| 终审修复 | complete | complete | 六组 235/235（parse +7 前缀用例） | 3c 运动态红绿待上板 | 314b205/ece2070 |

终审（fresh-context 评审）：无 Critical；Important 两条已修——flowtest 3c 原静止注入无法证伪旧实现（settling 约 1-2 ms 完成、wait_mode 粒度 5 ms），改运动态注入并重写论证；supervise_soft_limit 清零窗口竞态（预存）条件清零修复。Minor 两条经用户拍板同轮修复（tmc2209_enable 调用处前置条件说明、删除 cartfsm.c 无调用的 bsp.h include）。


---
## 2026-10-13-driver-core-split

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-10-13-driver-core-split.md)

## 验证记录（2026-10-13 执行会话回填）

环境：Windows 10 + ESP-IDF v6.1（IDF 于 C:\esp\v6.1\esp-idf，工具与 Python 用 C:\Espressif 的 EIM 安装，激活脚本 Microsoft.v6.1.PowerShell_profile.ps1）。

- 主工程构建：`idf.py -B build build` → Project build complete，退出码 0（Task 1/2/3 各验证一次）。
- 测试工程构建：`idf.py -C test build` → 生成 test\build\cartpole-test.bin，退出码 0，全部 TEST_COMPONENTS 编入，测试代码零改动适配。注意：不能写 `-C test -B build`——`-B` 相对当前目录解析会指向根工程 build 目录而被 IDF 拒绝。
- 宿主纯逻辑测试（`wsl gcc -std=c11 -Wall -Wextra -Werror`，退出码全 0）：cartfsm_core 79/79（须同时编译 params.c）、cartproto_parse 57/57、mt6835_crc 2/2、mt6835_urad 19/19、telemetry_format 15/15（需额外 -I as5600/mt6835/settings 的 include）、vel_ramp 48/48。
- include 审计（三个 _hw.c 的全部 #include）：
  - tmc2209_hw.c：自家 hw.h、string.h、public tmc2209.h、esp_log.h、driver/uart.h、freertos/FreeRTOS.h、freertos/semphr.h（互斥原语，允许集）
  - as5600_hw.c：as5600_hw.h、as5600.h
  - mt6835_hw.c：mt6835_hw.h、mt6835_urad.h
  - 三者均无 settings.h、无 bsp.h；构建通过为编译级依赖证据。
- 本会话未执行（上板验证项，不冒充已验）：[bringup] 寄存器核对、[spin] 实转、as5600 B 组硬件读、mt6835 静止稳定性与拔线分诊。真机行为回归需烧录测试固件后按 README 标签运行。
- 已知既有问题（非本次引入）：CONFIG_AS5600_INVERT_DIR=n 时旧代码本就无法编译（方向日志三目直接引用未定义宏）；本次的 AS5600_DIR_INVERTED 折算不受影响。

执行期裁定（详细过程见最终交接说明）：
1. 构建入口由计划写的 export.ps1 改为 EIM 激活脚本——export.ps1 会因 Git Bash 自动注入的 MSYSTEM 被 IDF 拒绝，且 EIM Python 与现有 build 缓存匹配。
2. tmc2209/CMakeLists 的 SRCS 由协作者先行加入 tmc2209_hw.c，与目标一致，保留其书写顺序。
3. as5600_hw_init 额外存储整个 config（读取时用运行时 invert_dir），是"镜像发生在读层"的必要实现，镜像表达式与原 #if 版本逐位一致。


---
## 2026-10-14-device-category-abstraction

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-10-14-device-category-abstraction.md)

## 附录 A：上板回归清单（需实机，人工执行）

1. **编码器在线**：`[as5600]` 与 `[mt6835]` 标签 B 组全绿（新口径：B16 为 counts/s、B17/B18 在 cartpos 层、含解释层对拍用例）；首读日志正常。
2. **STATE 数值域比对**：端侧联调（tools/cartpole_host.py）抓 STATE 行，行格式与 reason 逐字节一致；四个数值字段与迁移前记录差 ≤1 量化级（x_um ±1 µm、vx ±1 mm/s、vth ±1 mrad/s）；标定参数（POLE_ZERO_URAD/POLE_INV、$2）设置后数值与迁移前同参数一致。
3. **MODE reason 兼容**：拔 AS5600 / 拔 MT6835 各触发一次 FAULT，reason 为 "AS5600" / "MT6835"；失败期间 STATE 流保持最后成功值。
4. **FAULT 停机次序**：READY 下运动中注入编码器失联（flowtest），确认斜坡停 → 速度精确为零后关 EN → 推 MODE FAULT；RESET 恢复。
5. **flowtest 全量**：`[flowtest]` 用例全绿（3c 运动态注入语义不变）。
6. **$0 变更两条路径（新增）**：DISABLED 下 `$0` 改变后立即生效（x_um/cmd_position_um 读数不变）；READY 运动中 `$0` 改变 → 斜坡停 → 静止后自动应用，cmd_position_um 的 µm 值在变更前后一致（≤1 步重定基误差）。
7. **X_INV 符号验证（若台位启用）**：VEL 200 → x_um 增大；|E−C| 无系统性偏差。
8. **bringup / manual 段**：寄存器核对（含 init_microstep/电流经 config 注入后的上电值）；A9/A10 手动段。

## 附录 B：验证记录回填

环境：Windows 11 + ESP-IDF v6.1（`C:\esp\v6.1\esp-idf`）+ Ninja；宿主测试 WSL gcc 13.3.0。构建与宿主命令见 Global Constraints 与各任务 Step。

| 任务 | 日期 | 环境 | 命令与结果 | 上板项 |
|---|---|---|---|---|
| Task 1 | 2026-10-14（d5b6853） | 同上 | 双工程构建 MAIN=0 TEST=0；host t1=0（87/87）、t5=0（10/10——被删 counts_to_um 段实为 5 条断言，见偏差记录 5） | 附录 A 1/2 待上板 |
| Task 2 | 2026-10-14（0af7b84） | 同上 | 双工程构建 MAIN=0 TEST=0；host t3=0（2/2）、t4=0（16/16——被删 counts_to_mrad_s 段实为 3 条断言，见偏差记录 5）；契约改操作表分发见偏差记录 4 | 附录 A 1/2/3 待上板 |
| Task 3 | 2026-10-14（f8f5e23） | 同上 | TDD 红灯（cartaxis_conv.h 不存在编译失败）→ 绿灯 t7=0（18/18——计划写 17 系计数笔误）；主工程 MAIN=0 | — |
| Task 4 | 2026-10-14（5521dd6） | 同上 | 双工程构建 MAIN=0 TEST=0；host t1=0（87/87）、t6=0（48/48） | 附录 A 4/5/6/7/8 待上板 |
| Task 5 | 2026-10-14 | 同上 | host 七测全量：t1=0（87/87）、t2=0（64/64）、t3=0（2/2）、t4=0（16/16）、t5=0（10/10）、t6=0（48/48）、t7=0（18/18）；依赖规则 grep 逐条核对通过（规则 1–6）；双工程构建沿用 Task 4 结果（此后仅文档改动） | 附录 A 全部待上板 |

## 附录 C：终审记录与修复

终审（fresh 评审上下文，整分支规格+五任务）：Critical 1 条、Important 2 条、Minor 3 条；Strengths 确认五条 Review Focus 与迁移不变量 1–3 逐行核对通过、七测复核一致。

| 项 | 结论 | 处置 |
|---|---|---|
| C-1 `$0` 重定基用新换算系数记录旧单位步数（µm 不保持，评审者桩件实证；源自计划 Task 4 实现代码） | 成立（settings.c 先提交 `s_values[idx]` 后通知，回调时 `settings_steps_per_mm()` 已新档） | 修复强于评审建议：cartaxis 增 `s_applied_microstep`（已写入芯片的细分档）作为换算单一权威，`spm() = settings_full_steps() × applied ÷ settings_units_per_rev()`——挂起等待与写失败期间读数都保持旧档换算，应用后 µm 无跳变；另加 apply 忙标志串行化（settings 回调与 cartaxis 入口并发）。回归锚：新增 host t8（17 用例，含评审实证场景 $0 8→16 @1600 步 → µm 保持 40000、步数重定基 3200；挂起期无瞬态；写失败读数自洽；$2 即时生效） |
| I-1 MT6835 速度窗 hist int32 与位置 int64 域错配（累计 1024 净圈后速度错乱；源自计划正文的状态结构描述） | 成立 | hist 改 `int64_t`（静态区 +72 B），发布路径去截断 |
| I-2 Review Focus 3（$0 状态机）无自动化锚 | 成立 | 随 C-1 落 host t8（决策表三条路径 + DISABLED 交叉即静止路径 + $1/$2 即时）；poleang 算术桩化列为后续改进不阻塞 |
| M-1 µm 域中间量用 `long`（目标 32 位） | 缓办 | 物理域 ±2^31 µm ≈ ±2147 m 不可达，无行为违反；改动牵连 cartaxis_conv 已测纯函数签名，收益不成比例 |
| M-2 motor/Kconfig 菜单标题沿用旧域命名 | 成立 | 改「motor - 步进电机类别」 |
| M-3 对拍用例两读竞态（运动中偶发假失败） | 成立 | 断言改 ±1 count 环绕感知容差 |
| Recommendations（写失败日志提示换算状态、init 记录已生效档） | 采纳 | 两处日志已随 C-1 修复落地 |

修复后验证：双工程构建 MAIN=0 TEST=0；host 八测全量 t1=0（87/87）、t2=0（64/64）、t3=0（2/2）、t4=0（16/16）、t5=0（10/10）、t6=0（48/48）、t7=0（18/18）、t8=0（17/17）。上板项仍为附录 A 全部八项（含第 6 项 $0 两路径——现为 t8 的真机复核）。

终审修复核验（评审者独立复核，判定 Ready to merge）：四项修复全部通过（t8 至少 6 条断言经回退推演可证伪旧实现；八测与双工程构建经评审独立复跑一致）。核验轮新发现三项同日处置：

| 项 | 结论 | 处置 |
|---|---|---|
| N-1 busy 后到者直接返回——并发第二条 `$0` 变更在毫秒窗内既未应用也未挂起（当前无生产触发面，读数自洽可自愈） | 成立 | busy 分支改置 `s_pending_microstep` 后返回（幂等补推） |
| N-2 t8 缺「写失败后重设恢复」断言 | 成立 | D2 段 3 条断言补齐（重设→芯片档更新、步数重定基、µm 不变） |
| N-3 附录 C 数值笔误（±2^31 µm ≈ 214 m） | 成立 | 勘正为 ≈ 2147 m |

核验轮后复验：t8=0（20/20）；双工程 MAIN=0 TEST=0。


---
## 2026-10-14-device-decoupling

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-10-14-device-decoupling.md)

## 附录 A：上板回归清单（需实机，人工执行）

按 [testing.md](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/.agents/rules/testing.md) 要求记录日期、环境与范围；此前驱动核心拆分（2026-10-13）遗留的真机回归一并补记：

1. **编码器在线**：as5600 / mt6835 自测 B 组（[as5600] 与 [mt6835] 标签）全绿；首读日志正常。
2. **STATE 流字节核对**：端侧联调（tools/cartpole_host.py）抓取 STATE 行，与迁移前记录逐字段比对（x/theta/vx/vth 数值域一致）；标定参数（POLE_ZERO_URAD/POLE_INV）设置后 theta 数值与迁移前同参数一致。
3. **MODE reason 兼容**：拔 AS5600 / 拔 MT6835 各触发一次 FAULT，确认 MODE 行 reason 为 "AS5600" / "MT6835"；失败期间 STATE 流持续输出最后成功值（不清零、不中断）。
4. **FAULT 停机次序**：READY 下运动中注入编码器失联（flowtest），确认斜坡停 → 速度精确为零后才关 EN → 推 MODE FAULT；RESET 恢复。
5. **flowtest 全量**：test 工程 `[flowtest]` 标签用例全绿（标定、使能、软限位、失联注入——覆盖迁移不变量 2 的重定基时序与不变量 5 的注入语义；钩子已迁至域接口，用例不改）。
6. **bringup 段**：[bringup] 硬件寄存器核对（EN 引脚经 config 注入后首次真机验证）。
7. **手动段**：[manual] 手转轴 / 摆杆观察（多圈计数与方向镜像）。

## 附录 B：验证记录回填

环境：Windows 11 + ESP-IDF v6.1（`C:\esp\v6.1\esp-idf`）+ Ninja；宿主测试 WSL gcc 13.3.0。构建与宿主命令见 Global Constraints 与 Task 6 Step 1。

| 任务 | 日期 | 环境 | 命令与结果 | 上板项 |
|---|---|---|---|---|
| Task 1 | 2026-10-14 | 同上 | 主工程 `idf.py -B build build` → Project build complete；测试工程 `idf.py -C test build` → Project build complete | 附录 A 1 待上板 |
| Task 2 | 2026-10-14 | 同上 | 双工程 build → Project build complete；telemetry_format 宿主 15/15（exit=0，含 i2c_master 桩） | 附录 A 2 待上板 |
| Task 3 | 2026-10-14 | 同上 | motor_conv 宿主 RED（头文件缺失）→ GREEN PASS 15/15（exit=0）；主工程 build → Project build complete | — |
| Task 4 | 2026-10-14 | 同上 | 双工程 build → Project build complete | 附录 A 6 待上板 |
| Task 5 | 2026-10-14 | 同上 | 双工程 build → Project build complete；cartfsm_core+params 宿主 87/87（exit=0） | 附录 A 4/5 待上板 |
| Task 6 | 2026-10-14 | 同上 | host 七测全绿：87/64/2/19/15/48/15（exit=0 × 7）；双工程 build → Project build complete × 2 | 附录 A 全部待上板 |
| 终审修复 | 2026-10-14 | 同上 | I-1（cc47a27）：grep 零引用 + 双工程构建 + host 七测全绿；M-1/M-2（本轮）：双工程 build → Project build complete（MAIN_EXIT=0 / TEST_EXIT=0），host 七测 87/64/2/19/15/48/15（exit=0 × 7）——改动均为注释与文档，无行为变化 | — |

终审（fresh-context 整分支评审）：无 Critical；Important I-1（bsp_tmc_en_set 迁移后零调用者死代码）修复于 cc47a27。Minor 两条缓办后同日修复：M-1 mt6835.h 补 init 的 @return 错误码契约，同类缺口一并补齐（cartpos_as5600.h / poleang_mt6835.h / motor_tmc2209.h 三个实现 init 头）；M-2 规格「读函数在器件未初始化时返回 0 / false」与实现不符——s_ok 初值为 true（未观测到读取失败即视为正常），数值读函数返回 0 的半句正确，按实际语义修正措辞，同时清除规格 motor 表残留的单字母缩写（冻结 C / C 重定基 → 冻结指令位置 / 指令位置重定基，与 [motor.h](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/components/motor/include/motor.h) 实现一致），并在[写作规则](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/.agents/rules/writing.md)固化术语完整名称要求。


---
## 2026-10-17-rev2-encoder-migration

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-10-17-rev2-encoder-migration.md)

## 未决与预估

- 骨架内部回调接口形态、文件划分（T3）为预估，实施时按编译与测试反馈调整。
- D7 µrad 收口的最小形态实施时定。
- 按键行为语义：明确不在本计划，后续任务。
- ENN（GPIO21）外部上拉：2026-10-17 用户确认新板已做 3.3V 上拉（与 TMC2209 逻辑电源同轨），hardware.md §2 已更新，本项关闭。
- CH224Q I2C 地址 0x22/0x23：待上板扫描确认（T8）。
- 上板项（T9、T7 联调、T8 回读验证）依赖用户操作硬件。


---
## 2026-11-13-pd20-power-gate

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-11-13-pd20-power-gate.md)

## 验证记录

2026-11-13，云端宿主：17个C测试程序以`-std=c11 -Wall -Wextra -Werror`构建运行通过；
Python工具测试63项通过；`git diff --check`通过。覆盖稳定样本中断、等待锁期间更新采样
导致的时钟竞争、RESET→ENABLE后旧停机快照、供电任务未调度即超时等回归。
独立审查已对电源门和状态/输出互斥复核。

当前环境没有ESP-IDF：正式固件和Unity测试固件目标编译、双核调度、实际20V协商、
掉电与停止距离未验证。

PR #6 合并后，已基于main `166e256`整合：ENABLE同时检查供电验证和已保存行程/本次参考有效性；监督路径保留参考失效停机。补充CAL_PENDING、CONFIRM LEFT后供电失效、RESET后参考失效的组合回归；Python工具65项通过。

融合版本独立复核通过；追加4个标定/采样宿主C程序通过，共21个；其中采样测试使用gnu17，其余按各自文档命令构建。


---
## 2026-11-13-safe-disable

[原计划](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/plans/2026-11-13-safe-disable.md)

## 验证记录与范围
2026-11-13宿主环境：22个C程序与73项Python测试通过；解析、FSM命令、主机命令及引擎接口均先观察缺失行为失败再实现。高频ISR保持不变。独立审查在提交前执行。

尚无ESP-IDF目标构建、双核或真机运动验证。自然停稳路径中，递推同锁发布零速/停止标记，此后回调不再发步；正常禁用依赖此路径与FSM输出互斥。现有泛化急停与在途ISR同步是独立待核实问题，不属于此次修复结论。


## 旧规格追溯
- [2026-10-14-device-category-abstraction](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/specs/2026-10-14-device-category-abstraction.md)
- [2026-10-14-device-decoupling-design](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/specs/2026-10-14-device-decoupling-design.md)
- [2026-11-13-pd20-power-gate-design](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/superpowers/specs/2026-11-13-pd20-power-gate-design.md)

## 记录的使用边界

- 2026-10 月的构建和宿主测试只证明对应旧提交，不能替代本次 main 的目标构建。
- 旧迁移清单中的 AS5600、旧 UART/采样频率需按现行硬件和测试指南重写，不能直接执行。
- 2026-11-13 供电与正常禁用记录明确没有当轮 ESP-IDF 目标构建和真机运动证据；双核、掉电、停止距离及泛化急停与在途 ISR 同步不能由宿主结果推出。
- 按键业务语义、历史未执行上板项不因归档自动成为本轮开发任务。
