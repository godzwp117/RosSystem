"""Honest controlled protocol/model tests; none of these are ROSPaCe L2 evidence."""
from __future__ import annotations
import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.ensemble import ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from modules.member1_comm import module as m
from modules.member1_comm.data import reservoir, shard_index
from modules.member1_comm.metrics import evaluate
from modules.member1_comm.train import export_model, fit_preprocess, transform


def envelope(value=-5):
    return {'schema_version':'1.0.0-proposed','run_id':'controlled-unit-run','request_id':'req-unit',
        'created_at':'2026-10-13T12:00:05Z',
        'candidate_action':{'action_resource':'/rg/guarded_navigate','operation':'NAVIGATE','task_id':'patrol_a_001',
            'target':{'frame_id':'map','x':2,'y':2}},
        'observations':[{'source':'/rg/guarded_navigate','kind':'MOCK','observed_at':'2026-10-13T12:00:05Z',
            'detail':{'rospace_comm':{'features':{'feature_names':['rate'],'values':[value]}},
                'f0_runtime':{'communication':{'resource':'/rg/guarded_navigate','resource_type':'Action','operation':'GOAL_SEND'},
                    'request_count':10,'window':{'start':'2026-10-13T12:00:00Z','end':'2026-10-13T12:00:05Z','duration_ms':5000}}}}],
        'evidence_refs':[{'ref':'modules/member1_comm/test_module.py#envelope','kind':'MOCK','note':'synthetic controlled input; not actual ROS traffic'}]}


def artifact():
    return {'format':'member1-numeric-v1','algorithm':'logistic','feature_names':['rate'],'impute':[0.2],
        'mean':[0.0],'scale':[1.0],'weights':[3.0],'intercept':0.0,'threshold':0.5,'validation_gate_passed':False}


@pytest.fixture
def model_file(tmp_path,monkeypatch):
    # Patch only module root for isolation. Contract paths are copied verbatim.
    root=tmp_path/'repo'
    destination=root/'docs/interfaces/schemas'
    destination.mkdir(parents=True)
    for file in (ROOT/'docs/interfaces/schemas').glob('*.json'):
        (destination/file.name).write_bytes(file.read_bytes())
    path=root/'training_runs/test/model.json'
    path.parent.mkdir(parents=True)
    raw=json.dumps(artifact()).encode()
    path.write_bytes(raw)
    monkeypatch.setattr(m,'ROOT',root)
    return path,hashlib.sha256(raw).hexdigest()


def context(model_file,controlled_test=False):
    path,digest=model_file
    return {'model':path,'model_sha256':digest,'controlled_test':controlled_test}


@pytest.mark.parametrize('value,state',[(-5,'NORMAL'),(5,'SUSPICIOUS')])
def test_real_numeric_predictions_and_valid_contract(value,state,model_file):
    env=envelope(value)
    m.validate(env,'module_input')
    result,detail=m.analyse('comm_risk',env,context(model_file,True))
    assert result==state
    output=m.build_output(env,result,detail)
    m.validate(output,'comm_risk_evidence')
    assert output['producer']['source']=='EXTERNAL'
    assert output['evidence_refs'][0]['kind']=='MOCK'
    assert output['window']['duration_ms']==5000
    assert output['frequency_hz']==2
    assert output['anomaly_category'] in {'NONE','UNKNOWN'}


def test_unvalidated_normal_prediction_is_withheld(model_file):
    state,detail=m.analyse('comm_risk',envelope(),context(model_file))
    assert state=='UNKNOWN'
    assert detail['risk_level']=='UNKNOWN'


def test_absent_features_is_schema_valid_unknown(model_file):
    env=envelope()
    del env['observations'][0]['detail']['rospace_comm']
    state,detail=m.analyse('comm_risk',env,context(model_file))
    assert state=='UNKNOWN'
    m.validate(m.build_output(env,state,detail),'comm_risk_evidence')


def test_bad_model_returns_schema_valid_error(model_file):
    state,detail=m.analyse('comm_risk',envelope(),dict(context(model_file),model_sha256='f'*64))
    assert state=='ERROR'
    m.validate(m.build_output(envelope(),state,detail),'comm_risk_evidence')


def test_missing_model_never_defaults_normal(model_file):
    model_file[0].unlink()
    with pytest.raises(FileNotFoundError):
        m.analyse('comm_risk',envelope(),context(model_file))


@pytest.mark.parametrize('field',['request_count','communication','window'])
def test_mapping_cannot_fabricate_required_fields(field,model_file):
    env=envelope()
    del env['observations'][0]['detail']['f0_runtime'][field]
    with pytest.raises(ValueError,match='MAPPING_BLOCKED'):
        m.analyse('comm_risk',env,context(model_file))


@pytest.mark.parametrize('value',[True,float('nan'),float('inf'),'12'])
def test_non_numeric_values_not_coerced(value):
    with pytest.raises(ValueError):
        m.predict(artifact(),{'feature_names':['rate'],'values':[value]})


def test_feature_order_and_shape_rejected():
    for feature in [{'feature_names':['other'],'values':[5]}, {'feature_names':['rate'],'values':[]},None]:
        with pytest.raises(ValueError):
            m.predict(artifact(),feature)


def test_label_in_feature_object_rejected():
    with pytest.raises(ValueError,match='LABEL_LEAKAGE'):
        m.predict(artifact(),{'feature_names':['rate'],'values':[5],'attack':'observe'})


def test_f0_mock_and_business_label_have_no_effect(model_file):
    env=envelope(5)
    first=m.analyse('comm_risk',env,context(model_file))
    env['observations'][0]['detail']['f0_mock']={'comm_risk':{'scenario':'normal'}}
    env['observations'][0]['detail']['attack']='observe'
    env['extensions']={'model':'malicious.joblib','command':['bad']}
    second=m.analyse('comm_risk',env,context(model_file))
    assert first==second


def test_explicit_null_uses_declared_training_imputation(model_file):
    env=envelope(None)
    state,detail=m.analyse('comm_risk',env,context(model_file))
    assert detail['extensions']['member1_comm']['explicit_missing_value_count']==1
    assert any('median imputation' in b for b in detail['basis'])


def test_stale_observation_is_unknown(model_file):
    env=envelope()
    env['created_at']='2026-10-13T12:10:05Z'
    assert m.analyse('comm_risk',env,context(model_file))[0]=='UNKNOWN'


def test_window_semantics_and_provenance_checked(model_file):
    for field,value in [('duration_ms',0),('end','2026-10-13T11:59:59Z')]:
        env=envelope()
        env['observations'][0]['detail']['f0_runtime']['window'][field]=value
        with pytest.raises(ValueError):
            m.analyse('comm_risk',env,context(model_file))
    env=envelope()
    env['evidence_refs'][0]['kind']='RUNTIME_LOG'
    with pytest.raises(ValueError,match='provenance'):
        m.analyse('comm_risk',env,context(model_file))


def test_ambiguous_observations_not_first_match(model_file):
    env=envelope()
    env['observations'].append(copy.deepcopy(env['observations'][0]))
    with pytest.raises(ValueError,match='exactly one'):
        m.analyse('comm_risk',env,context(model_file))


def test_metrics_manual_confusion_matrix():
    # TP=2, FN=1, TN=3, FP=1. No same-function oracle.
    metrics=evaluate(['nmap SYN flood']*3+['observe']*4,[1,1,0,0,0,0,1])
    assert metrics['confusion']=={'tp':2,'tn':3,'fp':1,'fn':1}
    assert metrics['precision']==pytest.approx(2/3)
    assert metrics['recall']==pytest.approx(2/3)
    assert metrics['specificity']==pytest.approx(3/4)
    assert metrics['fpr']==pytest.approx(1/4)
    assert metrics['f1']==pytest.approx(2/3)
    assert metrics['balanced_accuracy']==pytest.approx((2/3+3/4)/2)
    assert metrics['binary_macro_recall']==metrics['balanced_accuracy']
    assert metrics['macro_attack_detection_recall']==pytest.approx(2/3)
    assert metrics['attack_class_recall']['ros2 reflection']['status']=='NOT_EVALUATED'


def test_preprocessing_is_train_only_and_immutable():
    train=np.array([[1,np.nan],[2,4],[3,6]],dtype=float)
    impute,scaler=fit_preprocess(train)
    saved=(impute.copy(),scaler.mean_.copy(),scaler.scale_.copy())
    transform(np.array([[1e10,1e20]]),impute,scaler)
    assert impute[1]==5
    assert np.array_equal(saved[0],impute)
    assert np.array_equal(saved[1],scaler.mean_)
    assert np.array_equal(saved[2],scaler.scale_)


@pytest.mark.parametrize('kind',['logistic','trees'])
def test_numeric_export_matches_estimator(kind):
    rng=np.random.default_rng(42)
    x=rng.normal(size=(100,2)); y=(x[:,0]>0).astype(int)
    impute,scaler=fit_preprocess(x)
    transformed=transform(x,impute,scaler)
    estimator=LogisticRegression() if kind=='logistic' else ExtraTreesClassifier(n_estimators=3,max_depth=4,random_state=42)
    estimator.fit(transformed,y)
    model=export_model(estimator,['x','y'],impute,scaler,0.5,False)
    for i in range(10):
        actual=m.predict(model,{'feature_names':['x','y'],'values':x[i].tolist()})
        assert actual==pytest.approx(estimator.predict_proba(transformed[i:i+1])[0,1],abs=1e-7)


def test_reservoir_includes_headerless_first_row_and_late_blocks():
    import random
    rows=[['observe',str(i)] for i in range(200)]+[['nmap SYN flood',str(i)] for i in range(200,1000)]
    sample,count,labels=reservoir(iter(rows),['attack','value'],100,random.Random(42))
    assert count==1000 and labels=={'observe':200,'nmap SYN flood':800}
    assert any(n>900 for n,_ in sample)
    assert {row[0] for _,row in sample}=={'observe','nmap SYN flood'}
    small,count,_=reservoir(iter(rows[:2]),['attack','value'],10,random.Random(42))
    assert small[0]==(1,rows[0])
    assert count==2


def test_numeric_shard_sort():
    names=['rospace_reduced_10.csv','rospace_reduced_2.csv','rospace_reduced_0.csv']
    assert sorted(names,key=shard_index)==[names[2],names[1],names[0]]


@pytest.mark.parametrize('raw',['{bad','{"x":1,"x":2}','{"x":NaN}','{}'])
def test_cli_invalid_input_fails_closed(raw):
    proc=subprocess.run([sys.executable,str(ROOT/'modules/member1_comm/module.py'),'--model-sha256','f'*64],input=raw,capture_output=True,text=True)
    assert proc.returncode==2
    assert proc.stdout==''


def test_unique_event_ids():
    env=envelope()
    a=m.build_output(env,'UNKNOWN',{})
    b=m.build_output(env,'UNKNOWN',{})
    assert a['event_id']!=b['event_id']
    assert a['request_id']==b['request_id']==env['request_id']


def test_complete_training_pipeline_on_controlled_data(tmp_path):
    # Only a software regression. Does not contribute to real ROSPaCe metrics.
    from modules.member1_comm.train import run
    from collections import Counter
    samples=tmp_path/'samples'
    samples.mkdir()
    rng=np.random.default_rng(100)
    files=[]
    for shard in range(7):
        x=rng.normal(size=(80,2))
        labels=np.where(x[:,0]>0,'nmap SYN flood','observe')
        np.savez_compressed(samples/f'shard_{shard}.npz',x=x,labels=labels,
            timestamps=np.asarray(['controlled-time']*len(labels)))
        files.append({'shard':shard,'sample_file':f'shard_{shard}.npz','missing_fraction':[0,0],
            'sample_labels':dict(Counter(labels.tolist()))})
    manifest={'feature_names':['a','b'],'files':files,'source':'CONTROLLED_UNIT_TEST_ONLY'}
    (samples/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    output=tmp_path/'run'
    report=run(samples,output)
    assert report['split']=={'train':[0,1,2],'validation':[3,4],'test':[5,6]}
    assert report['SESSION_INDEPENDENCE']=='UNVERIFIED'
    assert report['RUNTIME_MONITOR']=='NOT_READY'
    assert report['preprocessing_fit']=='train only; immutable before validation/test'
    assert len(report['validation_comparisons'])==2
    raw=(output/'model.json').read_bytes()
    assert report['model_sha256']==hashlib.sha256(raw).hexdigest()
    assert report['test']['confusion']['tp']>0
    assert report['test']['confusion']['tn']>0
    assert sum(item['sample_count'] for item in report['diagnostics'][0]['sample_label_timestamp_ranges_lexical'].values())==80


def test_streaming_tar_preserves_headerless_first_row(tmp_path):
    import io
    import tarfile
    from modules.member1_comm.data import prepare
    archive = tmp_path/'controlled.tar.gz'
    with tarfile.open(archive,'w:gz') as handle:
        # The official archive actually puts a headerless shard before _0.
        for name,body in [('controlled_1.csv ','t1,nmap SYN flood,2\nt2,observe,3\n'),
                          ('controlled_0.csv','timestamp,attack,value\nt0,observe,1\n')]:
            raw=body.encode()
            info=tarfile.TarInfo(name); info.size=len(raw)
            handle.addfile(info,io.BytesIO(raw))
    output=tmp_path/'samples'
    manifest=prepare(archive,output,['value'],rows_per_shard=100)
    assert [item['full_rows'] for item in manifest['files']]==[1,2]
    assert manifest['files'][1]['archive_member']=='controlled_1.csv '
    assert manifest['files'][1]['normalized_archive_member']=='controlled_1.csv'
    with np.load(output/'shard_1.npz',allow_pickle=False) as rows:
        assert rows['labels'].tolist()==['nmap SYN flood','observe']
        assert rows['x'].tolist()==[[2.0],[3.0]]


@pytest.mark.parametrize('name',['ROSPaCe_reduced.tar.gz','ROSPaCe_reduced.tar.gz.partial'])
def test_unverified_official_archive_rejected_before_reading_csv(tmp_path,name):
    from modules.member1_comm.data import prepare
    archive=tmp_path/name
    archive.write_bytes(b'incomplete')
    with pytest.raises(ValueError,match='incomplete|MD5 mismatch'):
        prepare(archive,tmp_path/'samples',['value'],100)


def test_duplicate_normalized_shards_are_not_silently_overwritten(tmp_path):
    import io
    import tarfile
    from modules.member1_comm.data import prepare
    archive=tmp_path/'duplicate.tar.gz'
    with tarfile.open(archive,'w:gz') as handle:
        for name in ['controlled_0.csv','controlled_0.csv ']:
            raw=b'timestamp,attack,value\nt0,observe,1\n'
            info=tarfile.TarInfo(name); info.size=len(raw)
            handle.addfile(info,io.BytesIO(raw))
    with pytest.raises(ValueError,match='duplicate normalized shard'):
        prepare(archive,tmp_path/'samples',['value'],100)
