#!/usr/bin/env python3
"""Generate paper SVGs from real evidence (no synthetic curves)."""
from __future__ import annotations
import csv, json, statistics
from pathlib import Path
OUT=Path(__file__).resolve().parent/'figures'; OUT.mkdir(exist_ok=True)
FONT='font-family="DejaVu Sans, Arial, sans-serif"'
COL={'PASS':'#2e7d32','BLOCKED':'#c62828','FAIL':'#c62828','NOT_VERIFIED':'#ef6c00','NOT_RUN':'#616161','FALSE':'#c62828','PASS_LAB':'#1565c0'}
def svg(w,h,body): return f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">{body}</svg>\n'
def box(x,y,w,h,fill='#fff',stroke='#333',rx=8): return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>'
def text(x,y,s,size=14,fill='#111',anchor='start',weight='normal'):
    return f'<text x="{x}" y="{y}" {FONT} font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">{s}</text>'
def arrow(x1,y1,x2,y2): return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#455a64" stroke-width="2" marker-end="url(#a)"/>'
# fig1
b=[f'<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#455a64"/></marker></defs>']
b.append(text(600,30,'RosSystem 1.1.0 跨层安全架构（实验室）',20,anchor='middle',weight='bold'))
for i,(x,label,sub) in enumerate([(60,'M1 通信风险','gate=false'),(300,'M2 当前身份','Ed25519/LAB'),(540,'M3 任务风险','advisory')]):
    b.append(box(x,70,200,90,'#e3f2fd')); b.append(text(x+100,105,label,14,anchor='middle',weight='bold')); b.append(text(x+100,132,sub,12,anchor='middle'))
b.append(arrow(360,160,360,195)); b.append(box(200,195,800,70,'#fff3e0')); b.append(text(600,235,'F0 联合准入（本地核验 + 三状态门）',16,anchor='middle',weight='bold'))
b.append(arrow(600,265,600,300)); b.append(box(380,300,440,60,'#f3e5f5')); b.append(text(600,336,'Planner 提交（仅 READY）',15,anchor='middle',weight='bold'))
b.append(arrow(600,360,600,395)); b.append(box(230,395,740,95,'#e8f5e9')); b.append(text(600,425,'Gateway：独立身份再核验 + TaskPolicy（权威）',15,anchor='middle',weight='bold')); b.append(text(600,452,'ALLOW only → /rg/nav_execute；G4：身份 ALLOW + 策略 BLOCK',12,anchor='middle'))
b.append(arrow(600,490,600,525)); b.append(box(380,525,440,60,'#eceff1')); b.append(text(600,561,'NavigationSim（recorded_only）',15,anchor='middle',weight='bold'))
b.append(text(60,620,'DDS-Security：独立 domain / 独立实验室 CA / Enforce 7+6 场景；不覆盖生产部署',12,fill='#37474f'))
(OUT/'fig1_architecture.svg').write_text(svg(1200,660,''.join(b)))
# fig2
b=[f'<defs><marker id="a" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#455a64"/></marker></defs>']
b.append(text(700,30,'真实请求身份验证链（意图主题；Action 级未验证）',20,anchor='middle',weight='bold'))
steps=[(40,'client 进程','真实证书 /planner','#e3f2fd'),(300,'DDS sample','writer GUID + payload','#e8f5e9'),(560,'m2_ingress','GUID→participant→subject','#fff3e0'),(820,'Ed25519 issuer','签名 request_digest','#f3e5f5'),(1080,'F0 / Gateway','独立核验 + nonce','#e0f2f1')]
for x,t,s,c in steps:
    b.append(box(x,80,220,100,c)); b.append(text(x+110,115,t,14,anchor='middle',weight='bold')); b.append(text(x+110,142,s,11,anchor='middle'))
for x in (260,520,780,1040): b.append(arrow(x,130,x+38,130))
b.append(box(80,240,1040,75,'#fff')); b.append(text(600,268,'proof: request_id + resource + operation + task_id + target digest + nonce + exp + subject',13,anchor='middle'))
b.append(text(600,292,'负向：篡改签名/正文/目标、重放 nonce、过期、错主体、未知签发者 → UNKNOWN/DENIED',12,anchor='middle',fill='#b71c1c'))
b.append(box(80,350,500,90,'#ffebee')); b.append(text(330,382,'已验证（实验室）',14,anchor='middle',weight='bold')); b.append(text(330,408,'17/17 意图链；30/30 组件重复',12,anchor='middle'))
b.append(box(620,350,500,90,'#fff8e1')); b.append(text(870,382,'未验证',14,anchor='middle',weight='bold')); b.append(text(870,408,'Action send_goal 原始 DDS reader → NO_ACTION_SERVER',12,anchor='middle'))
(OUT/'fig2_identity_chain.svg').write_text(svg(1400,470,''.join(b)))
# fig3 comparison status matrix
rows=[('DDS Enforce','NOT_RUN','PASS 7/7'),('DDS 负向','NOT_RUN','PASS 6/6'),('M2 当前身份','NOT_VERIFIED','LAB 17/17'),('Gateway 双层','NOT_VERIFIED','LAB 14/14'),('三真实 L1','PASS','PASS'),('三真实 L2','PASS','PASS'),('三真实 L3','BLOCKED','BLOCKED'),('M1 受信任 NORMAL','FAIL','BLOCKED')]
b=[text(520,30,'1.0.3 与 1.1.0 的可比状态（不是性能提升曲线）',18,anchor='middle',weight='bold')]
b.append(text(250,65,'1.0.3',14,anchor='middle',weight='bold')); b.append(text(650,65,'1.1.0',14,anchor='middle',weight='bold'))
for i,(name,a,c) in enumerate(rows):
    y=90+i*52; b.append(text(40,y+20,name,13)); b.append(box(200,y,200,36,'#eceff1')); b.append(text(300,y+23,a,12,anchor='middle'))
    b.append(box(600,y,200,36,'#e8f5e9' if 'PASS' in c else '#ffebee')); b.append(text(700,y+23,c,12,anchor='middle'))
(OUT/'fig3_comparison.svg').write_text(svg(900,540,''.join(b)))
# fig4 latency box/histogram
vals={'issue':[],'verify':[],'gateway':[]}; key={'issue':'issue_ms','verify':'verify_ms','gateway':'gateway_ms'}
with open(Path(__file__).resolve().parent/'data'/'latency_samples.csv') as f:
    for r in csv.DictReader(f):
        for k in vals: vals[k].append(float(r[key[k]]))
b=[text(520,30,'关键组件延迟（30 个真实样本；组件级，非端到端）',18,anchor='middle',weight='bold')]
for i,(k,data) in enumerate(vals.items()):
    y=90+i*120; data=sorted(data); lo,hi=data[0],data[-1]; med=statistics.median(data); p95=data[int(round(.95*(len(data)-1)))]
    b.append(text(40,y+25,k,14)); b.append(f'<line x1="180" y1="{y+20}" x2="820" y2="{y+20}" stroke="#b0bec5"/>')
    scale=lambda v: 180+(v-0)/(3.0)*640
    b.append(f'<rect x="{scale(lo):.1f}" y="{y+5}" width="{max(2,scale(hi)-scale(lo)):.1f}" height="30" fill="#bbdefb" stroke="#1565c0"/>')
    b.append(f'<line x1="{scale(med):.1f}" y1="{y}" x2="{scale(med):.1f}" y2="{y+40}" stroke="#c62828" stroke-width="3"/>')
    b.append(text(scale(med),y-6,f'p50 {med:.2f} ms',11,anchor='middle',fill='#c62828'))
    b.append(text(840,y+25,f'max {hi:.2f}',11))
b.append(text(40,470,'x 轴 0–3 ms；箱体为 min–max，红线为中位数。p95/p99 见 STATISTICAL_ANALYSIS.md。',11,fill='#455a64'))
(OUT/'fig4_latency.svg').write_text(svg(1100,500,''.join(b)))
# fig5 block matrix
cases=[('DDS S3 planner→nav_execute','DDS access control','BLOCK'),('DDS S4 unauthorized','DDS access control','BLOCK'),('N1 wrong CA','DDS authentication','BLOCK'),('N2 tampered p7s','DDS signature','BLOCK'),('N4 cert/dir mismatch','DDS identity','BLOCK'),('M2 invalid signature','Ed25519','BLOCK'),('M2 replay nonce','nonce ledger','BLOCK'),('F0 M1 UNKNOWN','module gate','BLOCK'),('Gateway G2 missing attestation','identity gate','BLOCK'),('Gateway G3 target mismatch','request binding','BLOCK'),('Gateway G4 out-of-region','TaskPolicy','BLOCK'),('P07 M3 BLOCK_RECOMMENDED','F0 module gate','BLOCK')]
b=[text(600,30,'安全阻断案例矩阵（真实运行；BLOCK 均伴随 0 Goal 或未提交）',18,anchor='middle',weight='bold')]
for i,(name,layer,res) in enumerate(cases):
    col=i%3; row=i//3; x=30+col*390; y=70+row*80
    b.append(box(x,y,360,58,'#ffebee')); b.append(text(x+12,y+23,name,11)); b.append(text(x+12,y+45,'layer: '+layer,10,fill='#455a64')); b.append(text(x+345,y+38,res,12,anchor='end',fill='#c62828',weight='bold'))
(OUT/'fig5_block_matrix.svg').write_text(svg(1220,420,''.join(b)))
# fig6 maturity
levels=[('A','受控在线/负向/复现','PASS'),('B','三真正向','BLOCKED (M1)'),('C','DDS+身份实验室','ACHIEVED'),('D','生产候选','NOT_RUN'),('E','生产验证','NOT_RUN')]
b=[text(520,30,'能力成熟度：LEVEL C（已完成）与 B/D/E 的缺口',18,anchor='middle',weight='bold')]
for i,(lv,desc,st) in enumerate(levels):
    y=80+i*75; key_status=st.split()[0]
    color={'PASS':'#e8f5e9','ACHIEVED':'#1565c0','BLOCKED':'#ffebee','NOT_RUN':'#eceff1'}[key_status]
    fill='#1565c0' if key_status=='ACHIEVED' else ('#ffcdd2' if key_status=='BLOCKED' else '#eceff1')
    b.append(box(60,y,880,55,fill)); b.append(text(85,y+35,'LEVEL '+lv,16,weight='bold',fill='#fff' if st=='ACHIEVED' else '#111')); b.append(text(230,y+35,desc,14,fill='#fff' if st=='ACHIEVED' else '#111')); b.append(text(900,y+35,st,13,anchor='end',fill='#fff' if st=='ACHIEVED' else '#111',weight='bold'))
b.append(text(60,490,'C 的边界：临时 CA、意图主题、文件 side channel、同宿主复现；不是生产。',12,fill='#455a64'))
(OUT/'fig6_maturity.svg').write_text(svg(1000,520,''.join(b)))
print('figures written', len(list(OUT.glob('*.svg'))))
