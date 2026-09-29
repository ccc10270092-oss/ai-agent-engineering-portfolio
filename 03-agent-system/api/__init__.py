"""API 层：FastAPI 网关（模块 F 的服务端）。

把 ``service.System`` 门面暴露为 REST API，供 Vue 前端调用，
并在生产模式下托管 ``frontend/dist`` 静态资源。
"""
