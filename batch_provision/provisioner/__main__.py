"""Entry: python -m provisioner [config.toml]  — runs all accounts in parallel."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, log, native
from .worker import AccountJob, LaunchThrottle

ROOT = Path(__file__).resolve().parent.parent
STATUS_TEXT = {'created': '已建', 'exists': '已存在', 'failed': '被拒绝', 'uncertain': '结果不确定',
               'no_slot': '没有空槽', None: '没尝试'}


def failure_rows(results, role_details):
    """One row per account that is not complete. role_details: {account: {role: state dict}}."""
    rows = []
    for r in results:
        if r['ok']:
            continue
        roles = r.get('roles') or {}
        missing = []
        for role, status in roles.items():
            if status in ('created', 'exists'):
                continue
            detail = role_details.get(r['account'], {}).get(role, {})
            why = detail.get('reason') or (f"result={detail['server_result']}" if 'server_result' in detail else '')
            missing.append(f"{role} {STATUS_TEXT.get(status, status)}{'：' + why if why else ''}")
        done = sum(s in ('created', 'exists') for s in roles.values())
        rows.append({'account': r['account'], 'done': done, 'total': len(roles),
                     'missing': '；'.join(missing) or '-', 'step': r.get('step') or '-', 'error': r.get('error') or '-'})
    return rows


def write_report(path, results, role_details, seconds):
    rows = failure_rows(results, role_details)
    lines = [f'# 建角报告 {time.strftime("%Y-%m-%d %H:%M")}', '',
             f'{len(results)} 个账号：完整 {len(results) - len(rows)}，未完成 {len(rows)}，总用时 {seconds:.0f}s。', '']
    if rows:
        lines += ['## 未完成（需要处理）', '', '|账号|已有/应有|没建成的角色|失败步骤|错误|', '|---|---|---|---|---|']
        lines += [f"|{x['account']}|{x['done']}/{x['total']}|{x['missing']}|{x['step']}|{x['error']}|" for x in rows]
        lines += ['', '重新运行 一键建角.cmd 会自动只补没建成的角色（已有的会跳过）。', '']
    else:
        lines += ['全部账号的角色都已建好。', '']
    path.write_text('\n'.join(lines), 'utf-8')
    return rows


def main():
    cfg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'config.toml'
    log_path = log.setup(ROOT / 'logs')
    logger = log.for_account('main')
    logger.info('日志文件: %s', log_path)
    try:
        settings = config.load(cfg_path)
    except Exception as e:
        logger.error('配置错误 (%s): %s', cfg_path, e)
        return 2
    if not native.LAUNCHER.is_file():
        logger.error('缺少 %s，请先运行 native\\build.ps1', native.LAUNCHER)
        return 2
    names = [a.name for a in settings.accounts]
    logger.info('账号 %d 个: %s；同时最多 %d 个窗口；每号 %d 个角色；重登核验=%s；建完保留窗口=%s；空闲内存下限 %dMB',
                len(names), ', '.join(names), settings.parallel, settings.roles_per_account,
                settings.relogin_after_create, settings.keep_windows_open, settings.min_free_memory_mb)

    throttle = LaunchThrottle.of(settings)
    jobs = [AccountJob(settings, a, ROOT, throttle) for a in settings.accounts]
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=settings.parallel, thread_name_prefix='acct') as pool:
        results = list(pool.map(lambda j: j.run(), jobs))

    seconds = time.monotonic() - started
    out = ROOT / 'logs' / (log_path.stem.replace('run_', 'summary_') + '.json')
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), 'utf-8')
    report = ROOT / 'logs' / (log_path.stem.replace('run_', 'provision_report_') + '.md')
    details = {j.account.name: j.state.data.get('roles', {}) for j in jobs}
    rows = write_report(report, results, details, seconds)
    logger.info('=' * 60)
    for r in results:
        logger.info('%-6s %s pid=%s 角色=%s%s', r['account'], '成功' if r['ok'] else '失败', r['pid'], r.get('roles'),
                    f" | 失败步骤={r['step']} {r['error']}" if r['error'] else '')
    for x in rows:
        logger.warning('未完成 %-6s %d/%d  %s', x['account'], x['done'], x['total'], x['missing'])
    logger.info('完成 %d/%d，未完成 %d 个号，总用时 %.1fs。报告: %s', len(results) - len(rows), len(results), len(rows),
                seconds, report)
    return 0 if not rows else 1


if __name__ == '__main__':
    sys.exit(main())
