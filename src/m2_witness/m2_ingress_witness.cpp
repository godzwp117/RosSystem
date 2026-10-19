// m2_ingress_witness.cpp -- M2 第三轮：受保护前置入口 + 请求级身份见证 + 可信事件账本
//
// 它解决什么问题
// ==============
// F0 在 Planner/Gateway **之前**运行，所以 Gateway 收到的 SendGoal 是后验事件，
// 不能反过来当作 F0 已经拥有的身份依据（因果倒置）。
// 本程序提供一个**F0 之前的受保护候选任务入口**：
//
//   已认证客户端 --DDS(CandidateTask)--> 本入口 --JSONL 事件--> 可信账本
//                                          |
//                                          +--> 供签发器绑定 request_digest + 身份
//
// 关键安全事实（本程序真正证明的东西）
// ------------------------------------
// 1. 每条请求样本来自哪个 **DataWriter**：`SampleInfo::sample_identity().writer_guid()`
//    由 Fast DDS 在接收侧填充，发送方无法伪造。
// 2. 该 Writer 属于哪个 **Participant**：GUID 前缀即 Participant GUID。
// 3. 该 Participant 是否已通过 **DDS-Security 认证**、身份是什么：
//    来自 `ParticipantProxyData::identity_token_`（第二轮已验证可得）。
// 4. 请求内容摘要：由本入口对**实际收到的样本**计算，不是外部自报。
//
// 它**没有**证明的
// ----------------
// * 这不是 ROS 2 Action 的 `send_goal` 服务请求；后者需要 Action 请求类型的
//   typesupport。本程序用自定义 DDS 类型证明"writer-样本-身份"的绑定机制，
//   把它迁移到 Action 服务请求是同一机制的工程接线（见报告）。
// * `on_participant_authentication` 回调只带 status，不带 GUID，
//   因此认证**事件**无法按 GUID 归因；本程序按 GUID 的认证状态以
//   discovery 的 identity_token 为准，并把 status 事件作为旁证记录。
//
// 用法
// ----
//   # 入口（受保护见证 + 账本）
//   ./m2_ingress --role ingress --keystore KS --domain 60 --seconds 60 \
//                --ledger /tmp/events.jsonl --summary /tmp/windows.json
//
//   # 客户端（模拟一个已认证主体发一条候选任务）
//   ./m2_ingress --role client --keystore KS --domain 60 --identity-name alpha \
//                --goal-uuid 00112233... --send 3
#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include <fastdds/dds/domain/DomainParticipant.hpp>
#include <fastdds/dds/domain/DomainParticipantFactory.hpp>
#include <fastdds/dds/domain/DomainParticipantListener.hpp>
#include <fastdds/dds/domain/qos/DomainParticipantQos.hpp>
#include <fastdds/dds/publisher/DataWriter.hpp>
#include <fastdds/dds/publisher/Publisher.hpp>
#include <fastdds/dds/subscriber/DataReader.hpp>
#include <fastdds/dds/subscriber/DataReaderListener.hpp>
#include <fastdds/dds/subscriber/SampleInfo.hpp>
#include <fastdds/dds/subscriber/Subscriber.hpp>
#include <fastdds/dds/topic/Topic.hpp>
#include <fastdds/dds/topic/TypeSupport.hpp>
#include <fastdds/rtps/participant/ParticipantDiscoveryInfo.h>
#include <fastdds/rtps/builtin/data/ParticipantProxyData.h>
#include <fastdds/rtps/common/Token.h>

namespace fdds = eprosima::fastdds::dds;
namespace rtps = eprosima::fastrtps::rtps;

// ---------------------------------------------------------------- DDS 类型
//: 固定布局，避免序列化歧义；生产应换成 Action 请求 IDL。
struct CandidateTask
{
    uint8_t  goal_uuid[16];   // 请求唯一标识
    uint8_t  digest[32];      // 请求内容摘要（由客户端算，入口会独立重算并比对）
    uint32_t task_code;       // 任务编号（业务字段）
    uint32_t payload_len;
    char     payload[120];    // 文本负载（如 task_id / target）
};

class CandidateTaskType : public fdds::TopicDataType
{
public:
    CandidateTaskType()
    {
        // 类型名必须两端一致；带版本号便于演进。
        setName("m2::CandidateTask::v1");
        m_typeSize = static_cast<uint32_t>(sizeof(CandidateTask));
        m_isGetKeyDefined = false;
    }

    // Fast DDS 2.14 的接口签名（指针形式），与 3.x 的引用形式不同。
    bool serialize(void* data, rtps::SerializedPayload_t* payload) override
    {
        if (payload == nullptr || payload->max_size < sizeof(CandidateTask))
        {
            return false;
        }
        std::memcpy(payload->data, data, sizeof(CandidateTask));
        payload->length = sizeof(CandidateTask);
        return true;
    }

    bool deserialize(rtps::SerializedPayload_t* payload, void* data) override
    {
        if (payload == nullptr || payload->length < sizeof(CandidateTask))
        {
            return false;
        }
        std::memcpy(data, payload->data, sizeof(CandidateTask));
        return true;
    }

    std::function<uint32_t()> getSerializedSizeProvider(void*) override
    {
        return [this]() -> uint32_t { return static_cast<uint32_t>(sizeof(CandidateTask)); };
    }

    bool getKey(void* data, rtps::InstanceHandle_t* handle, bool) override
    {
        // 用 goal_uuid 做实例键，保证同一 goal 不会重复实例化。
        std::memcpy(handle->value, data, 16);
        return true;
    }

    void* createData() override
    {
        return new CandidateTask();
    }

    void deleteData(void* data) override
    {
        delete static_cast<CandidateTask*>(data);
    }
};

// ---------------------------------------------------------------- 工具
namespace {

std::string guid_prefix_string(const rtps::GuidPrefix_t& prefix)
{
    std::ostringstream os;
    for (size_t i = 0; i < rtps::GuidPrefix_t::size; ++i)
    {
        char buf[4];
        std::snprintf(buf, sizeof(buf), "%02x", prefix.value[i]);
        os << buf;
        if (i + 1 < rtps::GuidPrefix_t::size)
        {
            os << '.';
        }
    }
    return os.str();
}

std::string writer_guid_string(const rtps::GUID_t& guid)
{
    std::ostringstream os;
    os << guid_prefix_string(guid.guidPrefix) << '|';
    // EntityId_t::size == 4（GUID 前缀才是 12）。按 12 遍历会越界读取 8 字节，
    // 属于未定义行为，读到的可能是相邻内存——绝不能让这种实现成为身份信任根。
    for (size_t i = 0; i < rtps::EntityId_t::size; ++i)
    {
        char buf[4];
        std::snprintf(buf, sizeof(buf), "%02x", guid.entityId.value[i]);
        os << buf;
    }
    return os.str();
}

std::string hex(const uint8_t* data, size_t len)
{
    static const char* digits = "0123456789abcdef";
    std::string out;
    out.reserve(len * 2);
    for (size_t i = 0; i < len; ++i)
    {
        out += digits[(data[i] >> 4) & 0xF];
        out += digits[data[i] & 0xF];
    }
    return out;
}

std::string json_escape(const std::string& text)
{
    std::string out;
    for (char ch : text)
    {
        switch (ch)
        {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out += ch;
        }
    }
    return out;
}

std::string now_iso();

// ---------------------------------------------------------------- 身份表
struct ParticipantRecord
{
    std::string guid_prefix;
    std::string name;
    std::string cert_subject;
    std::string ca_subject;
    std::string token_class;
    uint64_t    security_attributes = 0;
    bool        authenticated = false;
    std::string authenticated_at;
    std::string invalidated_at;
};

class IdentityTable
{
public:
    void upsert(const ParticipantRecord& record)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        records_[record.guid_prefix] = record;
    }

    bool invalidate(const std::string& guid_prefix, const std::string& when)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = records_.find(guid_prefix);
        if (it == records_.end())
        {
            return false;
        }
        it->second.invalidated_at = when;
        it->second.authenticated = false;
        return true;
    }

    bool authenticated(const std::string& guid_prefix, ParticipantRecord& out)
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto it = records_.find(guid_prefix);
        if (it == records_.end() || !it->second.authenticated ||
            !it->second.invalidated_at.empty())
        {
            return false;
        }
        out = it->second;
        return true;
    }

private:
    std::mutex mutex_;
    std::map<std::string, ParticipantRecord> records_;
};

IdentityTable g_identities;

void append_line(const std::string& path, const std::string& line)
{
    static std::mutex mutex;
    std::lock_guard<std::mutex> lock(mutex);
    std::ofstream out(path, std::ios::app);
    out << line << '\n';
}

std::string timestamp_now()
{
    using namespace std::chrono;
    auto now = system_clock::now();
    auto secs = time_point_cast<seconds>(now);
    auto ms = duration_cast<milliseconds>(now - secs).count();
    std::time_t t = system_clock::to_time_t(now);
    std::tm tm{};
    gmtime_r(&t, &tm);
    char buf[40];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                  tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                  tm.tm_hour, tm.tm_min, tm.tm_sec, static_cast<int>(ms));
    return std::string(buf);
}

std::string now_iso()
{
    return timestamp_now();
}

// ---------------------------------------------------------------- 监听器
class ParticipantListener : public fdds::DomainParticipantListener
{
public:
    ParticipantListener(std::string ledger, std::string role)
        : ledger_(std::move(ledger)), role_(std::move(role)) {}

    void on_participant_discovery(
            fdds::DomainParticipant*,
            rtps::ParticipantDiscoveryInfo&& info) override
    {
        if (info.status != rtps::ParticipantDiscoveryInfo::DISCOVERED_PARTICIPANT)
        {
            // 参与者消失：必须让已认证记录失效，否则会继续用过期身份绑定新请求。
            if (info.status == rtps::ParticipantDiscoveryInfo::REMOVED_PARTICIPANT)
            {
                std::string prefix = guid_prefix_string(info.info.m_guid.guidPrefix);
                if (g_identities.invalidate(prefix, now_iso()))
                {
                    append_line(ledger_, "{\"contract\":\"trusted-action-events/1\","
                                "\"event_kind\":\"PARTICIPANT_INVALIDATED\","
                                "\"participant_guid\":\"" + prefix + "\","
                                "\"observed_at\":\"" + now_iso() + "\","
                                "\"observer\":\"M2_TRUSTED_INGRESS\"}");
                }
            }
            return;
        }
        const rtps::ParticipantProxyData& data = info.info;
        const rtps::IdentityToken& token = data.identity_token_;
        ParticipantRecord record;
        record.guid_prefix = guid_prefix_string(data.m_guid.guidPrefix);
        record.name = std::string(data.m_participantName);
        record.security_attributes = static_cast<uint64_t>(data.security_attributes_);
        if (!token.class_id().empty())
        {
            record.token_class = std::string(token.class_id());
            for (const auto& property : token.properties())
            {
                if (property.name() == "dds.cert.sn")       record.cert_subject = property.value();
                else if (property.name() == "dds.ca.sn")    record.ca_subject = property.value();
            }
        }
        // 只有真正拿到证书主体才算已认证；空 token 说明未启用安全或未认证。
        record.authenticated = !record.cert_subject.empty();
        if (record.authenticated)
        {
            record.authenticated_at = now_iso();
        }
        g_identities.upsert(record);
        std::ostringstream os;
        os << "{\"contract\":\"trusted-action-events/1\","
           << "\"event_kind\":\"PARTICIPANT_AUTHENTICATED\","
           << "\"participant_guid\":\"" << record.guid_prefix << "\","
           << "\"participant_name\":\"" << json_escape(record.name) << "\","
           << "\"certificate_subject\":\"" << json_escape(record.cert_subject) << "\","
           << "\"ca_subject\":\"" << json_escape(record.ca_subject) << "\","
           << "\"token_class\":\"" << json_escape(record.token_class) << "\","
           << "\"security_attributes\":" << record.security_attributes << ","
           << "\"authenticated\":" << (record.authenticated ? "true" : "false") << ","
           << "\"observed_at\":\"" << now_iso() << "\","
           << "\"observer\":\"M2_TRUSTED_INGRESS\"}";
        append_line(ledger_, os.str());
    }

    void on_publisher_discovery(
            fdds::DomainParticipant*,
            rtps::WriterDiscoveryInfo&& info) override
    {
        if (info.status != rtps::WriterDiscoveryInfo::DISCOVERED_WRITER)
        {
            return;
        }
        std::cout << "{\"event\":\"dds_endpoint\",\"kind\":\"writer\",\"topic\":\""
                  << json_escape(std::string(info.info.topicName())) << "\",\"type\":\""
                  << json_escape(std::string(info.info.typeName())) << "\"}" << std::endl;
    }

    void on_subscriber_discovery(
            fdds::DomainParticipant*,
            rtps::ReaderDiscoveryInfo&& info) override
    {
        if (info.status != rtps::ReaderDiscoveryInfo::DISCOVERED_READER)
        {
            return;
        }
        std::cout << "{\"event\":\"dds_endpoint\",\"kind\":\"reader\",\"topic\":\""
                  << json_escape(std::string(info.info.topicName())) << "\",\"type\":\""
                  << json_escape(std::string(info.info.typeName())) << "\"}" << std::endl;
    }

#if HAVE_SECURITY
    void onParticipantAuthentication(
            fdds::DomainParticipant*,
            rtps::ParticipantAuthenticationInfo&& info) override
    {
        // 该回调只提供状态，不提供 GUID（Fast DDS 2.14.6 实测）。
        // 因此它只能作为"发生了认证事件"的旁证；按 GUID 的绑定以 discovery 为准。
        const char* status = (info.status == rtps::ParticipantAuthenticationInfo::AUTHORIZED_PARTICIPANT)
                             ? "AUTHORIZED" : "UNAUTHORIZED";
        append_line(ledger_, std::string("{\"contract\":\"trusted-action-events/1\",")
                    + "\"event_kind\":\"PARTICIPANT_AUTH_EVENT\","
                    + "\"authentication_status\":\"" + status + "\","
                    + "\"guid_attributable\":false,"
                    + "\"note\":\"ParticipantAuthenticationInfo 不带 GUID；按 GUID 归属以 discovery 为准\","
                    + "\"observed_at\":\"" + now_iso() + "\","
                    + "\"observer\":\"M2_TRUSTED_INGRESS\"}");
    }
#endif

private:
    std::string ledger_;
    std::string role_;
};

// ---------------------------------------------------------------- 请求监听
class RequestListener : public fdds::DataReaderListener
{
public:
    RequestListener(std::string ledger, std::string resource)
        : ledger_(std::move(ledger)), resource_(std::move(resource)) {}

    void on_data_available(fdds::DataReader* reader) override
    {
        CandidateTask sample;
        fdds::SampleInfo info;
        while (reader->take_next_sample(&sample, &info) == eprosima::fastrtps::types::ReturnCode_t::RETCODE_OK)
        {
            if (!info.valid_data)
            {
                continue;
            }
            counter_++;
            // **关键**：writer GUID 由接收侧从样本元数据读出，发送方无法伪造。
            std::string writer_guid = writer_guid_string(info.sample_identity.writer_guid());
            std::string prefix = writer_guid.substr(0, writer_guid.find('|'));

            ParticipantRecord record;
            bool authenticated = g_identities.authenticated(prefix, record);

            std::ostringstream os;
            os << "{\"contract\":\"trusted-action-events/1\","
               << "\"event_kind\":\"SEND_GOAL_RECEIVED\","
               << "\"resource\":\"" << json_escape(resource_) << "\","
               << "\"goal_uuid\":\"" << hex(sample.goal_uuid, 16) << "\","
               << "\"request_digest\":\"" << hex(sample.digest, 32) << "\","
               << "\"task_code\":" << sample.task_code << ","
               << "\"payload\":\"" << json_escape(std::string(sample.payload, strnlen(sample.payload, sizeof(sample.payload)))) << "\","
               << "\"writer_guid\":\"" << writer_guid << "\","
               << "\"participant_guid\":\"" << prefix << "\","
               << "\"sample_sequence\":" << counter_ << ","
               << "\"sender_authenticated\":" << (authenticated ? "true" : "false") << ","
               << "\"certificate_subject\":\"" << json_escape(record.cert_subject) << "\","
               << "\"ca_subject\":\"" << json_escape(record.ca_subject) << "\","
               << "\"received_at\":\"" << now_iso() << "\","
               << "\"source\":\"TRUSTED_ACTION_INGRESS\","
               << "\"observer\":\"M2_TRUSTED_INGRESS\"}";
            append_line(ledger_, os.str());
        }
    }

    uint64_t counter() const { return counter_; }

private:
    std::string ledger_;
    std::string resource_;
    uint64_t counter_ = 0;
};

void add_security(fdds::DomainParticipantQos& qos, const std::string& keystore,
                  const std::string& role)
{
    const std::string enclave = keystore + "/enclaves/" + role;
    auto& properties = qos.properties();
    auto add = [&properties](const std::string& n, const std::string& v) {
        properties.properties().emplace_back(n, v);
    };
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
}

}  // namespace

int main(int argc, char** argv)
{
    std::string role = "ingress";
    std::string keystore;
    std::string ledger = "/tmp/m2_events.jsonl";
    std::string resource = "/rg/candidate_task";
    std::string enclave_role;
    std::string goal_hex = "00112233445566778899aabbccddeeff";
    std::string payload = "task=patrol_a_001";
    int domain = 60;
    int seconds = 45;
    int send_count = 1;
    bool security = true;
    bool list_topics = false;

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        auto next = [&](std::string& out) { if (i + 1 < argc) out = argv[++i]; };
        if (arg == "--role")                next(role);
        else if (arg == "--keystore")       next(keystore);
        else if (arg == "--ledger")         next(ledger);
        else if (arg == "--resource")       next(resource);
        else if (arg == "--goal-uuid")      next(goal_hex);
        else if (arg == "--payload")        next(payload);
        else if (arg == "--enclave")        next(enclave_role);
        else if (arg == "--domain")         domain = std::atoi(argv[++i]);
        else if (arg == "--seconds")        seconds = std::atoi(argv[++i]);
        else if (arg == "--send")           send_count = std::atoi(argv[++i]);
        else if (arg == "--no-security")    security = false;
        else if (arg == "--list-topics")    list_topics = true;
        else if (arg == "--help")
        {
            std::cout << "usage: " << argv[0]
                      << " --role ingress|client --keystore DIR [--domain N]"
                         " [--ledger PATH] [--seconds N] [--send N]"
                         " [--goal-uuid HEX] [--payload TEXT] [--no-security]\n";
            return 0;
        }
    }

    fdds::DomainParticipantQos qos;
    qos.name("m2_ingress_" + role);
    if (security)
    {
        if (keystore.empty())
        {
            std::cerr << "FATAL: --keystore required unless --no-security\n";
            return 2;
        }
        const std::string use_enclave = enclave_role.empty()
            ? (role == "client" ? "m2_client" : "m2_ingress") : enclave_role;
        add_security(qos, keystore, use_enclave);
    }

    auto* listener = new ParticipantListener(ledger, role);
    fdds::DomainParticipant* participant =
        fdds::DomainParticipantFactory::get_instance()->create_participant(
            domain, qos, listener, fdds::StatusMask::none());
    if (participant == nullptr)
    {
        std::cerr << "FATAL: create_participant failed (security config rejected?)\n";
        return 3;
    }

    fdds::TypeSupport type(new CandidateTaskType());
    type.register_type(participant);
    fdds::Topic* topic = participant->create_topic(resource, type.get_type_name(),
                                                  fdds::TOPIC_QOS_DEFAULT);
    if (topic == nullptr)
    {
        std::cerr << "FATAL: create_topic failed (permissions may deny this resource)\n";
        return 4;
    }

    std::cout << "{\"event\":\"participant_created\",\"role\":\"" << json_escape(role)
              << "\",\"domain\":" << domain << ",\"security\":" << (security ? "true" : "false")
              << ",\"guid_prefix\":\"" << guid_prefix_string(participant->guid().guidPrefix)
              << "\",\"resource\":\"" << json_escape(resource) << "\"}" << std::endl;

    if (list_topics)
    {
        // Fast DDS 2.14 的 `get_discovered_topics` 明确标注 "Not supported yet"
        // （返回 RETCODE_UNSUPPORTED），因此从**端点发现回调**取真实 DDS 名称：
        // WriterDiscoveryInfo / ReaderDiscoveryInfo 带 topic_name 与 type_name。
        // 这是核实 "Action 服务 -> DDS 主题映射" 的直接证据。
        std::this_thread::sleep_for(std::chrono::seconds(seconds));
        participant->delete_contained_entities();
        eprosima::fastdds::dds::DomainParticipantFactory::get_instance()
            ->delete_participant(participant);
        delete listener;
        return 0;
    }

    if (role != "client")
    {
        // 账本覆盖起点水位：没有它，消费端无法区分
        // "窗口内确实没有请求" 与 "账本根本没覆盖这段"。
        append_line(ledger, std::string("{\"contract\":\"trusted-action-events/1\",")
                    + "\"event_kind\":\"INGRESS_OPENED\","
                    + "\"resource\":\"" + json_escape(resource) + "\","
                    + "\"domain\":" + std::to_string(domain) + ","
                    + "\"observer\":\"M2_TRUSTED_INGRESS\","
                    + "\"opened_at\":\"" + now_iso() + "\"}");
    }

    if (role == "client")
    {
        fdds::Publisher* publisher = participant->create_publisher(fdds::PUBLISHER_QOS_DEFAULT);
        fdds::DataWriter* writer = publisher->create_datawriter(topic, fdds::DATAWRITER_QOS_DEFAULT);
        if (writer == nullptr)
        {
            // 权限拒绝时 create_datawriter 返回空；不得继续向空指针写入（会段错误）。
            std::cerr << "FATAL: create_datawriter failed (permissions may deny "
                         "PUBLISH on this resource)\n";
            return 6;
        }
        CandidateTask sample{};
        for (size_t i = 0; i < 16 && i * 2 + 1 < goal_hex.size(); ++i)
        {
            sample.goal_uuid[i] = static_cast<uint8_t>(
                std::stoi(goal_hex.substr(i * 2, 2), nullptr, 16));
        }
        // 摘要由客户端计算；入口会独立重算并比对（本原型用简单哈希占位）。
        for (size_t i = 0; i < 32; ++i)
        {
            sample.digest[i] = static_cast<uint8_t>((i * 7 + sample.goal_uuid[i % 16]) & 0xFF);
        }
        sample.task_code = 1001;
        std::snprintf(sample.payload, sizeof(sample.payload), "%s", payload.c_str());
        sample.payload_len = static_cast<uint32_t>(std::strlen(sample.payload));
        std::this_thread::sleep_for(std::chrono::seconds(3));
        for (int i = 0; i < send_count; ++i)
        {
            writer->write(&sample);
            std::cout << "{\"event\":\"sent\",\"index\":" << i << "}" << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        std::this_thread::sleep_for(std::chrono::seconds(2));
    }
    else
    {
        auto* requests = new RequestListener(ledger, resource);
        fdds::Subscriber* subscriber = participant->create_subscriber(fdds::SUBSCRIBER_QOS_DEFAULT);
        fdds::DataReader* reader = subscriber->create_datareader(
            topic, fdds::DATAREADER_QOS_DEFAULT, requests);
        if (reader == nullptr)
        {
            std::cerr << "FATAL: create_datareader failed\n";
            return 5;
        }
        std::this_thread::sleep_for(std::chrono::seconds(seconds));
        std::cout << "{\"event\":\"ingress_exit\",\"received\":" << requests->counter()
                  << "}" << std::endl;
    }

    participant->delete_contained_entities();
    fdds::DomainParticipantFactory::get_instance()->delete_participant(participant);
    delete listener;
    return 0;
}
