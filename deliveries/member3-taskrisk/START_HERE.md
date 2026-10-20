# 成员 3 任务风险模块：源码交付版

本包直接提供 Python 源文件、配置、测试和说明，可以解压后直接阅读代码。
原交付包只有 Git 补丁，代码实际存放在 member3.patch 内，需要应用补丁后才生成源码文件。
这次补充的是同一实现的源码展示形式，没有修改算法，也没有把未完成的联调标为完成。

基线：RosSystem 的 baseline 分支，SHA `a4c597161d254192b662ee7b8f4d17f76a89cc16`。
实现提交：`00f3f219d8226cfe6b3ce3d02f6ae8b920905997`。
模块版本：0.1.0；契约：PROPOSED_V1，未冻结。
本包不是完整 RosSystem 仓库；模块需要基线已有的公共契约、策略解析和适配层代码。

## 先看哪些代码

| 文件 | 作用 |
| --- | --- |
| modules/member3_taskrisk/module.py | 程序入口：读取输入、调用算法、输出风险建议 |
| modules/member3_taskrisk/risk_model.py | 核心规则：策略、任务、坐标系、区域与可选审计历史分析 |
| modules/member3_taskrisk/experiments.py | 本地受控实验：运行真实输入并生成报告 |
| modules/member3_taskrisk/online_check.py | ROS 2 在线验收脚本，尚未完成实际 ROS 联调 |
| modules/member3_taskrisk/test_module.py | 成员测试的便捷运行入口 |
| tests/unit/test_member3_taskrisk.py | 模块单元及适配层测试代码 |
| config/team_modules.member3.yaml | 成员 3 接入配置，成员 1、2 仍使用 Mock |
| modules/member3_taskrisk/README.md | 详细安装、算法原理、集成与安全边界 |
| docs/member3/IMPLEMENTATION_REPORT.md | 实际验证结果及待完成内容 |
| docs/member3/PR_DRAFT.md | 向 baseline 提交的 PR 描述草稿，尚未创建远程 PR |

模块仅输出建议，最终执行必须由 SecurityGateway 决定。
ALLOW_RECOMMENDED 或 READY_FOR_GATEWAY_SUBMISSION 都不是机器人执行许可。

## 如何放进你已有的仓库

请先保存已有工作，在自己的 feature 分支操作。
源码的目录层级与 RosSystem 一致；按以下对应关系加入仓库，不需要把整个包作为新项目运行。

| 包内位置 | RosSystem 内位置 |
| --- | --- |
| modules/member3_taskrisk/ | modules/member3_taskrisk/ |
| config/team_modules.member3.yaml | config/team_modules.member3.yaml |
| tests/unit/test_member3_taskrisk.py | tests/unit/test_member3_taskrisk.py |
| docs/member3/ | docs/member3/ |

只加入这些成员 3 文件。已有同名文件时先比较内容，保留你和队友的修改，不直接覆盖。
不要把 config/ 整个替换，更不要替换团队已有的本地配置。
成员 1、2 已接入真实模块时，只把 example_config.yaml 中的 task_risk 配置合入你们的配置。

也可以采用 Git 补丁方式：将包内 member3.patch 放到 RosSystem 根目录，再运行：

```bash
git rev-parse HEAD
# 确认是以上精确基线；若 baseline 已前进，需要先做兼容审查
git switch -c feature/member3-taskrisk-source
git apply --check member3.patch
git apply member3.patch
```

手动复制与应用补丁任选一种，不要重复执行两种方式。
如果同名分支已经存在，用其他 feature 分支名或切换到你的现有分支。
应用补丁有冲突时先检查，不使用强制覆盖。

## 如何运行

下面命令都在 RosSystem 仓库根目录运行。独立算法验证不需要机器人硬件或 ROS 2。
虚拟环境放在仓库外，避免基线旧检查误报依赖中的公开 CA 证书。

```bash
python3 -m venv ../RosSystem-member3-venv
source ../RosSystem-member3-venv/bin/activate
python -m pip install -r modules/member3_taskrisk/requirements.txt
python modules/member3_taskrisk/test_module.py
python modules/member3_taskrisk/module.py < docs/interfaces/examples/module_input_valid.json
python modules/member3_taskrisk/experiments.py --out-dir logs/member3/offline-source-run1
python scripts/team_demo.py --input docs/interfaces/examples/module_input_valid.json --config config/team_modules.member3.yaml
```

已有同名实验输出时换一个新的输出目录，避免覆盖证据。
Windows PowerShell 使用同级虚拟环境的 Scripts/Activate.ps1；python3 不存在时使用 python。
真实 ROS 2 验收在团队已有的 Jazzy + DDS-Security Enforce 环境完成，具体见模块 README。

## 已验证范围与限制

以下是该源码实现之前实际运行的结果，本次只是补充源码文件，没有重复宣称新的验证结果：

- 成员 3 测试：95 passed。
- 全仓回归：428 passed，3 skipped，跳过不算通过。
- 自建受控策略场景：87/87 正确；不代表对未知攻击的泛化能力。
- 本地 CI 镜像：PASS；未推送远程，未获 PR 审批。
- 通用验收器：33 PASS、3 FAIL、1 NOT_RUN、1 BLOCKED，合入门槛 False。
  它仍使用 Mock 场景开关触发四状态，本真实规则模块不读取该开关；详见实现报告。
- L3 ROS 2 联调未完成；实时监测 NOT_READY；动态任务状态机和硬件验证未完成。

reports/ 保存原先实际运行的受控实验与通用验收报告，其中路径是当时研发机器的路径。
MANIFEST.json 列出 12 个新增源码、配置和说明文件的 SHA-256，可用于核对复制是否完整。
本包保留 member3.patch 供 Git 集成，不包含密钥、原始数据、模型文件、虚拟环境或完整仓库。

下一步是在你的基线上运行模块，与成员四解决通用验收器的真实条件兼容问题，
并取得真实 Gateway 审计及 NavigationSim Goal 证据后，再按团队规则提交 PR。
