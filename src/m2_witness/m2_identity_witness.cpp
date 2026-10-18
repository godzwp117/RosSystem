// m2_identity_witness.cpp -- M2 专项③ P0：验证 Fast DDS 是否把"已认证远端身份"暴露给应用层。
//
// 本程序要回答的问题非常具体：
//   在一个启用 DDS-Security 的域里，**应用进程**能否观察到
//   "对端 Participant 已经通过 PKI-DH 认证，且它的证书身份是什么"？
//
// 为什么这可能可行
// ----------------
// Fast DDS 2.14 的 ParticipantProxyData 里存在**公开**成员
//     IdentityToken identity_token_;      （受 HAVE_SECURITY 保护）
// 而 DomainParticipantListener::on_participant_discovery 会把这个
// ParticipantProxyData 交给应用。如果安全插件在认证成功后填入了该 token，
// 应用就能拿到对端的证书级身份（dds.cert.sn 等），这就是 DDS 原生身份来源。
//
// 本程序把观察结果打成结构化 JSON 行，供上层签发器消费：
//   {"event":"participant_discovered","guid_prefix":"...","name":"...",
//    "identity_token":{"class_id":"...","properties":{...}},
//    "security_attributes":N, "has_identity":true}
//
// 重要限定（不得混淆）
// --------------------
// 即使本程序能拿到 identity_token，它证明的是
//     "某个已认证 Participant 存在于本域"
// 而不是
//     "某条具体 Action 请求由该 Participant 发出"。
// 后者需要样本级 writer GUID → participant GUID 的绑定，见 witness 的 sample 路径。
#include <cstdio>
#include <cstring>
#include <iostream>
#include <map>
#include <sstream>
#include <string>

#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/domain/DomainParticipantListener.hpp>
#include <fastdds/dds/domain/qos/DomainParticipantQos.hpp>
#include <fastdds/rtps/participant/ParticipantDiscoveryInfo.h>
#include <fastdds/rtps/builtin/data/ParticipantProxyData.h>
#include <fastdds/rtps/common/Token.h>

using eprosima::fastdds::dds::DomainParticipant;
using eprosima::fastdds::dds::DomainParticipantFactory;
using eprosima::fastdds::dds::DomainParticipantListener;
using eprosima::fastdds::dds::DomainParticipantQos;
using eprosima::fastdds::dds::StatusMask;
using eprosima::fastrtps::rtps::ParticipantDiscoveryInfo;
using eprosima::fastrtps::rtps::ParticipantProxyData;

namespace {

std::string json_escape(const std::string& text) {
  std::string out;
  for (char ch : text) {
    switch (ch) {
      case '"': out += "\\\""; break;
      case '\\': out += "\\\\"; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default:
        if (static_cast<unsigned char>(ch) < 0x20) {
          char buf[8];
          std::snprintf(buf, sizeof(buf), "\\u%04x", ch);
          out += buf;
        } else {
          out += ch;
        }
    }
  }
  return out;
}

std::string guid_prefix_string(const eprosima::fastrtps::rtps::GuidPrefix_t& prefix) {
  std::ostringstream os;
  for (size_t i = 0; i < 12; ++i) {
    char buf[4];
    std::snprintf(buf, sizeof(buf), "%02x", prefix.value[i]);
    os << buf;
    if (i + 1 < 12) {
      os << '.';
    }
  }
  return os.str();
}

// 把 IdentityToken 的内容转成 JSON。Token = class_id + PropertySeq + BinaryPropertySeq。
// 我们**只**取 class_id 和文本 properties：证书序列号等身份信息在这里，
// binary properties 可能含密钥材料，一律不输出。
std::string identity_token_json(const eprosima::fastrtps::rtps::IdentityToken& token) {
  std::ostringstream os;
  os << "{\"class_id\":\"" << json_escape(token.class_id()) << "\",\"properties\":{";
  bool first = true;
  for (const auto& property : token.properties()) {
    if (!first) {
      os << ',';
    }
    first = false;
    os << '"' << json_escape(property.name()) << "\":\""
       << json_escape(property.value()) << '"';
  }
  os << "},\"property_count\":" << token.properties().size() << "}";
  return os.str();
}

class WitnessListener : public DomainParticipantListener {
 public:
  explicit WitnessListener(std::string role) : role_(std::move(role)) {}

  void on_participant_discovery(
      DomainParticipant*, eprosima::fastrtps::rtps::ParticipantDiscoveryInfo&& info) override {
    if (info.status != eprosima::fastrtps::rtps::ParticipantDiscoveryInfo::DISCOVERED_PARTICIPANT) {
      return;
    }
    const ParticipantProxyData& data = info.info;
    // identity_token_ 是 ParticipantProxyData 的公开成员（受 HAVE_SECURITY 保护）。
    // 若未启用安全，token 为空：class_id 与 properties 都为空。
    const auto& token = data.identity_token_;
    bool has_identity = !token.class_id().empty() || !token.properties().empty();
    std::cout << "{\"event\":\"participant_discovered\",\"observer_role\":\""
              << json_escape(role_) << "\",\"guid_prefix\":\""
              << guid_prefix_string(data.m_guid.guidPrefix) << "\",\"name\":\""
              << json_escape(std::string(data.m_participantName)) << "\",\"has_identity\":"
              << (has_identity ? "true" : "false") << ",\"security_attributes\":"
              << static_cast<unsigned long long>(data.security_attributes_)
              << ",\"permissions_token_properties\":"
              << data.permissions_token_.properties().size()
              << ",\"identity_token\":" << identity_token_json(token) << "}"
              << std::endl;
  }

 private:
  std::string role_;
};

void add_security_properties(DomainParticipantQos& qos, const std::string& keystore,
                             const std::string& role, const std::string& policies) {
  auto& properties = qos.properties();
  auto add = [&properties](const std::string& name, const std::string& value) {
    properties.properties().emplace_back(name, value);
  };
  const std::string enclave = keystore + "/enclaves/" + role;
  add("dds.sec.auth.plugin", "builtin.PKI-DH");
  add("dds.sec.auth.builtin.PKI-DH.identity_ca",
      "file://" + keystore + "/public/identity_ca.cert.pem");
  add("dds.sec.auth.builtin.PKI-DH.identity_certificate",
      "file://" + enclave + "/cert.pem");
  add("dds.sec.auth.builtin.PKI-DH.private_key", "file://" + enclave + "/key.pem");
  add("dds.sec.access.plugin", "builtin.Access-Permissions");
  add("dds.sec.access.builtin.Access-Permissions.permissions_ca",
      "file://" + keystore + "/public/permissions_ca.cert.pem");
  add("dds.sec.access.builtin.Access-Permissions.governance",
      "file://" + keystore + "/enclaves/governance.p7s");
  add("dds.sec.access.builtin.Access-Permissions.permissions",
      "file://" + enclave + "/permissions.p7s");
  add("dds.sec.crypto.plugin", "builtin.AES-GCM-GMAC");
  (void)policies;
}

}  // namespace

int main(int argc, char** argv) {
  std::string role = "witness";
  std::string keystore;
  int domain = 58;
  int seconds = 20;
  bool security = true;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    if (arg == "--role" && i + 1 < argc) {
      role = argv[++i];
    } else if (arg == "--keystore" && i + 1 < argc) {
      keystore = argv[++i];
    } else if (arg == "--domain" && i + 1 < argc) {
      domain = std::atoi(argv[++i]);
    } else if (arg == "--seconds" && i + 1 < argc) {
      seconds = std::atoi(argv[++i]);
    } else if (arg == "--no-security") {
      security = false;
    } else if (arg == "--help") {
      std::cout << "usage: " << argv[0]
                << " [--role NAME] [--keystore DIR] [--domain N] [--seconds N]"
                   " [--no-security]\n";
      return 0;
    }
  }

  DomainParticipantQos qos;
  qos.name("m2_identity_witness_" + role);
  if (security) {
    if (keystore.empty()) {
      std::cerr << "FATAL: --keystore required unless --no-security\n";
      return 2;
    }
    add_security_properties(qos, keystore, role, "");
  }

  auto* listener = new WitnessListener(role);
  DomainParticipant* participant =
      DomainParticipantFactory::get_instance()->create_participant(domain, qos, listener,
                                                                  StatusMask::none());
  if (participant == nullptr) {
    std::cerr << "FATAL: create_participant failed (security config rejected?)\n";
    return 3;
  }
  std::cout << "{\"event\":\"participant_created\",\"role\":\"" << json_escape(role)
            << "\",\"domain\":" << domain << ",\"security\":" << (security ? "true" : "false")
            << ",\"guid_prefix\":\""
            << guid_prefix_string(participant->guid().guidPrefix) << "\"}" << std::endl;

  // 观察窗口：只做发现监听，不创建任何 writer/reader。
  struct timespec ts {
    seconds, 0
  };
  nanosleep(&ts, nullptr);

  DomainParticipantFactory::get_instance()->delete_participant(participant);
  delete listener;
  std::cout << "{\"event\":\"witness_exit\"}" << std::endl;
  return 0;
}
