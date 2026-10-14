"""Build a controlled L1 evidence package; never call these fixtures real L2."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from modules.my_comm.module import strict_json,validate
from modules.my_comm.test_module import artifact,envelope
import yaml

runtime=ROOT/'training_runs/member1_controlled_protocol'
runtime.mkdir(parents=True,exist_ok=True)
evidence=ROOT/'artifacts/member1/local_evidence'
evidence.mkdir(parents=True,exist_ok=True)
raw=json.dumps(artifact()).encode()
model=runtime/'model.json'
model.write_bytes(raw)
digest=hashlib.sha256(raw).hexdigest()
commands=[sys.executable,str(ROOT/'modules/my_comm/module.py'),'--module','comm_risk',
    '--model',str(model),'--model-sha256',digest,'--controlled-test']
config=yaml.safe_load((ROOT/'config/team_modules.example.yaml').read_text(encoding='utf-8'))
config['modules']['comm_risk'].update(mode='external',command=commands,allow_fault_injection=False)
for name in ('identity_trust','task_risk'):
    config['modules'][name]['command'][0]=sys.executable
config['adapter']['log_path']=str(runtime/'adapter.jsonl')
config_path=ROOT/'config/team_modules.member1.controlled.local.yaml'
config_path.write_text(yaml.safe_dump(config),encoding='utf-8')
summary=[]
for case,expected in [('normal','NORMAL'),('suspicious','SUSPICIOUS'),('unknown','UNKNOWN'),('error','ERROR')]:
    env=envelope(-5 if case=='normal' else 5)
    if case=='unknown':
        del env['observations'][0]['detail']['rospace_comm']
    model.write_bytes(raw if case!='error' else b'{bad')
    proc=subprocess.run(commands,input=json.dumps(env),capture_output=True,text=True,timeout=20)
    assert proc.returncode==0,proc.stderr
    payload=strict_json(proc.stdout)
    validate(payload,'comm_risk_evidence')
    assert payload['status']==expected
    (evidence/(case+'.input.json')).write_text(json.dumps(env,indent=2),encoding='utf-8')
    (evidence/(case+'.output.json')).write_text(json.dumps(payload,indent=2),encoding='utf-8')
    summary.append({'case':case,'status':payload['status'],'returncode':proc.returncode,
        'schema':'PASS','test_layer':'L1_CONTROLLED_MODEL_PROTOCOL','source_kind':'MOCK'})
    if os.name=='posix':
        env['observations'][0]['detail']['f0_mock']={
            'identity_trust':{'scenario':'authorized'},'task_risk':{'scenario':'allow'}}
        adapter=subprocess.run([sys.executable,str(ROOT/'scripts/team_demo.py'),'--input','-',
            '--config',str(config_path),'--log',str(runtime/'adapter.jsonl')],
            input=json.dumps(env),cwd=ROOT,capture_output=True,text=True,timeout=30)
        result=strict_json(adapter.stdout)
        expected_decision='READY_FOR_GATEWAY_SUBMISSION' if case=='normal' else 'ADAPTER_BLOCK'
        assert result['decision']==expected_decision
        assert result['online']=={'enabled':False}
        if case!='normal': assert result['reason_code']=='ADAPTER_MODULE_STATUS_NOT_PROCEED'
        (evidence/(case+'.adapter.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
        summary[-1]['actual_adapter']={'decision':result['decision'],'reason_code':result['reason_code'],
            'returncode':adapter.returncode,'online':False}
model.write_bytes(raw)
(runtime/'model.sha256').write_text(digest+'\n',encoding='utf-8')
checker=subprocess.run([sys.executable,str(ROOT/'scripts/check_member_module.py'),'--module','comm_risk',
    '--config','config/team_modules.member1.controlled.local.yaml'],cwd=ROOT,capture_output=True,text=True)
(evidence/'baseline_checker.stderr.txt').write_text(checker.stderr,encoding='utf-8')
(evidence/'baseline_checker.stdout.txt').write_text(checker.stdout,encoding='utf-8')
report={'baseline_sha':'a4c597161d254192b662ee7b8f4d17f76a89cc16', 'research_reference_sha':'470cd4b3be8d3fa4aa2ad9690b1976aacaab93ce',
    'contract':'PROPOSED_V1', 'implementation_type':'EXPERIMENTAL_OFFLINE_PROTOTYPE', 'controlled_protocol':summary,
    'baseline_L1_checker':{'status':'BLOCKED' if os.name!='posix' else 'FAIL', 'returncode':checker.returncode,
        'cause':('baseline POSIX resource import unavailable on Windows' if os.name!='posix' else
            'baseline fixtures supply no real features/runtime metadata; module refuses invented mapping')},
    'old_model_reproduction':'BLOCKED_NO_OLD_MODEL_ARTIFACT',
    'RUNTIME_MONITOR':'NOT_READY',
    'scope':'This runner performs controlled L1 only; it does not assess other experiment layers',
    'other_evidence':{'real_data':'artifacts/member1/offline_experiments/',
        'live_ros_controlled_protocol':'artifacts/member1/ros_controlled_protocol/'},
    'pr_gate':'NOT_MET; draft only, no merge request until unresolved layers reviewed'}
(evidence/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
