"""Live secure ROS protocol test with explicitly synthetic communication input.

This executes the external module, F0 adapter, Planner, SecurityGateway and
NavigationSim. It is NOT ROSPaCe evaluation or a live intrusion detector.
Run inside the prepared Jazzy container after setup_sros2.sh for its Domain.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime,timedelta,timezone
from pathlib import Path

import yaml

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain',default='51')
    args=parser.parse_args()
    if not (ROOT/'security/keystore/enclaves/planner/permissions.p7s').exists():
        raise RuntimeError('verified SROS2 keystore required; no insecure fallback')
    name='member1-ros-controlled-'+uuid.uuid4().hex[:12]
    spec=importlib.util.spec_from_file_location('baseline_secure_helpers',ROOT/'tests/integration/sros2_check.py')
    helper=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    helper.RUN_ID=name
    runtime=ROOT/'training_runs'/name
    runtime.mkdir(parents=True)
    evidence=ROOT/'artifacts/member1/ros_controlled_protocol'
    evidence.mkdir(parents=True,exist_ok=True)
    model={'format':'member1-numeric-v1','algorithm':'logistic','feature_names':['rate'],
        'impute':[0.0],'mean':[0.0],'scale':[1.0],'weights':[1.0],'intercept':0.0,
        'threshold':0.5,'validation_gate_passed':False,'RUNTIME_MONITOR':'NOT_READY'}
    raw=json.dumps(model).encode()
    model_path=runtime/'model.json'
    model_path.write_bytes(raw)
    config=yaml.safe_load((ROOT/'config/team_modules.example.yaml').read_text(encoding='utf-8'))
    config['modules']['comm_risk'].update(mode='external',allow_fault_injection=False,
        command=[sys.executable,str(ROOT/'modules/my_comm/module.py'),'--model',str(model_path),
            '--model-sha256',hashlib.sha256(raw).hexdigest(),'--controlled-test'])
    for module in ('identity_trust','task_risk'): config['modules'][module]['command'][0]=sys.executable
    config['adapter']['log_path']=str(runtime/'adapter.jsonl')
    config_path=runtime/'config.yaml'
    config_path.write_text(yaml.safe_dump(config),encoding='utf-8')
    template=json.loads((ROOT/'artifacts/member1/local_evidence/normal.input.json').read_text(encoding='utf-8'))
    case=helper.Case('_stack','Member1 controlled secure protocol','Enforce stack ready',True)
    nodes=[]
    results=[]
    try:
        nodes,journal,audit,_=helper.start_stack(case,args.domain,True,
            {'operator':'/operator','gateway':'/gateway','navsim':'/navsim'})
        if not case.passed: raise RuntimeError('secure stack did not become ready')
        for variant,status in [('normal','NORMAL'),('suspicious','SUSPICIOUS'),('unknown','UNKNOWN'),('error','ERROR')]:
            model_path.write_bytes(b'{bad' if variant=='error' else raw)
            envelope=copy.deepcopy(template)
            now=datetime.now(timezone.utc)
            envelope['created_at']=now.isoformat()
            envelope['run_id']=name
            envelope['request_id']=name+'-'+variant
            observation=envelope['observations'][0]
            observation['observed_at']=now.isoformat()
            observation['detail']['f0_runtime']['window']={
                'start':(now-timedelta(seconds=5)).isoformat(),'end':now.isoformat(),'duration_ms':5000}
            observation['detail']['rospace_comm']['features']['values']=[-5 if variant=='normal' else 5]
            if variant=='unknown': del observation['detail']['rospace_comm']
            observation['detail']['f0_mock']={'identity_trust':{'scenario':'authorized'},'task_risk':{'scenario':'allow'}}
            input_path=runtime/(variant+'.input.json')
            input_path.write_text(json.dumps(envelope),encoding='utf-8')
            before=helper.count_lines(journal)
            env=dict(os.environ,ROS_DOMAIN_ID=args.domain,ROS_SECURITY_ENABLE='true',
                ROS_SECURITY_STRATEGY='Enforce',ROS_SECURITY_KEYSTORE=str(ROOT/'security/keystore'),
                ROS_SECURITY_ENCLAVE_OVERRIDE='/planner')
            command=[sys.executable,str(ROOT/'scripts/team_demo.py'),'--input',str(input_path),
                '--config',str(config_path),'--log',str(runtime/'adapter.jsonl'),'--online','--planner-timeout','45']
            process=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
            output=json.loads(process.stdout)
            communication_record=next(record for record in output['modules'] if record['module']=='comm_risk')
            assert communication_record['status']==status
            delta=helper.count_lines(journal)-before
            request_audit=[row for row in helper.read_jsonl(audit) if row.get('request_id')==envelope['request_id']]
            if variant=='normal':
                assert process.returncode==0
                assert output['decision']=='READY_FOR_GATEWAY_SUBMISSION'
                assert output['online']['submitted'] is True
                assert output['online']['planner_result']['outcome']=='RESULT'
                assert output['online']['planner_result']['status_code']=='EXECUTED'
                assert delta==1
                decision=next(row for row in request_audit if row.get('event_type')=='DecisionEvent')
                execution=next(row for row in request_audit if row.get('event_type')=='ExecutionEvent')
                assert decision['decision']=='ALLOW' and decision['reason_code']=='ALLOW_IN_POLICY'
                goals=[row for row in helper.read_jsonl(journal) if row.get('request_id')==envelope['request_id']]
                assert len(goals)==1 and execution['downstream_goal_id']==goals[0]['goal_id']
            else:
                assert process.returncode!=0
                assert output['reason_code']=='ADAPTER_MODULE_STATUS_NOT_PROCEED'
                assert output['online']['submitted'] is False
                assert delta==0 and not request_audit
            (evidence/(variant+'.adapter.json')).write_text(json.dumps(output,indent=2,ensure_ascii=False),encoding='utf-8')
            results.append({'case':variant,'expected_status':status,'actual_status':communication_record['status'],'result':'PASS',
                'request_id':envelope['request_id'],'decision':output['decision'],
                'reason_code':output['reason_code'],'goal_delta':delta,'gateway_audit_rows':len(request_audit)})
            print(variant,output['decision'],'goal_delta=',delta,flush=True)
        (evidence/'audit.jsonl').write_text(helper.read_text(audit),encoding='utf-8')
        (evidence/'navsim_goals.jsonl').write_text(helper.read_text(journal),encoding='utf-8')
    finally:
        leftovers=helper.stop_all(nodes)
        model_path.write_bytes(raw)
    assert not leftovers
    report={'run_id':name,'security_mode':'Enforce','domain':args.domain,
        'source_kind':'MOCK','model':'CONTROLLED_NUMERIC_FIXTURE_NOT_TRAINED_MODEL',
        'identity_trust':'BASELINE_MOCK','task_risk':'BASELINE_MOCK','cases':results,
        'live_ros_protocol':'PASS','real_detector_online':'NOT_READY','RUNTIME_MONITOR':'NOT_READY',
        'no_leftover_nodes':True,'scope':'Module + adapter + actual secure Gateway/NavigationSim protocol; no IDS effectiveness claim'}
    (evidence/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2),flush=True)
    return 0


if __name__=='__main__': sys.exit(main())
