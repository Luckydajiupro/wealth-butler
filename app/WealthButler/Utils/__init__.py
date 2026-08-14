"""业务工具层

职责：
- 提供财富管家业务专用的工具函数（金融计算、数据转换、格式化）
- 封装业务常用的辅助方法（不含业务逻辑，纯函数式）
- 与 Base.RicUtils 的区别：本层是业务特化的，Base.RicUtils 是通用的

分层原则：
- 本层只提供"纯函数"，无状态、无副作用
- 不操作数据库、不调用外部服务
- 可被 Service、Agent、Api 层自由调用
- 通用工具优先放 Base.RicUtils，业务特化的才放这里

典型模块：
- financeCalc.py          金融计算工具
  - 年化收益率、复利计算、净值计算
  - 夏普比率、最大回撤、波动率
  - 投资组合权重优化（马科维茨模型）

- riskCalc.py             风险计算工具
  - VaR（风险价值）计算
  - 风险等级映射（保守/稳健/激进）
  - 风险承受能力评分

- dataFormatter.py        数据格式化工具
  - 金额格式化（万元、亿元、货币符号）
  - 收益率格式化（百分比、正负号、颜色标记）
  - 日期时间格式化（交易日、工作日判断）

- chartHelper.py          图表辅助工具
  - ECharts 配置生成（折线图、饼图、K线图）
  - 数据聚合与降采样（时间序列压缩）
  - 颜色主题映射

- validator.py            业务校验工具
  - 身份证号校验、手机号校验
  - 银行卡号校验（Luhn 算法）
  - 投资金额合法性校验

示例：
    # financeCalc.py
    def calc_annualized_return(start_value: float, end_value: float, days: int) -> float:
        '''计算年化收益率'''
        if start_value <= 0 or days <= 0:
            return 0.0
        return ((end_value / start_value) ** (365 / days) - 1) * 100

    def calc_sharpe_ratio(returns: list, risk_free_rate: float = 0.03) -> float:
        '''计算夏普比率'''
        import numpy as np
        excess_returns = np.array(returns) - risk_free_rate
        return np.mean(excess_returns) / np.std(excess_returns) if np.std(excess_returns) > 0 else 0

    # dataFormatter.py
    def format_amount(amount: float, unit: str = '元') -> str:
        '''格式化金额显示'''
        if amount >= 100000000:
            return f"{amount / 100000000:.2f}亿{unit}"
        elif amount >= 10000:
            return f"{amount / 10000:.2f}万{unit}"
        else:
            return f"{amount:.2f}{unit}"

使用规范：
- 优先使用标准库（math、statistics、decimal）
- 金融计算涉及精度时使用 decimal.Decimal 而非 float
- 复杂算法可引入 numpy、pandas、scipy
"""

__all__ = []
