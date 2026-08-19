"""Phase 5 目标 REST 契约的薄适配层。"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field, field_validator

from app.Base.Models.roleModel import Permission
from app.Base.RicUtils.httpUtils import HttpResponse
from app.Base.Service.authService import AuthService
from app.WealthButler.Api.chatApi import get_authenticated_chat_user
from app.WealthButler.Models.baseUserExtModel import BaseUserExtModel


router = APIRouter(tags=["Phase 5 目标契约"])

_KNOWLEDGE_TYPE_TO_STORAGE = {"产品说明": "产品说明书"}
_KNOWLEDGE_TYPE_FROM_STORAGE = {"产品说明书": "产品说明"}
_KNOWLEDGE_STATUS_TO_STORAGE = {"待入库": "待审核", "已入库": "已上线"}
_KNOWLEDGE_STATUS_FROM_STORAGE = {"待审核": "待入库", "已上线": "已入库"}


def _business_user(current_user: Any) -> BaseUserExtModel:
    user = BaseUserExtModel.get_by_id(getattr(current_user, "id", None))
    if user is None:
        raise HTTPException(status_code=403, detail="当前账号没有财富管家业务身份")
    return user


def _require_permission(current_user: Any, permission: str) -> None:
    if not AuthService.has_permission(
        current_user.id,
        permission,
        getattr(current_user, "source_module", None),
    ):
        raise HTTPException(status_code=403, detail=f"缺少权限: {permission}")


def _require_employee_permission(current_user: Any, permission: str) -> BaseUserExtModel:
    business_user = _business_user(current_user)
    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="该接口仅限员工访问")
    _require_permission(current_user, permission)
    return business_user


def _serialize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if hasattr(value, "model_dump"):
        return _serialize(value.model_dump())
    return value


def _paginate(items: list[Any], total: int, limit: int, offset: int) -> dict[str, Any]:
    return {"items": _serialize(items), "total": total, "limit": limit, "offset": offset}


def _serialize_knowledge(value: Any) -> dict[str, Any]:
    item = _serialize(value)
    item["knowledge_type"] = _KNOWLEDGE_TYPE_FROM_STORAGE.get(
        item.get("knowledge_type"), item.get("knowledge_type")
    )
    item["status"] = _KNOWLEDGE_STATUS_FROM_STORAGE.get(item.get("status"), item.get("status"))
    return item


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    knowledge_type: str
    top_k: int = Field(default=5, ge=1, le=20)


class AssessmentAnswer(BaseModel):
    question_no: int = Field(ge=1, le=16)
    option: str = Field(min_length=1, max_length=1, pattern=r"^[A-Pa-p]$")
    score: Optional[int] = None

    @field_validator("option")
    @classmethod
    def normalize_option(cls, value: str) -> str:
        return value.strip().upper()


class AssessmentRequest(BaseModel):
    answers: list[AssessmentAnswer] = Field(min_length=16, max_length=16)


class ProductRecommendRequest(BaseModel):
    customer_id: int = Field(gt=0)


class RiskMonitorRequest(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)
    rule_codes: Optional[list[str]] = None

    @field_validator("rule_codes")
    @classmethod
    def validate_rule_codes(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is not None and any(not item.startswith("RW-") for item in value):
            raise ValueError("规则编号必须使用 RW-xxx 格式")
        return value


class RecalculateConfidenceRequest(BaseModel):
    customer_id: Optional[int] = Field(default=None, gt=0)


@router.post("/api/knowledge/upload")
async def upload_knowledge(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    knowledge_type: str = Form(...),
    title: str = Form(..., min_length=1, max_length=200),
    source_file: Optional[str] = Form(default=None, max_length=200),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Service.knowledgeAdminService import KnowledgeAdminService

    content = await file.read(KnowledgeAdminService.MAX_UPLOAD_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传文档不能为空")
    if len(content) > KnowledgeAdminService.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="上传文档不能超过 10MB")
    safe_name = Path(file.filename or "knowledge.txt").name
    if Path(safe_name).suffix.lower() not in KnowledgeAdminService.ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="仅支持 txt、md 和 docx 文档")
    try:
        record = KnowledgeAdminService.create_pending(
            knowledge_type=knowledge_type,
            title=title,
            source_file=source_file or safe_name,
            uploaded_by=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    background_tasks.add_task(
        KnowledgeAdminService.ingest_bytes,
        record_id=record.id,
        filename=safe_name,
        content=content,
        content_type=file.content_type,
    )
    return HttpResponse.ok(data={"id": record.id, "status": "待入库"})


@router.post("/api/knowledge/search")
def search_knowledge(
    request: KnowledgeSearchRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Service.knowledgeAdminService import KnowledgeAdminService
    from app.WealthButler.Service.knowledgeService import KnowledgeService

    collection = KnowledgeAdminService.TYPE_TO_COLLECTION.get(request.knowledge_type)
    if collection is None:
        raise HTTPException(status_code=400, detail="不支持的知识类型")
    return HttpResponse.ok(data=KnowledgeService.retrieve(request.query, collection, request.top_k))


@router.get("/api/knowledge/list")
def list_knowledge(
    knowledge_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel

    filters = {key: value for key, value in {
        "knowledge_type": _KNOWLEDGE_TYPE_TO_STORAGE.get(knowledge_type, knowledge_type),
        "status": _KNOWLEDGE_STATUS_TO_STORAGE.get(status, status),
    }.items() if value}
    all_items = KnowledgeMetaModel.find_by(order_by="updated_at", order="DESC", **filters)
    items = [_serialize_knowledge(item) for item in all_items[offset:offset + limit]]
    return HttpResponse.ok(data=_paginate(items, len(all_items), limit, offset))


@router.delete("/api/knowledge/{knowledge_id}")
def retire_knowledge(
    knowledge_id: int,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Models.knowledgeMetaModel import KnowledgeMetaModel

    record = KnowledgeMetaModel.get_by_id(knowledge_id)
    if record is None:
        raise HTTPException(status_code=404, detail="知识条目不存在")
    if not record.update(status="已下线"):
        raise HTTPException(status_code=500, detail="知识条目下线失败")
    return HttpResponse.ok(data={"id": record.id, "status": "已下线"})


@router.get("/api/profile/assessment/questions")
def get_assessment_questions(current_user: Any = Depends(get_authenticated_chat_user)):
    _business_user(current_user)
    from app.WealthButler.Service.riskAssessService import RiskAssessService

    return HttpResponse.ok(data={"questions": RiskAssessService.get_questionnaire()})


@router.get("/api/profile/{customer_id}")
def get_profile(
    customer_id: int,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type == "CUSTOMER":
        if current_user.id != customer_id:
            raise HTTPException(status_code=403, detail="客户只能查看本人画像")
        employee_view = False
    else:
        _require_permission(current_user, Permission.PRODUCT_QUERY)
        business_role = getattr(business_user, "employee_role", None)
        if business_role in {"客户经理", "业务管理员"}:
            from app.WealthButler.Service.operatorAccessService import OperatorAccessService
            if not OperatorAccessService.can_access_customer(current_user.id, customer_id):
                raise HTTPException(status_code=403, detail="该客户不在当前客户经理的办理范围内")
        employee_view = True
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    from app.WealthButler.Service.riskAssessService import RiskAssessService

    profile = CustomerProfileModel.find_by_customer_id(customer_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="客户画像不存在")
    data = _serialize(profile)
    assessment = RiskAssessService.get_latest_assessment(customer_id)
    data["valid_until"] = _serialize(getattr(assessment, "valid_until", None))
    if not employee_view:
        allowed = {"customer_id", "risk_level", "valid_until", "asset_allocation", "product_preference"}
        data = {key: value for key, value in data.items() if key in allowed}
    return HttpResponse.ok(data=data)


@router.post("/api/profile/{customer_id}/assessment")
def submit_assessment(
    customer_id: int,
    request: AssessmentRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type == "CUSTOMER":
        if current_user.id != customer_id:
            raise HTTPException(status_code=403, detail="客户只能提交本人风评")
    else:
        _require_permission(current_user, Permission.RISK_REASSESS)
    from app.WealthButler.Service.customerProfileService import CustomerProfileService
    from app.WealthButler.Service.riskAssessService import RiskAssessService

    question_map = {item["id"]: item for item in RiskAssessService.get_questionnaire()}
    if len({item.question_no for item in request.answers}) != 16:
        raise HTTPException(status_code=400, detail="16题必须全部作答且不能重复")
    selected: dict[int, int] = {}
    stored_answers = []
    for answer in request.answers:
        if answer.question_no not in question_map:
            raise HTTPException(status_code=400, detail=f"第{answer.question_no}题不存在")
        index = ord(answer.option) - ord("A")
        options = question_map[answer.question_no]["options"]
        if index < 0 or index >= len(options):
            raise HTTPException(status_code=400, detail=f"第{answer.question_no}题选项无效")
        selected[answer.question_no] = index
        stored_answers.append({
            "question_no": answer.question_no,
            "option": answer.option,
            "option_index": index,
            "score": options[index]["score"],
        })
    total_score, risk_level = RiskAssessService.calculate_risk_level(selected)
    assessment = RiskAssessService.save_assessment_result(
        customer_id, stored_answers, total_score, risk_level,
    )
    if assessment is None:
        raise HTTPException(status_code=500, detail="风险评估保存失败")
    profile = CustomerProfileService.get_comprehensive_profile(customer_id, updated_reason="人工触发")
    return HttpResponse.ok(data={"assessment": _serialize(assessment), "profile": _serialize(profile)})


@router.get("/api/product/list")
def list_products(
    product_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="产品列表仅限员工访问")
    _require_permission(current_user, Permission.PRODUCT_QUERY)
    from app.WealthButler.Models.productModel import ProductModel

    filters = {key: value for key, value in {
        "product_type": product_type, "risk_level": risk_level, "status": status,
    }.items() if value}
    items = ProductModel.find_by(order_by="updated_at", order="DESC", **filters)
    if keyword:
        lowered = keyword.casefold()
        items = [item for item in items if lowered in f"{item.product_name} {item.product_code}".casefold()]
    return HttpResponse.ok(data=_paginate(items[offset:offset + limit], len(items), limit, offset))


@router.get("/api/product/{product_id}")
def get_product(
    product_id: int,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="产品详情仅限员工访问")
    _require_permission(current_user, Permission.PRODUCT_QUERY)
    from app.WealthButler.Service.productService import ProductService

    product = ProductService.get_product_by_id(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="产品不存在")
    return HttpResponse.ok(data=_serialize(product))


@router.post("/api/product/recommend")
def recommend_products(
    request: ProductRecommendRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="产品推荐仅限员工访问")
    _require_permission(current_user, Permission.PRODUCT_RECOMMEND)
    from app.WealthButler.Service.advisorService import AdvisorService
    from app.WealthButler.Tools.graphQueryTool import GraphQueryTool

    result = AdvisorService().recommend_products(
        request.customer_id,
        graph_query=GraphQueryTool().execute,
    )
    return HttpResponse.ok(data=result["recommendations"])


@router.post("/api/risk/monitor")
def monitor_risk(
    request: RiskMonitorRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Agent.riskAgent import (
        DAILY_RULE_IDS,
        REALTIME_RULE_IDS,
        WEEKLY_RULE_IDS,
        RiskAgent,
    )

    all_rules = set(REALTIME_RULE_IDS) | set(DAILY_RULE_IDS) | set(WEEKLY_RULE_IDS)
    requested = set(request.rule_codes or all_rules)
    unknown = requested - all_rules
    if unknown:
        raise HTTPException(status_code=400, detail=f"批量扫描不支持规则: {sorted(unknown)}")
    customer_ids = [request.customer_id] if request.customer_id else None
    agent = RiskAgent()
    result = agent.scan_selected_rules(sorted(requested), customer_ids=customer_ids)
    alerts = result.get("triggered_alerts", [])
    return HttpResponse.ok(data=alerts)


@router.get("/api/graph/stats")
def graph_stats(current_user: Any = Depends(get_authenticated_chat_user)):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.Base.Client.neo4jClient import Neo4jClient

    client = Neo4jClient()
    try:
        nodes = client.run("MATCH (n) UNWIND labels(n) AS label RETURN label, count(*) AS count ORDER BY label")
        edges = client.run("MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS count ORDER BY type")
    finally:
        client.close()
    return HttpResponse.ok(data={"nodes": nodes, "relationships": edges})


@router.get("/api/graph/visualization/{customer_id}")
def graph_visualization(
    customer_id: int,
    depth: int = Query(default=2, ge=1, le=3),
    current_user: Any = Depends(get_authenticated_chat_user),
):
    business_user = _business_user(current_user)
    if business_user.user_type != "EMPLOYEE":
        raise HTTPException(status_code=403, detail="客户图谱仅限员工访问")
    _require_permission(current_user, Permission.PRODUCT_QUERY)
    from app.Base.Client.neo4jClient import Neo4jClient

    cypher = f"""
    MATCH p=(c:Customer {{customer_id: $customer_id}})-[*1..{depth}]-(n)
    RETURN
      [node IN nodes(p) | {{key: head(labels(node)) + ':' + coalesce(toString(node.customer_id),
        toString(node.product_id), toString(node.level), toString(node.industry_name),
        toString(node.market_name), toString(node.manager_name)), labels: labels(node),
        properties: properties(node)}}] AS nodes,
      [rel IN relationships(p) | {{source: head(labels(startNode(rel))) + ':' + coalesce(toString(startNode(rel).customer_id),
        toString(startNode(rel).product_id), toString(startNode(rel).level),
        toString(startNode(rel).industry_name), toString(startNode(rel).market_name),
        toString(startNode(rel).manager_name)), target: head(labels(endNode(rel))) + ':' + coalesce(toString(endNode(rel).customer_id),
        toString(endNode(rel).product_id), toString(endNode(rel).level),
        toString(endNode(rel).industry_name), toString(endNode(rel).market_name),
        toString(endNode(rel).manager_name)), type: type(rel), properties: properties(rel)}}] AS edges
    LIMIT 100
    """
    client = Neo4jClient()
    try:
        rows = client.run(cypher, {"customer_id": customer_id})
    finally:
        client.close()
    nodes_by_key: dict[str, dict] = {}
    edges_by_key: dict[tuple, dict] = {}
    for row in rows:
        for node in row.get("nodes", []):
            key = node.get("key")
            if key:
                nodes_by_key[key] = node
        for edge in row.get("edges", []):
            key = (edge.get("source"), edge.get("target"), edge.get("type"))
            edges_by_key[key] = edge
    return HttpResponse.ok(data={"nodes": list(nodes_by_key.values()), "edges": list(edges_by_key.values())})


@router.post("/api/admin/recalculate-confidence")
def recalculate_confidence(
    request: RecalculateConfidenceRequest,
    current_user: Any = Depends(get_authenticated_chat_user),
):
    _require_employee_permission(current_user, Permission.SYSTEM_CONFIG)
    from app.WealthButler.Models.customerProfileModel import CustomerProfileModel
    from app.WealthButler.Service.memoryService import SOURCE_TO_BASE
    from app.WealthButler.Tools.confidenceCalcTool import BaseConfidenceCalc

    profiles = (
        [CustomerProfileModel.find_by_customer_id(request.customer_id)]
        if request.customer_id else CustomerProfileModel.get_all()
    )
    affected = 0
    now = datetime.now()
    for profile in (item for item in profiles if item is not None):
        units = profile.memory_units if isinstance(profile.memory_units, list) else []
        recalculated = []
        for unit in units:
            item = dict(unit)
            created = item.get("create_time") or item.get("created_at")
            try:
                created_at = datetime.fromisoformat(created) if isinstance(created, str) else created
                age_days = max(0, (now - created_at).days) if created_at else 0
            except (TypeError, ValueError):
                age_days = 0
            base = SOURCE_TO_BASE.get(item.get("source"), 0.2)
            item["confidence"] = BaseConfidenceCalc.calculate(
                base,
                int(item.get("evidence_count", 0) or 0),
                int(item.get("conflict_count", 0) or 0),
                age_days,
            )
            recalculated.append(item)
        overall = round(sum(item["confidence"] for item in recalculated) / len(recalculated), 3) if recalculated else 0.2
        if profile.update(memory_units=recalculated, confidence_score=Decimal(str(overall))):
            affected += 1
    return HttpResponse.ok(data={"affected_count": affected})


def register_phase5_contract_api(app) -> None:
    app.include_router(router)
