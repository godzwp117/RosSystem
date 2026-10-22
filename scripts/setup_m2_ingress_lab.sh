#!/usr/bin/env bash
# setup_m2_ingress_lab.sh -- TEST_ONLY lab keystore for the M2 trusted DDS ingress.
#
# The production policy (security/policies/minimal_permissions.xml) does not
# grant the pre-admission intent topic, and it must not: widening it to make an
# experiment run would invalidate the least-privilege result. This script
# generates a *separate* research keystore from
# security/policies/research/m2_ingress_lab.xml on a separate domain (45).
#
# Private keys stay under artifacts/research/**/keystore (git-ignored) and are
# never copied into evidence. The script prints only subjects and hashes.
set -uo pipefail

RG_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${RG_SCRIPT_DIR}/lib.sh"

POLICY_HOST="${RG_WS_HOST}/security/policies/research/m2_ingress_lab.xml"
POLICY_CTR="${RG_CONTAINER_WS}/security/policies/research/m2_ingress_lab.xml"
KEYSTORE_HOST="${RG_WS_HOST}/artifacts/research/v110/m2-ingress/keystore"
KEYSTORE_CTR="${RG_CONTAINER_WS}/artifacts/research/v110/m2-ingress/keystore"
DOMAIN="${RG_M2_INGRESS_DOMAIN:-45}"
ENCLAVES="/witness /planner /operator /gateway /navsim /rogue"

if [ ! -f "${POLICY_HOST}" ]; then
  echo "ERROR: research policy missing: ${POLICY_HOST}" >&2
  exit 3
fi
if grep -q '<!--' "${POLICY_HOST}"; then
  echo "ERROR: policy contains XML comments; sros2 0.13.6 falls back to a permissive" >&2
  echo "       default policy before failing. Move explanations to a README." >&2
  exit 3
fi

rm -rf "${KEYSTORE_HOST}"
mkdir -p "$(dirname "${KEYSTORE_HOST}")"

rg_ros "
  export ROS_DOMAIN_ID=${DOMAIN}
  ros2 security create_keystore '${KEYSTORE_CTR}' || exit 1
  ros2 security generate_artifacts -k '${KEYSTORE_CTR}' -e ${ENCLAVES} -p '${POLICY_CTR}' || exit 1
" || { echo 'ERROR: keystore generation failed' >&2; exit 1; }

python3 - "${KEYSTORE_HOST}" "${DOMAIN}" <<'PY' || exit 1
import hashlib
import pathlib
import sys
import xml.etree.ElementTree as ET

keystore = pathlib.Path(sys.argv[1])
domain = sys.argv[2]
expected = {
    'witness': ('CN=/witness', {
        'subscribe': {'rt/m2/candidate_task',
                      'rq/rg/guarded_navigate/_action/send_goalRequest'},
        'publish': {'rr/rg/guarded_navigate/_action/send_goalReply'}}, set()),
    'planner': ('CN=/planner', {
        'publish': {'rt/m2/candidate_task',
                    'rq/rg/guarded_navigate/_action/send_goalRequest'},
        'subscribe': {'rr/rg/guarded_navigate/_action/send_goalReply'}}, set()),
    'operator': ('CN=/operator', {'publish': {'rt/m2/candidate_task'}}, set()),
    'gateway': ('CN=/gateway', {
        'publish': {'rq/rg/nav_execute/_action/send_goalRequest',
                    'rr/rg/guarded_navigate/_action/send_goalReply'},
        'subscribe': {'rr/rg/nav_execute/_action/send_goalReply'}}, set()),
    'navsim': ('CN=/navsim', {
        'subscribe': {'rq/rg/nav_execute/_action/send_goalRequest'},
        'publish': {'rr/rg/nav_execute/_action/send_goalReply'}}, set()),
    'rogue': ('CN=/rogue', {'publish': {'rt/m2/not_the_ingress'}}, set()),
}
errors = []
for name, (subject, directions, _) in expected.items():
    path = keystore / 'enclaves' / name / 'permissions.xml'
    if not path.is_file():
        errors.append('{0}: permissions.xml missing'.format(name))
        continue
    root = ET.fromstring(path.read_bytes())
    grants = [e for e in root.iter() if e.tag.endswith('grant')]
    if len(grants) != 1:
        errors.append('{0}: expected one grant'.format(name))
        continue
    grant = grants[0]
    defaults = [(x.text or '').strip().upper() for x in grant if x.tag.endswith('default')]
    if defaults != ['DENY']:
        errors.append('{0}: default is not DENY ({1})'.format(name, defaults))
    subj = [x.text.strip() for x in grant.iter() if x.tag.endswith('subject_name')]
    if subj != [subject]:
        errors.append('{0}: subject {1} != {2}'.format(name, subj, subject))
    ids = {x.text.strip() for x in grant.iter() if x.tag.endswith('id')}
    if ids != {domain}:
        errors.append('{0}: domain {1} != {2}'.format(name, sorted(ids), domain))
    for tag, wanted in directions.items():
        got = set()
        for direction in grant.iter():
            if direction.tag.endswith(tag):
                got |= {(t.text or '').strip() for t in direction.iter()
                        if t.tag.endswith('topic')}
        if not wanted <= got:
            errors.append('{0}: {1} missing {2} (got {3})'.format(
                name, tag, sorted(wanted), sorted(got)))
    if name == 'rogue':
        text = path.read_text(encoding='utf-8')
        if 'candidate_task' in text:
            errors.append('rogue: must not be allowed on the ingress topic')
if errors:
    for error in errors:
        print('FAIL: ' + error, file=sys.stderr)
    sys.exit(1)
print('M2 INGRESS PERMISSIONS: PASS ({0} enclaves, domain {1})'.format(
    len(expected), domain))
PY

chmod 700 "${KEYSTORE_HOST}" 2>/dev/null || true
chmod -R go-rwx "${KEYSTORE_HOST}" 2>/dev/null || true
echo "[m2-ingress] keystore: ${KEYSTORE_HOST} (git-ignored; no private key leaves this tree)"
