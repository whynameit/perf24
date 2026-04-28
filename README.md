# perf24

`perf24` 是一个面向 Linux 服务器的 7x24 持续 CPU Profiling 采集工具。
## 项目结构

```
perf24/
├── src/
│   └── perf24/
│       ├── __init__.py       # 版本号定义
│       ├── cli.py            # 命令行入口，定义所有子命令
│       ├── collector.py      # 采集核心：启动/停止 perf，管理后台进程
│       ├── config.py         # 配置文件解析（TOML格式），定义所有默认参数
│       ├── flamegraph.py     # SVG 火焰图渲染器，纯 Python 实现无外部依赖
│       ├── query.py          # 时间点检索：扫描分片索引，解析 perf script 输出
│       └── systemd.py        # 生成 systemd service 单元文件
├── tests/
│   ├── test_config.py        # 测试配置解析和 perf 命令行构建
│   ├── test_flamegraph.py    # 测试 SVG 火焰图渲染逻辑
│   ├── test_query.py         # 测试时间片检索和调用栈解析
│   └── test_perf24.py        # 集成测试（整体流程验证）
├── systemd/
│   └── perf24.service        # systemd 服务模板（生产部署用）
└── README.md                 # 使用说明与设计说明
```

### 运行时数据目录结构

```
/var/lib/perf24/
├── data/                          # perf 原始采样数据
│   ├── perf.data.20260428T145100  # 每分钟一个分片
│   ├── perf.data.20260428T145200  # 自动滚动覆盖旧文件
│   └── ...
└── logs/
    └── collector.log              # 采集进程日志

/var/run/perf24/
└── perf24.pid                     # 后台进程 PID 文件
```


## 设计说明

### 为什么用"分片滚动保存"

持续采集如果写入单个文件，运行数天后磁盘会被撑爆。
本工具使用 `perf record --switch-output` 参数，每隔固定时间（默认1分钟）
自动切换到新文件，同时通过 `--switch-max-files` 限制最大保留文件数，
旧文件自动删除，磁盘占用始终维持在可控范围内。

### 如何实现"时间点检索"

每个分片文件生成后，工具将其起止时间戳写入索引文件
`metadata/segments.jsonl`，每行一条JSON记录。

查询时：
1. 读取索引文件，找到时间窗口包含目标时间点的分片
2. 若无精确匹配，则找距离最近的分片（前后各取一个候选，比较距离）
3. 对命中的分片执行 `perf script` 解析调用栈，生成火焰图

这种基于索引文件的线性扫描在分片数量有限（默认保留7天=10080片）
时性能完全够用，无需二分查找。

它的思路不是让单个 `perf record` 无限长跑，而是把采样切成固定时间片持续落盘：

- 后台常驻采集 `perf.data`
- 每个时间片生成一个独立 segment
- 维护一个轻量索引，按时间点快速定位对应的 segment
- 在问题发生后，直接按时间点导出火焰图 SVG

这样既能保留历史现场，也避免单个 `perf.data` 无限膨胀难以回放。

## 使用说明

### 环境要求

- Linux 内核 4.x+（推荐 5.x+）
- Python 3.10+
- perf 工具：`sudo apt install linux-tools-common linux-tools-generic`
- py-spy（本地演示环境火焰图生成）：`pip install py-spy`
- 安装依赖：`pip install tomli`（Python 3.10 以下需要）

### 安装

```bash
git clone https://github.com/whynameit/perf24.git
cd perf24
export PYTHONPATH=$(pwd)/src
```

### 第一步：生成配置文件

```bash
python3 -m perf24.cli init --config /etc/perf24.toml
```

配置文件关键参数说明：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `collect.freq` | 99 | 每秒采样次数 |
| `collect.segment_duration` | 1m | 每个分片时长 |
| `collect.retain_segments` | 10080 | 最多保留分片数（7天） |
| `paths.data_dir` | /var/lib/perf24/data | 数据存储目录 |

### 第二步：启动后台采集

> **注意**：WSL2 环境下需要手动指定 `PYTHONPATH`，完整 Linux 环境安装后可直接使用 `perf24` 命令。
> WSL2 下 perf 采集受内核限制，`run` 命令需在完整 Linux 环境执行。

```bash
# 前台运行（调试用）
sudo PYTHONPATH=$(pwd)/src python3 -m perf24.cli run --config /etc/perf24.toml

# 后台常驻运行
sudo PYTHONPATH=$(pwd)/src python3 -m perf24.cli start --config /etc/perf24.toml

# 查看运行状态
sudo PYTHONPATH=$(pwd)/src python3 -m perf24.cli status --config /etc/perf24.toml

# 停止采集
sudo PYTHONPATH=$(pwd)/src python3 -m perf24.cli stop --config /etc/perf24.toml
```

### 第三步：出问题时查询指定时间点

先制造 CPU 压力（模拟生产事故）：

```bash
python3 -c "
import math
while True:
    math.factorial(10000)
" &
```

记录当前时间（出问题的时间点）：

```bash
date "+%Y-%m-%d %H:%M:%S"
```

等待 2 分钟后，查询该时间点附近的分片：

```bash
sudo PYTHONPATH=$(pwd)/src python3 -m perf24.cli locate \
  --config /etc/perf24.toml \
  --at "填入上面date输出的时间" \
  --before 30s \
  --after 30s
```

停止压力进程：

```bash
kill %1
```
### 第四步：生成火焰图

**生产环境（完整 Linux，perf 符号完整）：**

```bash
sudo python3 -m perf24.cli export-flamegraph \
  --config /etc/perf24.toml \
  --at "2026-04-28 14:52:00" \
  --before 30s \
  --after 30s \
  --output ./flamegraph.svg
```

**本地演示环境（WSL2，使用 py-spy）：**

> WSL2 使用微软定制内核，缺少对应的 debuginfo 符号包，perf 生成的火焰图函数名显示为 unknown。
> 本地演示改用 py-spy，采样原理相同，函数名显示完整。

```bash
# 启动目标进程（模拟 CPU 压力）
python3 -c "
import math
while True:
    math.factorial(10000)
" &

# 采样 15 秒并生成火焰图
sudo $(which py-spy) record \
  -o ./flamegraph.svg \
  --pid $! \
  --duration 15

# 停止压力进程
kill %1
```

用浏览器打开 `flamegraph.svg`，宽度越大的色块表示 CPU 占用越高，即为根因。
```bash
explorer.exe "$(wslpath -w ./flamegraph.svg)"
```
若失败选择手动打开

### 可选：按进程名或 PID 过滤（生产环境）

```bash
# 只看 nginx 进程
sudo python3 -m perf24.cli export-flamegraph \
  --config /etc/perf24.toml \
  --at "2026-04-28 14:52:00" \
  --output ./flamegraph.svg \
  --comm nginx

# 只看指定 PID
sudo python3 -m perf24.cli export-flamegraph \
  --config /etc/perf24.toml \
  --at "2026-04-28 14:52:00" \
  --output ./flamegraph.svg \
  --pid 1234
```

### 生产环境部署（systemd）

```bash
# 生成 systemd service 文件
python3 -m perf24.cli render-systemd \
  --config /etc/perf24.toml \
  --binary perf24 > /etc/systemd/system/perf24.service

# 启用开机自启
sudo systemctl enable --now perf24
sudo systemctl status perf24
```

### 运行测试

```bash
# 单元测试
python3 -m unittest discover -s tests -v

# 验证 perf 命令行参数正确性
sudo python3 -m perf24.cli doctor --config /etc/perf24.toml
```


## 已知边界

- 这是按时间片保存现场，不是纳秒级精确回放
- 一个 segment 内只包含该时间窗口内的样本
- 如果故障持续时间很短，建议把 `segment-seconds` 调低到 `15` 或 `30`
- 如果机器 CPU 数量很多、负载很高，`perf.data` 体积会增长较快，需要结合 retention 做容量规划

## 后续可扩展方向

- 对接 `systemd journal` 或告警平台，自动拉取异常时间点生成图
- 支持按 PID / cgroup / 进程名分流采样
- 支持生成热点函数 TopN 摘要
- 支持自动压缩历史 segment
