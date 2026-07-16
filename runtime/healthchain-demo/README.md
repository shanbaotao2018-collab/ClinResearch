# HealthChain Local Demo

## Purpose

本目录提供一个基于 `HealthChain` 的本地最小演示服务：

- 输入：官方样例 `notereader_cda.xml`
- 输出：结构化摘要
- 输出：基础质检结果

## Layout

- `demo_app.py`: 本地 FastAPI / HealthChainAPI 演示服务
- `tests/test_demo_app.py`: 最小接口测试
- `.venv/`: Python 虚拟环境

## Start

```bash
cd "/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo"
./.venv/bin/python -m uvicorn demo_app:app --host 127.0.0.1 --port 8011
```

## Endpoints

- Demo page: [http://127.0.0.1:8011/demo](http://127.0.0.1:8011/demo)
- Sample API: [http://127.0.0.1:8011/api/analyze/sample](http://127.0.0.1:8011/api/analyze/sample)
- OpenAPI docs: [http://127.0.0.1:8011/docs](http://127.0.0.1:8011/docs)

## Test

```bash
cd "/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo"
./.venv/bin/python -m unittest tests.test_demo_app -v
```

## Current Behavior

当前样例返回结果包括：

- `4` 条 problem / diagnosis
- `1` 条 medication
- `0` 条 allergy
- `2` 条基础质检提示

## Notes

- 这是最小本地演示，不依赖真实 EHR/FHIR 凭证
- 结构化解析由 `HealthChain` 的 `CdaAdapter` 完成
- 质检规则目前是本地补的一层最小规则逻辑
