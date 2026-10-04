# Getting Started

## Installation

```bash
git clone https://github.com/5h4d0wn1k/toxindb.git
cd toxindb
pip install -e ".[dev]"
```

## Usage

### CLI

```bash
toxindb monitor examples/traces/clean_trace.jsonl
toxindb canary --help
toxindb provenance examples/traces/clean_trace.jsonl
toxindb report examples/traces/poison_trace.jsonl
toxindb demo
```

### Python API

```python
from toxindb import api, Trace

result = api.analyze_trace('examples/traces/poison_trace.jsonl')
print(f"Alerts: {result.alert_count}")
```
