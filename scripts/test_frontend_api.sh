#!/bin/bash
# 前端API对接快速测试脚本
# 用于验证数据分析和风控API是否正常工作

API_BASE="http://localhost:8010"
TOKEN=""

echo "================================================"
echo "智能财富管家系统 - API端点测试"
echo "================================================"
echo ""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 测试函数
test_endpoint() {
    local method=$1
    local endpoint=$2
    local description=$3
    local expect_auth=$4

    echo -n "测试: $description ... "

    if [ "$expect_auth" = "true" ]; then
        # 需要认证的请求（预期返回401）
        response=$(curl -s -X $method "$API_BASE$endpoint" -w "\n%{http_code}")
        status_code=$(echo "$response" | tail -n1)

        if [ "$status_code" = "401" ]; then
            echo -e "${GREEN}✓ PASS${NC} (需要认证，返回401)"
        else
            echo -e "${RED}✗ FAIL${NC} (期望401，实际$status_code)"
        fi
    else
        # 不需要认证的请求
        response=$(curl -s -X $method "$API_BASE$endpoint" -w "\n%{http_code}")
        status_code=$(echo "$response" | tail -n1)
        body=$(echo "$response" | head -n -1)

        if [ "$status_code" = "200" ] || [ "$status_code" = "404" ]; then
            echo -e "${GREEN}✓ PASS${NC} (HTTP $status_code)"
        else
            echo -e "${RED}✗ FAIL${NC} (HTTP $status_code)"
            echo "  响应: $body" | head -c 100
        fi
    fi
}

# 1. 基础服务测试
echo "================================================"
echo "1. 基础服务测试"
echo "================================================"
test_endpoint "GET" "/docs" "API文档页面" "false"
test_endpoint "GET" "/chat/analyst" "数据分析工作台页面" "false"
test_endpoint "GET" "/chat/risk" "风控工作台页面" "false"
echo ""

# 2. 数据分析API测试
echo "================================================"
echo "2. 数据分析API测试"
echo "================================================"
test_endpoint "GET" "/api/wealth/analyst/query-history" "查询历史记录" "true"
test_endpoint "POST" "/api/chat/analyst" "NL2SQL查询接口" "true"
echo ""

# 3. 风控API测试
echo "================================================"
echo "3. 风控API测试"
echo "================================================"
test_endpoint "GET" "/api/wealth/risk/alerts" "风险预警列表" "true"
test_endpoint "GET" "/api/wealth/risk/stats" "风控统计数据" "true"
test_endpoint "GET" "/api/wealth/risk/trend?days=7" "风险趋势数据" "true"
test_endpoint "GET" "/api/wealth/risk/alert/1" "单个预警详情" "true"
echo ""

# 4. 前端页面路由测试
echo "================================================"
echo "4. 前端页面路由测试"
echo "================================================"
echo -n "测试: 登录页面 ... "
response=$(curl -s -o /dev/null -w "%{http_code}" "$API_BASE/login")
if [ "$response" = "200" ]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${YELLOW}⚠ WARN${NC} (HTTP $response)"
fi

echo -n "测试: 客户工作台 ... "
response=$(curl -s "$API_BASE/chat/customer" | head -1)
if [[ "$response" == *"<!DOCTYPE html>"* ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo -n "测试: 理财顾问工作台 ... "
response=$(curl -s "$API_BASE/chat/advisor" | head -1)
if [[ "$response" == *"<!DOCTYPE html>"* ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo -n "测试: 数据分析工作台 ... "
response=$(curl -s "$API_BASE/chat/analyst" | head -1)
if [[ "$response" == *"<!DOCTYPE html>"* ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo -n "测试: 风控工作台 ... "
response=$(curl -s "$API_BASE/chat/risk" | head -1)
if [[ "$response" == *"<!DOCTYPE html>"* ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo -n "测试: 客户经理工作台 ... "
response=$(curl -s "$API_BASE/chat/operator" | head -1)
if [[ "$response" == *"<!DOCTYPE html>"* ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${RED}✗ FAIL${NC}"
fi

echo ""

# 5. CORS测试
echo "================================================"
echo "5. CORS跨域配置测试"
echo "================================================"
echo -n "测试: CORS Headers ... "
response=$(curl -s -I -X OPTIONS "$API_BASE/api/wealth/risk/alerts" \
    -H "Origin: http://localhost:3000" \
    -H "Access-Control-Request-Method: GET" | grep -i "access-control-allow")
if [[ "$response" != "" ]]; then
    echo -e "${GREEN}✓ PASS${NC}"
else
    echo -e "${YELLOW}⚠ WARN${NC} (CORS可能未正确配置)"
fi
echo ""

# 总结
echo "================================================"
echo "测试完成"
echo "================================================"
echo ""
echo -e "${YELLOW}注意事项:${NC}"
echo "1. 需要认证的API返回401是正常的（需要JWT Token）"
echo "2. 完整功能测试需要先登录获取Token"
echo "3. 页面访问地址："
echo "   - 数据分析: http://localhost:8010/chat/analyst"
echo "   - 风控专员: http://localhost:8010/chat/risk"
echo ""
echo "详细测试报告请查看: docs/前端对接测试报告.md"
echo "访问指南请查看: docs/前端页面访问指南.md"
echo ""
