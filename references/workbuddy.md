# WorkBuddy 加载与文件交付

核查与反馈记录日期：2026-10-04。第一版验收宿主为 WorkBuddy；此前安装包的加载和创造力自然语言生成流程已获用户反馈通过。v0.1.0-rc.1 候选沿用该包层级，但未重新在 WorkBuddy 加载，不能把此前反馈写成本候选自动实测记录。

## 已确认的入口与包结构

WorkBuddy“技能→添加技能→上传技能”支持拖拽或选择本地技能包，已安装技能可以启用、关闭。来源：[官方技能说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Skills-Market)。

“做一做（Craft）”可以执行任务、生成文件，对话中可选择已安装技能。使用宿主已有模型，权限仍由 WorkBuddy 当前设置控制；本 Skill 不要求换模型或改变全局权限。来源：[官方任务栏说明](https://www.workbuddy.ai/docs/zh/workbuddy/From-Beginner-to-Expert-Guide/Function-Description/Task-Bar)。

候选 ZIP 保持此前用户成功加载的 `kcsz-course-survey/SKILL.md` 目录层级，并包含脚本、正式数据、引用说明和两份原 PDF。公开源码另提供构建与测试材料。实际运行资源见 [runtime.md](runtime.md)，白名单与构建入口见 [BUILDING.md](../BUILDING.md)。不要只上传入口文件，也不要删除 PDF 后忽略校验。

## 安装和最短使用步骤

1. 在 [v0.1.0-rc.1 预发布页面](https://github.com/awei0728/kcsz-course-survey/releases/tag/v0.1.0-rc.1)取得 `kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip`，或使用[固定版本下载入口](https://github.com/awei0728/kcsz-course-survey/releases/download/v0.1.0-rc.1/kcsz-course-survey-v0.1.0-rc.1-workbuddy.zip)，再在官方上传入口选择 ZIP。本次发布完成前远端下载入口尚不可用。
2. 在已安装技能中找到并启用 `kcsz-course-survey`。
3. 新建 Craft 任务并选择该技能，沿用当前模型，发送“帮我生成一份用于 Python 课程前测的学生创造力问卷。”
4. 宿主定位实际加载的 Skill 根目录，使用当前可用的 Python 3.10+，核实 catalog 后完整导出。课程和场景只进入标题，未指定输出位置就使用程序默认目录。
5. 读取 JSON 结果，确认 `ok`、项目/版本及实际文件，再返回 TXT。首次加载本候选若失败，保留真实上传、调用或文件返回错误，不将本地检查写成宿主通过。

多卷请求如“生成批判性思维前测问卷”应询问 A/B；前后测不决定卷别。工程伦理调用当前整卷修正版，仍为 11 道作答题、19 字段，并附人工排序核对说明。具体参数安全与错误处理见 [public-call.md](public-call.md)。

## 调用与文件返回

通过宿主当次可用的进程工具，以可执行文件和参数数组调用脚本；不要采用其他产品的目录或根路径占位符。使用实际解释器，不硬编码开发机的 Python 路径，不安装或切换全局环境。

结果文件从 `artifacts[].path` 获取，TXT 为 `role=primary`，教师说明和来源映射辅助交付。本机曾有文件展示工具依据；其名称与参数须以当前 WorkBuddy 会话真实工具定义为准，不在本 Skill 中猜测 API。若只能返回本地文件，给完整实际路径。官方 [快速开始](https://www.workbuddy.ai/docs/workbuddy/Quickstart)介绍结果面板的文件与预览，不构成 Python 附件上传协议。

用户反馈范围见 [import-feedback.md](import-feedback.md)：问卷星创造力与工程伦理修正版两版通过，其余十四版待反馈。WorkBuddy 此前通过的是加载与创造力生成流程，没有扩展为全部十六版宿主自然语言验收。新候选的上传接受、当次工具和文件可访问性尚须实际会话确认。

本机配置、缓存和安装路径的历史核查留在开发审计资料中，不作为公开安装协议，也不要求用户复制本机配置。

原创代码采用 [MIT](../LICENSE)；两份来源 PDF、量规原文、逐字题项与对应来源内容保留原作者及出版方权利，不纳入 MIT。用户已确认 PDF 可以公开发布，安装包仍保留实际运行所需的原文件。详见 [来源说明](../SOURCES.md)。
