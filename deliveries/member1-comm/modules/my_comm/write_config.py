"""Generate a local adapter config. Only comm_risk is replaced."""
import argparse
import json
from pathlib import Path
import sys
import yaml

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,default=Path('training_runs/member1'))
    parser.add_argument('--output',type=Path,default=Path('config/team_modules.local.yaml'))
    args=parser.parse_args()
    directory=(ROOT/args.run_dir).resolve()
    if not directory.is_relative_to((ROOT/'training_runs').resolve()):
        raise ValueError('run-dir must be inside training_runs')
    digest=(directory/'model.sha256').read_text(encoding='utf-8').strip()
    config=yaml.safe_load((ROOT/'config/team_modules.example.yaml').read_text(encoding='utf-8'))
    config['modules']['comm_risk'].update(mode='external',
        command=[sys.executable,str(ROOT/'modules/my_comm/module.py'),'--module','comm_risk',
                 '--model',str(directory/'model.json'),'--model-sha256',digest],allow_fault_injection=False)
    # Runtime interpreter paths in the other modules are resolved locally; implementations stay mock.
    for name in ('identity_trust','task_risk'):
        config['modules'][name]['command'][0]=sys.executable
    target=ROOT/args.output
    target.write_text(yaml.safe_dump(config,allow_unicode=True),encoding='utf-8')
    print(target)


if __name__=='__main__':
    main()
