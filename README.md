# Data Factory

一个用于数据处理与数据质量检测的模块化 Python 包。目前包含 pickle →
Parquet 转换，以及分钟行情与日线行情的一致性检测。

## 模块划分

```text
data_factory/
├── core/                       # 两个子系统共用的约定，不做任何 I/O
│   ├── fields.py               # 字段名（MINUTE_FIELDS / PRICE_FIELDS）
│   ├── symbols.py              # 股票代码解析的唯一规则
│   ├── layout.py               # 目录、文件名与输出重命名规则
│   └── logging.py              # 日志配置
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
    ├── convert.py
    ├── quality.py              # 子命令由 registry 生成
    └── render.py               # 与具体检查无关的报告渲染
```

`core` 是唯一允许被两个子系统同时依赖的层：股票代码怎么解析、文件叫什么名字，
只在这里定义一次，避免 `processing` 和 `quality` 对同一份数据得出不同结论。

Python 调用统一使用包的公共接口，命令行调用统一使用 `pyproject.toml`
中注册的 console scripts。

## Python API

```python
from pathlib import Path

from data_factory.processing import ConversionConfig, convert_dataset

result = convert_dataset(
    ConversionConfig(
        input_root=Path("data"),
        output_root=Path("data-out"),
        part="all",
    )
)
print(result.regular.table, result.minute_days, result.copied.copied)
```

所有质量检查都遵循 `QualityCheck` 协议：声明 `name`、`scope`，并且
`run() -> QualityReport`。

```python
from pathlib import Path

from data_factory.quality import PriceConsistencyCheck

report = PriceConsistencyCheck(
    trade_date=20260722,
    input_root=Path("data"),
).run()
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

## 命令行

查看所有可用命令：

```bash
uv run data-factory --help
uv run data-factory convert --help
uv run data-factory check --help                    # 列出全部检查
uv run data-factory check price-consistency --help  # 单个检查的参数
```

也可以用 `uv run python -m data_factory` 代替 `uv run data-factory`。
每个子命令都接受 `--log-dir`，日志同时输出到终端和 `<log-dir>/<命令>_<时间戳>.log`。

完整转换（数据量很大时建议在持久终端中执行）：

```bash
uv run data-factory convert
```

也可分别执行，或先查看本次转换计划：

```bash
uv run data-factory convert --part regular
uv run data-factory convert --dry-run
uv run data-factory convert --part minute --overwrite
```

默认只处理 pickle。增加 `--copy-other` 可复制其他文件；已有普通输出默认跳过，
分钟宽表已有任一目标文件时会停止，使用 `--overwrite` 覆盖。
`--dry-run` 只扫描并显示计划处理的文件，不读取 pickle，也不创建数据输出。

执行质量检查：

```bash
uv run data-factory check price-consistency --date 20260722
```

检查和转换一样以源数据根目录为入口（默认 `data`，用 `--input` 改），
具体读哪些文件由 `core/layout.py` 推导：分钟在 `market/bars/1m/`，
日线矩阵在 `market/bars/1d/`，复权因子在 `market/adjustment/adjfactor.pkl`。

## 开发

```bash
uv sync                                    # 含 dev 依赖（ruff、ipython）
uv run python -m unittest discover -s tests -t .
uv run ruff check .
uv run ruff format .
```
