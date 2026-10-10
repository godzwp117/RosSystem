#!/usr/bin/env python3
"""export_gitlog.py -- 导出完整 Git 提交历史到本地留存文件 gitlog.md。

为什么需要它
------------
仓库的提交历史本身是研发过程证据（谁在什么时候因什么原因改了什么）。
但它同时包含**提交者姓名与邮箱**等个人信息，不适合作为公开提交物。
因此本脚本把完整历史导出为 `gitlog.md`，并且：

* 该文件**只保存在本地**，由 `.gitignore` 排除，绝不上传；
* 数据**只来自 Git 对象数据库**（git log / git show / git tag 等），
  不从 README、CHANGELOG 等文档拼接，避免"文档说改了"被当成"历史确实如此"；
* 保留**完整 40 位 SHA**，不使用缩写，避免重名歧义；
* 对附注标签同时输出标签对象 SHA 与它最终指向的提交 SHA，
  防止把标签对象误当成代码提交。

用法：
    python3 scripts/export_gitlog.py [--out gitlog.md] [--no-patch-stats]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RECORD_SEP = '\x1e'
FIELD_SEP = '\x1f'


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(['git', '-C', REPO_ROOT] + list(args),
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError('git {0} 失败: {1}'.format(' '.join(args),
                                                      proc.stderr.strip()))
    return proc.stdout


def git_ok(*args: str) -> bool:
    return subprocess.run(['git', '-C', REPO_ROOT] + list(args),
                          capture_output=True).returncode == 0


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


# ------------------------------------------------------------------ 采集
def collect_workspace() -> dict:
    return {
        'branch': git('branch', '--show-current').strip() or '(detached HEAD)',
        'head': git('rev-parse', 'HEAD').strip(),
        'head_short': git('rev-parse', '--short', 'HEAD').strip(),
        'head_subject': git('log', '-1', '--pretty=%s').strip(),
        'head_date': git('log', '-1', '--pretty=%cI').strip(),
        'dirty': git('status', '--porcelain').strip(),
        'shallow': git('rev-parse', '--is-shallow-repository').strip(),
        'total_commits_all': git('rev-list', '--all', '--count').strip(),
        'total_commits_head': git('rev-list', 'HEAD', '--count').strip(),
    }


def collect_branches() -> list:
    out = git('for-each-ref', '--format=%(refname)%1f%(objectname)%1f%(committerdate:iso-strict)%1f%(subject)',
              'refs/heads', 'refs/remotes')
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(FIELD_SEP)
        if len(parts) >= 4:
            rows.append({'name': parts[0], 'sha': parts[1], 'date': parts[2],
                         'subject': parts[3]})
    return sorted(rows, key=lambda r: r['name'])


def collect_tags() -> list:
    rows = []
    out = git('for-each-ref', '--format=%(refname:short)%1f%(objecttype)%1f%(objectname)',
              'refs/tags')
    for line in out.splitlines():
        if not line.strip():
            continue
        name, objtype, objsha = (line.split(FIELD_SEP) + ['', '', ''])[:3]
        target = objsha
        if objtype == 'tag':
            # 附注标签：解析它最终指向的提交，避免把标签对象 SHA 当成代码提交
            target = git('rev-list', '-n', '1', name).strip()
        rows.append({'name': name, 'object_type': objtype, 'object_sha': objsha,
                     'commit_sha': target,
                     'date': git('log', '-1', '--pretty=%cI', target + '^{commit}').strip()
                     if target else '',
                     'subject': git('log', '-1', '--pretty=%s', target + '^{commit}').strip()
                     if target else ''})
    return rows


def collect_commits(include_stats: bool) -> list:
    fmt = FIELD_SEP.join(['%H', '%h', '%P', '%an', '%ae', '%aI', '%cn', '%ce', '%cI',
                          '%D', '%s', '%B']) + RECORD_SEP
    raw = git('log', '--all', '--date-order', '--pretty=format:' + fmt)
    commits = []
    for record in raw.split(RECORD_SEP):
        record = record.strip('\n')
        if not record.strip():
            continue
        parts = record.split(FIELD_SEP)
        if len(parts) < 12:
            continue
        sha, short, parents, an, ae, ai, cn, ce, ci, refs, subject = parts[:11]
        body = FIELD_SEP.join(parts[11:])
        entry = {
            'sha': sha, 'short': short,
            'parents': [p for p in parents.split() if p],
            'author_name': an, 'author_email': ae, 'author_date': ai,
            'committer_name': cn, 'committer_email': ce, 'commit_date': ci,
            'refs': refs, 'subject': subject, 'body': body.strip(),
        }
        if include_stats:
            stat = git('show', '--stat', '--oneline', '--no-color', sha)[0:0]
            stat = git('diff-tree', '--no-commit-id', '--numstat', '-r', sha)
            files = []
            for line in stat.splitlines():
                cols = line.split('\t')
                if len(cols) == 3:
                    files.append({'added': cols[0], 'deleted': cols[1], 'path': cols[2]})
            entry['file_stats'] = files
            entry['file_count'] = len(files)
        commits.append(entry)
    return commits


def collect_graph(limit: int = 200) -> str:
    return git('log', '--all', '--graph', '--oneline', '--decorate',
               '--date-order', '-n', str(limit))


def classify_refs(commits: list, tags: list) -> dict:
    """把提交按"是否被哪些引用可达"归类。"""
    tag_by_commit = {}
    for tag in tags:
        tag_by_commit.setdefault(tag['commit_sha'], []).append(tag['name'])
    branches = [b['name'] for b in collect_branches()]
    info = {'tags': tag_by_commit, 'branches': branches}
    for commit in commits:
        commit['tags'] = tag_by_commit.get(commit['sha'], [])
        reachable = []
        for branch in branches:
            if git_ok('merge-base', '--is-ancestor', commit['sha'], branch):
                reachable.append(branch)
        commit['reachable_from'] = reachable
    return info


# ------------------------------------------------------------------ 渲染
def render(ws: dict, branches: list, tags: list, commits: list, graph: str,
           include_stats: bool) -> str:
    lines = ['# RosSystem Git 提交历史', '',
             '> 本文件由 `scripts/export_gitlog.py` 从 Git 对象数据库导出，'
             '**仅供本地留存，不得上传**。', '']
    lines += ['## 1. 归档信息', '',
              '| 项 | 值 |', '| --- | --- |',
              '| 生成时间(UTC) | {0} |'.format(utc_now()),
              '| 仓库根目录 | （本地受控路径，已刻意不写入） |',
              '| 生成方式 | 直接读取 Git 对象数据库，未引用任何文档 |',
              '| 提交总数(HEAD) | {0} |'.format(ws['total_commits_head']),
              '| 提交总数(所有引用) | {0} |'.format(ws['total_commits_all']),
              '| 是否浅克隆 | {0} |'.format(ws['shallow']),
              '| 涉及提交数(本文件) | {0} |'.format(len(commits)), '']

    lines += ['## 2. 当前工作区与 HEAD', '',
              '| 项 | 值 |', '| --- | --- |',
              '| 当前分支 | {0} |'.format(ws['branch']),
              '| HEAD 完整 SHA | `{0}` |'.format(ws['head']),
              '| HEAD 标题 | {0} |'.format(ws['head_subject']),
              '| HEAD 提交时间 | {0} |'.format(ws['head_date']),
              '| 未提交改动 | {0} |'.format(
                  '无' if not ws['dirty'] else '有（见下方清单）'), '']
    if ws['dirty']:
        lines += ['未提交改动清单：', '', '```text', ws['dirty'], '```', '']

    lines += ['## 3. 版本基线与标签', '',
              '标签按创建时间排列。**附注标签必须同时看"标签对象 SHA"与"指向的提交 SHA"**，'
              '两者不同，后者才是代码提交。', '',
              '| 标签 | 类型 | 标签对象 SHA | 指向的提交 SHA | 提交标题 |',
              '| --- | --- | --- | --- | --- |']
    for tag in sorted(tags, key=lambda t: t['date']):
        lines.append('| `{0}` | {1} | `{2}` | `{3}` | {4} |'.format(
            tag['name'], '附注' if tag['object_type'] == 'tag' else '轻量',
            tag['object_sha'], tag['commit_sha'], tag['subject'][:48]))
    lines.append('')

    lines += ['## 4. 本地和远程分支', '', '| 引用 | 完整 SHA | 最近提交时间 | 标题 |',
              '| --- | --- | --- | --- |']
    for row in branches:
        lines.append('| `{0}` | `{1}` | {2} | {3} |'.format(
            row['name'], row['sha'], row['date'], row['subject'][:44]))
    lines.append('')

    lines += ['## 5. 完整提交历史', '',
              '每条包含完整 SHA、父提交、作者与提交时间、可达引用与标签。'
              '正文（提交说明全文）原样保留。', '']
    for index, commit in enumerate(commits, 1):
        lines.append('### {0}. `{1}`'.format(index, commit['sha']))
        lines.append('')
        lines.append('- 标题：{0}'.format(commit['subject']))
        lines.append('- 父提交：{0}'.format(
            ', '.join('`{0}`'.format(p) for p in commit['parents']) or '（根提交）'))
        lines.append('- 作者：{0} <{1}>'.format(commit['author_name'],
                                                commit['author_email']))
        lines.append('- 作者时间：{0}'.format(commit['author_date']))
        lines.append('- 提交时间：{0}'.format(commit['commit_date']))
        if commit['refs']:
            lines.append('- 装饰引用：{0}'.format(commit['refs']))
        if commit.get('tags'):
            lines.append('- **标签：{0}**'.format(
                ', '.join('`{0}`'.format(t) for t in commit['tags'])))
        if commit.get('reachable_from'):
            lines.append('- 可达自：{0}'.format(
                ', '.join('`{0}`'.format(b) for b in commit['reachable_from'])))
        if include_stats and commit.get('file_stats'):
            lines.append('- 变更文件数：{0}'.format(commit['file_count']))
            for item in commit['file_stats'][:40]:
                lines.append('    - `{0}` (+{1}/-{2})'.format(
                    item['path'], item['added'], item['deleted']))
            if commit['file_count'] > 40:
                lines.append('    - …（其余 {0} 个文件略）'.format(
                    commit['file_count'] - 40))
        if commit['body']:
            lines.append('')
            lines.append('提交说明全文：')
            lines.append('')
            lines.append('```text')
            lines.append(commit['body'])
            lines.append('```')
        lines.append('')

    lines += ['## 6. 分支与合并关系', '',
              '下列为 `git log --all --graph --oneline --decorate` 的实际输出'
              '（已限制条数以便阅读）：', '', '```text', graph.rstrip(), '```', '']

    lines += ['## 7. 重要里程碑索引', '',
              '按标签与关键提交归纳研发阶段。**标签指向的是"最终状态"，'
              '不等于"最近一次经过验收的代码版本"**，两者需分别记录。', '',
              '| 阶段 | 标签 | 指向提交 | 说明 |', '| --- | --- | --- | --- |']
    milestone_note = {
        'p0-before-m1-20261009': 'M1 改动前的原始快照，用于界定改动边界',
        'p0-stable-v1.0': 'P0 与 M1 全部测试通过后冻结的稳定基线',
        'm2-secure-v1.0': 'M2 安全通信验收证据归档提交',
    }
    for tag in sorted(tags, key=lambda t: t['date']):
        lines.append('| {0} | `{1}` | `{2}` | {3} |'.format(
            tag['name'], tag['name'], tag['commit_sha'],
            milestone_note.get(tag['name'], '—')))
    lines += ['',
              '未冻结事项：M3 开发分支上的提交**尚未**被声明为稳定版本；'
              '团队交接版本（F0）在本次导出时**尚未冻结**。', '']

    lines += ['## 8. 归档完整性说明', '',
              '| 项 | 说明 |', '| --- | --- |',
              '| 数据来源 | 仅 Git 对象数据库（log / for-each-ref / rev-list / diff-tree） |',
              '| SHA 形式 | 完整 40 位，不使用缩写 |',
              '| 标签解析 | 附注标签已解析到最终提交 SHA |',
              '| 覆盖范围 | `git log --all`，即所有本地与已获取远程引用可达的提交 |',
              '| 未覆盖 | 未被任何引用可达的悬空提交（如需覆盖须显式启用 reflog 导出） |',
              '| 个人数据 | 含提交者姓名与邮箱，故**仅限本地留存** |',
              '| 再生成 | 重新运行导出脚本即可覆盖本文件 |', '',
              '局限声明：本文件是"历史事实的本地留档"，不是公开提交物；'
              '它不能证明任何代码正确性，也不能替代验收证据。', '']
    return '\n'.join(lines) + '\n'


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='导出完整 Git 历史到本地 gitlog.md')
    parser.add_argument('--out', default=os.path.join(REPO_ROOT, 'gitlog.md'))
    parser.add_argument('--no-patch-stats', action='store_true',
                        help='不导出逐提交文件变更统计（更快）')
    args = parser.parse_args(argv)

    if not git_ok('rev-parse', '--git-dir'):
        print('ERROR: 当前目录不是 Git 仓库', file=sys.stderr)
        return 2

    include_stats = not args.no_patch_stats
    ws = collect_workspace()
    branches = collect_branches()
    tags = collect_tags()
    commits = collect_commits(include_stats)
    classify_refs(commits, tags)
    graph = collect_graph()
    content = render(ws, branches, tags, commits, graph, include_stats)
    with open(args.out, 'w', encoding='utf-8') as handle:
        handle.write(content)
    print('WROTE {0} ({1} bytes, {2} commits, {3} tags, {4} refs)'.format(
        args.out, len(content.encode('utf-8')), len(commits), len(tags),
        len(branches)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
