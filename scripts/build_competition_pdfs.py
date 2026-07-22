"""Build the four competition evidence PDFs from verified MVP facts."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deliverables" / "ai-competition-evidence-2026-07-22"

FONT_NAME = "ArialUnicode"
pdfmetrics.registerFont(TTFont(FONT_NAME, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))


def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleCN", parent=base["Title"], fontName=FONT_NAME, fontSize=20,
            leading=28, textColor=colors.HexColor("#0D514D"), alignment=TA_CENTER, spaceAfter=8,
        ),
        "subtitle": ParagraphStyle(
            "SubtitleCN", parent=base["Normal"], fontName=FONT_NAME, fontSize=10,
            leading=15, textColor=colors.HexColor("#59736F"), alignment=TA_CENTER, spaceAfter=22,
        ),
        "h1": ParagraphStyle(
            "H1CN", parent=base["Heading1"], fontName=FONT_NAME, fontSize=15,
            leading=22, textColor=colors.HexColor("#0D514D"), spaceBefore=12, spaceAfter=7,
        ),
        "h2": ParagraphStyle(
            "H2CN", parent=base["Heading2"], fontName=FONT_NAME, fontSize=12,
            leading=18, textColor=colors.HexColor("#176B65"), spaceBefore=8, spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "BodyCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=9.3,
            leading=16, textColor=colors.HexColor("#1E2D2A"), spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "BulletCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=9.2,
            leading=15, leftIndent=14, firstLineIndent=-10, textColor=colors.HexColor("#1E2D2A"), spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "SmallCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.8,
            leading=11, textColor=colors.HexColor("#59736F"),
        ),
        "cell": ParagraphStyle(
            "CellCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.7,
            leading=10.5, textColor=colors.HexColor("#1E2D2A"),
        ),
        "cell_head": ParagraphStyle(
            "CellHeadCN", parent=base["BodyText"], fontName=FONT_NAME, fontSize=7.7,
            leading=10.5, textColor=colors.white,
        ),
    }


S = styles()


def P(text, kind="body"):
    return Paragraph(text.replace("\n", "<br/>"), S[kind])


def bullet(text):
    return P("• " + text, "bullet")


def table(headers, rows, widths):
    data = [[P(item, "cell_head") for item in headers]]
    for row in rows:
        data.append([P(item, "cell") for item in row])
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D514D")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B7CBC7")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F8F7")]),
    ]))
    return result


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#B7CBC7"))
    canvas.line(1.8 * cm, 1.45 * cm, A4[0] - 1.8 * cm, 1.45 * cm)
    canvas.setFont(FONT_NAME, 7.5)
    canvas.setFillColor(colors.HexColor("#59736F"))
    canvas.drawString(1.8 * cm, 0.95 * cm, "临床科研智能体工作台 | 参赛佐证材料")
    canvas.drawRightString(A4[0] - 1.8 * cm, 0.95 * cm, f"第 {doc.page} 页")
    canvas.restoreState()


def build(filename, label, sections):
    story = [P(label, "title"), P("临床科研智能体工作台 | “智行合e・全员AI秀”AI 应用技能大赛", "subtitle")]
    for section in sections:
        title, content = section
        story.append(P(title, "h1"))
        for item in content:
            if isinstance(item, tuple) and item[0] == "table":
                story.extend([Spacer(1, 4), table(*item[1:]), Spacer(1, 7)])
            elif isinstance(item, tuple) and item[0] == "sub":
                story.append(P(item[1], "h2"))
            elif isinstance(item, tuple) and item[0] == "bullet":
                story.append(bullet(item[1]))
            else:
                story.append(P(item))
    story.extend([Spacer(1, 8), P("说明：本材料为科研辅助 MVP 的功能与验证说明，不构成临床诊疗建议或最终学术结论。", "small")])
    doc = SimpleDocTemplate(
        str(OUT / filename), pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        title=label,
        author="临床科研智能体工作台",
    )
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


build("佐证材料3-产品架构与业务闭环.pdf", "佐证材料3：产品架构与业务闭环", [
    ("一、建设背景", [
        "临床科研从研究想法到方案或综述草稿，需要跨越研究设计、检索、筛选、证据整理、方法学评价和写作等重复环节。传统流程工具分散、过程难追溯，方法学结构与交接记录容易缺失。",
        "本项目将医疗科研 Skills、MCP 工具、OpenCode Agent、本地项目记录和人工复核点组合为可执行工作流，建设面向科研人员的临床科研智能体工作台。",
    ]),
    ("二、总体架构", [
        "科研人员 -> OpenCode Agent 执行入口 / B/S 工作台 -> 专业 Skills + MCP Tools -> 本地项目数据库 -> 人工确认、审批与审计。",
        ("bullet", "Agent 负责任务编排、状态推进和结构化交付。"),
        ("bullet", "Skill 提供 PICO、检索、证据评价和写作等科研方法规范。"),
        ("bullet", "MCP Tool 执行真实 PubMed/Europe PMC 检索、基础样本量计算、项目记录与导出。"),
        ("bullet", "SQLite 保存项目、题录、PRISMA、证据、草稿、审批和审计，是 MVP 的唯一事实来源。"),
    ]),
    ("三、四个业务 Agent 闭环", [
        ("table", ["Agent", "核心处理", "可交付成果"], [
            ["临床科研选题与研究设计", "PICO、报告规范、纳排标准、结局、基础样本量、随机化计划", "研究设计蓝图、方案初稿、样本量假设"],
            ["文献检索与综述", "检索式、真实数据库检索、导入去重、初筛建议、PRISMA", "题录集、PRISMA 快照、综述大纲"],
            ["证据抽取与系统评价", "全文字段、撤稿核查、RoB 2/NOS/QUADAS-2 初评、二分类 Meta", "证据表、森林图、系统评价包"],
            ["科研写作与方案成稿", "大纲、方法、讨论、版本化草稿、来源清单", "protocol/proposal/methods/discussion 草稿"],
        ], [3.2*cm, 7.1*cm, 6.1*cm]),
    ]),
    ("四、可追溯与人机协同", [
        "任务从自然语言问题开始，Agent 调度专业 Skills 与 MCP Tools；工具结果写入项目记录，形成检索式、题录、样本量、证据字段和草稿版本等可核验产物。",
        ("bullet", "Skill 执行回执由 OpenCode 运行时签名记录，后端在关键节点验证必需回执。"),
        ("bullet", "筛选定稿、样本量假设、随机化、证据包和写作导出均保留研究者复核或审批节点。"),
        ("bullet", "RCT 实际随机分配序列和审批密钥不进入普通网页、模型上下文或导出包。"),
    ]),
    ("五、与普通问答式助手的差异", [
        "系统不是单轮回答：它能够真实调用数据库和计算工具，持久化项目过程，验证 Skill 执行，并在高风险结果处停止等待人工确认。研究者可在工作台中查看输入、产物、审批、审计与导出记录。",
    ]),
])

build("佐证材料4-真实案例与成果说明.pdf", "佐证材料4：真实案例与成果说明", [
    ("一、案例使用范围", [
        "研究设计案例使用脱敏或聚合演示参数；文献与证据案例使用公开发表论文和公开全文。以下结果用于验证软件工作流，不构成临床建议或最终学术结论。",
    ]),
    ("二、三类研究设计闭环", [
        ("table", ["研究类型", "演示课题", "已验证成果"], [
            ["务实 RCT", "SGLT2 抑制剂与 2 型糖尿病患者心衰住院风险", "SPIRIT/CONSORT 蓝图；两组率样本量 1110；审批前阻断随机表；导出不含分配序列"],
            ["诊断准确性", "肺结节 AI 辅助 CT 诊断准确性研究", "STARD 蓝图；两组率样本量 554；不适用随机化时不生成分配表"],
            ["预后队列", "心衰患者再入院预后队列研究", "TRIPOD 蓝图；两组率样本量 670；审批与审计可追溯"],
        ], [2.5*cm, 5.2*cm, 8.7*cm]),
        "可交付成果包括研究问题、PICO、研究类型/报告规范、纳排标准、结局、创新性与可行性、基础样本量假设、随机化计划、审批状态和导出包。",
    ]),
    ("三、真实医学数据库检索", [
        "课题示例为“SGLT2 抑制剂与 2 型糖尿病患者心力衰竭住院风险”。系统根据问题生成 PICO 与检索概念，调用 PubMed 与 Europe PMC 真实接口获取题录，完成导入、去重、初筛建议和 PRISMA 计数。",
        "系统不伪造 PMID、DOI、试验名称或效应值；初筛建议不自动等同于最终纳入决定。",
    ]),
    ("四、公开全文证据提取与写作", [
        "使用公开的 RECOVERY trial（PMID 33031652）与 WHO Solidarity trial（PMID 33264556）作为历史性方法学测试案例，保存全文来源、结局字段与 RoB 2 初评。",
        ("table", ["研究", "干预组死亡/总数", "对照组死亡/总数", "来源位置"], [
            ["RECOVERY", "421/1561", "790/3155", "Results > Primary Outcome"],
            ["WHO Solidarity", "104/947", "84/906", "Results > Primary Outcome"],
        ], [3.2*cm, 4.1*cm, 4.1*cm, 4.5*cm]),
        "系统以 28-day all-cause mortality、RR 和 DerSimonian-Laird 随机效应模型生成演示性 Meta 结果：RR 1.09，95% CI 0.99 至 1.20，I² 0.0%，k=2，并生成森林图。科研写作 Agent 可读取已保存来源生成讨论草稿。",
        "上述结果始终标记为需人工复核，不能据此产生临床推荐。",
    ]),
])

build("佐证材料5-测试验证与数据安全合规说明.pdf", "佐证材料5：测试验证与数据安全合规说明", [
    ("一、测试结论", [
        "截至 2026 年 7 月 22 日，后端自动化测试重新执行并通过：39 passed。测试覆盖研究设计、文献检索、证据抽取、科研写作、审批、审计以及工作台读取/导出接口。",
    ]),
    ("二、代表性验证", [
        ("table", ["验证对象", "已验证内容"], [
            ["研究设计 Agent", "三种研究类型、审批门禁、随机分配序列隔离、导出脱敏和工作流审计。"],
            ["Skill 执行回执", "OpenCode Skill 完成后生成签名回执；后端在关键工作流推进前验签。"],
            ["证据抽取与系统评价", "公开全文、字段抽取、RoB 2 初评、二分类 Meta、森林图和审批门禁。"],
            ["科研写作", "基于已保存来源生成版本化草稿，并在人工复核门禁处正确停止。"],
            ["B/S 工作台", "聚合查看研究设计、文献综述、证据工作流、写作草稿和待确认事项。"],
        ], [4.1*cm, 11.8*cm]),
    ]),
    ("三、数据安全与合规", [
        ("bullet", "仅使用脱敏、聚合或公开数据；禁止将患者身份信息传入模型提示词、MCP 调用或普通日志。"),
        ("bullet", "公开全文入库前对公开网页中的作者联系邮箱做最小化处理，来源位置仍可回溯。"),
        ("bullet", "不提供直接临床诊断、治疗建议或最终临床决策。"),
        ("bullet", "筛选定稿、样本量假设、随机化、系统评价和写作导出均保留研究者人工确认。"),
        ("bullet", "随机分配序列与审批密钥不进入模型、普通网页或导出包。"),
        ("bullet", "模型 API Key、审批 Key、Skill 回执签名 Key 均通过运行环境管理，不写入仓库、提示词或参赛材料。"),
    ]),
    ("四、当前边界", [
        "当前工作台为只读 P0，可查看、追溯和导出现有 Agent 成果。网页发起任务、统一身份认证、角色权限和网页审批属于后续迭代。生产化部署需进一步接入院内统一身份认证、权限审计、对象存储和合规数据治理体系。",
    ]),
])

build("佐证材料6-可复用能力清单.pdf", "佐证材料6：可复用能力清单", [
    ("一、可复用设计", [
        "本项目采用“Agent 编排 + Skill 方法规范 + MCP Tool 实际执行 + 项目记录与人工复核”的拆分方式。更换疾病领域、专科方向或研究问题后，仍可复用同一套流程和产物结构。",
        "当前项目本地维护 30 个筛选后的医疗科研 Skills，对外封装为 4 个业务 Agent，并保留 search-agent、screening-agent 两个内部专业子 Agent。",
    ]),
    ("二、核心能力映射", [
        ("table", ["业务 Agent", "主要复用能力", "标准化产物"], [
            ["研究设计", "PICO、纳排标准、研究方案、基础样本量、随机化", "设计蓝图、样本量假设、方案大纲"],
            ["文献检索综述", "PubMed/Europe PMC、检索策略、题录管理、PRISMA", "检索式、题录集、去重与 PRISMA"],
            ["证据抽取系统评价", "全文、基线/结局、偏倚风险、二分类 Meta、森林图", "证据表、偏倚风险初评、证据包"],
            ["科研写作", "生物医学大纲、方法、讨论、研究计划书", "版本化 protocol/proposal/methods/discussion 草稿"],
        ], [3.2*cm, 7.3*cm, 5.4*cm]),
    ]),
    ("三、关键工具", [
        ("bullet", "search_pubmed：调用 PubMed 获取真实医学题录。"),
        ("bullet", "search_europepmc：调用 Europe PMC 交叉检索候选题录。"),
        ("bullet", "fetch_paper_metadata：按标识符补全可追溯的题录元数据。"),
        ("bullet", "export_review_bundle：导出检索、筛选和综述项目包。"),
        ("bullet", "calculate_study_sample_size：在明确假设下计算基础样本量并保存参数。"),
        ("bullet", "export_systematic_evidence_bundle：通过审批门禁后导出系统评价成果。"),
    ]),
    ("四、可迁移场景与边界", [
        "可用于专科课题立项、药物疗效/安全性综述、诊断准确性研究、预后和真实世界研究准备，以及科研管理交接。",
        "当前 MVP 不覆盖复杂生存分析、ROC、LASSO、PSM、院内 EMR/FHIR 对接、中文病历 NLP 或临床数据集自动导出。可复用能力不替代研究者、统计师与伦理审查的专业判断。",
    ]),
])


def build_screenshot_pdf():
    story = [P("佐证材料2：产品界面截图", "title"), P("临床科研智能体工作台 | B/S 只读成果查看界面", "subtitle")]
    screenshots = [
        ("01-工作台总览与研究设计.png", "工作台首页与研究设计详情：项目总览、研究问题、PICO、样本量、随机化受保护提示、审批与导出。"),
        ("02-文献证据工作流.png", "文献与证据项目详情：检索策略、题录记录、PRISMA、项目审计和导出入口。"),
    ]
    for index, (filename, caption) in enumerate(screenshots):
        image_path = OUT / "02-产品截图" / filename
        story.append(P(caption, "body"))
        image = Image(str(image_path))
        image._restrictSize(16.8 * cm, 15.0 * cm)
        story.extend([image, Spacer(1, 8)])
        if index < len(screenshots) - 1:
            story.append(PageBreak())
    story.append(P("界面仅展示已保存的科研辅助项目事实。随机分配序列、审批密钥和患者身份信息不会出现在普通网页或导出包中。", "small"))
    doc = SimpleDocTemplate(
        str(OUT / "佐证材料2-产品界面截图.pdf"), pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.8 * cm,
        title="佐证材料2：产品界面截图", author="临床科研智能体工作台",
    )
    doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)


build("佐证材料1-四智能体演示视频索引.pdf", "佐证材料1：四智能体演示视频索引", [
    ("一、视频材料说明", [
        "四段视频均为本地实际运行录制，用于展示研究设计、文献检索综述、证据抽取系统评价和科研写作四类 Agent 的输入、工具调用、人工确认或成果产出。",
    ]),
    ("二、建议播放顺序", [
        ("table", ["顺序", "视频文件", "展示重点"], [
            ["1", "01-研究设计Agent.mp4", "从课题描述到 PICO、纳排、样本量、随机化计划与人工确认。"],
            ["2", "02-文献检索综述Agent.mp4", "真实数据库检索、题录导入、去重、筛选建议与 PRISMA。"],
            ["3", "03-证据抽取系统评价Agent.mp4", "公开全文、证据字段、偏倚风险初评、Meta 与森林图。"],
            ["4", "04-科研写作Agent.mp4", "读取已保存来源，生成带来源清单和版本信息的写作草稿。"],
        ], [1.3*cm, 5.4*cm, 9.2*cm]),
    ]),
    ("三、评委观看建议", [
        "优先播放 3 至 5 分钟的总览剪辑；若需要核验具体能力，再播放对应的单 Agent 原始视频。视频与材料中的案例均使用公开文献、脱敏或聚合演示参数。",
    ]),
])

build_screenshot_pdf()

# Expanded architecture material: this second build intentionally replaces the earlier
# brief PDF with the competition-ready version containing all four agent architectures.
build("佐证材料3-产品架构与业务闭环.pdf", "佐证材料3：产品架构与业务闭环", [
    ("一、产品定位与总体架构", [
        "临床科研智能体工作台将 OpenCode Agent、医疗科研 Skills、MCP Tools、FastAPI + SQLite 项目事实库和人工复核组合为可执行科研辅助闭环。当前 B/S 工作台用于成果查看、审计追溯和导出；任务执行入口为 OpenCode。",
        "统一执行链路：科研人员输入 -> OpenCode Agent 编排 -> 必需 Skills 方法门槛 -> MCP 真实操作 -> 项目事实保存 -> 研究者确认或 OpenCode Allow/Deny -> 受控导出。",
        ("table", ["架构层", "当前实现与职责"], [
            ["Agent 编排层", "4 个 OpenCode 主 Agent；文献检索综述 Agent 内部再调用 search-agent 与 screening-agent 两个专业子 Agent。"],
            ["Skill 方法层", "筛选后的医疗科研 Skills 规定 PICO、检索、证据抽取、偏倚风险、Meta 与写作的输入、字段和结构；缺少必需 Skill 时 Agent 应停止。"],
            ["MCP 执行层", "FastAPI MCP Server 执行真实 PubMed/Europe PMC 检索、基础样本量计算、项目持久化、审批状态查询和成果导出。"],
            ["项目事实与治理层", "SQLite 保存项目、题录、PRISMA、证据、全文来源、偏倚风险、Meta、草稿、审批、工作流事件和 Skill 回执。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
    ("二、Agent 1：临床科研选题与研究设计", [
        "定位：将去标识化或聚合的临床科研想法转为可审阅设计草稿，支持诊断、疗效、病因和预后研究。MVP 样本量限定为等分配两组均值或两组率比较。",
        ("sub", "执行架构"),
        "临床问题、科室背景、资源/病例量 -> study-design-agent -> 研究设计/纳排/方案/样本量/随机化 Skills -> MCP 项目与计算工具 -> StudyDesignProject 与审计 -> OpenCode Allow/Deny -> 受控研究设计包。",
        ("table", ["层级", "实现内容"], [
            ["编排 Agent", "study-design-agent：澄清目标 -> PICO -> 创建项目 -> 设计蓝图 -> 保存方案内容 -> 样本量 -> RCT 随机化计划 -> 确认/导出。"],
            ["主要 Skills", "clinic-research-design、inclusion-criteria-gen、research-proposal-generator、sample-size-basic、randomization-gen、biomed-outline-generator、method-writing、phi-prompt-guard。"],
            ["MCP Tools", "create_study_design_project、generate_study_design_blueprint、save_study_design_content、calculate_study_sample_size、save_rct_randomization_plan、finalize_study_design、get_study_design_approval_status。"],
            ["项目事实", "PICO、研究类型/报告规范、纳排标准、结局、创新性、可行性、方案大纲、样本量假设与结果、随机化计划、工作流事件。"],
            ["人工确认与成果", "finalize_study_design 触发 OpenCode 原生 Allow/Deny；批准后才生成受保护 RCT 分配表并导出。成果为设计蓝图、方案初稿、样本量与受控导出包；分配序列不进入 Agent、网页或普通导出包。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
    ("三、Agent 2：文献检索与综述", [
        "定位：将已确认研究问题转为可复现的检索、导入、去重、筛选与 PRISMA 工作流；检索使用真实 PubMed 和 Europe PMC 数据源。",
        ("sub", "执行架构"),
        "研究问题、PICO、纳排标准 -> literature-review 主 Agent -> search-agent（检索逻辑）+ screening-agent（初筛建议） -> 检索/筛选 Skills -> MCP 检索与项目工具 -> Project、Citation、ScreeningDecision、PRISMA 与审计 -> 研究者确认 -> 综述项目包。",
        ("table", ["层级", "实现内容"], [
            ["编排结构", "literature-review 为主 Agent；search-agent 负责同义词、布尔逻辑和数据库建议；screening-agent 仅产生标题/摘要层面的建议。"],
            ["主要 Skills", "pubmed-search-specialist、pubmed-database、reference-search、literature-filtering、systematic-review-screener、citation-chasing-mapping、retraction-watcher、literature-review、systematic-review、biomed-outline-generator、method-writing。"],
            ["MCP Tools", "create_review_project、generate_project_search_strategy、search_pubmed、search_europepmc、import_citations_to_project、deduplicate_project_citations、submit_screening_decisions、export_review_bundle；必要时 fetch_paper_metadata。"],
            ["项目事实", "研究问题、PICO、检索式与查询记录、候选题录、去重记录、筛选理由、PRISMA 计数、导出记录与审计。"],
            ["人工确认与成果", "筛选建议不等于最终纳入/排除；研究者明确确认后才写入筛选决定。成果为可复现检索式、题录集、去重记录、PRISMA、筛选结果、证据脉络与综述大纲。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
    ("四、Agent 3：证据抽取与系统评价", [
        "定位：对研究者已确认纳入的文献进行来源受限的字段抽取、全文评价和系统评价准备。缺失字段记录为 not_reported，系统不推测结果或效应量。",
        ("sub", "执行架构"),
        "已纳入题录、公开全文或研究者提供全文 -> evidence-extraction-agent -> 抽取/全文/偏倚风险/Meta Skills -> MCP 证据、全文、Meta 与审批工具 -> EvidenceExtraction、FullTextDocument、BiasAssessment、Meta 与审计 -> OpenCode Allow/Deny -> 系统评价包。",
        ("table", ["层级", "实现内容"], [
            ["编排 Agent", "evidence-extraction-agent：仅接收已保存为 include 的题录；先启动抽取工作流并绑定 workflow.run_id。"],
            ["主要 Skills", "clinical-study-info-extractor、methodology-extractor、retraction-watcher、fulltext-fetcher、pdf-extract、meta-screening-fulltext、baseline-extraction-for-clinical-trials、outcome-extraction-for-clinical-trials、RoB 2/NOS/QUADAS-2、meta-analysis、meta-forest-binary-plot。"],
            ["MCP Tools", "start_evidence_extraction_workflow、save_evidence_extractions、check_project_retractions、export_evidence_table、save_full_text_documents、fetch_and_save_open_access_full_text、save_full_text_evidence_details、save_bias_assessments、run_binary_meta_analysis、request/approve/export_systematic_evidence_bundle。"],
            ["项目事实", "evidence_basis、缺失字段、撤稿核查时间点、全文来源与定位、基线/结局原始计数、偏倚风险域与理由、二分类 Meta、森林图、审计。"],
            ["人工确认与成果", "抽取行默认 needs_human_review；偏倚风险均为初评。经研究者确认范围并由 OpenCode Allow/Deny 批准后才能导出。成果为证据表、来源清单、偏倚风险初评、匹配二分类 RR/OR Meta、森林图和系统评价包。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
    ("五、Agent 4：科研写作与方案成稿", [
        "定位：基于已保存的研究设计项目，或已完成证据抽取的综述项目，生成带来源清单和版本信息的科研写作草稿；不补造文献、数据、结果或审批信息。",
        ("sub", "执行架构"),
        "已保存研究设计或完成证据抽取的综述项目 -> research-writing-agent -> 大纲/方法/讨论/方案 Skills -> MCP 来源读取、草稿保存、审批与导出工具 -> ResearchWritingDraft、Source Manifest、Version 与审计 -> OpenCode Allow/Deny -> 草稿包。",
        ("table", ["层级", "实现内容"], [
            ["编排 Agent", "research-writing-agent：先读取保存来源，再启动写作工作流；支持 protocol、proposal、methods、discussion 四类草稿。"],
            ["主要 Skills", "biomed-outline-generator、method-writing、discussion-section-architect；proposal 额外使用 research-proposal-generator。"],
            ["MCP Tools", "get_research_writing_source、start_research_writing_workflow、save_research_writing_draft、request_research_writing_approval、approve_research_writing、get_research_writing_approval_status、export_research_writing_bundle。"],
            ["项目事实", "来源类型与 ID、source_manifest、标题、大纲、方法草稿、讨论框架、方案草稿、限制项、未解决项、版本、审批和导出审计。"],
            ["人工确认与成果", "缺失信息必须写入 unresolved_items；研究者确认范围后，由 OpenCode Allow/Deny 才可导出。成果为带来源清单的 protocol/proposal/methods/discussion 草稿，不是正式申报书或临床结论。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
    ("六、跨 Agent 协同、可追溯与安全边界", [
        "研究设计 Agent 形成 PICO、纳排和方案草稿；文献综述 Agent 形成确认纳入题录和 PRISMA；只有 include 题录可进入证据抽取；证据抽取完成后可作为写作 Agent 的综述/讨论来源。写作 Agent 同时可读取研究设计来源，生成方案类草稿。",
        ("table", ["治理机制", "当前实现"], [
            ["Skill 执行回执", "OpenCode 运行时记录签名回执；后端在关键工作流推进前验证必需 Skills 的执行证据。"],
            ["工作流审计", "关键 MCP 操作保存输入/输出摘要、workflow.run_id、项目关联和导出记录，可在工作台追溯。"],
            ["受控信息", "随机分配序列、审批密钥和患者身份信息不进入模型、普通网页或普通导出包。"],
            ["当前边界", "不提供诊疗建议或最终学术结论；MVP 不表述为已支持复杂生存分析、ROC、LASSO、PSM、院内 EMR/FHIR 对接、中文病历 NLP 或临床数据集自动导出。"],
        ], [3.3*cm, 11.6*cm]),
    ]),
])

print(f"Generated PDFs in {OUT}")
