# M1 数据审计结果

- 生成时间：2026-10-18T16:00:49Z
- 分片数：15
- 每片抽样行数：20000
- 标签列：第 61 列（共 62 列）

## 采样标签分布

| 标签 | 样本数 | 占比 |
| --- | --- | --- |
| metasploit SYN flood | 149803 | 49.71% |
| observe | 75528 | 25.06% |
| nmap SYN flood | 65466 | 21.72% |
| nmap discovery | 5756 | 1.91% |
| ros2 reconnaissance | 4715 | 1.56% |
| ros2 node crashing | 65 | 0.02% |
| ros2 reflection | 38 | 0.01% |
| attack | 1 | 0.00% |

## 平凡基线（任何模型的最低可接受线）

- 恒预测"攻击" F1 = **0.8567**
- 恒预测"正常" F1 = **0.4008**

> 任何模型若低于恒预测攻击基线，说明它连"一律报警"都不如。

## 分片标签纯度

| 分片 | 主导类别占比 | 标签分布 |
| --- | --- | --- |
| rospace_reduced_0.csv | 61.14% | attack=1, nmap discovery=5756, observe=12275, ros2 reconnaissance=2045 |
| rospace_reduced_1.csv | 86.59% | observe=17385, ros2 reconnaissance=2670, ros2 reflection=22 |
| rospace_reduced_2.csv | 99.70% | observe=20158, ros2 node crashing=45, ros2 reflection=16 |
| rospace_reduced_3.csv | 57.39% | nmap SYN flood=11480, observe=8503, ros2 node crashing=20 |
| rospace_reduced_4.csv | 95.57% | nmap SYN flood=19131, observe=887 |
| rospace_reduced_5.csv | 94.33% | nmap SYN flood=18920, observe=1138 |
| rospace_reduced_6.csv | 79.64% | metasploit SYN flood=3229, nmap SYN flood=15935, observe=846 |
| rospace_reduced_7.csv | 97.77% | metasploit SYN flood=19716, observe=450 |
| rospace_reduced_8.csv | 98.23% | metasploit SYN flood=19665, observe=355 |
| rospace_reduced_9.csv | 99.36% | metasploit SYN flood=19997, observe=129 |
| rospace_reduced_10.csv | 98.63% | metasploit SYN flood=19799, observe=274 |
| rospace_reduced_11.csv | 99.21% | metasploit SYN flood=19920, observe=159 |
| rospace_reduced_12.csv | 99.32% | metasploit SYN flood=19969, observe=136 |
| rospace_reduced_13.csv | 71.75% | metasploit SYN flood=14464, observe=5695 |
| rospace_reduced_14.csv | 64.63% | metasploit SYN flood=13044, observe=7138 |

## 缺失率最高的特征

| 特征 | 平均缺失率 |
| --- | --- |
| `layers.sll.sll.pkttype` | 100.00% |
| `layers.ip.ip.dsfield_tree.ip.dsfield.ecn` | 100.00% |
| `layers.ip.ip.checksum.status` | 100.00% |
| `layers.tcp.tcp.flags_tree.tcp.flags.ack` | 100.00% |
| `layers.tcp.tcp.options_tree.tcp.options.nop` | 100.00% |
| `layers.ipv6.ip.version` | 100.00% |
| `Disk_Read` | 100.00% |
| `Net_Received` | 100.00% |
| `pgpgin` | 84.73% |
| `pgfault` | 80.59% |

## 警告

- 存在单一类别占比 >95% 的分片：文件级划分近似类别划分，在该划分上报告的高指标不能代表泛化能力。
