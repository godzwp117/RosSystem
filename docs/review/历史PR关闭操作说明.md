# 历史 PR 关闭操作说明与执行结果

> **状态：`OLD_PRS_CLOSED: PASS`** —— 已于 2026-10-12 全部执行完毕。
>
> 本文件保留**操作说明**部分（供今后同类清理参考），并在下方记录**实际结果**。

---

## 执行结果（经 GitHub 公开 API 权威核实）

核实方式：`GET https://api.github.com/repos/godzwp117/RosSystem/pulls/<n>`

| PR | 标题 | head | base | state | merged | merged_at |
| --- | --- | --- | --- | --- | --- | --- |
| **#1** | m3-feat(m3): 可信任务动态最小权限准入 + 验收证据脱敏自动发布 | `feature/m3-dynamic-policy` | `main` | **`closed`** | **`false`** | `null` |
| **#2** | f0-feat(f0): 多成员环境隔离与容器复用校验（阶段 A/B，未完成） | `feature/framework-f0` | `main` | **`closed`** | **`false`** | `null` |
| **#3** | Baseline-docs: 发布 F0 团队研发基线 baseline | `baseline` | `main` | **`closed`** | **`false`** | `null` |

**三项全部已关闭、全部未合并。**

| 完成项 | 结果 |
| --- | --- |
| 每个 PR 留有英文关闭说明 | ✅ |
| 关闭但**未合并** | ✅ `merged=false` |
| 来源分支**全部保留** | ✅ 未删除任何远程分支 |
| 未误关闭无关 Issue 或其他工作项 | ✅ |
| `main` 未被重建或强推 | ✅ 仍为 `838f66f41821edf0421612a205d162ae8e9eb955` |

### ⚠️ 一个容易误判的显示细节

GitHub **分支页**的 `Pull request` 列中：

| 图标颜色 | 含义 |
| --- | --- |
| 🟢 绿色 | PR **仍处于 open** |
| 🟣 紫色 | PR **已合并** |
| 🔴 **红色** | PR **已关闭但未合并** ← **本次的目标状态** |

因此关闭后该列显示**红色**是**正确**的，并非「没关掉」。
判断应以 PR 页面上的 `Closed` 徽章与 API 的 `merged` 字段为准。

---

## 附：操作说明（保留供今后参考）

### 需要关闭的三项 PR

| PR | 源分支 | 目标分支 |
| --- | --- | --- |
| #1 | `feature/m3-dynamic-policy` | `main` |
| #2 | `feature/framework-f0` | `main` |
| #3 | `baseline` | `main` |

> ⚠️ **执行前请先重新列出所有开放 PR** 确认编号、源分支、目标分支与状态。
> 若出现来源、责任或用途不明确的新 PR，**不要盲目关闭**，先报告冲突。

### 执行前记录（每项 PR）

```bash
gh auth status
gh pr list --state open --limit 50
gh pr view <N> --json number,title,url,state,headRefName,baseRefName,headRefOid
```

### 关闭说明（三项通用，实际使用即为此文）

```text
Closing this historical PR without merging.

The RosSystem team now uses `baseline` as the shared development and
integration branch. Research modules are reviewed through PRs targeting
`baseline`, not `main`.

This closure does not reject or discard previous work. The source branch
and all commits are preserved for future reference.

No merge, branch deletion, or force-push is performed.
```

### 必须遵守

- **不执行 merge**；
- **保留**对应研究分支与全部提交；
- **不删除**远程分支；
- **不关闭**无关 Issue；
- **不重建或强推** `main`。

### 关于「不再保留开放 PR」的正确理解

清理的是**历史悬挂 PR**，**不是**取消 Pull Request 审查制度。

- 今后研究模块仍**必须**通过短期审查 PR 合入 `baseline`；
- PR 可在审查期间短暂保持 OPEN；
- 但审查结束后**必须**：合并，或拒绝并关闭（保留分支与评审记录）；
- **不得**长期保留无人负责的开放 PR。



用户已明确决定：**不再保留这三项历史开放 PR，不将其内容合并进 main。**

| PR | 源分支 | 目标分支 |
| --- | --- | --- |
| #1 | `feature/m3-dynamic-policy` | `main` |
| #2 | `feature/framework-f0` | `main` |
| #3 | `baseline` | `main` |

> ⚠️ **执行前请先重新列出所有开放 PR** 确认编号、源分支、目标分支与状态，
> 不要用本文档的编号直接批量操作（编号可能因新 PR 而变化）。
>
> 若出现来源、责任或用途不明确的新 PR，**不要盲目关闭**，先报告冲突。

---

## 执行前记录（每项 PR）

```bash
gh auth status
gh pr list --state open --limit 50
gh pr view <N> --json number,title,url,state,headRefName,baseRefName,headRefOid
```

把 `number / title / url / state / headRefName / baseRefName / headRefOid`
记录下来，存档到本文件或验收报告。

---

## 关闭说明（可直接粘贴，三项通用）

```text
Closing this historical PR without merging.

The team has unified on `baseline` as the integration target for all research
modules. Research work now flows as:

    feature/member<N>-<topic>  ->  baseline

`main` is not the destination for research modules, and we are not merging
`baseline` into `main` at this time.

This closure does **not** reject or discard the work in this PR:
- the source branch and all of its commits are preserved;
- no remote branch has been deleted;
- the changes remain reachable for future reference.

If any part of this work is still wanted, it can be re-proposed as a short-lived
review PR against `baseline`, with the required test and security gates.
```

---

## 执行

```bash
# 对每一项 PR（把 <N> 换成实际编号）
gh pr comment <N> --body-file pr_close_comment.txt
gh pr close   <N>

# 关闭后验证（三项都必须是 closed 且 merged=false）
for n in <N1> <N2> <N3>; do
  gh pr view "$n" --json number,state,merged \
    --template '{{.number}} state={{.state}} merged={{.merged}}{{"\n"}}'
done
```

---

## 必须遵守

- **不执行 merge**；
- **保留**对应研究分支与全部提交；
- **不删除**远程分支；
- **不关闭**无关 Issue；
- **不重建或强推** `main`。

---

## 完成后的记录项

| 项 | 值 |
| --- | --- |
| #1 最终状态 | 待填（期望 `closed` / `merged=false`） |
| #2 最终状态 | 待填（期望 `closed` / `merged=false`） |
| #3 最终状态 | 待填（期望 `closed` / `merged=false`） |
| 远程分支是否仍存在 | 待填（期望「是」） |
| 是否误关闭其他工作项 | 待填（期望「否」） |

---

## 关于「不再保留开放 PR」的正确理解

本轮清理的是**历史悬挂 PR**，**不是**取消 Pull Request 审查制度。

- 今后研究模块仍**必须**通过短期审查 PR 合入 `baseline`；
- PR 可在审查期间短暂保持 OPEN；
- 但审查结束后**必须**：合并，或拒绝并关闭（保留分支与评审记录）；
- **不得**长期保留无人负责的开放 PR。
