# src/m2_witness — 辅助参考源码（**不是** colcon 包）

本目录下的两个 .cpp 是 M2 身份见证组件的**参考实现/对照源码**，
用于阅读与审计身份见证的判定逻辑，不参与本作品的构建与运行。

因此：

- 这里**没有** `package.xml`，也**没有** `CMakeLists.txt`；
- `colcon build` 会（正确地）跳过本目录，构建结果为 4 个包；
- 真正参与在线判定的是 `identity_trust/`（M2 评估器）与 F0 的本地核验器。

如果将来要把这两个文件纳入构建，必须先补齐 `package.xml` 与 `CMakeLists.txt`
并声明依赖，而不是为了让 `colcon list` 多显示一个包而强行补文件。
