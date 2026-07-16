# HealthChain Local Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本地部署一套最小可运行的 HealthChain 演示，验证官方能力和可展示效果。

**Architecture:** 先复用 HealthChain 官方仓库和样例，避免自建业务逻辑。优先跑通不依赖院内系统的本地 demo；如果官方样例无法在当前环境直接运行，再补一层最薄的本地包装代码用于演示输入输出。

**Tech Stack:** Python 3, venv, HealthChain, FastAPI/Uvicorn, 官方 cookbook/demo 脚本

---

### Task 1: 准备本地工作目录

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/vendor/`
- Create: `/Users/shanbaotao/Documents/agent 2/runtime/`

- [ ] **Step 1: 创建 vendor 和 runtime 目录**

Run: `mkdir -p '/Users/shanbaotao/Documents/agent 2/vendor' '/Users/shanbaotao/Documents/agent 2/runtime'`
Expected: 目录创建成功，无报错

- [ ] **Step 2: 检查目录**

Run: `find '/Users/shanbaotao/Documents/agent 2' -maxdepth 2 -type d | sort`
Expected: 输出包含 `vendor` 和 `runtime`

### Task 2: 获取 HealthChain 源码

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/vendor/HealthChain/`

- [ ] **Step 1: 克隆官方仓库**

Run: `git clone https://github.com/healthchainai/HealthChain '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain'`
Expected: 仓库克隆完成

- [ ] **Step 2: 检查关键目录**

Run: `find '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain' -maxdepth 2 -type d | sort | sed -n '1,80p'`
Expected: 输出包含 `cookbook`、`docs`、`healthchain`

### Task 3: 构建 Python 运行环境

**Files:**
- Create: `/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo/.venv/`

- [ ] **Step 1: 创建虚拟环境**

Run: `python3 -m venv '/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo/.venv'`
Expected: `.venv` 创建成功

- [ ] **Step 2: 安装最小依赖**

Run: `'/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo/.venv/bin/pip' install -e '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain'`
Expected: `HealthChain` 安装成功

- [ ] **Step 3: 验证 CLI**

Run: `'/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo/.venv/bin/healthchain' --help`
Expected: 输出 CLI 帮助信息

### Task 4: 选择并运行可本地演示的官方样例

**Files:**
- Read: `/Users/shanbaotao/Documents/agent 2/vendor/HealthChain/cookbook/`

- [ ] **Step 1: 识别当前环境可运行样例**

Run: `find '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain/cookbook' -maxdepth 1 -type f | sort`
Expected: 输出 cookbook 脚本列表

- [ ] **Step 2: 优先运行不依赖外部 EHR 凭证的样例**

Run: `'/Users/shanbaotao/Documents/agent 2/runtime/healthchain-demo/.venv/bin/python' '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain/cookbook/cds_discharge_summarizer_hf_chat.py'`
Expected: 如果缺少模型令牌或网络，明确暴露缺口；如果可运行，产出 demo 输出

- [ ] **Step 3: 如果上一步不可运行，切换到更低依赖样例或本地包装**

Run: `find '/Users/shanbaotao/Documents/agent 2/vendor/HealthChain/cookbook' -maxdepth 2 -type f | sort | sed -n '1,120p'`
Expected: 找到备选 demo 路径

### Task 5: 输出部署结果与下一步

**Files:**
- Modify: `/Users/shanbaotao/Documents/agent 2/healthchain-病历结构化与质检助手-mvp方案.md`

- [ ] **Step 1: 记录本地部署结果**

Run: `printf 'deployment complete\n'`
Expected: 明确当前是跑通官方 demo、还是卡在依赖/网络/模型层

- [ ] **Step 2: 给出下一步实施分支**

Run: `printf 'next step decided\n'`
Expected: 在结果里明确下一步是继续做本地结构化质检包装，还是先解决外部依赖
