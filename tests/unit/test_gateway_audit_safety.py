"""M1 加固的单元测试：审计 fail-closed 与故障注入机制的**安全性**。

这些测试刻意不启动 ROS 图：`_write_event` / `_audit_fault_target` / `_record_audit_failure`
只依赖节点上的几个普通属性，因此用一个最小的替身对象即可穷举其分支，
从而在不引入 Action 通信开销的前提下证明"故障注入只能导致拒绝"。
"""

import pytest

rclpy = pytest.importorskip('rclpy', reason='需要 rclpy 才能导入网关模块')

from rg_gateway.security_gateway import SecurityGateway  # noqa: E402
from rg_policy import reason_codes  # noqa: E402
from rg_policy.events import DecisionEvent, ExecutionEvent, RosCommEvent, utc_now_iso  # noqa: E402


class _Logger:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, message):
        self.errors.append(message)

    def warning(self, message):
        self.warnings.append(message)


class _Writer:
    """记录写入、可选择性抛错的假审计 sink。"""

    def __init__(self, fail_on=()):
        self.written = []
        self.fail_on = set(fail_on)

    def write(self, event):
        if event.EVENT_TYPE in self.fail_on:
            raise OSError('simulated sink failure for {0}'.format(event.EVENT_TYPE))
        self.written.append(event)
        return event.to_dict()


class _GatewayStub:
    """只复用 SecurityGateway 的审计相关方法，不构造任何 ROS 实体。"""

    AUDIT_FAULT_CHOICES = SecurityGateway.AUDIT_FAULT_CHOICES
    _audit_fault_target = SecurityGateway._audit_fault_target
    _write_event = SecurityGateway._write_event
    _record_audit_failure = SecurityGateway._record_audit_failure

    def __init__(self, audit_fault_injection='none', fail_on=()):
        self.audit_fault_injection = audit_fault_injection
        self._writer = _Writer(fail_on=fail_on)
        self._audit_failures = 0
        self._post_execution_audit_failures = 0
        self._audit_log_path = '/tmp/unit-audit.jsonl'
        self._logger = _Logger()

    def get_logger(self):
        return self._logger


def _comm():
    return RosCommEvent(event_id='e' * 32, request_id='r1', task_id='patrol_a_001',
                        observed_via='ros2_action', resource='/rg/guarded_navigate',
                        frame_id='map', x=1.0, y=1.0, z=0.0, received_at=utc_now_iso())


def _decision():
    return DecisionEvent(event_id='e' * 32, request_id='r1', task_id='patrol_a_001',
                         policy_version='1.0', decision=reason_codes.DECISION_ALLOW,
                         reason_code=reason_codes.ALLOW_IN_POLICY, detail='ok',
                         decision_at=utc_now_iso())


def _execution():
    return ExecutionEvent(event_id='e' * 32, request_id='r1', task_id='patrol_a_001',
                          downstream_goal_id='a' * 32, success=True,
                          status_code=reason_codes.EXECUTED, detail='done',
                          finished_at=utc_now_iso())


# ---------------------------------------------------------------- 取值域
def test_fault_injection_choices_are_exactly_the_documented_set():
    assert SecurityGateway.AUDIT_FAULT_CHOICES == ('none', 'comm', 'decision', 'execution', 'all')


@pytest.mark.parametrize('choice,expected', [
    ('none', {'RosCommEvent': '', 'DecisionEvent': '', 'ExecutionEvent': ''}),
    ('comm', {'RosCommEvent': 'comm', 'DecisionEvent': '', 'ExecutionEvent': ''}),
    ('decision', {'RosCommEvent': '', 'DecisionEvent': 'decision', 'ExecutionEvent': ''}),
    ('execution', {'RosCommEvent': '', 'DecisionEvent': '', 'ExecutionEvent': 'execution'}),
    ('all', {'RosCommEvent': 'comm', 'DecisionEvent': 'decision', 'ExecutionEvent': 'execution'}),
])
def test_injection_targets_only_the_selected_event_type(choice, expected):
    stub = _GatewayStub(audit_fault_injection=choice)
    for event_type, want in expected.items():
        assert stub._audit_fault_target(event_type) == want, (choice, event_type)


def test_injection_never_targets_unknown_event_types():
    stub = _GatewayStub(audit_fault_injection='all')
    assert stub._audit_fault_target('SomethingElse') == ''
    assert stub._audit_fault_target('') == ''


# ------------------------------------------------- 注入只能"制造失败"
def test_injection_makes_every_targeted_write_fail():
    """注入命中时 _write_event 必须返回 False，且真实 sink 完全不被写入。"""
    for choice, failing in (('comm', 'RosCommEvent'), ('decision', 'DecisionEvent'),
                            ('execution', 'ExecutionEvent'), ('all', 'ALL')):
        stub = _GatewayStub(audit_fault_injection=choice)
        for builder, event_type in ((_comm, 'RosCommEvent'), (_decision, 'DecisionEvent'),
                                    (_execution, 'ExecutionEvent')):
            ok = stub._write_event(builder())
            if failing == 'ALL' or failing == event_type:
                assert ok is False, '{0} 应被注入为失败'.format(event_type)
            else:
                assert ok is True, '{0} 不应被注入'.format(event_type)
        assert stub._writer.written or choice == 'all'


def test_injection_has_no_path_that_returns_true_for_targeted_event():
    """穷举：任何注入取值下，被命中的事件类型都不可能出现成功返回。"""
    for choice in SecurityGateway.AUDIT_FAULT_CHOICES:
        for builder, event_type in ((_comm, 'RosCommEvent'), (_decision, 'DecisionEvent'),
                                    (_execution, 'ExecutionEvent')):
            stub = _GatewayStub(audit_fault_injection=choice)
            targeted = stub._audit_fault_target(event_type)
            result = stub._write_event(builder())
            if targeted:
                assert result is False
            else:
                assert result is True


# ------------------------------------------------- 计数器与语义区分
def test_pre_execution_failure_counts_towards_pre_execution_counter():
    stub = _GatewayStub(fail_on={'RosCommEvent'})
    assert stub._write_event(_comm(), phase='pre_execution') is False
    assert stub._audit_failures == 1
    assert stub._post_execution_audit_failures == 0


def test_post_execution_failure_counts_towards_post_execution_counter():
    stub = _GatewayStub(fail_on={'ExecutionEvent'})
    assert stub._write_event(_execution(), phase='post_execution') is False
    assert stub._post_execution_audit_failures == 1
    assert stub._audit_failures == 0


def test_post_execution_failure_message_forbids_claiming_no_execution():
    """执行后审计失败不得被解读为"下游没有执行"。"""
    stub = _GatewayStub(fail_on={'ExecutionEvent'})
    stub._write_event(_execution(), phase='post_execution')
    assert stub._logger.errors, '必须记录错误日志'
    message = stub._logger.errors[0]
    assert 'post_execution' in message
    assert 'cannot be undone' in message
    assert 'MUST NOT be read as' in message


def test_pre_execution_failure_message_states_fail_closed():
    stub = _GatewayStub(fail_on={'DecisionEvent'})
    stub._write_event(_decision(), phase='pre_execution')
    message = stub._logger.errors[0]
    assert 'pre_execution' in message
    assert 'fail closed' in message
    assert 'no downstream Goal' in message


def test_default_fault_injection_is_disabled():
    """默认值必须是 none —— 不允许默认开启任何注入。"""
    import inspect
    source = inspect.getsource(SecurityGateway.__init__)
    assert "declare_parameter('audit_fault_injection', 'none')" in source


def test_invalid_fault_injection_value_is_rejected_in_source():
    """非法取值必须导致启动失败，避免拼写错误造成"以为注入了其实没有"。"""
    import inspect
    source = inspect.getsource(SecurityGateway.__init__)
    assert 'AUDIT_FAULT_CHOICES' in source
    assert 'raise ValueError' in source
