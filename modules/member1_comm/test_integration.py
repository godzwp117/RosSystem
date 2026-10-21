"""L1: actual CLI/model execution and POSIX adapter four-state integration."""
import copy
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from modules.member1_comm.module import validate
from modules.member1_comm.test_module import artifact,envelope


@pytest.fixture
def run_files():
    directory=ROOT/'training_runs'/('controlled-test-'+uuid.uuid4().hex)
    directory.mkdir(parents=True)
    model=directory/'model.json'
    raw=json.dumps(artifact()).encode()
    model.write_bytes(raw)
    # 适配后的模块默认校验"特征清单一致性"：受控单特征模型必须配套声明
    # 自己的特征清单，否则会被判为 MODEL_FEATURE_LIST_MISMATCH（失败关闭）。
    features=directory/'features.json'
    features.write_text(json.dumps({'feature_names':['rate']}),encoding='utf-8')
    command=[sys.executable,str(ROOT/'modules/member1_comm/module.py'),'--model',str(model),
             '--model-sha256',hashlib.sha256(raw).hexdigest(),
             '--features',str(features),'--controlled-test']
    yield directory,command
    # Retain generated controlled artifacts in ignored training_runs for inspection.


@pytest.mark.parametrize('case,state',[('normal','NORMAL'),('attack','SUSPICIOUS'),('unknown','UNKNOWN'),('error','ERROR')])
def test_cli_four_states(case,state,run_files):
    directory,command=run_files
    env=envelope(-5 if case=='normal' else 5)
    if case=='unknown':
        del env['observations'][0]['detail']['rospace_comm']
    if case=='error':
        (directory/'model.json').write_text('{bad',encoding='utf-8')
    proc=subprocess.run(command,input=json.dumps(env),capture_output=True,text=True,timeout=10)
    assert proc.returncode==0,proc.stderr
    payload=json.loads(proc.stdout)
    validate(payload,'comm_risk_evidence')
    assert payload['status']==state
    assert payload['request_id']==env['request_id']
    assert payload['run_id']==env['run_id']
    assert 'status=' in proc.stderr


@pytest.mark.skipif(os.name!='posix',reason='Baseline team_demo imports POSIX resource; run in Linux/Jazzy environment')
@pytest.mark.parametrize('case,state',[('normal','NORMAL'),('attack','SUSPICIOUS'),('unknown','UNKNOWN'),('error','ERROR')])
def test_actual_adapter_four_states(case,state,run_files):
    directory,command=run_files
    env=envelope(-5 if case=='normal' else 5)
    env['observations'][0]['detail']['f0_mock']={
        'identity_trust':{'scenario':'authorized'},'task_risk':{'scenario':'allow'}}
    if case=='unknown':
        del env['observations'][0]['detail']['rospace_comm']
    if case=='error':
        (directory/'model.json').write_text('{bad',encoding='utf-8')
    config=yaml.safe_load((ROOT/'config/team_modules.example.yaml').read_text(encoding='utf-8'))
    config['modules']['comm_risk'].update(mode='external',command=command,allow_fault_injection=False)
    for name in ('identity_trust','task_risk'):
        config['modules'][name]['command'][0]=sys.executable
    config['adapter']['log_path']=str(directory/'adapter.jsonl')
    path=directory/'team.yaml'
    path.write_text(yaml.safe_dump(config),encoding='utf-8')
    proc=subprocess.run([sys.executable,str(ROOT/'scripts/team_demo.py'),'--input','-', '--config',str(path),
        '--log',str(directory/'adapter.jsonl')],
        input=json.dumps(env),capture_output=True,text=True,timeout=30,cwd=ROOT)
    payload=json.loads(proc.stdout)
    if state=='NORMAL':
        assert proc.returncode==0,proc.stderr
        assert payload['decision']=='READY_FOR_GATEWAY_SUBMISSION'
    else:
        assert proc.returncode!=0
        assert payload['decision']=='ADAPTER_BLOCK'
        assert payload['reason_code']=='ADAPTER_MODULE_STATUS_NOT_PROCEED'
    # Baseline's actual offline contract has only enabled=false; outcome is
    # populated exclusively when an online submission has been requested.
    assert payload['online']=={'enabled':False}
    assert (directory/'adapter.jsonl').exists()
