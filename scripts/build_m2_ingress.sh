#!/usr/bin/env bash
# Build the M2 trusted DDS ingress (reference component) inside the ROS 2 Jazzy
# container. The Action-request typesupport is linked in, but Action capture is
# OFF unless the binary is started with --action-capture.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS="$(cd "$HERE/.." && pwd)"
OUT="${1:-/tmp/m2_ingress}"
INC="$(for d in /opt/ros/jazzy/include/*/; do printf ' -I%s' "$d"; done)"
g++ -std=c++17 -O2 "$WS/src/m2_witness/m2_ingress_witness.cpp" -o "$OUT" \
  -I/opt/ros/jazzy/include $INC \
  -I"$WS/install/rg_interfaces/include/rg_interfaces" \
  -L/opt/ros/jazzy/lib -L"$WS/install/rg_interfaces/lib" \
  -Wl,-rpath,"$WS/install/rg_interfaces/lib" \
  -lrg_interfaces__rosidl_typesupport_fastrtps_cpp \
  -lrg_interfaces__rosidl_generator_c \
  -lrg_interfaces__rosidl_typesupport_c \
  -lrg_interfaces__rosidl_typesupport_cpp \
  -lrosidl_typesupport_fastrtps_cpp -lrosidl_typesupport_cpp \
  -lfastrtps -lfastcdr -lrosidl_runtime_c -lrcutils -lrmw -lpthread
echo "built: $OUT"
