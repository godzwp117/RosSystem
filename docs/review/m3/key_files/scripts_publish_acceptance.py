#!/usr/bin/env python3
"""publish_acceptance.py -- 验收证据脱敏后自动发布到 GitHub 证据分支（Task A）。

流程（每一步失败都不会被粉饰成成功）
------------------------------------
    读取本地证据包
        ↓ ① 校验原始包（Schema / 哈希 / 证据引用）
    临时发布目录
        ↓ ② 脱敏（redact_evidence）
    重建元数据
        ↓ ③ 重算 SHA-256、重建 file_hashes.json / manifest / 归档
    校验脱敏副本
        ↓ ④ 再跑一次完整校验（用的是新哈希，绝不复用原始哈希）
    安全扫描
        ↓ ⑤ check_evidence_safety（阻断级问题 → 不 push）
    隔离 worktree
        ↓ ⑥ 只在证据分支上提交本次 run_id
    推送
        ↓ ⑦ 非快进则 fetch + rebase 重试；绝不 force push
    输出远程 commit SHA / 证据地址 / 状态

安全与一致性约束
----------------
* 使用独立临时 git worktree 操作，绝不污染当前工作分支或工作区。
* 幂等：同一 run_id 内容未变化时不产生新提交（状态 ALREADY_PUBLISHED）。
* 并发：对同一仓库加文件锁，避免多个智能体同时发布互相覆盖。
* 网络/权限失败：保留本地待发布产物并给出重试命令，状态记 FAIL/BLOCKED。
* 不创建 GitHub Release，不修改任何基线标签。
* 发布包内**不含**脱敏映射表，避免"用映射表还原真实身份"。

用法：
    python3 scripts/publish_acceptance.py --run-id <run_id> \
        [--remote origin] [--branch evidence/m3] [--dry-run] [--no-push]
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(REPO_ROOT, 'scripts')
EXPORTS_DIR = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'exports')
PUBLISHED_DIR = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'published')
SCHEMA_PATH = os.path.join(REPO_ROOT, 'artifacts', 'acceptance', 'schema',
                           'acceptance.schema.json')
SCHEMA_VERSION = '1.1'
LOCK_PATH = os.path.join(REPO_ROOT, '.git', 'rg_evidence_publish.lock')

STATUS_PUBLISHED = 'PUBLISHED'
STATUS_ALREADY = 'ALREADY_PUBLISHED'
STATUS_NO_CHANGES = 'NO_CHANGES'
STATUS_BLOCKED = 'BLOCKED'
STATUS_FAIL = 'FAIL'


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(path: str) -> str:
    """对目录内容做稳定摘要（相对路径 + 内容），用于幂等判断。"""
    digest = hashlib.sha256()
    for base, dirnames, filenames in os.walk(path):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, path).replace(os.sep, '/')
            digest.update(rel.encode('utf-8'))
            digest.update(b'\0')
            digest.update(sha256_file(full).encode('ascii'))
            digest.update(b'\n')
    return digest.hexdigest()


def run(argv, cwd=None, timeout=600, env=None):
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True,
                          timeout=timeout, env=env)
    return proc.returncode, (proc.stdout or '') + (proc.stderr or '')


def verify_package(pkg_dir: str):
    code, out = run([sys.executable, os.path.join(SCRIPTS, 'verify_acceptance.py'),
                     pkg_dir, '--quiet'], cwd=REPO_ROOT)
    return code == 0, out.strip()


def safety_scan(path: str):
    code, out = run([sys.executable, os.path.join(SCRIPTS, 'check_evidence_safety.py'),
                     '--path', path, '--quiet', '--json',
                     os.path.join(tempfile.gettempdir(), 'rg_safety_latest.json')],
                    cwd=REPO_ROOT)
    report = {}
    try:
        with open(os.path.join(tempfile.gettempdir(), 'rg_safety_latest.json'),
                  'r', encoding='utf-8') as handle:
            report = json.load(handle)
    except (OSError, json.JSONDecodeError):
        pass
    return code == 0, report


def rebuild_file_hashes(pkg_dir: str, run_id: str) -> int:
    """按脱敏后的真实内容重建 file_hashes.json（绝不复用原始哈希）。"""
    entries = []
    excluded = []
    for base, dirnames, filenames in os.walk(pkg_dir):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, pkg_dir).replace(os.sep, '/')
            if rel == 'file_hashes.json':
                continue
            entries.append({'path': rel, 'sha256': sha256_file(full),
                            'size_bytes': os.path.getsize(full)})
    entries.sort(key=lambda item: item['path'])
    doc = {
        'schema_version': SCHEMA_VERSION,
        'run_id': run_id,
        'algorithm': 'sha256',
        'files': entries,
        'excluded': excluded,
    }
    with open(os.path.join(pkg_dir, 'file_hashes.json'), 'w', encoding='utf-8') as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=2)
    return len(entries)


def make_archive(pkg_dir: str, archive_path: str, mtime: int = 0) -> str:
    """生成归档。成员 mtime 固定，保证同一内容产生字节一致的归档（幂等前提）。"""
    if os.path.exists(archive_path):
        os.remove(archive_path)
    run_id = os.path.basename(pkg_dir)

    def _normalize(info):
        info.mtime = mtime
        info.uid = 0
        info.gid = 0
        info.uname = ''
        info.gname = ''
        return info

    with tarfile.open(archive_path, 'w:gz') as archive:
        archive.add(pkg_dir, arcname=run_id, filter=_normalize)
    digest = sha256_file(archive_path)
    with open(archive_path + '.sha256', 'w', encoding='utf-8') as handle:
        handle.write('{0}  {1}\n'.format(digest, os.path.basename(archive_path)))
    return digest


def patch_manifest(pkg_dir: str, redaction: dict, archive_name: str,
                   archive_digest: str, file_count: int, total_bytes: int):
    path = os.path.join(pkg_dir, 'manifest.json')
    with open(path, 'r', encoding='utf-8') as handle:
        manifest = json.load(handle)
    manifest['schema_version'] = SCHEMA_VERSION
    manifest['redaction'] = redaction
    artifacts = manifest.get('artifacts') or {}
    artifacts.update({'archive': archive_name, 'archive_sha256': archive_digest,
                      'file_count': file_count, 'total_bytes': total_bytes})
    manifest['artifacts'] = artifacts
    notes = list(manifest.get('notes') or [])
    notes.append('本包为公开证据副本：内容已脱敏，文件哈希按脱敏后内容重新计算；'
                 '原始证据包仅保存在受控本地环境。')
    manifest['notes'] = notes
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
    return manifest


def tree_stats(pkg_dir: str):
    count = 0
    total = 0
    for base, _dirnames, filenames in os.walk(pkg_dir):
        for name in filenames:
            full = os.path.join(base, name)
            count += 1
            total += os.path.getsize(full)
    return count, total


class PublishLock:
    """跨进程文件锁：避免多个智能体同时发布互相覆盖。"""

    def __init__(self, path: str):
        self.path = path
        self.handle = None

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, 'w', encoding='utf-8')
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise RuntimeError('另一个证据发布进程正在运行（锁: {0}）'.format(self.path))
        self.handle.write('pid={0}\n'.format(os.getpid()))
        self.handle.flush()
        return self

    def __exit__(self, *exc):
        try:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
        finally:
            self.handle.close()
        return False


def git(worktree: str, *args, timeout=600):
    return run(['git', '-C', worktree] + list(args), timeout=timeout)


def remote_branch_exists(remote: str, branch: str) -> bool:
    code, out = run(['git', '-C', REPO_ROOT, 'ls-remote', '--heads', remote, branch],
                    timeout=120)
    return code == 0 and bool(out.strip())


def remote_sha(remote: str, branch: str):
    code, out = run(['git', '-C', REPO_ROOT, 'ls-remote', '--heads', remote, branch],
                    timeout=120)
    if code == 0 and out.strip():
        return out.split()[0]
    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='验收证据脱敏并发布到 GitHub 证据分支')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--remote', default='origin')
    parser.add_argument('--branch', default='evidence/m3')
    parser.add_argument('--source-dir', default=None, help='默认 artifacts/acceptance/exports/<run_id>')
    parser.add_argument('--dry-run', action='store_true', help='只做脱敏/校验/扫描，不推送')
    parser.add_argument('--no-push', action='store_true', help='提交到本地 worktree 但不推送')
    parser.add_argument('--max-retries', type=int, default=3)
    parser.add_argument('--remove-run', default=None,
                        help='从证据分支移除某个已发布的 run_id（普通提交，非强推）')
    args = parser.parse_args(argv)

    if args.remove_run:
        return remove_published_run(args)

    run_id = args.run_id
    src_dir = args.source_dir or os.path.join(EXPORTS_DIR, run_id)
    result = {'run_id': run_id, 'remote': args.remote, 'branch': args.branch,
              'status': STATUS_FAIL, 'steps': [], 'started_at': utc_now()}

    def step(name, ok, detail):
        result['steps'].append({'step': name, 'result': 'PASS' if ok else 'FAIL',
                                'detail': str(detail)[:600]})
        print('  [{0}] {1}{2}'.format('PASS' if ok else 'FAIL', name,
                                      '' if ok else ' -- ' + str(detail)[:300]))
        return ok

    print('=== 证据发布: {0} -> {1}/{2} ==='.format(run_id, args.remote, args.branch))
    if not os.path.isdir(src_dir):
        step('定位本地证据包', False, '不存在: {0}'.format(src_dir))
        result['detail'] = '源证据包不存在'
        print(json.dumps(result, ensure_ascii=False))
        return 2
    step('定位本地证据包', True, src_dir)

    try:
        lock_ctx = PublishLock(LOCK_PATH)
        lock_ctx.__enter__()
        result['lock'] = 'acquired'
    except RuntimeError as exc:
        step('获取发布锁', False, exc)
        result['status'] = STATUS_BLOCKED
        result['detail'] = str(exc)
        print(json.dumps(result, ensure_ascii=False))
        return 1

    try:
        # ① 校验原始包
        ok, detail = verify_package(src_dir)
        if not step('校验原始证据包（Schema/哈希/证据引用）', ok, detail):
            result['status'] = STATUS_FAIL
            result['detail'] = '原始证据包未通过校验，拒绝发布'
            print(json.dumps(result, ensure_ascii=False))
            return 1

        source_archive = os.path.join(os.path.dirname(src_dir), run_id + '.tar.gz')
        source_archive_sha = sha256_file(source_archive) if os.path.isfile(source_archive) else None
        result['source_package_sha256'] = source_archive_sha

        # 幂等前置检查：若远程证据分支已有同一 run_id 且 source_package_sha256 相同，
        # 说明这份证据已经发布过，直接返回，不产生任何新提交。
        if not args.dry_run and remote_branch_exists(args.remote, args.branch):
            run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch], timeout=300)
            rel = 'artifacts/acceptance/published/{0}.publish.json'.format(run_id)
            code, published_json = run(['git', '-C', REPO_ROOT, 'show',
                                        'FETCH_HEAD:{0}'.format(rel)], timeout=120)
            if code == 0:
                try:
                    existing = json.loads(published_json)
                except json.JSONDecodeError:
                    existing = {}
                if (existing.get('source_package_sha256')
                        and existing.get('source_package_sha256') == source_archive_sha):
                    result['status'] = STATUS_ALREADY
                    result['remote_sha'] = remote_sha(args.remote, args.branch)
                    result['detail'] = ('同一 run_id 且源包哈希一致，已发布过，未产生新提交')
                    step('幂等检查（远程已有同源同 run_id 的发布）', True,
                         'source_package_sha256={0}'.format(str(source_archive_sha)[:16]))
                    print(json.dumps(result, ensure_ascii=False))
                    return 0

        # ② 脱敏到 staging
        staging_root = tempfile.mkdtemp(prefix='rg_publish_')
        redacted_dir = os.path.join(staging_root, run_id)
        redact_report = os.path.join(staging_root, 'redaction_report.json')
        code, out = run([sys.executable, os.path.join(SCRIPTS, 'redact_evidence.py'),
                         '--src', src_dir, '--dst', redacted_dir,
                         '--workspace-root', REPO_ROOT,
                         '--report', redact_report], cwd=REPO_ROOT)
        redaction_summary = {}
        try:
            with open(redact_report, 'r', encoding='utf-8') as handle:
                redaction_summary = json.load(handle)
        except (OSError, json.JSONDecodeError):
            pass
        blocked_key_files = redaction_summary.get('rejected_files') or []
        if not step('脱敏（确定性映射，映射表不落盘）', code == 0 and not blocked_key_files,
                    out.strip().splitlines()[-1] if out.strip() else 'ok'):
            result['status'] = STATUS_BLOCKED
            result['detail'] = '脱敏阶段发现密钥类文件: {0}'.format(blocked_key_files)
            print(json.dumps(result, ensure_ascii=False))
            return 1
        result['redaction'] = redaction_summary

        # ③ 重建元数据
        with open(os.path.join(src_dir, 'manifest.json'), 'r', encoding='utf-8') as handle:
            src_manifest = json.load(handle)
        source_commit = (src_manifest.get('source') or {}).get('commit_sha')
        # 脱敏时间取源包时间戳而不是当前时间：同一次运行的重复发布会得到
        # 完全一致的公开副本，幂等判断才有意义。
        redacted_at = (src_manifest.get('timestamp_utc') or utc_now())
        redaction_block = {
            'redacted': True,
            'redacted_at': redacted_at,
            'source_run_id': run_id,
            'source_commit_sha': source_commit,
            'source_package_sha256': source_archive_sha,
            'tool': 'scripts/redact_evidence.py',
            'counts': redaction_summary.get('redaction_counts') or {},
            'files_redacted': redaction_summary.get('files_redacted'),
            'files_opaque_copied': redaction_summary.get('files_opaque_copied'),
            'note': ('公开副本内容已脱敏，file_hashes.json 中的 SHA-256 是脱敏后内容的哈希，'
                     '与原始包中同名文件不同；source_package_sha256 指向本地原始包，'
                     '供受控环境自行比对。映射表不随包发布。'),
        }
        archive_name = run_id + '.tar.gz'
        published_run_dir = os.path.join(PUBLISHED_DIR, run_id)
        os.makedirs(PUBLISHED_DIR, exist_ok=True)
        if os.path.isdir(published_run_dir):
            shutil.rmtree(published_run_dir)
        shutil.copytree(redacted_dir, published_run_dir)

        # 顺序很重要：先写 manifest，再据最终内容算 file_hashes，最后打包。
        # 若先算哈希再改 manifest，manifest 的登记哈希会立即过期；
        # 若把归档自身的 sha256 写回 manifest，则归档内容变→哈希变，形成循环依赖，
        # 因此 manifest.artifacts.archive_sha256 保持 null（与导出器一致），
        # 归档校验以 .sha256 sidecar 与 publish.json 为准。
        file_count, total_bytes = tree_stats(published_run_dir)
        patch_manifest(published_run_dir, redaction_block, archive_name, None,
                       file_count, total_bytes)
        registered = rebuild_file_hashes(published_run_dir, run_id)
        published_archive = os.path.join(PUBLISHED_DIR, archive_name)
        archive_digest = make_archive(published_run_dir, published_archive)
        publish_meta = {
            'run_id': run_id,
            'source_commit_sha': source_commit,
            'source_package_sha256': source_archive_sha,
            'published_archive': archive_name,
            'published_archive_sha256': archive_digest,
            'content_digest': sha256_tree(published_run_dir),
            'redaction': redaction_block,
            'created_at': redacted_at,
            'note': ('归档哈希记录在包外，避免"归档哈希写回包内 manifest 导致归档变化"的循环依赖；'
                     '包内 manifest.artifacts.archive_sha256 因此为 null。'),
        }
        with open(os.path.join(PUBLISHED_DIR, run_id + '.publish.json'), 'w',
                  encoding='utf-8') as handle:
            json.dump(publish_meta, handle, ensure_ascii=False, indent=2)
        step('重建脱敏副本的哈希/manifest/归档', True,
             'files={0} archive_sha256={1}'.format(registered, archive_digest[:16]))

        # ④ 校验脱敏副本
        ok, detail = verify_package(published_run_dir)
        if not step('校验脱敏副本（使用新哈希，不复用原始哈希）', ok, detail):
            result['status'] = STATUS_FAIL
            result['detail'] = '脱敏副本未通过校验，拒绝发布'
            print(json.dumps(result, ensure_ascii=False))
            return 1
        ok, detail = verify_package(published_archive)
        step('校验脱敏归档', ok, detail)

        # ⑤ 安全扫描（阻断级问题绝不 push）
        ok, safety = safety_scan(published_run_dir)
        result['safety'] = {'result': safety.get('result'),
                            'blocking': safety.get('blocking_count'),
                            'warnings': safety.get('warning_count'),
                            'categories': safety.get('categories')}
        if not step('敏感信息扫描（独立模式集）', ok,
                    'blocking={0} {1}'.format(safety.get('blocking_count'),
                                              safety.get('categories'))):
            result['status'] = STATUS_BLOCKED
            result['detail'] = ('安全扫描发现阻断级问题，已拒绝推送；'
                                '本地待发布产物保留在 {0}'.format(PUBLISHED_DIR))
            result['retry_command'] = 'python3 scripts/publish_acceptance.py --run-id {0}'.format(run_id)
            print(json.dumps(result, ensure_ascii=False))
            return 1

        result['published_local_dir'] = published_run_dir
        result['published_archive'] = published_archive
        result['content_digest'] = sha256_tree(published_run_dir)

        if args.dry_run:
            result['status'] = 'DRY_RUN'
            result['detail'] = 'dry-run：已完成脱敏/校验/扫描，未提交也未推送'
            step('dry-run（跳过 git 提交与推送）', True, 'ok')
            print(json.dumps(result, ensure_ascii=False))
            return 0

        # ⑥ 隔离 worktree 上提交
        exists = remote_branch_exists(args.remote, args.branch)
        worktree = tempfile.mkdtemp(prefix='rg_evidence_wt_')
        os.rmdir(worktree)
        try:
            if exists:
                code, out = run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch],
                                timeout=300)
                if not step('拉取远程证据分支', code == 0, out.strip()[-300:]):
                    result['status'] = STATUS_FAIL
                    print(json.dumps(result, ensure_ascii=False))
                    return 1
            else:
                step('拉取远程证据分支', True, '远程分支尚不存在，将新建')

            code, out = run(['git', '-C', REPO_ROOT, 'worktree', 'add', '--detach', worktree,
                             ('FETCH_HEAD' if exists else 'HEAD')], timeout=300)
            if not step('创建隔离 worktree', code == 0, out.strip()[-300:]):
                result['status'] = STATUS_FAIL
                print(json.dumps(result, ensure_ascii=False))
                return 1
            if not exists:
                # 关键：`git checkout --orphan` 会**保留当前索引与工作树**，
                # 于是新分支会继承整棵源码树（实测把 426 个源码文件推上了证据分支）。
                # 必须显式清空索引，并把工作树里遗留的受版本管理文件删掉。
                git(worktree, 'checkout', '--orphan', args.branch)
                git(worktree, 'rm', '-rf', '--cached', '.')
                code, out = git(worktree, 'ls-files')
                if out.strip():
                    step('清空继承的索引（孤儿分支必须从空开始）', False, out.strip()[:200])
                    result['status'] = STATUS_FAIL
                    print(json.dumps(result, ensure_ascii=False))
                    return 1
                step('清空继承的索引（孤儿分支从空开始）', True, 'index empty')
            # 无论是新建分支还是复用已存在分支，索引里都可能混入非证据内容
            # （新建时来自 checkout --orphan 继承的索引；复用时来自历史污染）。
            # 这里先把树里所有非 artifacts/acceptance/published/** 的路径移除，
            # 使证据分支的内容**恒等于**"已发布证据集合"。这是普通提交而非强推，
            # 历史不会被销毁，但后续每个版本的树都是干净的。
            listing = git(worktree, 'ls-tree', '-r', '--name-only', 'HEAD')[1].split()
            prefix = 'artifacts/acceptance/published/'
            extras = sorted(p for p in listing if p.strip() and not p.startswith(prefix))
            if extras:
                chunks = [extras[i:i + 200] for i in range(0, len(extras), 200)]
                for chunk in chunks:
                    git(worktree, 'rm', '-r', '-q', '--ignore-unmatch', '--', *chunk)
                step('清理证据分支上的非证据内容', True,
                     '移除 {0} 个文件（一次普通提交，非强推）'.format(len(extras)))
            # 证据分支不应继承代码分支的忽略规则：published/ 在功能分支被 .gitignore
            # 排除（本地暂存不跟踪），若沿用该规则，`git add` 会**静默地什么都不加**，
            # 结果提交了空内容却报告成功。这里删掉工作树中的 .gitignore 并强制添加。
            ignore_in_worktree = os.path.join(worktree, '.gitignore')
            if os.path.isfile(ignore_in_worktree):
                os.remove(ignore_in_worktree)

            dest_rel = os.path.join('artifacts', 'acceptance', 'published')
            dest_abs = os.path.join(worktree, dest_rel)
            os.makedirs(dest_abs, exist_ok=True)
            target = os.path.join(dest_abs, run_id)
            if os.path.isdir(target):
                shutil.rmtree(target)
            shutil.copytree(published_run_dir, target)
            shutil.copy2(published_archive, os.path.join(dest_abs, archive_name))
            shutil.copy2(published_archive + '.sha256',
                         os.path.join(dest_abs, archive_name + '.sha256'))
            publish_meta_src = os.path.join(PUBLISHED_DIR, run_id + '.publish.json')
            if os.path.isfile(publish_meta_src):
                shutil.copy2(publish_meta_src,
                             os.path.join(dest_abs, run_id + '.publish.json'))
            readme = os.path.join(worktree, 'artifacts', 'acceptance', 'published', 'README.md')
            if not os.path.isfile(readme):
                with open(readme, 'w', encoding='utf-8') as handle:
                    handle.write(PUBLISHED_README)

            git(worktree, 'add', '-f', '-A', '--', 'artifacts/acceptance/published')

            staged = [p for p in git(worktree, 'diff', '--cached', '--name-only')[1].split()
                      if p.strip()]
            expected_manifest = os.path.join(dest_rel, run_id, 'manifest.json').replace(os.sep, '/')
            if not staged:
                pass  # 幂等路径：无变化，稍后按 ALREADY_PUBLISHED 处理
            elif expected_manifest not in staged:
                step('本次证据确实被加入提交', False,
                     '期望 {0}，实际 staged {1} 个'.format(expected_manifest, len(staged)))
                result['status'] = STATUS_FAIL
                result['detail'] = 'git add 未真正加入证据文件（很可能被忽略规则吞掉），已中止推送'
                print(json.dumps(result, ensure_ascii=False))
                return 1
            else:
                step('本次证据确实被加入提交', True, '{0} 个文件'.format(len(staged)))

            code, out = git(worktree, 'diff', '--cached', '--quiet')
            if code == 0:
                result['status'] = STATUS_ALREADY
                result['detail'] = '同一 run_id 内容未变化，未产生新提交'
                result['remote_sha'] = remote_sha(args.remote, args.branch)
                step('提交（幂等：内容未变化）', True, 'ALREADY_PUBLISHED')
            else:
                message = ('evidence({0}): publish redacted acceptance package\n\n'
                           'source_commit: {1}\nsource_run_id: {2}\n'
                           'archive_sha256: {3}\nredacted: true\n'.format(
                               run_id, source_commit, run_id, archive_digest))
                code, out = git(worktree, 'commit', '-m', message)
                if not step('提交到证据分支', code == 0, out.strip()[-300:]):
                    result['status'] = STATUS_FAIL
                    print(json.dumps(result, ensure_ascii=False))
                    return 1
                local_sha = git(worktree, 'rev-parse', 'HEAD')[1].strip()
                result['local_commit_sha'] = local_sha

                # 最终闸门：校验**提交后的结果树**，而不是 diff。
                # diff 只反映本次相对父提交的改动，看不到从父提交继承来的内容 ——
                # 第一版正因只看 diff，把 426 个源码文件随证据一起推了上去。
                tree = git(worktree, 'ls-tree', '-r', '--name-only', 'HEAD')[1].split()
                prefix = dest_rel.replace(os.sep, '/') + '/'
                outside = sorted(p for p in tree if p.strip() and not p.startswith(prefix))
                if outside:
                    step('结果树只含证据文件（按树校验，非按 diff）', False,
                         '越界 {0} 个，例如 {1}'.format(len(outside), outside[:5]))
                    result['status'] = STATUS_FAIL
                    result['detail'] = '证据分支树内容越界，已中止推送'
                    print(json.dumps(result, ensure_ascii=False))
                    return 1
                if expected_manifest not in tree:
                    step('结果树包含本次证据 manifest', False, expected_manifest)
                    result['status'] = STATUS_FAIL
                    print(json.dumps(result, ensure_ascii=False))
                    return 1
                step('结果树只含证据文件（按树校验，非按 diff）', True,
                     '{0} 个文件，全部位于 {1}'.format(len(tree), dest_rel))

                if args.no_push:
                    result['status'] = STATUS_NO_CHANGES
                    result['detail'] = '--no-push：已提交到隔离 worktree，未推送'
                else:
                    pushed = False
                    for attempt in range(1, args.max_retries + 1):
                        code, out = git(worktree, 'push', args.remote,
                                        'HEAD:refs/heads/{0}'.format(args.branch), timeout=300)
                        if code == 0:
                            pushed = True
                            step('推送到 {0}/{1}（第 {2} 次尝试）'.format(
                                args.remote, args.branch, attempt), True, 'ok')
                            break
                        step('推送到 {0}/{1}（第 {2} 次尝试）'.format(
                            args.remote, args.branch, attempt), False, out.strip()[-200:])
                        # 非快进：先取回远程再 rebase，绝不 force push
                        rc, _ = run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch],
                                    timeout=300)
                        if rc == 0:
                            rc2, out2 = git(worktree, 'rebase', 'FETCH_HEAD', timeout=300)
                            if rc2 != 0:
                                git(worktree, 'rebase', '--abort')
                                step('非快进冲突处理', False, out2.strip()[-200:])
                                break
                    if pushed:
                        result['status'] = STATUS_PUBLISHED
                        result['remote_sha'] = remote_sha(args.remote, args.branch)
                        # 远程复核：必须**重新 fetch** 后再看树。
                        # 直接读 FETCH_HEAD 会拿到推送前的旧引用，产生假失败。
                        run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch],
                            timeout=300)
                        rc, listing = run(['git', '-C', REPO_ROOT, 'ls-tree', '-r',
                                           '--name-only', 'FETCH_HEAD'], timeout=120)
                        top = {line.split('/')[0] for line in listing.splitlines() if line.strip()}
                        unexpected = sorted(t for t in top if t != 'artifacts')
                        result['remote_tree_ok'] = not unexpected
                        if unexpected:
                            step('远程树只含证据目录', False, '发现额外顶层条目: {0}'.format(unexpected))
                            result['status'] = STATUS_BLOCKED
                            result['detail'] = '远程证据分支出现非证据内容，请人工处理'
                        else:
                            step('远程树只含证据目录', True, 'ok')
                    else:
                        result['status'] = STATUS_BLOCKED
                        result['detail'] = ('推送失败（网络/权限/冲突）：本地待发布产物已保留，'
                                            '可修复后重试')
                        result['retry_command'] = (
                            'python3 scripts/publish_acceptance.py --run-id {0}'.format(run_id))
        finally:
            git(REPO_ROOT, 'worktree', 'remove', '--force', worktree)
            git(REPO_ROOT, 'worktree', 'prune')
    finally:
        lock_ctx.__exit__(None, None, None)

    repo_slug = 'godzwp117/RosSystem'
    result['evidence_url'] = 'https://github.com/{0}/tree/{1}/artifacts/acceptance/published/{2}'.format(
        repo_slug, args.branch, run_id)
    result['finished_at'] = utc_now()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in (STATUS_PUBLISHED, STATUS_ALREADY, 'DRY_RUN',
                                     STATUS_NO_CHANGES) else 1


def remove_published_run(args) -> int:
    """从证据分支移除某个已发布的 run（用于撤回误发布的测试包）。

    使用普通提交删除文件，不做强推、不改写历史，删除动作本身留在提交记录里可审计。
    """
    run_id = args.remove_run
    if not remote_branch_exists(args.remote, args.branch):
        print('ERROR: 证据分支不存在: {0}/{1}'.format(args.remote, args.branch))
        return 2
    run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch], timeout=300)
    worktree = tempfile.mkdtemp(prefix='rg_evidence_rm_')
    os.rmdir(worktree)
    try:
        code, out = run(['git', '-C', REPO_ROOT, 'worktree', 'add', '--detach', worktree,
                         'FETCH_HEAD'], timeout=300)
        if code != 0:
            print('ERROR: 创建 worktree 失败: {0}'.format(out.strip()[-200:]))
            return 1
        prefix = 'artifacts/acceptance/published/'
        listing = git(worktree, 'ls-tree', '-r', '--name-only', 'HEAD')[1].split()
        targets = sorted(p for p in listing if p.strip().startswith(prefix + run_id)
                         or p.strip() == prefix + run_id + '.tar.gz'
                         or p.strip() == prefix + run_id + '.tar.gz.sha256'
                         or p.strip() == prefix + run_id + '.publish.json')
        if not targets:
            print('NOTHING_TO_REMOVE {0}'.format(run_id))
            return 0
        for i in range(0, len(targets), 200):
            git(worktree, 'rm', '-q', '--ignore-unmatch', '--', *targets[i:i + 200])
        code, out = git(worktree, 'commit', '-m',
                        'evidence({0}): remove published package\n\n'
                        '撤回测试包；普通提交删除，历史保留可审计。'.format(run_id))
        if code != 0:
            print('ERROR: 提交失败: {0}'.format(out.strip()[-200:]))
            return 1
        code, out = git(worktree, 'push', args.remote,
                        'HEAD:refs/heads/{0}'.format(args.branch), timeout=300)
        if code != 0:
            run(['git', '-C', REPO_ROOT, 'fetch', args.remote, args.branch], timeout=300)
            git(worktree, 'rebase', 'FETCH_HEAD')
            code, out = git(worktree, 'push', args.remote,
                            'HEAD:refs/heads/{0}'.format(args.branch), timeout=300)
        print('REMOVED {0} files={1} push_exit={2}'.format(run_id, len(targets), code))
        return 0 if code == 0 else 1
    finally:
        git(REPO_ROOT, 'worktree', 'remove', '--force', worktree)
        git(REPO_ROOT, 'worktree', 'prune')


PUBLISHED_README = """# published/ — 可公开发布的脱敏验收证据

本目录由 `scripts/publish_acceptance.py` 自动生成并推送到证据分支。

* 每个 `<run_id>/` 是一次验收运行的**脱敏公开副本**；
* `<run_id>.tar.gz` 为同内容的归档，`.sha256` 为其校验值；
* `file_hashes.json` 登记的是**脱敏后**文件的 SHA-256；
* 原始（未脱敏）证据包仅保存在受控本地环境的
  `artifacts/acceptance/exports/<run_id>/`，可通过
  `manifest.redaction.source_package_sha256` 在本地比对；
* 脱敏映射表**不随包发布**，无法据此还原真实主机身份。

校验方式：

```bash
python3 scripts/verify_acceptance.py artifacts/acceptance/published/<run_id>
python3 scripts/check_evidence_safety.py --path artifacts/acceptance/published/<run_id>
```
"""


if __name__ == '__main__':
    sys.exit(main())
