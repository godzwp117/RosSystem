# 故障模块 fixtures

用于验证成员模块验收工具的**有界读取、超时与进程组清理**。
它们**故意**表现为洪水输出、挂起或派生子进程 —— **不是**可用的研究模块。

| 文件 | 故障行为 |
| --- | --- |
| `flood_stdout.py` | 持续向 stdout 洪泛 |
| `flood_stderr.py` | stdout 合法但 stderr 持续洪泛 |
| `hang.py` | 读完输入后挂起不退出 |
| `spawn_child.py` | 派生子进程后自身挂起 |
| `huge_utf8.py` | 输出多字节 UTF-8（按字节计数验证） |
