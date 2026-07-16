from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import Body
from fastapi.responses import HTMLResponse

from healthchain.gateway.api.app import HealthChainAPI
from healthchain.io import CdaAdapter
from healthchain.models import CdaRequest


BASE_DIR = Path(__file__).resolve().parent
SAMPLE_CDA_PATH = (
    BASE_DIR.parent.parent / "vendor" / "HealthChain" / "cookbook" / "data" / "notereader_cda.xml"
)


def _first_coding(resource: Any) -> dict[str, Any]:
    codeable = getattr(resource, "code", None) or getattr(
        resource, "medicationCodeableConcept", None
    )
    if not codeable or not getattr(codeable, "coding", None):
        return {"code": None, "display": None, "system": None}

    coding = codeable.coding[0]
    return {
        "code": getattr(coding, "code", None),
        "display": getattr(coding, "display", None),
        "system": getattr(coding, "system", None),
    }


def analyze_cda_document(xml_text: str, source: str) -> dict[str, Any]:
    adapter = CdaAdapter()
    document = adapter.parse(CdaRequest(document=xml_text))

    problems = []
    for condition in document.fhir.problem_list or []:
        coded = _first_coding(condition)
        problems.append(
            {
                "id": condition.id,
                "code": coded["code"],
                "display": coded["display"],
                "system": coded["system"],
                "clinical_status": (
                    condition.clinicalStatus.coding[0].code
                    if condition.clinicalStatus and condition.clinicalStatus.coding
                    else None
                ),
            }
        )

    medications = []
    for medication in document.fhir.medication_list or []:
        coded = _first_coding(medication)
        medications.append(
            {
                "id": medication.id,
                "code": coded["code"],
                "display": coded["display"],
                "system": coded["system"],
                "status": getattr(medication, "status", None),
            }
        )

    allergies = []
    for allergy in document.fhir.allergy_list or []:
        coded = _first_coding(allergy)
        allergies.append(
            {
                "id": allergy.id,
                "code": coded["code"],
                "display": coded["display"],
                "system": coded["system"],
            }
        )

    summary = {
        "problem_count": len(problems),
        "medication_count": len(medications),
        "allergy_count": len(allergies),
        "note_text_length": len(document.text or ""),
        "problems": problems,
        "medications": medications,
        "allergies": allergies,
    }

    quality_findings = []
    if summary["allergy_count"] == 0:
        quality_findings.append(
            {
                "rule_id": "missing_allergy_list",
                "severity": "medium",
                "message": "未解析到过敏史条目，需人工确认是否文档缺失或患者确无过敏史。",
            }
        )
    if summary["note_text_length"] == 0:
        quality_findings.append(
            {
                "rule_id": "missing_note_text",
                "severity": "low",
                "message": "CDA 解析结果未提取到可用自由文本，当前结果主要来自结构化段落。",
            }
        )
    if summary["problem_count"] == 0:
        quality_findings.append(
            {
                "rule_id": "missing_problem_list",
                "severity": "high",
                "message": "未解析到诊断问题列表，结构化结果不完整。",
            }
        )

    return {
        "source": source,
        "summary": summary,
        "quality_findings": quality_findings,
    }


def load_sample_analysis() -> dict[str, Any]:
    return analyze_cda_document(
        SAMPLE_CDA_PATH.read_text(), source=str(SAMPLE_CDA_PATH.name)
    )


def create_app() -> HealthChainAPI:
    app = HealthChainAPI(
        title="HealthChain Local Demo",
        description="Local CDA structuring and quality-check demo built on HealthChain",
        service_type="demo",
        enable_events=False,
    )

    @app.get("/demo", response_class=HTMLResponse)
    def index() -> str:
        return """
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>HealthChain 本地演示</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; margin: 32px; background: #f7f8fb; color: #111827; }
    h1 { margin-bottom: 8px; }
    button { background: #111827; color: white; border: 0; border-radius: 8px; padding: 10px 16px; cursor: pointer; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 20px; }
    .card { background: white; border-radius: 12px; padding: 16px; box-shadow: 0 2px 12px rgba(0,0,0,.06); }
    pre { white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.5; }
  </style>
</head>
<body>
  <h1>HealthChain 病历结构化与质检助手 Demo</h1>
  <p>当前页面直接调用本地接口，解析官方样例 CDA，输出结构化摘要和基础质检结果。</p>
  <button onclick="loadSample()">分析官方样例</button>
  <div class="grid">
    <div class="card">
      <h3>结构化摘要</h3>
      <pre id="summary">点击按钮后加载</pre>
    </div>
    <div class="card">
      <h3>质检结果</h3>
      <pre id="quality">点击按钮后加载</pre>
    </div>
  </div>
  <script>
    async function loadSample() {
      const response = await fetch('/api/analyze/sample');
      const payload = await response.json();
      document.getElementById('summary').textContent = JSON.stringify(payload.summary, null, 2);
      document.getElementById('quality').textContent = JSON.stringify(payload.quality_findings, null, 2);
    }
  </script>
</body>
</html>
        """

    @app.get("/api/analyze/sample")
    def analyze_sample() -> dict[str, Any]:
        return load_sample_analysis()

    @app.post("/api/analyze")
    def analyze(document: str = Body(..., embed=True)) -> dict[str, Any]:
        return analyze_cda_document(document, source="inline-document")

    return app


app = create_app()
