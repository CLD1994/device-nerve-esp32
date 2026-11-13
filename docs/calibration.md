# 标定保存与重启后的左参考确认

本功能保存装置参数，不保存断电时的小车位置，也不自动回零。小车编码器的单圈绝对角无法区分断电后的整圈位移。每次启动保持 `DISABLED`；即使存在完整记录，也必须手动建立本次位置参考，才能另行 `ENABLE`。

## 操作前准备与首次升级

下列命令在 **Windows PowerShell 的项目根目录**执行，以控制口 `COM11`、`460800` 波特率为例。替换为设备实际控制串口和固件波特率；不要使用日志口。关闭其他占用该串口的软件。固件可在开发容器中编译、烧录，但 Windows 中的仓库和 `tools/cartpole_host.py` 也必须更新到支持 `confirm-left`、`calib-status` 的同一版本。

**旧固件的标定只在 RAM，刷机重启不会自动迁入 NVS。** 升级前可执行 `dump` 留存已确认的摆角参数；第一次刷入本功能仍要完成一次两点标定，并重新下发摆角参数。正常升级不要执行 `erase-flash`；擦除 NVS 会删除保存记录。固件不内置某台设备的历史标定值。

全程先保持电机禁用，摆杆自然下垂，确认磁铁、传动和接线已正确安装。标记两端时使用可重复到达的固定位置，不要强推或撞击挡块。

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 query
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
```

`query` 应收到 `[MODE] DISABLED NONE`。没有对应回执、出现串口数据异常或不是 DISABLED 时，先停止本流程，不进行标记或使能。首次没有记录时，状态为 `CAL_STATE=0`、`CAL_SAVED=0`、`CAL_LENGTH_UM=0`；`CAL_STORAGE` 可以是记录不存在的非零错误码，这表示尚无可恢复记录，不是保存成功。

## 首次保存

### 1. 保存已测得的摆角配置

只有编码器、磁铁和摆杆安装未变化时，才可沿用此前实测的零偏和方向。以下 PowerShell 输入的是本装置已经验证的值，不是通用默认值：

```powershell
$PoleZero = [int](Read-Host '输入已验证的 POLE_ZERO_URAD（微弧度）')
$PoleInv = [int](Read-Host '输入已验证的 POLE_INV（0 或 1）')
python tools/cartpole_host.py --port COM11 --baud 460800 config POLE_ZERO_URAD $PoleZero
python tools/cartpole_host.py --port COM11 --baud 460800 config POLE_INV $PoleInv
python tools/cartpole_host.py --port COM11 --baud 460800 dump
python tools/cartpole_host.py --port COM11 --baud 460800 state --secs 3
```

两个 CONFIG 命令都收到对应 `[OK]` 后，参数**已经自动保存到 NVS，不需要额外 save 命令**。用 `dump` 核对数值；下垂时角度应在 ±180° 附近，直立时在 0° 附近，方向按[协议符号约定](protocol.md#符号约定实机验证方法)验证。±180° 两侧切换是角度环绕，不宜取两侧读数的算术平均值。

这两个参数只能在 DISABLED 下设置，保存成功后才生效；它们也可以在轨道两点标定之后配置。其他运行参数仍按原逻辑使用。零偏默认值不代表摆角已做物理校准。

### 2. 标记左端

手推小车到以后每次都能复现的左标记，停稳，再单独执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 mark-left
```

应收到 `[OK] MARK_LEFT = ...`。此命令先保存旧行程失效记录，再捕获左端；成功后状态为 `CAL_STATE=1`，等待右点。此后掉电不能再恢复旧行程。

### 3. 标记右端并保存

保持禁用，手推至右标记，停稳，再执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 mark-right
```

应收到 `[OK] MARK_RIGHT = <行程µm>`。两个标记之间的**小车同一点位移**是行程，不是两挡块间空距。当前合法范围仍为100～1000 mm；不能用恢复命令绕过该范围。

成功回执表示行程和机械比例已经保存，并已建立以中点为零的本次坐标；不需要再执行 save 或 confirm-left，也不会使能电机。右点写失败或参考失败的区别见[存储失败与恢复](#存储失败与恢复)，不要仅凭某个数值继续。

### 4. 核对保存结果

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
python tools/cartpole_host.py --port COM11 --baud 460800 query
```

例如本次实测行程若是853436 µm，应得到：

```text
[OK] CAL_STATE = 2
[OK] CAL_LENGTH_UM = 853436
[OK] CAL_SAVED = 1
[OK] CAL_STORAGE = 0
[MODE] DISABLED NONE
```

示例长度不能直接套用，必须核对本装置实测结果。`calib-status` 要求四项回执齐全；命令返回成功只表示收齐查询结果，**还必须阅读状态和值**，不能把它等同于已标定或可以使能。

## 重启后的恢复与保存验收

首次保存后，先进行一次重启验收；以后同一装置每次启动也按此流程。

### 1. 重启并检查已保存参数

在 DISABLED 下重启设备，不清除 NVS，然后执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 query
python tools/cartpole_host.py --port COM11 --baud 460800 dump
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
```

应仍为 `DISABLED NONE`；`dump` 中两个摆角参数与保存前相同；`CAL_STATE=3`、`CAL_SAVED=1`、`CAL_STORAGE=0`，`CAL_LENGTH_UM` 与保存前相同。状态3表示**装置参数已恢复，本次小车位置尚未确认**，不是故障，此时 ENABLE 会被拒绝。

### 2. 手推到同一个左标记并确认

确认轨道、传动、磁铁、每转距离与左标记没有变化。手推至**首次两点标定使用的同一个左标记**，停稳后执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 confirm-left
python tools/cartpole_host.py --port COM11 --baud 460800 calib-status
python tools/cartpole_host.py --port COM11 --baud 460800 query
```

若保存行程为853436 µm，确认回执应是 `[OK] CONFIRM_LEFT = -426718`；随后 `CAL_STATE=2`、`CAL_SAVED=1`、`CAL_STORAGE=0`，模式仍是 `DISABLED NONE`。左参考的位置为整数 `-L/2` µm，奇数行程按整数除法向零取整；编码器位置与步进指令位置同步。

**重启恢复用 `confirm-left`，不要用 `mark-left`。** 前者复用保存行程，后者撤销旧行程并开始新的两点标定，必须继续完成右点。

### 3. 独立决定何时使能

确认成功后，可在禁用状态下缓慢手推到轨道中间，连续位置仍会被跟踪。准备好低速验证和独立停机手段后，才单独执行：

```powershell
python tools/cartpole_host.py --port COM11 --baud 460800 enable
```

成功回执为 `[MODE] READY NONE`。确认左点本身不使能、不发送 STEP，也不自动移动。不要将保存验收直接接成高加速度试验；还需单独验证运动方向、限位和制动距离。若位置采样中断，保持禁用并重新确认参考，不以反复 ENABLE 绕过保护。

## 物理条件与安全边界

用户必须保证实际停在左标记，软件不能检测挡块或替用户确认物理位置。断电期间小车可以移动，但启动后仍需回到同一左标记确认，不能使用断电前的当前位置。

采样门禁只验证读取成功、CRC与时间连续性，不是磁铁或机械安装自检。MT6835的磁弱、欠压、过速状态目前仍沿驱动的告警策略处理，不进入本次参考门禁；请人工确认磁铁安装、状态告警及读数随小车运动的对应关系。

## 固件扩展命令

现有协议说明的入口是 [protocol.md](protocol.md)。以下为本固件新增接口；配套主项目协议文档需要同步后，上位机才能将其作为共同协议使用。

| 命令 | 成功回执 | 前提 |
|---|---|---|
| `CONFIRM LEFT` | `OK CONFIRM_LEFT <负半行程µm>` | DISABLED、有保存的有效行程、比例匹配、非两点标定进行中、位置读数有效且稳定 |
| `CALIB?` | 四行 `OK CAL_STATE`、`OK CAL_LENGTH_UM`、`OK CAL_SAVED`、`OK CAL_STORAGE` | 只读，可在所有模式查询 |

`CAL_STATE`：0=无可用定位，1=等待右点，2=本次已定位，3=有保存行程但等待左确认。`CAL_LENGTH_UM` 为可用保存行程，不可用时为0；`CAL_SAVED` 为是否存在比例匹配的有效行程；`CAL_STORAGE` 为最近一次载入或写入的 ESP-IDF 错误码，0表示成功。缺记录或记录损坏会保留诊断码，不伪装为已保存。查询不代表物理位置正确。

标记/确认时需连续100 ms采样，位置跨度不超过100 µm，每次检查都需新样本，最近样本不超过20 ms，期间不能出现读失败或采样空窗。条件不满足会拒绝，不修改原点。轨道两点之间也必须维持编码器连续采样；失败后应重新 `mark-left`。样本失效后，即使后来恢复读数，本次位置也须重新确认；READY 下按现有编码器故障路径停机。

## 存储失败与恢复

记录位于 NVS 的 `cartcal` 命名空间，固定版本格式、CRC32和范围校验；一次完整 blob 写入及提交，不持续写入200 Hz位置流。NVS保证记录更新的掉电恢复；应用只接受完整且校验通过的版本。未知版本不自动解释或迁移，擦除NVS也会使记录丢失，需重新标定。

- `ERR CAL_STORAGE`：写入未确认成功。角配置不在RAM生效；右点保留等待右点，可同位置重试。左点失败不开始新两点标定，当前定位门关闭；此前完整记录可能仍存在，查询后决定重新标定或左确认。不要把写失败当成已保存。
- `ERR CAL_REFERENCE`：参考连续性或比例发生变化。若右点记录已写入但定基失败，则保留已保存行程、禁止使能，手推回左点执行确认；如果仍显示等待右点，则重新 `mark-left`。
- `ERR CONFIRM_LEFT`：参考点未确认，保持禁用。检查状态、记录、传动比例和编码器，停稳后再试。
- 改变轨道、传动、磁铁或编码器安装，必须主动重新两点标定；比例不匹配的保存行程不能恢复。恢复出厂/NVS清除后不能用旧行程自动建立位置。

首次刷入本功能时，旧固件RAM标定不会自动进入NVS，需要重新两点标定并设置摆角参数。本功能未替代制动距离与最大加速度的真机验收；原有软限位不是提前制动保证。

## 宿主回归与真机验收边界

从仓库根目录执行下列单元测试，硬件、NVS、任务调度使用受接口约束的替身：

```bash
gcc -std=c11 -Wall -Wextra -Werror \
  -Icomponents/cartcal/host_stub -Icomponents/cartcal/include \
  -Icomponents/cartparams/include -Icomponents/settings/include \
  host_tests/cartcal_test.c components/cartcal/cartcal.c \
  components/cartparams/params.c -lm -o /tmp/cartcal-test
/tmp/cartcal-test

gcc -std=c11 -Wall -Wextra -Werror \
  -Ihost_tests/power_stubs -Icomponents/cartfsm/host_stub -Icomponents/cartcal/host_stub -Ihost_tests/stub \
  $(find components -type d -name include -printf '-I%p ') \
  host_tests/cartfsm_calibration_test.c components/cartfsm/cartfsm_core.c \
  components/cartparams/params.c -lm -o /tmp/cartfsm-calibration-test
/tmp/cartfsm-calibration-test

python -m unittest discover -s tools -p 'test_*.py'
```

采样和参考点单元测试命令见[对应替身说明](../host_tests/encoder_reference_stubs/README.md)。存储测试覆盖记录缺失、损坏、版本、范围、失效记录与各存储阶段失败；FSM测试覆盖保存、重启、禁用门、确认、原点同步、配置写失败与重试。

宿主通过不能证明ESP-IDF目标构建、NVS物理断电一致性、实际传感器采样连续性或电机安全。真机验收应保持电机禁用，分别验证：两点保存后重启不能直接ENABLE；左确认后坐标恢复；断电后移动再确认；存储记录清除后拒绝恢复；标定期间移动/传感器失败拒绝操作。最后单独完成低速限位与加速度验收。不要由测试脚本自动使能或撞挡块。
