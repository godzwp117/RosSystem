# 成员一：通信异常离线实验原型

基线：`a4c597161d254192b662ee7b8f4d17f76a89cc16`。契约保持 `PROPOSED_V1 / 1.0.0-proposed`。
模块输出建议，最终执行准入由 SecurityGateway 判定。模型输出、自报 producer、request_id 均不能证明 DDS 身份。

## 已实现

- `module.py` 的 `analyse()` 使用实际数值模型计算预测，不读取 f0_mock 场景或业务标签选择结果。
- 采用可验证 SHA256 的纯数值 JSON 模型；不加载 pickle/joblib，不从输入信封选择模型或执行命令。模型只能位于本仓库 `training_runs/`。
- `CommRiskEvidence` 输出使用现有公共 Schema 和严格时间检查。stdin 单对象，stdout 单 JSON，诊断 stderr。
- 缺模型退出 3；非法信封退出 2；缺真实资源/窗口/业务请求计数，拒绝伪造完整证据，退出 4。
- 可映射且缺特征/顺序错误输出合法 UNKNOWN；损坏模型/哈希不匹配输出合法 ERROR；二者均不得推进。
- 正常预测须通过验证门槛且观察来源适用。未通过模型或 MOCK/UNKNOWN 来源的正常预测默认保留 UNKNOWN。`--controlled-test` 只能用于受控 L1 配置，明确记录在结果中，不用于生产或在线安全声明。
- 输入特征必须显式包含精确的 feature_names 顺序和 values。没有列名/缺少值不补 0；**存在的 null** 按训练集拟合的中位数处理，输出记录缺失数量和处理依据。该缺失值策略属于离线数据预处理，不能把补值作为实时已采集特征的证明。
- 二分类检出异常时状态为 SUSPICIOUS，类别为既有枚举 UNKNOWN；未臆造 NETWORK_TRAFFIC_ANOMALY 或具体攻击子类。

## 安装和测试

在仓库根目录，Python 3.11：

```bash
python3 -m venv .research-venv
.research-venv/bin/python -m pip install -r modules/my_comm/requirements.txt
.research-venv/bin/python -m pytest modules/my_comm/test_module.py modules/my_comm/test_integration.py tests/unit/test_team_contracts.py -q
.research-venv/bin/python scripts/validate_team_contracts.py --all
```

Windows 使用 `.research-venv/Scripts/python.exe`。适配层本身使用 POSIX `resource`，必须在 Linux/WSL/Jazzy 环境执行；本模块不修改适配层以迁就 Windows。Linux CI 增加成员一的四状态真实子进程及适配层测试。这些受控测试属于 L1，不是 ROSPaCe L2。

## ROSPaCe 离线实验

从官方合集取得 `ROSPaCe_reduced.tar.gz` 和 `ROSPaCe_reduced_noperiodicity.tar.gz`：
https://springernature.figshare.com/collections/ROSpace_Intrusion_Detection_Dataset_for_a_ROS2-Based_Cyber-Physical_System/6924364

压缩包放在忽略目录 `data/ROSPaCe_reduced/`，禁止提交原始数据。下载完成必须对照 Figshare 文件元数据核验尺寸和 MD5。

可执行 `python3 modules/my_comm/download_data.py --dataset both` 自动从官方API取得文件信息、断点续传并核验；失败后可以重试同一命令，已校验的范围不会重复下载。`.partial` 文件绝不能当作完整数据用于训练。

系统代理导致 S3 的 TLS EOF 时，可加 `--direct`，只对该下载进程使用直连 HTTPS，证书检查保留。没有修改系统代理或 Windows 安全设置。下载时间取决于网络；最终归档必须同时通过尺寸与发布者 MD5 检查，数据预处理会再次核验，不能把文件大小或部分成功范围当作下载完成。

```bash
# 全部读取15个分片，每分片均匀蓄水池抽样，决不只读前N行
.research-venv/bin/python modules/my_comm/train.py \
  --archive data/ROSPaCe_reduced/ROSPaCe_reduced.tar.gz \
  --samples data/member1_samples/reduced --output training_runs/member1

# 去周期性10分片：独立训练/验证/测试，保持同一算法比较方案
.research-venv/bin/python modules/my_comm/train.py \
  --archive data/ROSPaCe_reduced/ROSPaCe_reduced_noperiodicity.tar.gz \
  --samples data/member1_samples/noperiodicity --output training_runs/member1_noperiodicity
```

原始文件只读；流式解压，不将14GB/10GB CSV写到磁盘。数据所有行参与标签审计，内存由每分片采样上限决定。默认每分片10000条，保留样本在原分片的行编号和时间。只有实际表头进入列索引；无表头分片首行是数据，不跳过。

官方主归档里的 `rospace_reduced_11.csv ` 尾部有空格。识别时只去除文件名尾部空白，证据保留原始名称；归一后出现重复分片会报错，不静默覆盖。这避免漏读第11分片而改变验证集和类别统计。

分片按数字编号排序。末2片测试，前2片验证，其余训练；训练/验证/测试不交叉。这个划分仅证明 FILE_DISJOINT_SPLIT，**不证明独立采集会话泛化**。官方归档先出现无表头分片，因此先流式定位真实 `_0` 表头，再流式处理全部分片；缺少真实表头会报错，不猜测列名。

49特征来自研究分支的实际特征可采集性清单，并逐一和原始CSV表头核对；61原始非标签字段不与49模型特征混用。标签只用于训练目标及评估。特征中禁止 attack/label/timestamp/group_id 等字段。中位数与 signed-log StandardScaler 只拟合训练集，验证与测试全程固定。

比较：带类别权重的 LogisticRegression 与 ExtraTrees（固定参数）。阈值只在验证集固定网格选择，选定模型之后一次性评估测试集，不用测试指标调参。输出包括：

- F1、Precision、Recall、Balanced Accuracy、FPR、specificity、二分类 Macro Recall；
- 各攻击类别实际出现数量及召回，未出现标 NOT_EVALUATED；
- `macro_attack_detection_recall` 单独定义；
- average precision 的 PR-AUC；
- 恒预测攻击/恒预测正常两个基线、划分清单、模型SHA256、全量/采样标签比例；
- 每分片采样量纲、缺失率、时间范围诊断。诊断描述统计不能作为漏报根因的因果证明。

验证门槛：F1高于恒预测攻击、Balanced Accuracy>0.5、攻击召回和正常specificity均≥0.5。它只是本实验的最低门槛，不是赛事性能要求，也不保证在线安全。未通过则模型正常预测默认不推进。

## 适配输入与配置

同一 `observations[]` 对象的 detail 提供：

```json
{
  "rospace_comm": {
    "features": {"feature_names": ["实际完整有序列名"], "values": [1.5]}
  },
  "f0_runtime": {
    "communication": {"resource": "/rg/guarded_navigate", "resource_type": "Action", "operation": "GOAL_SEND"},
    "request_count": 10,
    "window": {"start": "2026-10-13T12:00:00Z", "end": "2026-10-13T12:00:05Z", "duration_ms": 5000}
  }
}
```

这是子结构展示，不是完整信封。`observations[].source` 必须与真实通信资源一致，观察时间位于窗口内，窗口时长与起止一致。`request_count` 必须来自实际业务观察，**不是数据集包数**。观察及引用来源要一致；字段自报不能证明来源真实性。缺映射时退出4，不能把候选目标资源冒充被观察资源。不得把离线 CSV 恢复为实时观察。

训练完成后，创建本地适配配置，只替换 comm_risk；其他模块保持基线 Mock：

```bash
.research-venv/bin/python modules/my_comm/write_config.py --run-dir training_runs/member1
.research-venv/bin/python scripts/check_member_module.py --module comm_risk --config config/team_modules.local.yaml
.research-venv/bin/python scripts/team_demo.py --input YOUR_REAL_ENVELOPE.json --config config/team_modules.local.yaml
```

统一验收器当前只构造 `detail.f0_mock` 场景，没有真实特征、资源窗口和业务请求计数。本模块会忽略该场景并安全失败，所以不能直接把该脚本用于算法有效性验收，更不能为过它而在真实模块添加场景开关。需成员四确认扩展验收 fixture 注入能力。本模块的 `test_integration.py` 在 Linux 上用显式受控数值模型执行正常/可疑/UNKNOWN/ERROR四状态及真实适配层路径。

## 交付限制

已准备 Jazzy 与经过最小权限核验的 SROS2 keystore 后，可在成员一容器中执行受控在线接口验收：

```bash
RG_MEMBER=1 RG_SECURE_DOMAIN_ID=51 scripts/setup_sros2.sh
docker exec rg_member1 bash -lc 'cd /ws && source /opt/ros/jazzy/setup.bash && source install/setup.bash && python3 modules/my_comm/run_ros_controlled_protocol.py --domain 51'
```

该脚本复用既有安全节点和 Planner，只有正常状态会经 Gateway 产生 1 个 NavigationSim Goal，其他状态均不提交。输出含真实 Gateway 审计与 Goal ID 关联证据，四个状态的特征与数值模型明确标为受控 MOCK，两位其他成员仍是 baseline Mock。**这证明实际 ROS 协议链路，不证明检测器在真实在线流量上的效果。** 密钥和模型仅在忽略目录，发布包不含它们。

当前 `RUNTIME_MONITOR: NOT_READY`。不能宣称已实现 Jazzy 在线 IDS。本轮缺少旧模型训练产物，旧F1=0.1967、Recall=0.1091仅是基线指引报告，不能冒充本次复现。旧0.9956被证伪结果不用作对照实绩。

成员二应消费现有 CommRiskEvidence；当前公共契约不需改动。L3必须真实 Gateway 审计与 NavigationSim Goal，独立单测或离线 READY 不能替代。PR base必须为baseline，未完成门槛保持草稿，需至少一名审批人和CI后才可合入。
