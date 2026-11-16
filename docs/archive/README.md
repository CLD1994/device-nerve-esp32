# 历史证据与实施记录

归档用于追溯，不是现行配置、操作命令或当前验收结论。当前入口见[文档导航](../README.md)。

## 台架报告和原始证据

- [2026-09-17 旧协议 case8](legacy-acceptance-case8.md)
- [2026-09-18 旧协议端到端验收](legacy-acceptance.md)：保留失败和跳过项，不能套用于当前协议。
- [2026-10-23 MT6835 CS 时序验证](reviews/2026-10-23-mt6835-spi-cs-validation.md)
- [2026-10-23 无运动系统验收](reviews/2026-10-23-system-acceptance.md)
- [2026-10-26 电流测量](reviews/2026-10-26-current-measurement.md)
- [2026-10-26 固件重刷记录](reviews/2026-10-26-firmware-reflash.md)
- [2026-11-13 运动与采样实验](2026-11-13-experiment-results.md)

上述 reviews 报告的原始文本、JSON 证据在同目录的 `evidence/`，迁移时未改内容。历史实际相电流、请求参数、软件累计 STEP 与机械运动证据必须按各报告的限定区分。

## 实施过程取舍

[实施验证记录](implementation-validation.md)汇集七份旧计划中独有的构建/测试回填、审查修正与尚未验证边界，并用固定提交链接保留全部原文。十份长篇计划/规格的实现配方不再作为当前导航；有效架构已收敛到[架构参考](../reference/architecture.md)，供电行为由[硬件文档](../hardware.md)维护。

旧 T8/T10 验收文件只是未填写模板，含 HOME、SGTHRS、AS5600、200 Hz 等旧流程，没有实测证据，已移除。需要追溯时可查看[固定版本的 T8](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/reviews/T8-acceptance.md)和[T10](https://github.com/CLD1994/device-nerve-esp32/blob/64e2a4e5daa15a7ae8be80832a3fb4d90277e4c2/docs/reviews/T10-acceptance.md)。

归档中的待验事项不会自动重新成为开发任务；是否补验应由当前功能变更和现场需求决定。

- [新板改版检查记录](board-revision-checklist.md)：原硬件指南中的带日期检查状态，不作为当前待办。
