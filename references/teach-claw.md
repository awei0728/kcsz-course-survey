# teach_claw：后续版本接入说明

当前第一版只验收 WorkBuddy。teach_claw 接入与运行验证留到后续版本，当前没有完成加载、消息路由或文件交付接线，不作为 v0.1.0-rc.1 的发布条件。

开发阶段读取到的教学工作流模板曾使用 `TeachClaw` 作为对外身份、`teachclaw` 作为账号名称；模板不是本项目已部署协议。用户所称 `teach_claw` 与目标实例的实际名称、账号及进程映射仍需确认。本项目结果中的 `verification.teach_claw` 只是验证状态字段，不是绑定配置。

当前可以迁移的是独立 Python 核心：[查询](../scripts/survey_data.py)、[导出](../scripts/survey_export.py)、[公共调用契约](public-call.md)和[完整运行资源](runtime.md)。自然语言仍由目标宿主理解；核心保持参数化 CLI、UTF-8 JSON、真实 artifacts 和空 `model_trace`，不重复题库或加入模型 API。

后续接入前需要提供不含秘密的实际加载机制、进程参数协议、解释器与工作目录、可写输出位置、附件工具协议及跨执行环境的文件可见性。协议明确后再决定是否需要薄适配层；不能根据其他 Skill 或建议模板猜测注册命令、路径、请求文件参数或账号配置。

目前只能先在目标节点独立运行核心校验与导出；这不等于 teach_claw 接入或自然语言运行通过。
