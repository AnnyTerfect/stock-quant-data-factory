# Data Factory

一个用于数据更新、数据处理与数据质量检测的模块化 Python 包。目前包含增量交付的
合并更新、pickle → Parquet 转换，以及分钟行情与日线行情的一致性检测。

## 数据目录

```text
data/
├── full/           # 本地全量历史：增量更新写入它，转换和检查读取它
├── incremental/    # 一次交付一个子目录，按交付日期命名
│   └── 2026-08-08/
└── out/            # 转换产出的 parquet
```

三棵子树互不重叠，所以任何一条命令都不会读到自己刚写出的东西。目录约定只在
`core/layout.py` 里写一次，命令行默认值和 Python 默认参数都从那里取。

## 模块划分

```text
data_factory/
├── core/                       # 各子系统共用的约定，不做任何 I/O
│   ├── fields.py               # 字段名（MINUTE_FIELDS / PRICE_FIELDS）
│   ├── symbols.py              # 股票代码解析的唯一规则
│   ├── layout.py               # 数据目录、文件名与输出重命名规则
│   └── logging.py              # 日志配置
├── ingestion/                  # 增量更新：交付目录 → data/full
│   ├── errors.py               # UpdateError（数据问题 vs 程序 bug）
│   ├── conventions.py          # 交付包命名、快照清单、各类阈值
│   ├── models.py               # Tolerance / UpdateConfig / UpdateStats
│   ├── pickle_io.py            # pickle 读写
│   ├── archives.py             # zip 遍历（含嵌套日包）
│   ├── catalog.py              # 扫描数据目录，建立「文件名 -> 路径」索引
│   ├── matrix.py               # 日期 × 股票矩阵的比较与合并
│   ├── snapshots.py            # 全量参考快照的校验
│   ├── date_consistency.py     # 更新后最近 1000 日的全局一致性校验
│   ├── staging.py              # 暂存区，全部通过后一次性提交
│   ├── report.py               # 问题收集与汇总输出
│   ├── sources/                # 各数据源的更新策略
│   │   ├── barra.py            # Barra 全量覆盖
│   │   └── factor_database.py  # 因子库按日合并
│   └── service.py              # 流程编排
├── processing/                 # 数据处理，按能力分子包
│   └── conversion/             # pickle → parquet 转换
│       ├── models.py           # ConversionConfig / ConversionResult
│       ├── normalization.py    # 无 I/O 的 DataFrame 标准化
│       ├── regular.py          # 普通 pickle 转换与文件复制
│       ├── minute.py           # 分钟行情流式转换
│       └── service.py          # 转换任务编排
├── quality/                    # 数据质量
│   ├── models.py               # 检查协议、报告模型、CheckSpec
│   ├── registry.py             # 检查的注册与发现
│   └── checks/
│       └── price_consistency/  # 分钟/日线一致性检查
│           ├── frames.py       # 加载层与计算层之间的数据契约
│           ├── loaders.py      # 全部读盘操作
│           ├── metrics.py      # 无 I/O 的比较与统计
│           └── check.py        # 组装 QualityReport 与 CheckSpec
└── cli/                        # 参数解析和终端输出
    ├── main.py                 # 子命令装配与统一日志
    ├── update.py
    ├── convert.py
    ├── quality.py              # 子命令由 registry 生成
    └── render.py               # 与具体检查无关的报告渲染
```

`core` 是唯一允许被所有子系统同时依赖的层：股票代码怎么解析、文件叫什么名字、
数据放在哪个目录，只在这里定义一次，避免各子系统对同一份数据得出不同结论。

`ingestion` 内部的依赖方向也是自上而下：`matrix.py` / `snapshots.py` 只提供机制
（比较、合并、校验），「差异了该报错还是该告警」这类策略放在 `sources/` 里，
两个数据源各自决定。

Python 调用统一使用包的公共接口，命令行调用统一使用 `pyproject.toml`
中注册的 console scripts。

## 命令行

查看所有可用命令：

```bash
uv run data-factory --help
uv run data-factory update --help
uv run data-factory convert --help
uv run data-factory check --help                    # 列出全部检查
uv run data-factory check price-consistency --help  # 单个检查的参数
```

也可以用 `uv run python -m data_factory` 代替 `uv run data-factory`。
每个子命令都接受 `--log-dir`，日志同时输出到终端和
`<log-dir>/<命令>_<时间戳>.log`；`--dry-run` 的那次会在文件名末尾加上
`_dryrun`，光看目录列表就能分清校验跑和真正改过数据的那次。控制台按 `--verbose`
决定详略，**日志文件里始终是 DEBUG 全量**——出问题之后再加 `--verbose` 重跑一遍
往往已经来不及：交付包可能已被下一批覆盖，本地数据也可能已经变了。

### 增量更新

```bash
# 先完整校验，不落盘
uv run data-factory update --delivery 2026-08-08 --trusted-pickle --dry-run

# 汇总全部问题后，通过 y/n 确认是否正式更新
uv run data-factory update --delivery 2026-08-08 --trusted-pickle
```

`--delivery` 只给名字时按 `data/incremental/<名字>` 解析，带目录则按给定路径。
`--data` 默认 `data/full`。

`pickle` 反序列化本身可以执行代码，因此程序要求显式传入 `--trusted-pickle`；
这表示交付包来自已经认证的可信来源。该参数不能把不可信 pickle 变安全，来源不明
的交付物不得交给本程序读取。

### 转换

完整转换（数据量很大时建议在持久终端中执行）：

```bash
uv run data-factory convert
```

也可分别执行，或先查看本次转换计划：

```bash
uv run data-factory convert --part regular
uv run data-factory convert --dry-run
uv run data-factory convert --part minute --overwrite
uv run data-factory convert --part minute --workers 8 --overwrite
```

默认只处理 pickle。增加 `--copy-other` 可复制其他文件；已有普通输出默认跳过，
分钟宽表已有任一目标文件时会停止，使用 `--overwrite` 覆盖。
`--dry-run` 只扫描并显示计划处理的文件，不读取 pickle，也不创建数据输出。
分钟数据按交易日多进程转换，默认使用 CPU 数量的一半（至少 1 个进程）；可用 `--workers`
根据机器的 CPU 和内存调整，设为 `1` 可关闭并行。

### 质量检查

```bash
uv run data-factory check price-consistency --date 20260722
```

检查和转换一样以源数据根目录为入口（默认 `data/full`，用 `--input` 改），
具体读哪些文件由 `core/layout.py` 推导：分钟在 `market/bars/1m/`，
日线矩阵在 `market/bars/1d/`，复权因子在 `market/adjustment/adjfactor.pkl`。

## 增量更新的处理规则

匹配一律按**文件名**做：交付包的目录结构（`FundData/fund_asset.pkl`）和本地数据
目录的组织方式（`market/bars/1d/...`）完全不同，文件名是唯一稳定的对应关系。
因此数据目录下出现同名文件会直接报错。分钟行情（`market/bars/1m/`）不参与更新：
它是一天一个长表文件，没有可合并的日期轴，也由另一个本模块不处理的交付包提供。

交付目录里的两个压缩包各自有不同的更新语义：

**`barra.zip`（全量覆盖）**
每次交付都是全历史文件，对应 `data/full/barra/`。程序在共同股票池上检查全部重叠
历史，发现数值差异时输出 `WARNING` + 差异数量 + 样例，但仍用输入覆盖——供应商每期
会重估全历史，历史值本来就可能变。结构性问题记为 `ERROR`：缺少本地已有日期、缺少
本地已有股票、没有共同股票、索引重复、本地因子在包里找不到、包里的文件在本地找
不到。日期和股票两个轴都要求输入是本地的超集——覆盖式更新没有兜底，输入少什么
本地就丢什么。程序继续检查其余文件并在末尾统一汇总；只要 Barra 出现一条 `ERROR`，
本次 Barra 的全部暂存结果都会撤销。

**`factorDatabase_incre_pkl.zip`（按日合并）**
外层是一天一个 zip，按日期从早到晚处理。只更新在数据目录下能找到**唯一同名文件**
的成员，其余跳过（增量包覆盖面远大于本地，跳过是正常状态）。

- 因子矩阵：先在共同股票池上校验所有重叠日期，通过后再合并新增日期和新增股票。
  本地独有的股票不会在重叠日期被清空。重叠部分对不上会记为 `ERROR`——增量包
  的历史应当和本地完全一致，对不上说明基准数据已经错了；本次因子增量的全部
  暂存结果会撤销，并禁止提交。
- `trd_cal.pkl`、`stkcode.pkl`、`stk_info.pkl` 是包内的全量参考快照，
  不做日期合并，结构校验（类型不变、字段及顺序不变、已有主键不得丢失、主键
  不重复）通过后整体替换。
- 行索引不像 8 位 `YYYYMMDD` 的文件（例如行号是 `0..570` 的 `ind_code_CI.pkl`）
  不会被当成日期矩阵合并，而是记 `WARNING` 后跳过。这类文件多半是新出现的参考
  表，应当补一条全量快照规则，而不是在行号上求交集把表改坏。

内层日包名称必须严格为 `factorDatabase_incre_pkl_YYYYMMDD.zip`。重复日期、非法
日期、重复目标文件以及无法识别的嵌套 zip 都会按 `ERROR` 处理。压缩包成员数量、
展开大小和压缩比也有防护上限，避免损坏压缩包耗尽机器资源。

**两阶段提交与人工确认**
所有文件先写到数据目录同级的临时暂存目录。程序会尽量完成全部文件检查，最后集中
列出所有 `WARNING`、`ERROR`（包括不一致、缺失和结构问题）。只要存在任何 `ERROR`，
程序不会询问并且不会写入；命令行以状态码 2 退出。只有没有 `ERROR` 且明确输入 `y`
才替换目标文件；输入 `n`、直接回车、EOF 或 Ctrl-C 都不会写入。

提交前会备份所有目标。普通文件系统异常导致提交中断时，已经替换的文件会自动
恢复。单个文件仍通过同文件系统内的 `os.replace` 原子替换；不可恢复的进程崩溃、
断电或回滚本身发生硬件故障不属于文件系统能够提供的跨文件事务保证范围。

提交前还会以更新后的 `trd_cal.pkl` 为基准，检查所有日期矩阵最近 1000 个交易日。
`stkcode.pkl`、`stk_info.pkl`、`ind_code_CI.pkl` 没有日期轴，不参与该项校验。
三种偏差分开处理，严重程度并不相同：

| 偏差 | 含义 | 处理 |
| --- | --- | --- |
| 空洞 | 文件在自己已覆盖的区间内漏掉了日历上的交易日 | `ERROR` |
| 多余日期 | 文件有、日历上没有的日期 | `ERROR` |
| 尾部滞后 | 文件末日期早于日历末日期，已覆盖部分完全吻合 | 不超过 `MAX_DATE_LAG_DAYS`（默认 5 个交易日）记 `WARNING`，超过记 `ERROR` |

尾部滞后必须单独处理：供应商的部分文件（如 `univ_ex_ss.pkl`）本来就比行情晚一拍
发布，把它当成错误会让每一次正常交付都被自己的校验挡死。比较区间取「文件自己
覆盖到的范围」和「基准窗口」的交集，因此起步晚的新因子也不会因为没有更早的历史
就被判为缺日期。

浮点历史比较默认 `rtol=1e-7`、`atol=1e-7`，可用 `--rtol` / `--atol` 调整。
两者必须是非负有限数。注意 Barra 是 `float32` 存储（机器精度约 `1.2e-7`），默认
容差就压在噪声底噪上，全历史重估的末位抖动会长期刷出告警；差异告警里会一并给出
差异占比和**最大相对偏差**，用来区分浮点噪声和真的算错了。

尚未处理：`Kline_incre.zip`。交付目录里有，但分钟行情不参与本模块的更新流程。

## Python API

```python
from pathlib import Path

from data_factory.ingestion import UpdateConfig, update_dataset

stats = update_dataset(
    UpdateConfig(
        delivery_dir=Path("data/incremental/2026-08-08"),
        dry_run=True,
        trusted_pickle=True,
    )
)
print(stats.error_count, stats.warning_count, stats.factors_merged)
```

```python
from data_factory.processing import ConversionConfig, convert_dataset

result = convert_dataset(ConversionConfig(part="all"))
print(result.regular.table, result.minute_days, result.copied.copied)
```

所有质量检查都遵循 `QualityCheck` 协议：声明 `name`、`scope`，并且
`run() -> QualityReport`。

```python
from data_factory.quality import PriceConsistencyCheck

report = PriceConsistencyCheck(trade_date=20260722).run()
print(report.status, report.metrics, report.issues)
```

也可以按名字取用：

```python
from data_factory.quality import registry

spec = registry.get("price-consistency")
report = spec.build({"trade_date": 20260722}).run()
```

### 新增一个质量检查

1. 在 `quality/checks/` 下新建子包，实现 `QualityCheck` 协议；
2. 用 `CheckOption` 声明它的可调参数，导出一个 `CheckSpec`；
3. 把这个 spec 加进 `quality/registry.py` 的 `_BUILTIN_SPECS`。

命令行会自动多出对应的子命令，`cli/` 不需要任何改动。`scope` 用来区分检查针对
的是上游源数据（`DataScope.SOURCE`）还是转换产出（`DataScope.OUTPUT`）。

### 适配新的交付结构

优先只改 `ingestion/conventions.py`：交付包名、全量快照清单、无日期轴的参考文件、
各类资源上限和比较参数都集中在那里。新增一个数据源则在 `ingestion/sources/` 下加
一个模块，暴露同样的 `update(...)` 入口，并在 `ingestion/service.py` 里编排。

## 开发

```bash
uv sync                                    # 含 dev 依赖（ruff、ipython）
uv run python -m unittest discover -s tests -t .
uv run ruff check .
uv run ruff format .
```
