# Data Factory

一个用于数据处理与数据质量检测的模块化 Python 包。目前包含 pickle →
Parquet 转换，以及分钟行情与日线行情的一致性检测。

## 模块划分

```text
data_factory/
├── processing/             # 数据处理
│   ├── models.py           # ConversionConfig / ConversionResult
│   ├── normalization.py    # 无 I/O 的 DataFrame 标准化
│   ├── paths.py            # 文件发现与命名规则
│   ├── regular.py          # 普通 pickle 转换
│   ├── minute.py           # 分钟行情流式转换
│   └── service.py          # 转换任务编排
├── quality/                # 数据质量
│   ├── models.py           # 通用检查协议与报告模型
│   └── price_consistency.py# 分钟/日线一致性检查
└── cli/                    # 参数解析和终端输出
```

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
print(result)
```

所有质量检查都遵循 `QualityCheck.run() -> QualityReport`：

```python
from pathlib import Path

from data_factory.quality import PriceConsistencyCheck

report = PriceConsistencyCheck(
    trade_date=20260722,
    minute_dir=Path("1min_kline"),
    daily_dir=Path("daily_kline"),
).run()
print(report.status, report.metrics, report.issues)
```

新增质量规则时实现 `QualityCheck` 协议即可，并统一返回 `QualityReport`。

## 命令行

查看所有可用命令：

```bash
uv run data-factory --help
uv run data-factory convert --help
uv run data-factory check --help
```

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
uv run data-factory check \
  --date 20260722 \
  --minute-dir 1min_kline \
  --daily-dir daily_kline
```
