"""前端关键旅程的静态契约测试。"""

from pathlib import Path


FRONTEND_DIR = Path(__file__).parents[1] / "app" / "WealthButler" / "Frontend"


def _read(relative_path: str) -> str:
    return (FRONTEND_DIR / relative_path).read_text(encoding="utf-8")


def test_login_clears_stale_customer_context() -> None:
    html = _read("login.html")

    assert "localStorage.removeItem('customer_id')" in html
    assert "localStorage.removeItem('customer_name')" in html
    assert "function clearStaleClientSession" in html
    assert "sessionStorage.removeItem('operator_chat_session')" in html
    assert 'autocomplete="new-password"' in html
    assert "document.getElementById('loginForm').reset()" in html
    # Login fixtures come from the existing database; do not hard-code or
    # mutate a particular employee account in a static frontend contract.
    assert 'data-type="employee"' in html
    assert 'userData.roles.includes' in html
    assert '/chat/operator' in html
    assert '<span class="username">admin</span>' not in html
    assert "const loginName = account.username;" in html
    assert "button.dataset.username = account.username;" in html
    assert "account.quick_login_kind === 'customer_numbered'" in html
    assert "account.quick_login_kind === 'employee_named'" in html


def test_customer_dashboard_does_not_mask_backend_failures_with_mock_data() -> None:
    html = _read("pages/customer_dashboard.html")

    assert "function useMockData" not in html
    assert "function generateMockReply" not in html
    assert "/api/wealth/holdings/profit-today" in html
    assert "window.location.href = '/login.html'" not in html
    assert "async function consumeSse" in html
    assert "payloadLines.join('\\n')" in html
    assert "result.data?.holdings || []" in html
    assert "holding.current_value" in html
    assert "result.code" not in html
    assert 'data-view="transactions"' in html
    assert 'data-view="products"' in html
    assert "/api/wealth/customer/transactions" in html
    assert "/api/wealth/customer/products" in html
    assert "calculation_source === 'simulated'" in html
    assert "模拟 ${formatPercent(rate)}" in html
    assert 'id="totalAssetsCard"' in html
    assert 'id="assetAllocationModal"' in html
    assert "function renderAssetAllocation" in html
    assert "function refreshCustomerDataForResult" in html
    assert "经办客户经理：${notification.handler_name}" in html
    assert "new Set(['申购', '追加申购', '赎回', '转账'])" in html
    assert "Promise.all([loadHoldings(), loadTransactions()])" in html
    assert "经办客户经理" in html
    assert "function appendComplianceEvidence" in html
    assert "item.type === 'compliance_evidence'" in html
    assert "let notificationBaselineReady = false" in html
    assert "首次打开客户页不重放 Redis 中的历史结果消息" in html
    assert "function isRecentWorkOrderResult(notification)" in html
    assert "!isRecentWorkOrderResult(item)" in html


def test_advisor_workflow_is_read_only_and_requires_managed_customer() -> None:
    html = _read("pages/advisor_dashboard.html")

    assert "请先在客户管理中选择一位服务客户" in html
    assert "/api/chat/advisor" in html
    assert "/api/chat/operator" not in html
    assert "申购服务" not in html
    assert "赎回服务" not in html
    assert "result.status_code !== 200" in html
    assert "payloadLines.join('\\n')" in html
    assert "result.code" not in html
    assert "? 'confirm' : 'cancel'" not in html
    assert 'onclick="switchAgent(this)"' not in html
    assert "function switchAgent(tab)" not in html
    assert "action: 'claim'" in html
    assert "handler_id: userId" not in html
    assert 'id="productAnalysisCustomerSelect"' in html
    assert "请先选择要分析的客户" in html
    assert "/analysis-records" in html
    assert "投顾分析记录" in html
    assert "function generateWorkorderAllocationPlan()" in html
    assert "生成产品配置方案" in html


def test_operator_workflow_requires_customer_and_supports_confirmation() -> None:
    html = _read("pages/operator_dashboard.html")

    assert "onclick=\"selectCustomer(this)\"" in html
    assert "尚未选择客户" in html
    assert "openCustomerPicker('选择客户','selectAssistantCustomer')" in html
    assert "请先选择客户，再进行查询或业务办理" in html
    assert "selectedCustomerSummary" in html
    assert "客户等级：${summary.customerLevel}" in html
    assert "/api/chat/operator/confirm" in html
    assert "确认令牌" in html
    assert "result.status_code !== 200" in html
    assert "payloadLines.join('\\n')" in html
    assert "/api/wealth/operator/clients" not in html
    assert "/api/wealth/operator/stats" not in html
    assert "/api/wealth/advisor/clients" not in html
    assert "/api/wealth/advisor/stats" not in html
    assert "result.code" not in html
    assert "? 'confirm' : 'cancel'" not in html
    assert "id=\"aiMessages\"" in html
    assert "id=\"aiContext\"" in html
    assert "function showAIConfirmation()" in html
    assert "function explainOperatorMessage(message)" in html
    assert "还缺少双录合规记录" in html
    assert "等待客户二次确认" in html
    assert "客户确认前不会执行交易" in html
    assert "resolvePendingOperatorAction('confirm')" not in html
    assert "撤回申请" in html
    assert "/api/chat/operator/confirmations/${encodeURIComponent(confirmToken)}" in html
    assert "客户已完成二次确认" in html
    assert "startConfirmationStatusPolling" in html
    assert "alert('业务助手回复" not in html
    assert "action: action" in html
    assert "function getOperatorSessionId(customerId)" in html
    assert "function resetOperatorAssistant(customerName)" in html
    assert "上一客户的助手消息已清除" in html
    assert "messages.replaceChildren()" in html
    assert 'class="ai-suggestion funds"' in html
    assert '办理转账（暂未开放）' in html
    assert '真实转入账户接入后开放' in html
    assert "session_id: customerId ? getOperatorSessionId(customerId) : `operator_product_query_${userId}`" in html
    assert "session_id: `operator_dashboard_${Date.now()}`" not in html
    assert "const customerId = Number(selectedCustomerId) || storedCustomerId || null" in html
    assert "当前已领取工单事项：${activeOrder.intent_summary || activeOrder.title || ''}" in html
    assert "const operationQuery = activeOrder" in html
    assert "办理转账（暂未开放）" in html
    assert "为当前客户变更联系方式" in html
    assert "function showOperatorModal" in html
    assert "function submitWorkorder" in html
    assert "function formatWorkorderType(order)" in html
    assert "business_subtype: businessSubtype" in html
    assert "newWorkorderSubtype" in html
    assert "function queryCustomer" in html
    assert "const isProductQuery = /查询.*(产品|理财|基金)" in html
    assert "查询在售产品无需选择客户" in html
    assert "客户查询功能开发中" not in html
    assert "转账审核功能开发中" not in html
    assert "工单详情页面或打开弹窗" not in html
    assert "/api/operation/customers/${customerId}/overview" in html
    assert "function loadCustomerOverview(customerId)" in html
    assert ".filter(order => ['处理中', '待审核', '已完成', '已关闭', '已驳回'].includes(order.status))" in html
    assert "当前持仓" in html
    assert "最近交易" in html
    assert "function renderAssetAllocation(allocation)" in html
    assert "const assetAllocationKeys = new Set([" in html
    assert "Object.entries(allocation).filter(([key]) => assetAllocationKeys.has(key))" in html
    assert "function renderProfilePreference(preference)" in html
    assert "function renderCustomerPortrait(profile)" in html
    assert "function renderAdvisorPlan(plan)" in html
    assert "最新顾问配置方案" in html
    assert "顾问生成方案后会在此处同步展示" in html
    assert "JSON.stringify(data.asset_allocation" not in html
    assert "JSON.stringify(data.product_preference" not in html
    assert "body: JSON.stringify({action: 'claim'})" in html
    assert "status: '处理中'" not in html
    assert "let activeWorkorderId = null" in html
    assert "closeOperatorModal();\n            updateAIContext(order);" in html
    assert "function completeActiveWorkorder" in html
    assert "related_entity_type: 'transaction'" in html
    assert "related_entity_id: transactionId" in html
    assert 'id="totalCount"' in html
    assert 'id="completedCount"' in html
    assert 'id="pendingCount"' in html
    assert 'id="unclaimedCount"' in html
    assert "function workorderCategory(order)" in html
    assert "if (scope === 'unclaimed') return '待领取'" in html
    assert "if (scope === 'owned' && ['处理中', '待审核'].includes(order.status)) return '待处理'" in html
    assert ".filter(order => order.assignment_scope === 'owned')" in html
    assert "const filtered = filterOrdersByCategory(allWorkorders, type)" in html
    assert "filterWorkorders(currentFilter)" in html
    assert "'待处理': '我的待处理工单'" in html
    assert "'待领取': '待领取工单'" in html
    assert "function startOperatorNotificationPolling()" in html
    assert "/api/chat/operator/notifications?limit=50" in html
    assert "operatorNotificationBaselineReady" in html
    assert "notifications.forEach(item => item.id && seen.add(item.id))" in html
    assert "function openCloseWorkorder(orderId, event)" in html
    assert "function submitCloseWorkorder(orderId)" in html
    assert "确认关闭并通知客户" in html
    assert "body: JSON.stringify({action: 'close', remark: reason})" in html
    assert "申购金额不满足产品起投要求" in html
    assert "该操作不会执行交易" in html
    assert "function parseWorkorderAmount(order)" in html
    assert "async function autoCloseInsufficientBalance(order)" in html
    assert "自动校验失败：申购金额" in html
    assert "未发起双录或交易" in html


def test_customer_confirmation_card_exposes_actions_and_explains_double_record() -> None:
    html = _read("pages/customer_dashboard.html")

    assert 'data-action="cancel"' in html
    assert 'data-action="confirm"' in html
    assert "双录完成不会自动执行交易" in html
    assert "确认执行/取消" in html
