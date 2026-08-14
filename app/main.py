"""项目启动入口（app/ 顶层）

脚手架包位于 app/Base/，包名为 Base（与原脚手架一致）。
本文件是薄入口：把 Base.main 里的 FastAPI 应用转发出来，方便在 app/ 目录下
直接 `python main.py` 启动，等价于原脚手架的 `python -m Base.main`。

启动方式（任选其一，均在 app/ 目录下执行）：
    python main.py                      # 本入口
    python -m Base.main                 # 直接跑脚手架包内主程序
    uvicorn Base.main:app --port 8010   # 常规 uvicorn 方式

注意：FastAPI 应用本体、路由注册、定时任务都在 app/Base/main.py，这里只做转发。
"""
from Base.main import app

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app=app, host="0.0.0.0", port=8010)
