# M2 Fast DDS 身份 API 实测核查（专项③ P0）

> 代码基准：`be47ccd6c1b19460b65abc0ea8004706383d01d4`
> 容器：`rg_m2`（`ros:jazzy`），Domain **58**，独立于演示域 56/43
> 证据：`artifacts/research/m2/m2api-20261018T160244Z/`

## 1. 软件版本（实测）

| 组件 | 版本 |
| --- | --- |
| ROS | Jazzy |
| `ros-jazzy-fastrtps` | **2.14.6** |
| `ros-jazzy-fastcdr` | 2.2.8 |
| `ros-jazzy-rmw-fastrtps-cpp` | 8.4.4 |

## 2. 调查结论：应用层**可以**获得 DDS 原生已认证身份

这一点推翻了此前"rclpy 不暴露，因此不可行"的假设。

### 2.1 关键 API

```cpp
// fastdds/rtps/builtin/data/ParticipantProxyData.h
class ParticipantProxyData {
public:                       // <-- 注意：public 段
    #if HAVE_SECURITY
    IdentityToken identity_token_;        // 第 100 行
    PermissionsToken permissions_token_;
    security::ParticipantSecurityAttributesMask security_attributes_;
    #endif
...
private:                      // 第 222 行起
};
```

配合：

```cpp
DomainParticipantListener::on_participant_discovery(
    DomainParticipant*, ParticipantDiscoveryInfo&& info);
// info.info 即 const ParticipantProxyData&
```

即：**应用进程在自己的 DomainParticipantListener 里就能读到对端
Participant 的 `identity_token_`**，无需修改中间件、无需私有头文件。

### 2.2 实测结果（两个启用安全的 Participant 互相发现）

见证组件 `src/m2_witness/m2_identity_witness.cpp` 编译并运行后输出：

```json
{"event":"participant_discovered","observer_role":"m2_probe",
 "guid_prefix":"eb.e3.c7.17.12.87.98.cf.05.16.44.78",
 "name":"m2_identity_witness_m2_peer","has_identity":true,
 "security_attributes":2147483655,"permissions_token_properties":2,
 "identity_token":{"class_id":"DDS:Auth:PKI-DH:1.0",
   "properties":{"dds.cert.sn":"/CN=\\/m2_peer",
                 "dds.cert.algo":"EC-prime256v1",
                 "dds.ca.sn":"/CN=sros2CA",
                 "dds.ca.algo":"EC-prime256v1"},
   "property_count":4}}
```

对端视角同样成立（`m2_peer` 观察到 `/CN=\\/m2_probe`）。
**证书主体、CA 主体、算法均来自 DDS-Security 的 PKI-DH 认证结果，不是自报。**

### 2.3 编译与运行命令（可复现）

```bash
g++ -std=c++17 -O2 -I/opt/ros/jazzy/include -I/opt/ros/jazzy/include/fastrtps \
    -I/opt/ros/jazzy/include/fastcdr -DHAVE_SECURITY=1 \
    src/m2_witness/m2_identity_witness.cpp -o /tmp/witness \
    -L/opt/ros/jazzy/lib -lfastrtps -lfastcdr -lpthread

# 独立研究 keystore（绝不使用演示 keystore）
ros2 security create_keystore  $KS
ros2 security create_enclave   $KS /m2_probe
ros2 security create_enclave   $KS /m2_peer

LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=58 \
  /tmp/witness --role m2_probe --keystore $KS --domain 58 --seconds 14 &
LD_LIBRARY_PATH=/opt/ros/jazzy/lib ROS_DOMAIN_ID=58 \
  /tmp/witness --role m2_peer  --keystore $KS --domain 58 --seconds 8
```

### 2.4 未启用安全时的对照

同一程序加 `--no-security` 时不产生 `identity_token`（`has_identity=false`），
说明该字段确实是安全插件在认证成功后填充的，而不是常驻元数据。

## 3. 仍然存在的缺口（必须与上面的成果分开说）

| 能力 | 状态 | 原因 |
| --- | --- | --- |
| 观察到"某已认证 Participant 的身份" | **已实现** | `identity_token_` |
| 把**某条具体请求**绑定到该 Participant | **未实现** | 需要样本级 `SampleInfo.sample_identity().writer_guid()`，且需要一个 DDS 层订阅者订阅该 Action goal 话题（需 typesupport 生成与链接） |
| 从 rclpy 直接取得身份 | **不可行** | rclpy 未暴露 listener 的 ParticipantProxyData |
| 自定义安全插件获取更多信息 | **不可行** | Fast DDS 2.14 未安装 `SecurityManager.h`，公共头文件里也没有插件注册/工厂 API |

`SecurityManager.h` 在全系统 `find /` 下**不存在**；公共头文件中
除 `Authentication.h` 的插件抽象接口外，没有任何 `get_identity` /
`remote_identity` 之类的访问器。这两条是"不可行"结论的直接证据。

## 4. 结论

**`DDS_IDENTITY_SOURCE_VERIFIED` = PASS**
（有编译产物 + 运行日志 + 双向观察 + 无安全对照）

**`DDS_REQUEST_ORIGIN_BOUND` = BLOCKED**
（身份来源已解决；请求级绑定需要 DDS 层 Action 订阅，尚未实现）
