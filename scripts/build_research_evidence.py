#!/usr/bin/env python3
"""Build the read-only 1.1.0 research evidence snapshot for the dashboard."""
from __future__ import annotations
import json, datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def main():
    acc=load('artifacts/acceptance/exports/research_v110/acceptance_v110.json')
    mat=load('artifacts/acceptance/exports/research_v110/p01_p12_matrix.json')
    three=load('artifacts/research/v110/three-real/summary.json')
    rep=load('artifacts/research/v110/repeats/v110rep-20261021T195500Z/summary.json')
    dds=load('artifacts/acceptance/exports/m2_sros2_enforce_v110/evidence_manifest.json')
    ddsn=load('artifacts/acceptance/exports/m2_sros2_enforce_v110_negative/evidence_manifest.json')
    m2=load('artifacts/acceptance/exports/m2_lab_identity_v110/evidence_manifest.json')
    gw=load('artifacts/acceptance/exports/m2_gateway_identity_v110/evidence_manifest.json')
    items=[
      {'id':'DDS_ENFORCE','label':'DDS 实验室 Enforce','status':'PASS','value':f"{dds['passed']}/{dds['total']}",'detail':'domain 43；新实验室 CA；S1–S6 + S3C','evidence':'artifacts/acceptance/exports/m2_sros2_enforce_v110'},
      {'id':'DDS_NEGATIVE','label':'DDS 负向（带对照）','status':'PASS','value':f"{ddsn['passed']}/{ddsn['total']}",'detail':'不同 CA、篡改 p7s、证书/目录错配、Enforce 关闭对照','evidence':'artifacts/acceptance/exports/m2_sros2_enforce_v110_negative'},
      {'id':'M2_IDENTITY','label':'M2 当前请求身份（意图主题）','status':'PASS','value':f"{m2['passed']}/{m2['total']}",'detail':'writer GUID→证书主体→request_digest→Ed25519；不是 Action send_goal','evidence':'artifacts/acceptance/exports/m2_lab_identity_v110'},
      {'id':'GATEWAY','label':'Gateway 独立身份 + TaskPolicy','status':'PASS','value':f"{gw['passed']}/{gw['total']}",'detail':'G1 ALLOW/1 Goal；G2/G3 BLOCK/0；G4 身份 ALLOW 但策略 OUT_OF_REGION/0','evidence':'artifacts/acceptance/exports/m2_gateway_identity_v110'},
      {'id':'REPEATS','label':'组件级重复实验','status':'PASS','value':f"{rep['positive_ok']}/{rep['trials']}",'detail':'3/3 负向；verify p50 %.3f ms / p99 %.3f ms；非端到端'%(rep['latency_ms']['verify']['p50'],rep['latency_ms']['verify']['p99']),'evidence':'artifacts/research/v110/repeats/v110rep-20261021T195500Z'},
      {'id':'THREE_REAL_L1','label':'三真实 LEVEL 1','status':three['levels']['THREE_EXTERNAL_CALLED'],'value':three['levels']['THREE_EXTERNAL_CALLED'],'detail':'三个真实 External 进程被调用','evidence':'artifacts/research/v110/three-real/summary.json'},
      {'id':'THREE_REAL_L2','label':'三真实 LEVEL 2','status':three['levels']['THREE_EXTERNAL_VALIDATED'],'value':three['levels']['THREE_EXTERNAL_VALIDATED'],'detail':'Schema 与关联字段校验','evidence':'artifacts/research/v110/three-real/summary.json'},
      {'id':'THREE_REAL_L3','label':'三真正向 LEVEL 3','status':three['levels']['THREE_EXTERNAL_ONLINE_PROCEED'],'value':three['levels']['THREE_EXTERNAL_ONLINE_PROCEED'],'detail':'M1 UNKNOWN → F0 BLOCK；未实现正向','evidence':'artifacts/research/v110/three-real/summary.json'},
      {'id':'M1_GATE','label':'M1 validation gate','status':'FALSE','value':'false','detail':'部署模型 49 维；三真正向被阻断','evidence':'modules/member1_comm/model/comm_risk_model.json'},
      {'id':'P07','label':'P07 M3 阻断（隔离）','status':'PASS','value':'13/13','detail':'真实 M3 BLOCK_RECOMMENDED → F0 BLOCK；M1/M2 MOCK 隔离；不是三真实','evidence':'artifacts/research/v110/p07/p07-20261022T024200Z'},
      {'id':'P09','label':'P09 Planner 超时','status':'PASS','value':'10/10','detail':'Planner RESULT_TIMEOUT；Gateway ALLOW；Goal 1；执行晚于 Planner 退出','evidence':'artifacts/research/v110/p09/p09-20261022T030000Z'},
      {'id':'ACTION_BINDING','label':'Action send_goal 身份','status':'NOT_VERIFIED','value':'—','detail':'原始 DDS reader 破坏服务发现；没有捕获样本','evidence':'artifacts/research/v110/m2-action-probe/summary.json'},
    ]
    doc={
      'contract':'rosystem-research-evidence/1',
      'version':'1.1.0',
      'evidence_class':'ARCHIVED_RESEARCH_EVIDENCE',
      'online_evidence':False,
      'generated_at':datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
      'source_head':'488491f5320a6b83ab199d6da2f21169645b0b24',
      'items':items,
      'p_matrix':{'summary':mat['summary'],'final_level':mat['final_level'],
                  'final_level_name':mat['final_level_name']},
      'acceptance':{'status':acc['acceptance'],'exit_code':acc['exit_code'],
                    'not_run':acc.get('not_run',[])},
      'notice':'归档研究证据，只读；不是本次在线运行。ONLINE_EVIDENCE 仅指当前 controller 运行产生的事实。',
    }
    out=ROOT/'submission/creative-work/dashboard/research_evidence.json'
    out.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(out)
if __name__=='__main__': main()
