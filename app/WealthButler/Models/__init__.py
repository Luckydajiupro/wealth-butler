"""业务模型层（ORM）

职责：
- 定义数据库表结构与 ORM 映射（继承 Base.Models.baseModel.BaseModel）
- 封装单表的 CRUD 操作（find_by_id、save、update、delete）
- 定义字段校验规则与默认值
- 管理表关系（一对多、多对多）

分层原则：
- 本层只做"数据映射"，不写业务逻辑
- 复杂查询可以写在 Model 内作为 @classmethod，但不包含业务判断
- 继承 Base.Models.baseModel.BaseModel 获得通用 CRUD 能力
- 表名统一前缀 wealth_ 避免与脚手架表冲突

典型模块：
- advisorModel.py           投顾信息表（投顾资质、专长领域、服务评分）
- productModel.py           理财产品表（产品类型、风险等级、预期收益）
- userProfileModel.py       用户画像表（风险偏好、投资目标、资产状况）
- portfolioModel.py         资产配置表（用户持仓、配置方案、历史调仓）
- riskAssessmentModel.py    风险评估表（问卷记录、评分历史、等级变更）
- consultationModel.py      咨询记录表（预约时间、咨询内容、满意度评价）
- transactionModel.py       交易记录表（买入卖出、手续费、收益统计）

示例：
    from app.Base.Models.baseModel import BaseModel
    from sqlalchemy import Column, String, Integer, Float, Enum

    class AdvisorModel(BaseModel):
        __tablename__ = 'wealth_advisor'
        __table_args__ = {'comment': '投顾信息表'}

        name = Column(String(50), nullable=False, comment='投顾姓名')
        license_no = Column(String(50), unique=True, comment='执业证书号')
        specialty = Column(String(200), comment='专长领域（JSON）')
        risk_level = Column(Enum('conservative', 'moderate', 'aggressive'), comment='擅长风险等级')
        rating = Column(Float, default=5.0, comment='服务评分')
        status = Column(String(20), default='active', comment='状态')

        @classmethod
        def find_by_risk_specialty(cls, risk_level: str):
            return cls.query().filter(cls.risk_level == risk_level, cls.status == 'active').all()

数据库迁移：
- 表结构变更需要在 Base/Models/migrations/ 添加迁移文件
- 或使用 Alembic 管理 DDL（如果脚手架集成了）
"""

__all__ = []
