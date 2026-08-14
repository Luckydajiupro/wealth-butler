from app.Base.Config.setting import settings
from app.Base.Repository.base.baseDBModel import BaseDBModel
from app.Base.Repository.base.connectionManager import ConnectionManager


class BaseModuleDBModel(BaseDBModel):
    """
    Base模块数据库模型基类
    """
    _db_connection = ConnectionManager.get('base_module')