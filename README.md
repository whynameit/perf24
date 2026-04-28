# perf24

`perf24` 是一个面向 Linux 服务器的 7x24 持续 CPU Profiling 采集工具。

它的思路不是让单个 `perf record` 无限长跑，而是把采样切成固定时间片持续落盘：

- 后台常驻采集 `perf.data`
- 每个时间片生成一个独立 segment
- 维护一个轻量索引，按时间点快速定位对应的 segment
- 在问题发生后，直接按时间点导出火焰图 SVG

这样既能保留历史现场，也避免单个 `perf.data` 无限膨胀难以回放。

## 功能

- `start`: 后台启动常驻采集
- `collect`: 前台持续采集，便于配合 `systemd`
- `stop`: 停止后台采集
- `status`: 查看运行状态和最近一个 segment
- `query --at <时间>`: 根据时间点定位对应采样文件
- `flame --at <时间>`: 根据时间点导出火焰图 SVG 和 folded stack 文本

## 目录结构

默认数据目录是 `/var/lib/perf24`：

```text
/var/lib/perf24
├── exports/
├── logs/
├── metadata/
│   └── segments.jsonl
├── runtime/
│   ├── perf24.pid
│   └── status.json
└── segments/
    └── YYYY/MM/DD/HH/
        └── segment_<start>__<end>.perf.data
```

## 依赖

- Linux
- `perf`
- Python 3.10+
- root 权限或具备运行 `perf record -a` 的权限

如果机器做过内核裁剪，还需要确认：

- `kernel.perf_event_paranoid` 允许采样
- `kptr_restrict` 不会把内核栈全部隐藏
- 业务二进制尽量保留符号，至少保留 `debuginfo` 包

## 快速开始

前台运行：

```bash
python3 perf24.py collect \
  --data-root /var/lib/perf24 \
  --segment-seconds 60 \
  --retention-hours 168 \
  --freq 99 \
  --event cpu-clock \
  --call-graph fp
```

后台运行：

```bash
python3 perf24.py start \
  --data-root /var/lib/perf24 \
  --segment-seconds 60 \
  --retention-hours 168
```

查看状态：

```bash
python3 perf24.py status --data-root /var/lib/perf24
```

按时间点定位 segment：

```bash
python3 perf24.py query \
  --data-root /var/lib/perf24 \
  --at "2026-04-27 14:35:00"
```

导出火焰图：

```bash
python3 perf24.py flame \
  --data-root /var/lib/perf24 \
  --at "2026-04-27 14:35:00" \
  --output /tmp/cpu-20260427-1435.svg
```

## 时间点回放机制

采集器按 `segment-seconds` 固定切片，例如 60 秒一段：

- `14:35:00` 到 `14:36:00`
- `14:36:00` 到 `14:37:00`
- `14:37:00` 到 `14:38:00`

当你输入 `--at "2026-04-27 14:35:23"` 时，工具会：

1. 读取 `metadata/segments.jsonl`
2. 找到覆盖该时间点的 segment
3. 如果没有完全覆盖，则选最近的 segment
4. 用该 segment 执行 `perf script`
5. 将栈折叠后输出 SVG 火焰图

## 推荐参数

线上默认建议先从下面一组配置起步：

```text
segment-seconds = 60
retention-hours = 168
freq = 99
event = cpu-clock
call-graph = fp
```

说明：

- `60s` 切片足够细，按分钟回放排障比较方便
- `168h` 就是保留 7 天
- `99Hz` 比较适合长期常驻，额外开销相对可控
- `fp` 开销低，适合 7x24；如果栈不完整，再考虑 `dwarf`

## `fp` 和 `dwarf` 的取舍

`--call-graph fp`：

- 优点是开销低，适合常驻
- 缺点是依赖 frame pointer，某些编译产物栈可能不完整

`--call-graph dwarf`：

- 优点是栈更完整
- 缺点是 CPU 和存储开销明显更高

建议先从 `fp` 上线，确认关键服务编译参数后再决定是否切到 `dwarf`。

## systemd 部署

仓库里带了一个模板：

[`systemd/perf24.service`](/C:/Users/lenovo/Documents/Codex/2026-04-27-7x24-cpu-profiling-perf-cpu/systemd/perf24.service)

Linux 目标机上可参考：

```bash
mkdir -p /opt/perf24
cp perf24.py /opt/perf24/
cp systemd/perf24.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now perf24
systemctl status perf24
```

## 输出文件

`flame` 命令会生成两个文件：

- `*.svg`: 可直接浏览器打开的火焰图
- `*.folded.txt`: 折叠后的栈文本，可用于二次分析

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
