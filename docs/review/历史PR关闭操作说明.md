# 历史开放 PR 关闭操作说明（需人工执行）

> **状态：`OLD_PRS_CLOSED: BLOCKED`**
>
> 本环境**无法执行** PR 关闭操作，原因如下（已穷尽检查）：
>
> | 检查项 | 结果 |
> | --- | --- |
> | `gh` CLI | **不可用** |
> | `GITHUB_TOKEN` / `GH_TOKEN` | **未设置** |
> | git credential helper | 未配置 |
> | `~/.config/gh` | 不存在 |
> | 远程协议 | `git@github.com:...`（**SSH**） |
>
> SSH 可以推送代码，但**无法调用 GitHub REST API**，因此无法 `gh pr comment` /
> `gh pr close`。这是环境限制，不是操作失败。

---

## 需要关闭的三项 PR

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
