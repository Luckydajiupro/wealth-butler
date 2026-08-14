import json
import logging
import re
from typing import Any, Dict, List

from Base.Ai.base.baseLlm import UserMessages
from Base.Ai.llms.qwenLlm import get_default_qwen_llm
from Base.Repository.base.baseDBModel import BaseDBModel

logger = logging.getLogger(__name__)


class BaseAiDBModel(BaseDBModel):
    """
    带 AI 能力的数据库模型基类，支持自然语言查询（NL2SQL）。
    """

    @classmethod
    def query_by_natural_language(cls, natural_language: str, limit: int = 100) -> Dict[str, Any]:
        """
        自然语言查询本表数据。

        工作流程：
        1. 自动提取本表的字段名、类型、描述，构建 schema prompt
        2. 调用 Qwen LLM 生成 SELECT SQL
        3. 执行 SQL 并返回结果

        Args:
            natural_language: 用户的自然语言查询描述
            limit: 查询结果数量限制，默认 100

        Returns:
            dict:
                - success: bool，是否成功
                - data: list，查询结果列表（字典）
                - sql: str，实际执行的 SQL
                - error: str，错误信息（成功时为 None）

        Example:
            # InterviewRecordPo.query_by_natural_language("查询张三最近的所有面试记录")
            # InterviewRecordPo.query_by_natural_language("统计每个公司的面试记录数量")
        """
        try:
            # 1. 构建表结构描述
            table_name = cls.get_table_name()
            schema_desc = cls._build_schema_description()

            # 2. 调用 LLM 生成 SQL
            sql = cls._generate_sql(table_name, schema_desc, natural_language, limit)
            if not sql:
                return {"success": False, "data": None, "sql": "", "error": "LLM 未能生成有效 SQL"}

            # 3. 安全校验：只允许 SELECT
            stripped = sql.strip().upper()
            if not stripped.startswith("SELECT"):
                return {"success": False, "data": None, "sql": sql, "error": f"生成的 SQL 不是 SELECT 语句: {sql}"}

            # 4. 执行查询
            db = cls.get_db_connection()
            if db is None:
                return {"success": False, "data": None, "sql": sql, "error": "数据库连接未设置"}

            logger.info(f"NL2SQL [{cls.__name__}] 执行 SQL: {sql}")
            results = db.execute(sql)

            return {
                "success": True,
                "data": results if results else [],
                "sql": sql,
                "error": None,
            }
        except Exception as e:
            logger.error(f"{cls.__name__}.query_by_natural_language 失败：{e}", exc_info=True)
            return {"success": False, "data": None, "sql": "", "error": str(e)}

    @classmethod
    def _build_schema_description(cls) -> str:
        """
        构建表的 schema 描述，用于 LLM prompt。
        """
        table_name = cls.get_table_name()
        fields = []

        for field_name, field_info in cls.model_fields.items():
            if field_name in ("id",) or field_name.startswith("_"):
                continue
            field_type = field_info.annotation.__name__ if hasattr(field_info.annotation, "__name__") else str(field_info.annotation)
            description = field_info.description or ""
            fields.append(f"  - `{field_name}` ({field_type}): {description}")

        schema_lines = [
            f"表名: `{table_name}`",
            "字段列表:",
        ]
        schema_lines.extend(fields)

        return "\n".join(schema_lines)

    @classmethod
    def _generate_sql(cls, table_name: str, schema_desc: str, natural_language: str, limit: int) -> str:
        """
        调用 LLM 生成 SQL。
        """
        system_prompt = (
            "你是一个专业的 MySQL 数据库专家，负责将用户的自然语言需求转换为 SQL 查询语句。\n"
            "请严格遵守以下规则：\n"
            "1. 只输出 SELECT 语句，不要输出任何其他内容\n"
            "2. 不要包含 DDL、DML（INSERT/UPDATE/DELETE）或任何危险操作\n"
            "3. 字符串值使用单引号包裹\n"
            "4. 如果查询涉及模糊匹配，使用 LIKE 和通配符 %%\n"
            "5. 只输出 SQL 语句本身，不要用 markdown 代码块包裹，不要任何解释\n"
            "6. SQL 语句末尾不要加分号"
        )

        user_content = (
            f"请根据以下表结构，将用户的查询需求转换为 SQL 语句。\n\n"
            f"### 表结构\n"
            f"{schema_desc}\n\n"
            f"### 注意事项\n"
            f"- 表名是 `{table_name}`，请在 FROM 子句中使用它\n"
            f"- 如果用户没有指定数量限制，默认最多返回 {limit} 条记录\n"
            f"- 如果涉及时间字段，可以直接使用字符串比较\n"
            f"- 中文字段匹配时可以使用 LIKE 模糊查询\n\n"
            f"### 用户查询\n"
            f"{natural_language}\n\n"
            f"请直接输出 SQL 语句："
        )

        llm = get_default_qwen_llm()

        response = llm.chat([
            UserMessages(user_content),
        ], temperature=0.1)

        sql = response.strip()

        # 清理可能的 markdown 代码块
        sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE).strip()
        sql = re.sub(r"\s*```$", "", sql).strip()
        # 清理末尾分号
        sql = sql.rstrip(";").strip()

        return sql
