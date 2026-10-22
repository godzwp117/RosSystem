#include <cstdio>
#include "rg_interfaces/action/detail/patrol_navigate__struct.hpp"
#include "rg_interfaces/action/detail/patrol_navigate__rosidl_typesupport_fastrtps_cpp.hpp"
#include "rosidl_typesupport_fastrtps_cpp/message_type_support.h"
int main() {
  const rosidl_message_type_support_t * ts =
    ROSIDL_TYPESUPPORT_INTERFACE__MESSAGE_SYMBOL_NAME(
      rosidl_typesupport_fastrtps_cpp, rg_interfaces, action,
      PatrolNavigate_SendGoal_Request)();
  auto * cb = static_cast<const message_type_support_callbacks_t *>(ts->data);
  std::printf("ns=%s name=%s ser=%p deser=%p size=%p\n",
              cb->message_namespace_, cb->message_name_,
              (void*)cb->cdr_serialize, (void*)cb->cdr_deserialize,
              (void*)cb->get_serialized_size);
  std::printf("sizeof struct=%zu\n", sizeof(rg_interfaces::action::PatrolNavigate_SendGoal_Request));
  return 0;
}
