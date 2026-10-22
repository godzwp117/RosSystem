# RosSystem 参赛作品运行镜像（固定 ROS 2 Jazzy）
# 说明：基础镜像需联网拉取一次；此后可离线复用。
FROM ros:jazzy

ENV DEBIAN_FRONTEND=noninteractive \
    RMW_IMPLEMENTATION=rmw_fastrtps_cpp \
    ROS_DISTRO=jazzy

# 作品运行所需最小依赖（jsonschema 供模块输出校验）
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3-jsonschema \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /ws
CMD ["bash"]
