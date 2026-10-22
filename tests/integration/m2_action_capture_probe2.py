#!/usr/bin/env python3
from __future__ import annotations
import json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT/'tests'/'integration'))
import sros2_check as sc
KS=ROOT/'artifacts/research/v110/m2-ingress/keystore'; BIN=Path('/tmp/m2_ingress_action'); DOMAIN=45
out=ROOT/'artifacts/research/v110/m2-action-probe2'; out.mkdir(parents=True,exist_ok=True)
ledger=out/'action_events.jsonl'; ledger.unlink(missing_ok=True)
sc.EVIDENCE_ROOT=str(ROOT/'tests'/'evidence'); sc.RUN_ID='m2-action-probe2'; sc.KEYSTORE=str(KS)
case=sc.Case('_probe2','probe','ready',secure=True)
nodes,j,a,g=sc.start_stack(case,DOMAIN,True,{'navsim':'/navsim','gateway':'/gateway'},with_operator=False)
print('stack',case.passed)
if not case.passed: sys.exit(1)
wlog=out/'witness.log'
w=subprocess.Popen([str(BIN),'--role','ingress','--keystore',str(KS),'--enclave','/witness','--domain',str(DOMAIN),'--resource','rt/m2/candidate_task','--ledger',str(ledger),'--seconds','25','--action-capture'],cwd=str(ROOT),stdout=open(wlog,'wb'),stderr=subprocess.STDOUT)
time.sleep(4)
try:
 r=sc.run_planner(case,'/planner',DOMAIN,True,'action-capture-002',1.5,1.5,1); print(r['result'])
 time.sleep(3)
finally:
 sc.stop_all(nodes); w.wait(timeout=40)
rows=[json.loads(l) for l in ledger.read_text().splitlines() if l.strip()] if ledger.is_file() else []
print('events',[(x.get('event_kind'),x.get('request_id'),x.get('certificate_subject'),x.get('sender_authenticated')) for x in rows])
print('log',wlog.read_text()[-500:])
